"""UNiNUS Remote Console integration for Home Assistant."""

from __future__ import annotations

import asyncio
import difflib
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import CONF_RESOURCE_TYPE_WS, LOVELACE_DATA, MODE_STORAGE
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    CARD_RESOURCE_URL,
    CARD_STATIC_URL,
    CONF_APPROVAL_WINDOW_SECONDS,
    DATA_AUDIT_LOG,
    DATA_HOST_STATE,
    DATA_APPROVALS,
    CONF_BROKER_HOST,
    CONF_BROKER_PORT,
    CONF_CALLBACK_IP,
    CONF_DISCOVERY_HOST_NAME,
    CONF_DOMAIN,
    CONF_HOSTS,
    CONF_PASSWORD,
    CONF_REQUIRE_CONFIRM_DANGEROUS,
    CONF_USERNAME,
    DEFAULT_APPROVAL_WINDOW_SECONDS,
    DEFAULT_BROKER_PORT,
    DEFAULT_DISCOVERY_HOST_NAME,
    DEFAULT_REQUIRE_CONFIRM_DANGEROUS,
    DOMAIN,
    HEALTH_STALE_SECONDS,
    MAX_AUDIT_LOG,
)
from .mqtt_helper import UNiNUSMQTT

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.TEXT]

DATA_MQTT = "mqtt"
DATA_HOSTS = "hosts"
DATA_TOKENS = "tokens"
DATA_CONSOLE_HISTORY = "console_history"


async def _async_ensure_lovelace_resource(hass: HomeAssistant, resource_url: str) -> None:
    for _attempt in range(12):
        lovelace_data = hass.data.get(LOVELACE_DATA)
        if lovelace_data is None:
            await asyncio.sleep(5)
            continue

        if lovelace_data.resource_mode != MODE_STORAGE:
            _LOGGER.info("Skipped unircon resource persistence because Lovelace is not in storage mode")
            return

        resources = lovelace_data.resources
        await resources.async_get_info()
        items = list(resources.async_items() or [])

        target_item = None
        for item in items:
            url = str(item.get("url") or "")
            if url == resource_url or CARD_STATIC_URL in url or "unircon-console-card.js" in url:
                target_item = item
                break

        if target_item is None:
            await resources.async_create_item({"url": resource_url, CONF_RESOURCE_TYPE_WS: "module"})
            _LOGGER.info("Registered unircon card resource in Lovelace storage: %s", resource_url)
            return

        if target_item.get("url") != resource_url or target_item.get("type") != "module":
            await resources.async_update_item(
                target_item["id"],
                {"url": resource_url, CONF_RESOURCE_TYPE_WS: "module"},
            )
            _LOGGER.info("Updated unircon card resource in Lovelace storage: %s", resource_url)
        return

    _LOGGER.warning("Lovelace data not ready, skipped unircon resource persistence")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up UNiNUS Remote Console domain data and dashboard card."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    if not domain_data.get("card_static_registered"):
        card_path = os.path.join(os.path.dirname(__file__), "www", "unircon-console-card.js")
        if os.path.isfile(card_path):
            await hass.http.async_register_static_paths(
                [StaticPathConfig(CARD_STATIC_URL, card_path, cache_headers=False)]
            )
            domain_data["card_static_registered"] = True
            domain_data["card_resource_url"] = CARD_RESOURCE_URL
            _LOGGER.info("Registered unircon card static path at %s", CARD_STATIC_URL)

    if not domain_data.get("card_resource_registered"):
        frontend.add_extra_js_url(hass, domain_data.get("card_resource_url", CARD_RESOURCE_URL))
        domain_data["card_resource_registered"] = True
        _LOGGER.info("Auto-loaded unircon card resource: %s", domain_data.get("card_resource_url", CARD_RESOURCE_URL))

    hass.async_create_task(
        _async_ensure_lovelace_resource(
            hass, domain_data.get("card_resource_url", CARD_RESOURCE_URL)
        )
    )

    return True


def generate_deploy_config(params: dict) -> str:
    """Generate device deploy config from parameters."""
    lines = []
    bp = params.get("backup_protocol", "ftp")
    bs = params.get("backup_server", "192.168.1.222")
    bf = params.get("backup_file", "share/^sn^.txt")
    lines.append(f"backup protocol {bp}")
    lines.append(f"  server {bs}")
    lines.append(f"  file {bf}")
    lines.append("!")

    up = params.get("update_protocol", "mqtt")
    us = params.get("update_server", "192.168.1.222")
    upt = params.get("update_port", "1883")
    uu = params.get("update_user", "admin")
    upw = params.get("update_password", "")
    sub = params.get("update_subscribe", "^ha_prefix^/sub/^hostname^")
    pub = params.get("update_publish", "^ha_prefix^/pub/^hostname^")
    pubr = params.get("update_publish_response", "^ha_prefix^/pubrsp/^hostname^")
    publ = params.get("update_publish_log", "^ha_prefix^/log/^hostname^")
    lines.append(f"update protocol {up}")
    lines.append(f"  server {us} {upt}")
    lines.append(f"  user {uu} {upw}")
    lines.append(f"  subscribe {sub}")
    lines.append(f"  publish {pub}")
    lines.append(f"  publish response {pubr}")
    lines.append(f"  publish log {publ}")
    lines.append("!")

    ssid = params.get("sta_ssid", "")
    spw = params.get("sta_password", "")
    if ssid:
        lines.append("interface sta")
        lines.append("  ip dhcp")
        lines.append(f"  sta ssid {ssid}")
        lines.append(f"  sta password {spw}")
        lines.append("!")

    ntp = params.get("ntp_server", "118.163.81.62")
    tz = params.get("ntp_timezone", "8")
    lines.append(f"ntp server {ntp}")
    lines.append(f"ntp timezone {tz}")
    lines.append("!")

    return "\n".join(lines)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up UNiNUS from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    config = {**entry.data, **entry.options}
    broker_host = config[CONF_BROKER_HOST]
    broker_port = int(config.get(CONF_BROKER_PORT, DEFAULT_BROKER_PORT))
    username = config[CONF_USERNAME]
    password = config[CONF_PASSWORD]
    urcon_domain = config.get(CONF_DOMAIN, "uninus")
    discovery_host_name = config.get(CONF_DISCOVERY_HOST_NAME, DEFAULT_DISCOVERY_HOST_NAME)
    callback_ip = config.get(CONF_CALLBACK_IP, "")
    hosts = config.get(CONF_HOSTS, [])

    # Card static path registered in async_setup (domain level)

    # Create MQTT client
    mqtt_client = UNiNUSMQTT(
        host=broker_host,
        port=broker_port,
        username=username,
        password=password,
        urcon_domain=urcon_domain,
        host_name=f"ha-unircon-{entry.entry_id[:8]}",
        discovery_host_name=discovery_host_name,
        default_callback_ip=callback_ip,
    )

    device_data = {
        DATA_MQTT: mqtt_client,
        DATA_HOSTS: hosts,
        DATA_TOKENS: {},
        DATA_CONSOLE_HISTORY: {h: [] for h in hosts},
        DATA_HOST_STATE: {},
        DATA_AUDIT_LOG: [],
        DATA_APPROVALS: {},
    }
    hass.data[DOMAIN][entry.entry_id] = device_data

    def _now_iso() -> str:
        return dt_util.utcnow().isoformat()

    def _ensure_host_state(host: str) -> dict[str, Any]:
        state_map = device_data.setdefault(DATA_HOST_STATE, {})
        return state_map.setdefault(
            host,
            {
                "host": host,
                "status": "offline",
                "last_seen": None,
                "last_topic": None,
                "message_count": 0,
                "last_command": None,
                "last_command_at": None,
                "last_health_check_at": None,
                "firmware_version": None,
                "device_model": None,
                "last_error": None,
                "last_backup_at": None,
                "last_backup_change_type": None,
                "last_backup_changed": None,
                "last_backup_sha256": None,
                "last_backup_serial": None,
                "last_backup_site": None,
                "last_backup_archive_path": None,
                "last_backup_metadata_path": None,
                "last_backup_sync_at": None,
            },
        )

    for host in hosts:
        _ensure_host_state(host)

    def _require_confirm_dangerous() -> bool:
        return bool(
            entry.options.get(
                CONF_REQUIRE_CONFIRM_DANGEROUS,
                entry.data.get(
                    CONF_REQUIRE_CONFIRM_DANGEROUS,
                    DEFAULT_REQUIRE_CONFIRM_DANGEROUS,
                ),
            )
        )

    def _approval_window_seconds() -> int:
        return int(
            entry.options.get(
                CONF_APPROVAL_WINDOW_SECONDS,
                entry.data.get(
                    CONF_APPROVAL_WINDOW_SECONDS,
                    DEFAULT_APPROVAL_WINDOW_SECONDS,
                ),
            )
        )

    def _classify_command(command: str) -> str | None:
        normalized = " ".join(command.lower().strip().split())
        dangerous_patterns = [
            "write erase",
            "write erase all",
            "write erase force",
            "write default",
            "config restore",
            "restore factory",
            "reload",
            "reboot",
            "copy ",
            "exec autodeploy",
        ]
        for pattern in dangerous_patterns:
            if normalized.startswith(pattern):
                return pattern
        return None

    def _approval_key(host: str, command: str) -> str:
        return f"{host}::{command.strip().lower()}"

    def _has_active_approval(host: str, command: str) -> bool:
        approvals = device_data.setdefault(DATA_APPROVALS, {})
        key = _approval_key(host, command)
        info = approvals.get(key)
        if not info:
            return False
        expires_at = info.get("expires_at")
        try:
            expires_dt = dt_util.parse_datetime(expires_at) if expires_at else None
        except Exception:
            expires_dt = None
        if expires_dt is None or expires_dt <= dt_util.utcnow():
            approvals.pop(key, None)
            return False
        return True

    def _grant_approval(host: str, command: str, *, ttl_seconds: int, note: str | None = None) -> dict[str, Any]:
        expires_dt = dt_util.utcnow() + timedelta(seconds=ttl_seconds)
        approval = {
            "host": host,
            "command": command,
            "expires_at": expires_dt.isoformat(),
            "note": note or "",
        }
        device_data.setdefault(DATA_APPROVALS, {})[_approval_key(host, command)] = approval
        return approval

    def _policy_allows_command(host: str, command: str, call_data: dict[str, Any]) -> tuple[bool, str | None]:
        if not _require_confirm_dangerous():
            return True, None
        danger = _classify_command(command)
        if not danger:
            return True, None
        if bool(call_data.get("confirm", False)):
            return True, f"confirm flag for {danger}"
        if _has_active_approval(host, command):
            return True, f"active approval for {danger}"
        return False, danger

    def _append_audit(
        kind: str,
        *,
        host: str | None = None,
        status: str = "info",
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        entry_data = {
            "at": _now_iso(),
            "kind": kind,
            "status": status,
            "host": host,
            "message": message,
            "details": details or {},
        }
        audit_log = device_data.setdefault(DATA_AUDIT_LOG, [])
        audit_log.append(entry_data)
        if len(audit_log) > MAX_AUDIT_LOG:
            del audit_log[:-MAX_AUDIT_LOG]
        hass.loop.call_soon_threadsafe(
            hass.bus.async_fire,
            f"{DOMAIN}_audit",
            entry_data,
        )

    def _extract_line(data: Any, payload_text: str) -> str:
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            output = data["data"].get("output")
            if output:
                return str(output)
        if isinstance(data, dict) and "raw" in data:
            return str(data["raw"])
        if isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False)
        return payload_text

    def _update_host_state_from_line(host: str, line: str, topic: str) -> None:
        state = _ensure_host_state(host)
        state["status"] = "online"
        state["last_seen"] = _now_iso()
        state["last_topic"] = topic
        state["message_count"] = int(state.get("message_count", 0)) + 1

        firmware_match = re.search(r"\b\d+\.\d+\.\d+\([^)]+\)[A-Za-z0-9._-]*", line)
        if firmware_match:
            state["firmware_version"] = firmware_match.group(0)

        model_match = re.search(r"\b(?:Relay|UB-R|USS|UM-R)-[A-Za-z0-9]+\b", line)
        if model_match:
            state["device_model"] = model_match.group(0)

        lowered = line.lower()
        if "error" in lowered or "failed" in lowered or "timeout" in lowered:
            state["last_error"] = line[:300]

    def _mark_host_command(host: str, command: str, *, kind: str = "command") -> None:
        state = _ensure_host_state(host)
        state["last_command"] = command
        state["last_command_at"] = _now_iso()
        _append_audit(kind, host=host, message=command, details={"command": command})

    def _mark_health_check(host: str) -> None:
        state = _ensure_host_state(host)
        state["last_health_check_at"] = _now_iso()

    def _normalize_lookup(value: Any) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", "", str(value).lower())

    def _device_registry_candidates(host: str, token: Any) -> list[dict[str, Any]]:
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        state = _ensure_host_state(host)
        host_norm = _normalize_lookup(host)
        token_text = str(token).strip() if token is not None else ""
        token_norm = _normalize_lookup(token_text)
        model_norm = _normalize_lookup(state.get("device_model"))
        firmware_version = state.get("firmware_version")

        candidates: list[dict[str, Any]] = []
        for device in device_registry.devices.values():
            score = 0
            reasons: list[str] = []
            identifiers = sorted(
                f"{key}:{value}" for key, value in (getattr(device, "identifiers", set()) or set())
            )
            identifier_values = [str(value) for _, value in (getattr(device, "identifiers", set()) or set())]
            connection_values = [str(value) for _, value in (getattr(device, "connections", set()) or set())]
            names = [
                getattr(device, "name_by_user", None),
                getattr(device, "name", None),
                getattr(device, "default_name", None),
            ]
            normalized_names = {_normalize_lookup(name) for name in names if name}

            mqtt_identifier = None
            if token_text and token_text in identifier_values:
                mqtt_identifier = token_text
                score += 100
                reasons.append("identifier matches token")
            elif token_text and token_text in connection_values:
                mqtt_identifier = token_text
                score += 90
                reasons.append("connection matches token")

            if host_norm and host_norm in normalized_names:
                score += 70
                reasons.append("device name matches host")

            device_model = getattr(device, "model", None)
            if model_norm and _normalize_lookup(device_model) == model_norm:
                score += 20
                reasons.append("model matches runtime state")

            if firmware_version and getattr(device, "sw_version", None) == firmware_version:
                score += 10
                reasons.append("firmware matches runtime state")

            manufacturer = getattr(device, "manufacturer", None) or getattr(device, "default_manufacturer", None)
            if manufacturer and "uninus" in manufacturer.lower():
                score += 5
                reasons.append("manufacturer is UNiNUS")

            if score <= 0:
                continue

            entities = er.async_entries_for_device(
                entity_registry,
                device.id,
                include_disabled_entities=True,
            )
            entity_ids = sorted(entry.entity_id for entry in entities)
            entity_platforms = sorted({entry.platform for entry in entities if getattr(entry, "platform", None)})
            entity_domains = sorted({entry.entity_id.split(".", 1)[0] for entry in entities})

            if mqtt_identifier is None and token_norm:
                for ident in identifier_values:
                    if _normalize_lookup(ident) == token_norm:
                        mqtt_identifier = ident
                        break
            if mqtt_identifier is None and identifier_values:
                mqtt_identifier = identifier_values[0]

            candidates.append(
                {
                    "score": score,
                    "reasons": reasons,
                    "host": host,
                    "token": token_text or None,
                    "ha_device_id": device.id,
                    "device_name": getattr(device, "name_by_user", None) or getattr(device, "name", None),
                    "manufacturer": manufacturer,
                    "model": device_model,
                    "sw_version": getattr(device, "sw_version", None),
                    "mqtt_identifier": mqtt_identifier,
                    "identifiers": identifiers,
                    "entity_ids": entity_ids,
                    "entity_domains": entity_domains,
                    "entity_platforms": entity_platforms,
                    "is_mqtt_device": "mqtt" in entity_platforms,
                    "suggested_binding": {
                        "host": host,
                        "site": None,
                        "ha_device_id": device.id,
                        "mqtt_identifier": mqtt_identifier,
                        "manufacturer": manufacturer,
                        "model": device_model,
                        "sw_version": getattr(device, "sw_version", None),
                        "base_entities": entity_ids,
                        "notes": "; ".join(reasons),
                    },
                }
            )

        candidates.sort(key=lambda item: (-item["score"], item["device_name"] or ""))
        return candidates

    def _build_binding_candidate_export(hosts_list: list[str]) -> dict[str, Any]:
        binding_map: dict[str, Any] = {}
        unresolved_hosts: list[dict[str, Any]] = []
        candidates_by_host: dict[str, Any] = {}

        for host in hosts_list:
            state = dict(_ensure_host_state(host))
            raw_token = device_data[DATA_TOKENS].get(host) or state.get("token")
            token = str(raw_token).strip() if raw_token is not None else ""
            candidates = _device_registry_candidates(host, token)
            candidates_by_host[host] = {
                "token": token or None,
                "runtime_state": state,
                "candidates": candidates,
            }

            if token and candidates:
                binding_map[token] = candidates[0]["suggested_binding"]
            else:
                unresolved_hosts.append(
                    {
                        "host": host,
                        "token": token,
                        "reason": "no token" if not token else "no registry candidate",
                    }
                )

        return {
            "entry_id": entry.entry_id,
            "hosts": hosts_list,
            "binding_map": binding_map,
            "binding_map_json": json.dumps(binding_map, ensure_ascii=False, indent=2, sort_keys=True),
            "unresolved_hosts": unresolved_hosts,
            "candidates": candidates_by_host,
        }

    def _resolve_output_path(path_text: str | None, default_filename: str) -> Path:
        raw = (path_text or "").strip()
        if not raw:
            return Path(hass.config.path("unircon", default_filename))
        path = Path(raw)
        if path.is_absolute():
            return path
        return Path(hass.config.path(raw))

    def _write_text_file(target_path: Path, content: str, overwrite: bool) -> None:
        if target_path.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing file: {target_path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")

    def _resolve_metadata_root(path_text: str | None) -> Path:
        raw = (path_text or "").strip()
        if not raw:
            return Path("/share/emostore/repo/metadata")
        path = Path(raw)
        if path.is_absolute():
            return path
        return Path(hass.config.path(raw))

    def _resolve_repo_root_from_metadata_root(metadata_root: Path) -> Path:
        return metadata_root.parent if metadata_root.name == "metadata" else metadata_root

    def _resolve_serial_for_host(host: str) -> str | None:
        state = _ensure_host_state(host)
        candidates = [
            state.get("last_backup_serial"),
            device_data[DATA_TOKENS].get(host),
            state.get("token"),
        ]
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value:
                return value
        return None

    def _list_metadata_files(metadata_root: Path, serial: str) -> list[Path]:
        serial_dir = metadata_root / serial
        if not serial_dir.exists():
            return []
        return sorted(serial_dir.glob("*.json"))

    def _load_metadata_record(metadata_path: Path) -> dict[str, Any]:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"invalid metadata json: {metadata_path}")
        data["_metadata_file"] = str(metadata_path)
        data["_snapshot"] = metadata_path.stem
        return data

    def _resolve_metadata_record(
        metadata_root: Path,
        serial: str,
        snapshot: str | None,
        *,
        latest_index: int,
    ) -> dict[str, Any] | None:
        files = _list_metadata_files(metadata_root, serial)
        if not files:
            return None
        if snapshot:
            normalized = snapshot.removesuffix(".json")
            for path in files:
                if path.stem == normalized or path.name == snapshot:
                    return _load_metadata_record(path)
            return None
        target_index = len(files) - 1 - latest_index
        if target_index < 0 or target_index >= len(files):
            return None
        return _load_metadata_record(files[target_index])

    def _read_optional_text(path: Path | None) -> str | None:
        if path is None or not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _resolve_snapshot_path(repo_root: Path, relative_path: Any) -> Path | None:
        raw = str(relative_path or "").strip()
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_absolute() else repo_root / path

    def _build_backup_compare_payload(
        host: str,
        serial: str,
        current_record: dict[str, Any],
        previous_record: dict[str, Any],
        metadata_root: Path,
    ) -> dict[str, Any]:
        repo_root = _resolve_repo_root_from_metadata_root(metadata_root)
        current_norm_path = _resolve_snapshot_path(repo_root, current_record.get("normalized_path"))
        previous_norm_path = _resolve_snapshot_path(repo_root, previous_record.get("normalized_path"))
        current_text = _read_optional_text(current_norm_path) or ""
        previous_text = _read_optional_text(previous_norm_path) or ""
        diff_lines = list(
            difflib.unified_diff(
                previous_text.splitlines(),
                current_text.splitlines(),
                fromfile=previous_record.get("_snapshot", "previous"),
                tofile=current_record.get("_snapshot", "current"),
                lineterm="",
            )
        )
        added_lines = sum(
            1
            for line in diff_lines
            if line.startswith("+") and not line.startswith("+++")
        )
        removed_lines = sum(
            1
            for line in diff_lines
            if line.startswith("-") and not line.startswith("---")
        )
        preview_limit = 200
        return {
            "entry_id": entry.entry_id,
            "host": host,
            "serial": serial,
            "metadata_root": str(metadata_root),
            "current_snapshot": current_record.get("_snapshot"),
            "previous_snapshot": previous_record.get("_snapshot"),
            "current_received_at": current_record.get("received_at"),
            "previous_received_at": previous_record.get("received_at"),
            "current_change_type": current_record.get("change_type"),
            "previous_change_type": previous_record.get("change_type"),
            "current_sha256": current_record.get("sha256"),
            "previous_sha256": previous_record.get("sha256"),
            "current_archive_path": str(_resolve_snapshot_path(repo_root, current_record.get("archive_path")) or ""),
            "previous_archive_path": str(_resolve_snapshot_path(repo_root, previous_record.get("archive_path")) or ""),
            "current_metadata_path": current_record.get("_metadata_file"),
            "previous_metadata_path": previous_record.get("_metadata_file"),
            "line_additions": added_lines,
            "line_removals": removed_lines,
            "diff_preview": "\n".join(diff_lines[:preview_limit]),
            "diff_truncated": len(diff_lines) > preview_limit,
        }

    def _build_restore_preview_payload(
        host: str,
        serial: str,
        target_record: dict[str, Any],
        metadata_root: Path,
    ) -> dict[str, Any]:
        repo_root = _resolve_repo_root_from_metadata_root(metadata_root)
        archive_path = _resolve_snapshot_path(repo_root, target_record.get("archive_path"))
        latest_record = _resolve_metadata_record(metadata_root, serial, None, latest_index=0)
        return {
            "entry_id": entry.entry_id,
            "host": host,
            "serial": serial,
            "metadata_root": str(metadata_root),
            "target_snapshot": target_record.get("_snapshot"),
            "target_received_at": target_record.get("received_at"),
            "target_change_type": target_record.get("change_type"),
            "target_sha256": target_record.get("sha256"),
            "target_archive_path": str(archive_path or ""),
            "target_metadata_path": target_record.get("_metadata_file"),
            "latest_snapshot": latest_record.get("_snapshot") if latest_record else None,
            "latest_received_at": latest_record.get("received_at") if latest_record else None,
            "required_policy_gate": True,
            "warnings": [
                "Restore is a high-risk workflow, review diff before acting.",
                "Do not overwrite the current device blindly, verify host/serial first.",
                "Actual restore command depends on device firmware and field workflow, keep operator approval in the loop.",
            ],
            "manual_steps": [
                "Compare current snapshot vs target snapshot before restore.",
                "Stage the target archive file into the approved restore location or workflow.",
                "Use operator-approved device restore procedure for this firmware/model.",
                "After restore, run health check and sync backup status again.",
            ],
        }

    def _clear_backup_fields(state: dict[str, Any]) -> None:
        state["last_backup_at"] = None
        state["last_backup_change_type"] = None
        state["last_backup_changed"] = None
        state["last_backup_sha256"] = None
        state["last_backup_serial"] = None
        state["last_backup_site"] = None
        state["last_backup_archive_path"] = None
        state["last_backup_metadata_path"] = None
        state["last_backup_sync_at"] = _now_iso()

    def _load_latest_backup_metadata(metadata_root: Path) -> list[dict[str, Any]]:
        if not metadata_root.exists():
            raise FileNotFoundError(f"metadata root not found: {metadata_root}")

        records: list[dict[str, Any]] = []
        for serial_dir in sorted(metadata_root.iterdir()):
            if not serial_dir.is_dir():
                continue
            json_files = sorted(serial_dir.glob("*.json"))
            if not json_files:
                continue
            latest_file = json_files[-1]
            data = json.loads(latest_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data["_metadata_file"] = str(latest_file)
                records.append(data)
        return records

    def _match_backup_record_to_host(record: dict[str, Any], hosts_list: list[str]) -> str | None:
        record_host = str(record.get("host") or "").strip()
        serial = str(record.get("serial") or "").strip()

        if record_host and record_host in hosts_list:
            return record_host

        if serial:
            for host_name in hosts_list:
                state = _ensure_host_state(host_name)
                known_token = str(
                    device_data[DATA_TOKENS].get(host_name)
                    or state.get("token")
                    or ""
                ).strip()
                if known_token and known_token == serial:
                    return host_name

        return None

    def _apply_backup_record_to_host(host: str, record: dict[str, Any]) -> None:
        state = _ensure_host_state(host)
        serial = str(record.get("serial") or "").strip() or None
        if serial:
            device_data[DATA_TOKENS][host] = serial
            state["token"] = serial
        state["last_backup_at"] = record.get("received_at")
        state["last_backup_change_type"] = record.get("change_type")
        state["last_backup_changed"] = record.get("changed")
        state["last_backup_sha256"] = record.get("sha256")
        state["last_backup_serial"] = serial
        state["last_backup_site"] = record.get("site")
        state["last_backup_archive_path"] = record.get("archive_path")
        state["last_backup_metadata_path"] = record.get("_metadata_file") or record.get("metadata_path")
        state["last_backup_sync_at"] = _now_iso()
        identity = record.get("device_identity") or {}
        if isinstance(identity, dict):
            if identity.get("sw_version") and not state.get("firmware_version"):
                state["firmware_version"] = identity.get("sw_version")
            if identity.get("model") and not state.get("device_model"):
                state["device_model"] = identity.get("model")

    # Message handler
    def _handle_message_in_loop(topic: str, payload: str) -> None:
        try:
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                data = {"raw": payload}

            if topic.startswith("ha/sub/") or topic.startswith("urcom/"):
                if isinstance(data, dict) and data.get("type") in (13, 14):
                    _emit_console_event(
                        {
                            "kind": "urcon_discovery",
                            "source": "backend_mqtt",
                            "host": data.get("host"),
                            "ip": data.get("ip"),
                            "type": data.get("type"),
                            "topic": topic,
                            "data": data,
                        }
                    )
                    if data.get("type") == 14 and data.get("host"):
                        _emit_console_event(
                            {
                                "topic": topic,
                                "data": {
                                    "output": f"[MQTT-RX] {topic} {payload[:300]}"
                                },
                            }
                        )
                    return

            for host in list(device_data[DATA_HOSTS]):
                if f"/{host}/console/" in topic or f"pubrsp/{host}" in topic:
                    history = device_data[DATA_CONSOLE_HISTORY].get(host, [])
                    line = _extract_line(data, payload)
                    history.append({"topic": topic, "data": data, "line": line})
                    if len(history) > 500:
                        history[:] = history[-500:]
                    device_data[DATA_CONSOLE_HISTORY][host] = history
                    _update_host_state_from_line(host, line, topic)

                    if isinstance(data, dict):
                        token = data.get("token")
                        if not token and isinstance(data.get("data"), dict):
                            token = data["data"].get("token")
                        if token:
                            token_text = str(token).strip()
                            device_data[DATA_TOKENS][host] = token_text
                            _ensure_host_state(host)["token"] = token_text

                    _emit_console_event(
                        {"host": host, "topic": topic, "data": data}
                    )
                    break
        except Exception as err:
            _LOGGER.error("Message handling error: %s", err)

    def _on_message(topic: str, payload: str) -> None:
        hass.loop.call_soon_threadsafe(_handle_message_in_loop, topic, payload)

    mqtt_client.on_message(_on_message)

    # Best-effort initial connect: do not abort entry setup if broker is unavailable.
    try:
        await hass.async_add_executor_job(mqtt_client.connect)

        def _subscribe() -> None:
            if hosts:
                mqtt_client.subscribe_devices(hosts)
            mqtt_client.subscribe_urcom()

        await hass.async_add_executor_job(_subscribe)
    except Exception as err:
        _LOGGER.warning(
            "Initial MQTT connect failed for %s:%s; integration will stay loaded and retry on demand: %s",
            broker_host,
            broker_port,
            err,
        )

    def _emit_console_event(event_data: dict[str, Any]) -> None:
        hass.loop.call_soon_threadsafe(
            hass.bus.async_fire,
            f"{DOMAIN}_console",
            event_data,
        )

    def _fire_console_output(message: str, topic: str) -> None:
        _emit_console_event(
            {
                "topic": topic,
                "data": {"output": message},
            }
        )

    async def _ensure_backend_mqtt_connected(service_name: str) -> tuple[bool, str | None]:
        if mqtt_client.is_connected:
            return True, None

        _fire_console_output(
            f"[MQTT] Backend not connected, reconnecting to {broker_host}:{broker_port}...",
            f"service/{service_name}",
        )

        try:
            await hass.async_add_executor_job(mqtt_client.connect)

            def _resubscribe() -> None:
                if device_data[DATA_HOSTS]:
                    mqtt_client.subscribe_devices(device_data[DATA_HOSTS])
                mqtt_client.subscribe_urcom()

            await hass.async_add_executor_job(_resubscribe)
            _fire_console_output(
                f"[MQTT] Backend reconnected to {broker_host}:{broker_port}",
                f"service/{service_name}",
            )
            return True, None
        except Exception as err:
            _LOGGER.error("Backend MQTT reconnect failed: %s", err)
            return False, (mqtt_client.last_connect_error or str(err))

    # ===== Services =====

    def _broker_override_from_call(call_data: dict) -> tuple[str, int, str, str] | None:
        h = str(call_data.get("broker_host", "")).strip()
        if not h:
            return None
        p = int(call_data.get("broker_port", 0) or 0)
        u = str(call_data.get("broker_user", "")).strip()
        pw = str(call_data.get("broker_password", "")).strip()
        return (h, p or broker_port, u, pw)

    async def _switch_broker_if_needed(call_data: dict) -> tuple[bool, tuple | None]:
        nonlocal broker_host, broker_port
        ov = _broker_override_from_call(call_data)
        if not ov or ov[0] == broker_host:
            return False, None
        h, p, u, pw = ov
        _fire_console_output(f"[MQTT] 切換 Broker → {h}:{p}", "broker/switch")
        def _sw():
            return mqtt_client.reconnect_to(h, p, u, pw)
        try:
            old = await hass.async_add_executor_job(_sw)
            broker_host = h
            broker_port = p
            await asyncio.sleep(0.3)
            return True, old
        except Exception as e:
            _fire_console_output(f"[ERROR] 切換 Broker 失敗: {e}", "broker/switch")
            return False, None

    async def _restore_broker_if_needed(switched: bool, old_values: tuple | None) -> None:
        if not switched or not old_values:
            return
        _fire_console_output(f"[MQTT] 還原 Broker → {old_values[0]}:{old_values[1]}", "broker/restore")
        try:
            await hass.async_add_executor_job(lambda: mqtt_client.reconnect_to(*old_values))
        except Exception as e:
            _fire_console_output(f"[WARN] 還原 Broker 失敗: {e}", "broker/restore")

    async def handle_send_command(call: ServiceCall) -> None:
        host = call.data.get("host", "")
        command = call.data.get("command", "")
        token = call.data.get("token", "")
        if not host or not command:
            return
        if not token:
            token = device_data[DATA_TOKENS].get(host, "00000000")

        allowed, reason = _policy_allows_command(host, command, dict(call.data))
        if not allowed:
            _append_audit(
                "policy_blocked",
                host=host,
                status="blocked",
                message=f"blocked dangerous command: {command}",
                details={"command": command, "matched_rule": reason},
            )
            hass.bus.async_fire(
                f"{DOMAIN}_policy_blocked",
                {"host": host, "command": command, "matched_rule": reason},
            )
            _fire_console_output(
                f"[POLICY] Blocked dangerous command for {host}: {command}. Use confirm=true or approve_operation first.",
                "service/send_command",
            )
            return

        switched, old_vals = await _switch_broker_if_needed(call.data)
        ok, err_text = await _ensure_backend_mqtt_connected("send_command")
        if not ok:
            detail = f": {err_text}" if err_text else ""
            _fire_console_output(
                f"[ERROR] Backend MQTT reconnect failed; command not sent ({broker_host}:{broker_port}){detail}",
                "service/send_command",
            )
            return

        def _send() -> None:
            mqtt_client.send_command(host, token, command)

        await hass.async_add_executor_job(_send)
        _mark_host_command(host, command)
        if reason:
            _append_audit(
                "policy_allow",
                host=host,
                message=f"allowed dangerous command: {command}",
                details={"command": command, "reason": reason},
            )

    async def handle_approve_operation(call: ServiceCall) -> None:
        host = str(call.data.get("host", "")).strip()
        command = str(call.data.get("command", "")).strip()
        if not host or not command:
            return
        ttl_seconds = int(call.data.get("ttl_seconds", _approval_window_seconds()))
        note = str(call.data.get("note", "")).strip() or None
        approval = _grant_approval(host, command, ttl_seconds=ttl_seconds, note=note)
        _append_audit(
            "approval_granted",
            host=host,
            message=f"approval granted for {command}",
            details=approval,
        )
        _fire_console_output(
            f"[POLICY] Approved dangerous command for {host} until {approval['expires_at']}: {command}",
            "service/approve_operation",
        )

    async def handle_request_token(call: ServiceCall) -> None:
        host = call.data.get("host", "")
        user = call.data.get("username", config.get(CONF_USERNAME, "admin"))
        pw = call.data.get("password", config.get(CONF_PASSWORD, ""))
        if not host:
            return

        switched, old_vals = await _switch_broker_if_needed(call.data)
        ok, err_text = await _ensure_backend_mqtt_connected("request_token")
        if not ok:
            detail = f": {err_text}" if err_text else ""
            _fire_console_output(
                f"[ERROR] Backend MQTT reconnect failed; token request not sent ({broker_host}:{broker_port}){detail}",
                "service/request_token",
            )
            return

        def _req() -> None:
            mqtt_client.request_token(host, user, pw)

        await hass.async_add_executor_job(_req)
        _append_audit(
            "request_token",
            host=host,
            message="request token",
            details={"username": user},
        )

    async def handle_mqtt_publish(call: ServiceCall) -> None:
        topic = call.data.get("topic", "")
        payload = call.data.get("payload", "")
        if not topic:
            return

        switched, old_vals = await _switch_broker_if_needed(call.data)
        ok, err_text = await _ensure_backend_mqtt_connected("mqtt_publish")
        if not ok:
            detail = f": {err_text}" if err_text else ""
            _fire_console_output(
                f"[ERROR] Backend MQTT reconnect failed; publish not sent ({broker_host}:{broker_port}){detail}",
                "service/mqtt_publish",
            )
            return

        def _pub() -> None:
            mqtt_client.publish_test(topic, payload)

        await hass.async_add_executor_job(_pub)
        _append_audit(
            "mqtt_publish",
            message=f"{topic} <= {payload[:120]}",
            details={"topic": topic},
        )

    async def handle_collect_neighbors(call: ServiceCall) -> None:
        import asyncio

        switched, old_vals = await _switch_broker_if_needed(call.data)
        broker_host_used = str(call.data.get("broker_host", broker_host)).strip() or broker_host
        broker_port_used = int(call.data.get("broker_port", 0) or broker_port) or broker_port

        ok, err_text = await _ensure_backend_mqtt_connected("collect_neighbors")
        if not ok:
            detail = f": {err_text}" if err_text else ""
            _fire_console_output(
                f"[ERROR] Backend MQTT reconnect failed; neighbor discovery not sent ({broker_host_used}:{broker_port_used}){detail}",
                "service/collect_neighbors",
            )
            return

        _fire_console_output(
            "[MQTT] Refreshing backend URCON subscriptions before discovery...",
            "service/collect_neighbors",
        )

        def _resubscribe_urcom() -> None:
            mqtt_client.subscribe_urcom()

        await hass.async_add_executor_job(_resubscribe_urcom)
        await asyncio.sleep(0.5)

        requested_host_name = str(
            call.data.get(CONF_DISCOVERY_HOST_NAME, discovery_host_name)
        ).strip() or DEFAULT_DISCOVERY_HOST_NAME
        requested_callback_ip = str(
            call.data.get(CONF_CALLBACK_IP, callback_ip)
        ).strip()
        requested_domain = str(call.data.get(CONF_DOMAIN, urcon_domain)).strip() or urcon_domain

        def _collect() -> tuple[str, dict[str, Any]]:
            return mqtt_client.collect_neighbors(
                host_name=requested_host_name,
                callback_ip=requested_callback_ip,
                domain=requested_domain,
            )

        try:
            topic, payload_obj = await hass.async_add_executor_job(_collect)
            _append_audit(
                "neighbor_discovery",
                message="collect neighbors",
                details={"topic": topic, "domain": requested_domain},
            )
            _fire_console_output(
                f"[URCON] Neighbor discovery sent via backend MQTT ({broker_host_used}:{broker_port_used})",
                "service/collect_neighbors",
            )
            _fire_console_output(
                f"[URCON] Topic={topic} Payload={json.dumps(payload_obj, ensure_ascii=False)}",
                "service/collect_neighbors",
            )
        except Exception as err:
            _fire_console_output(
                f"[ERROR] Neighbor discovery failed: {err}",
                "service/collect_neighbors",
            )
        finally:
            pass  # Stay on chosen broker

    async def handle_batch_command(call: ServiceCall) -> None:
        hosts_list = call.data.get("hosts", [])
        commands = call.data.get("commands", [])
        delay = int(call.data.get("delay", 1))

        import asyncio

        ok, err_text = await _ensure_backend_mqtt_connected("batch_command")
        if not ok:
            detail = f": {err_text}" if err_text else ""
            _fire_console_output(
                f"[ERROR] Backend MQTT reconnect failed; batch not started ({broker_host}:{broker_port}){detail}",
                "service/batch_command",
            )
            return

        for host in hosts_list:
            _mark_health_check(host)
            token = device_data[DATA_TOKENS].get(host, "00000000")
            for cmd in commands:
                allowed, reason = _policy_allows_command(host, cmd, dict(call.data))
                if not allowed:
                    _append_audit(
                        "policy_blocked",
                        host=host,
                        status="blocked",
                        message=f"blocked dangerous batch command: {cmd}",
                        details={"command": cmd, "matched_rule": reason},
                    )
                    _fire_console_output(
                        f"[POLICY] Skipped dangerous batch command for {host}: {cmd}",
                        "service/batch_command",
                    )
                    continue

                def _send_batch(h=host, t=token, c=cmd) -> None:
                    mqtt_client.send_command(h, t, c)

                await hass.async_add_executor_job(_send_batch)
                _mark_host_command(host, cmd, kind="batch_command")
                if reason:
                    _append_audit(
                        "policy_allow",
                        host=host,
                        message=f"allowed dangerous batch command: {cmd}",
                        details={"command": cmd, "reason": reason},
                    )
                await asyncio.sleep(delay)

    async def handle_run_health_check(call: ServiceCall) -> None:
        hosts_list = call.data.get("hosts", []) or list(device_data[DATA_HOSTS])
        delay = float(call.data.get("delay", 1.0))

        ok, err_text = await _ensure_backend_mqtt_connected("run_health_check")
        if not ok:
            detail = f": {err_text}" if err_text else ""
            _fire_console_output(
                f"[ERROR] Backend MQTT reconnect failed; health check not started ({broker_host}:{broker_port}){detail}",
                "service/run_health_check",
            )
            return

        for host in hosts_list:
            if host not in device_data[DATA_HOSTS]:
                continue
            _mark_health_check(host)
            _append_audit("health_check", host=host, message="run health check")

            def _req(h=host) -> None:
                mqtt_client.request_token(h, username, password)

            await hass.async_add_executor_job(_req)
            await asyncio.sleep(delay)

            token = device_data[DATA_TOKENS].get(host, "00000000")
            for cmd in ["sh ver", "sh clock", "sh result"]:
                def _send_health(h=host, t=token, c=cmd) -> None:
                    mqtt_client.send_command(h, t, c)

                await hass.async_add_executor_job(_send_health)
                _mark_host_command(host, cmd, kind="health_check_command")
                await asyncio.sleep(delay)

    async def handle_sync_backup_status(call: ServiceCall) -> None:
        hosts_list = call.data.get("hosts", []) or list(device_data[DATA_HOSTS])
        clear_missing = bool(call.data.get("clear_missing", False))
        metadata_root = _resolve_metadata_root(call.data.get("metadata_root"))

        try:
            records = await hass.async_add_executor_job(_load_latest_backup_metadata, metadata_root)
        except FileNotFoundError as err:
            _fire_console_output(f"[ERROR] {err}", "service/sync_backup_status")
            _append_audit(
                "backup_status_sync",
                status="error",
                message="backup status sync failed",
                details={"reason": str(err), "metadata_root": str(metadata_root)},
            )
            return
        except Exception as err:
            _fire_console_output(f"[ERROR] Failed to load backup metadata: {err}", "service/sync_backup_status")
            _append_audit(
                "backup_status_sync",
                status="error",
                message="backup status sync failed",
                details={"reason": str(err), "metadata_root": str(metadata_root)},
            )
            return

        synced_hosts: list[str] = []
        unmatched_records: list[dict[str, Any]] = []
        seen_hosts: set[str] = set()

        for record in records:
            host = _match_backup_record_to_host(record, hosts_list)
            if not host:
                unmatched_records.append(
                    {
                        "serial": record.get("serial"),
                        "host": record.get("host"),
                        "metadata_file": record.get("_metadata_file"),
                    }
                )
                continue
            _apply_backup_record_to_host(host, record)
            seen_hosts.add(host)
            synced_hosts.append(host)

        if clear_missing:
            for host in hosts_list:
                if host not in seen_hosts:
                    _clear_backup_fields(_ensure_host_state(host))

        payload = {
            "entry_id": entry.entry_id,
            "hosts": hosts_list,
            "metadata_root": str(metadata_root),
            "synced_hosts": synced_hosts,
            "synced_count": len(synced_hosts),
            "unmatched_records": unmatched_records,
            "unmatched_count": len(unmatched_records),
            "cleared_missing": clear_missing,
        }
        hass.bus.async_fire(f"{DOMAIN}_backup_status", payload)
        _append_audit(
            "backup_status_sync",
            message=f"sync backup status ({len(synced_hosts)}/{len(hosts_list)} hosts)",
            details={
                "metadata_root": str(metadata_root),
                "synced_count": len(synced_hosts),
                "unmatched_count": len(unmatched_records),
                "clear_missing": clear_missing,
            },
        )
        _fire_console_output(
            f"[BACKUP] Synced backup status for {len(synced_hosts)} host(s) from {metadata_root}",
            "service/sync_backup_status",
        )

    async def handle_compare_backups(call: ServiceCall) -> None:
        host = str(call.data.get("host", "")).strip()
        if not host:
            return
        serial = _resolve_serial_for_host(host)
        if not serial:
            _fire_console_output(
                f"[ERROR] No serial/token known for host {host}",
                "service/compare_backups",
            )
            return

        metadata_root = _resolve_metadata_root(call.data.get("metadata_root"))
        current_snapshot = str(call.data.get("current_snapshot", "")).strip() or None
        previous_snapshot = str(call.data.get("previous_snapshot", "")).strip() or None

        try:
            current_record = await hass.async_add_executor_job(
                lambda: _resolve_metadata_record(
                    metadata_root,
                    serial,
                    current_snapshot,
                    latest_index=0,
                )
            )
            previous_record = await hass.async_add_executor_job(
                lambda: _resolve_metadata_record(
                    metadata_root,
                    serial,
                    previous_snapshot,
                    latest_index=1,
                )
            )
        except Exception as err:
            _fire_console_output(f"[ERROR] Failed to load compare metadata: {err}", "service/compare_backups")
            _append_audit(
                "backup_compare",
                host=host,
                status="error",
                message="backup compare failed",
                details={"reason": str(err), "metadata_root": str(metadata_root)},
            )
            return

        if not current_record or not previous_record:
            _fire_console_output(
                f"[ERROR] Not enough snapshots to compare for {host} ({serial})",
                "service/compare_backups",
            )
            return

        payload = await hass.async_add_executor_job(
            _build_backup_compare_payload,
            host,
            serial,
            current_record,
            previous_record,
            metadata_root,
        )
        hass.bus.async_fire(f"{DOMAIN}_backup_compare", payload)
        _append_audit(
            "backup_compare",
            host=host,
            message=f"compare backups {payload['previous_snapshot']} -> {payload['current_snapshot']}",
            details={
                "serial": serial,
                "metadata_root": str(metadata_root),
                "line_additions": payload["line_additions"],
                "line_removals": payload["line_removals"],
            },
        )
        _fire_console_output(
            f"[BACKUP] Compared {host} snapshots {payload['previous_snapshot']} -> {payload['current_snapshot']}",
            "service/compare_backups",
        )

    async def handle_generate_restore_preview(call: ServiceCall) -> None:
        host = str(call.data.get("host", "")).strip()
        if not host:
            return
        serial = _resolve_serial_for_host(host)
        if not serial:
            _fire_console_output(
                f"[ERROR] No serial/token known for host {host}",
                "service/generate_restore_preview",
            )
            return

        metadata_root = _resolve_metadata_root(call.data.get("metadata_root"))
        snapshot = str(call.data.get("snapshot", "")).strip() or None

        try:
            target_record = await hass.async_add_executor_job(
                lambda: _resolve_metadata_record(
                    metadata_root,
                    serial,
                    snapshot,
                    latest_index=0,
                )
            )
        except Exception as err:
            _fire_console_output(f"[ERROR] Failed to load restore preview metadata: {err}", "service/generate_restore_preview")
            _append_audit(
                "restore_preview",
                host=host,
                status="error",
                message="restore preview failed",
                details={"reason": str(err), "metadata_root": str(metadata_root)},
            )
            return

        if not target_record:
            _fire_console_output(
                f"[ERROR] Snapshot not found for {host} ({serial})",
                "service/generate_restore_preview",
            )
            return

        payload = await hass.async_add_executor_job(
            _build_restore_preview_payload,
            host,
            serial,
            target_record,
            metadata_root,
        )
        hass.bus.async_fire(f"{DOMAIN}_restore_preview_generated", payload)
        _append_audit(
            "restore_preview",
            host=host,
            message=f"generate restore preview for {payload['target_snapshot']}",
            details={
                "serial": serial,
                "metadata_root": str(metadata_root),
                "target_snapshot": payload["target_snapshot"],
            },
        )
        _fire_console_output(
            f"[BACKUP] Generated restore preview for {host} snapshot {payload['target_snapshot']}",
            "service/generate_restore_preview",
        )

    async def handle_export_inventory(call: ServiceCall) -> None:
        hosts_list = call.data.get("hosts", []) or list(device_data[DATA_HOSTS])
        now = dt_util.utcnow()
        inventory: list[dict[str, Any]] = []
        for host in hosts_list:
            state = dict(_ensure_host_state(host))
            last_seen_text = state.get("last_seen")
            health = "offline"
            if last_seen_text:
                try:
                    last_seen = dt_util.parse_datetime(last_seen_text)
                    if last_seen is not None:
                        age = (now - last_seen).total_seconds()
                        health = "healthy" if age <= HEALTH_STALE_SECONDS else "stale"
                except Exception:
                    health = "unknown"
            state["health"] = health
            state["token"] = device_data[DATA_TOKENS].get(host, state.get("token"))
            inventory.append(state)

        hass.bus.async_fire(
            f"{DOMAIN}_inventory_exported",
            {"entry_id": entry.entry_id, "hosts": hosts_list, "inventory": inventory},
        )
        _append_audit(
            "inventory_export",
            message=f"export inventory ({len(hosts_list)} hosts)",
            details={"count": len(hosts_list)},
        )

    async def handle_export_binding_candidates(call: ServiceCall) -> None:
        hosts_list = call.data.get("hosts", []) or list(device_data[DATA_HOSTS])
        payload = _build_binding_candidate_export(hosts_list)
        hass.bus.async_fire(f"{DOMAIN}_binding_candidates_exported", payload)
        _append_audit(
            "binding_candidates_export",
            message=f"export binding candidates ({len(hosts_list)} hosts)",
            details={
                "count": len(hosts_list),
                "resolved": len(payload["binding_map"]),
                "unresolved": len(payload["unresolved_hosts"]),
            },
        )

    async def handle_generate_binding_map(call: ServiceCall) -> None:
        hosts_list = call.data.get("hosts", []) or list(device_data[DATA_HOSTS])
        payload = _build_binding_candidate_export(hosts_list)
        hass.bus.async_fire(
            f"{DOMAIN}_binding_map_generated",
            {
                "entry_id": payload["entry_id"],
                "hosts": payload["hosts"],
                "binding_map": payload["binding_map"],
                "binding_map_json": payload["binding_map_json"],
                "resolved": len(payload["binding_map"]),
                "unresolved_hosts": payload["unresolved_hosts"],
            },
        )
        _append_audit(
            "binding_map_generate",
            message=f"generate binding map ({len(hosts_list)} hosts)",
            details={
                "count": len(hosts_list),
                "resolved": len(payload["binding_map"]),
                "unresolved": len(payload["unresolved_hosts"]),
            },
        )

    async def handle_save_binding_map(call: ServiceCall) -> None:
        hosts_list = call.data.get("hosts", []) or list(device_data[DATA_HOSTS])
        overwrite = bool(call.data.get("overwrite", False))
        output_path = _resolve_output_path(
            call.data.get("path"),
            "binding-map.generated.json",
        )
        payload = _build_binding_candidate_export(hosts_list)
        try:
            await hass.async_add_executor_job(
                _write_text_file,
                output_path,
                payload["binding_map_json"],
                overwrite,
            )
        except FileExistsError as err:
            _fire_console_output(f"[ERROR] {err}", "service/save_binding_map")
            _append_audit(
                "binding_map_save",
                status="error",
                message="save binding map blocked",
                details={"path": str(output_path), "reason": str(err)},
            )
            return
        except Exception as err:
            _fire_console_output(f"[ERROR] Failed to save binding map: {err}", "service/save_binding_map")
            _append_audit(
                "binding_map_save",
                status="error",
                message="save binding map failed",
                details={"path": str(output_path), "reason": str(err)},
            )
            return

        hass.bus.async_fire(
            f"{DOMAIN}_binding_map_saved",
            {
                "entry_id": payload["entry_id"],
                "hosts": payload["hosts"],
                "path": str(output_path),
                "binding_map": payload["binding_map"],
                "binding_map_json": payload["binding_map_json"],
                "resolved": len(payload["binding_map"]),
                "unresolved_hosts": payload["unresolved_hosts"],
            },
        )
        _append_audit(
            "binding_map_save",
            message=f"saved binding map to {output_path}",
            details={
                "path": str(output_path),
                "count": len(hosts_list),
                "resolved": len(payload["binding_map"]),
                "unresolved": len(payload["unresolved_hosts"]),
            },
        )

    async def handle_generate_deploy(call: ServiceCall) -> None:
        """Generate deploy config and return as event."""
        config_text = generate_deploy_config(dict(call.data))
        hass.bus.async_fire(f"{DOMAIN}_deploy_generated", {"config": config_text})
        _append_audit("deploy_generate", message="generate deploy config")

    async def handle_add_device(call: ServiceCall) -> None:
        """Add a new device to the running config."""
        new_host = str(call.data.get("host", "")).strip()
        if not new_host:
            return
        if new_host in device_data[DATA_HOSTS]:
            _fire_console_output(f"[INFO] Host already exists: {new_host}", "service/add_device")
            return

        updated_hosts = [*device_data[DATA_HOSTS], new_host]
        device_data[DATA_HOSTS] = updated_hosts
        device_data[DATA_CONSOLE_HISTORY][new_host] = []
        _ensure_host_state(new_host)

        self_data = {**entry.data, CONF_HOSTS: updated_hosts}
        hass.config_entries.async_update_entry(entry, data=self_data)

        if mqtt_client.is_connected:
            def _sub_single() -> None:
                mqtt_client.subscribe_devices([new_host])

            await hass.async_add_executor_job(_sub_single)

        _fire_console_output(f"[INFO] Added device: {new_host}", "service/add_device")
        _append_audit("add_device", host=new_host, message=f"added device {new_host}")
        _LOGGER.info("Added new device: %s", new_host)

        # Entry update listener will reload the integration.

    if not hass.services.has_service(DOMAIN, "send_command"):
        hass.services.async_register(DOMAIN, "send_command", handle_send_command)
        hass.services.async_register(DOMAIN, "approve_operation", handle_approve_operation)
        hass.services.async_register(DOMAIN, "request_token", handle_request_token)
        hass.services.async_register(DOMAIN, "mqtt_publish", handle_mqtt_publish)
        hass.services.async_register(DOMAIN, "collect_neighbors", handle_collect_neighbors)
        hass.services.async_register(DOMAIN, "batch_command", handle_batch_command)
        hass.services.async_register(DOMAIN, "run_health_check", handle_run_health_check)
        hass.services.async_register(DOMAIN, "sync_backup_status", handle_sync_backup_status)
        hass.services.async_register(DOMAIN, "compare_backups", handle_compare_backups)
        hass.services.async_register(DOMAIN, "generate_restore_preview", handle_generate_restore_preview)
        hass.services.async_register(DOMAIN, "export_inventory", handle_export_inventory)
        hass.services.async_register(DOMAIN, "export_binding_candidates", handle_export_binding_candidates)
        hass.services.async_register(DOMAIN, "generate_binding_map", handle_generate_binding_map)
        hass.services.async_register(DOMAIN, "save_binding_map", handle_save_binding_map)
        hass.services.async_register(DOMAIN, "generate_deploy", handle_generate_deploy)
        hass.services.async_register(DOMAIN, "add_device", handle_add_device)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data:
            mqtt_client = data.get(DATA_MQTT)
            if mqtt_client:
                await hass.async_add_executor_job(mqtt_client.disconnect)

    remaining_entry_data = [
        value for value in hass.data.get(DOMAIN, {}).values()
        if isinstance(value, dict) and DATA_MQTT in value
    ]
    if not remaining_entry_data:
        for svc in [
            "send_command",
            "approve_operation",
            "request_token",
            "mqtt_publish",
            "collect_neighbors",
            "batch_command",
            "run_health_check",
            "sync_backup_status",
            "compare_backups",
            "generate_restore_preview",
            "export_inventory",
            "export_binding_candidates",
            "generate_binding_map",
            "save_binding_map",
            "generate_deploy",
            "add_device",
        ]:
            if hass.services.has_service(DOMAIN, svc):
                hass.services.async_remove(DOMAIN, svc)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when config-entry data/options change."""
    await hass.config_entries.async_reload(entry.entry_id)
