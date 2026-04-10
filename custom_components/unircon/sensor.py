"""Sensor platform for UNiNUS Remote Console."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    DATA_AUDIT_LOG,
    DATA_CONSOLE_HISTORY,
    DATA_HOST_STATE,
    DATA_TOKENS,
    DOMAIN,
    HEALTH_STALE_SECONDS,
    STATE_OFFLINE,
    STATE_ONLINE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up UNiNUS sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    hosts = data.get("hosts", [])

    entities = []
    entities.append(UNiNUSFleetSummarySensor(hass, entry))
    entities.append(UNiNUSAuditLogSensor(hass, entry))
    for host in hosts:
        entities.append(UNiNUSConsoleSensor(hass, entry, host))
        entities.append(UNiNUSStatusSensor(hass, entry, host))
        entities.append(UNiNUSLastSeenSensor(hass, entry, host))
        entities.append(UNiNUSFirmwareSensor(hass, entry, host))

    async_add_entities(entities, update_before_add=True)


class UNiNUSFleetSummarySensor(SensorEntity):
    """Fleet-level summary for the current config entry."""

    _attr_icon = "mdi:server-network"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_name = f"UNiNUS {entry.title} Fleet Summary"
        self._attr_unique_id = f"unircon_{entry.entry_id[:8]}_fleet_summary"
        self._attr_native_value = "0/0 online"
        self._attr_extra_state_attributes = {}

    @callback
    def _handle_event(self, _event) -> None:
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._hass.bus.async_listen(f"{DOMAIN}_console", self._handle_event))
        self.async_on_remove(self._hass.bus.async_listen(f"{DOMAIN}_audit", self._handle_event))

    async def async_update(self) -> None:
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        hosts = data.get("hosts", [])
        state_map = data.get(DATA_HOST_STATE, {})
        now = dt_util.utcnow()
        online = 0
        healthy_hosts: list[str] = []
        stale_hosts: list[str] = []
        offline_hosts: list[str] = []
        firmware_versions: dict[str, str] = {}

        for host in hosts:
            state = state_map.get(host, {})
            last_seen_text = state.get("last_seen")
            if not last_seen_text:
                offline_hosts.append(host)
                continue
            try:
                last_seen = dt_util.parse_datetime(last_seen_text)
            except Exception:
                last_seen = None
            if last_seen is None:
                offline_hosts.append(host)
                continue
            online += 1
            age = (now - last_seen).total_seconds()
            if age <= HEALTH_STALE_SECONDS:
                healthy_hosts.append(host)
            else:
                stale_hosts.append(host)
            if state.get("firmware_version"):
                firmware_versions[host] = state["firmware_version"]

        self._attr_native_value = f"{online}/{len(hosts)} online"
        self._attr_extra_state_attributes = {
            "total_hosts": len(hosts),
            "online_hosts": healthy_hosts + stale_hosts,
            "healthy_hosts": healthy_hosts,
            "stale_hosts": stale_hosts,
            "offline_hosts": offline_hosts,
            "firmware_versions": firmware_versions,
        }


class UNiNUSAuditLogSensor(SensorEntity):
    """Expose latest integration audit entry."""

    _attr_icon = "mdi:clipboard-clock-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_name = f"UNiNUS {entry.title} Audit Log"
        self._attr_unique_id = f"unircon_{entry.entry_id[:8]}_audit_log"
        self._attr_native_value = "no audit yet"
        self._attr_extra_state_attributes = {"entries": []}

    @callback
    def _handle_audit(self, _event) -> None:
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._hass.bus.async_listen(f"{DOMAIN}_audit", self._handle_audit))

    async def async_update(self) -> None:
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        entries = data.get(DATA_AUDIT_LOG, [])
        if not entries:
            return
        latest = entries[-1]
        self._attr_native_value = latest.get("message", "audit")[:255]
        self._attr_extra_state_attributes = {
            "latest": latest,
            "entries": entries[-20:],
            "count": len(entries),
        }


class UNiNUSConsoleSensor(SensorEntity):
    """UNiNUS device console output sensor."""

    _attr_icon = "mdi:console"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, host: str) -> None:
        """Initialize the sensor."""
        self._hass = hass
        self._entry = entry
        self._host = host
        self._attr_name = f"UNiNUS {host} Console"
        self._attr_unique_id = f"unircon_{entry.entry_id[:8]}_{host}_console"
        self._attr_native_value: str | None = "等待指令..."
        self._attr_extra_state_attributes: dict[str, Any] = {
            "history": [],
            "history_count": 0,
            "host": host,
        }

    @callback
    def _handle_message(self, event) -> None:
        """Handle console message from MQTT."""
        if event.data.get("host") != self._host:
            return

        data = event.data.get("data", {})
        if isinstance(data, dict) and data.get("data", {}).get("output"):
            line = data["data"]["output"]
        elif isinstance(data, dict) and "raw" in data:
            line = data["raw"]
        else:
            line = json.dumps(data, ensure_ascii=False)

        self._attr_native_value = line
        history = self._attr_extra_state_attributes.get("history", [])
        history.append(line)
        if len(history) > 200:
            history = history[-200:]
        self._attr_extra_state_attributes["history"] = history
        self._attr_extra_state_attributes["history_count"] = len(history)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register event listener."""
        self.async_on_remove(
            self._hass.bus.async_listen(f"{DOMAIN}_console", self._handle_message)
        )

    async def async_update(self) -> None:
        """Update sensor state."""
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        history = data.get(DATA_CONSOLE_HISTORY, {}).get(self._host, [])
        if history:
            lines = [str(item.get("line", "")) for item in history[-200:]]
            last = lines[-1]
            self._attr_native_value = last[:200]
            self._attr_extra_state_attributes["history"] = lines
            self._attr_extra_state_attributes["history_count"] = len(lines)


class UNiNUSStatusSensor(SensorEntity):
    """UNiNUS device connection status sensor."""

    _attr_icon = "mdi:lan-connect"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, host: str) -> None:
        """Initialize the sensor."""
        self._hass = hass
        self._entry = entry
        self._host = host
        self._attr_name = f"UNiNUS {host} Status"
        self._attr_unique_id = f"unircon_{entry.entry_id[:8]}_{host}_status"
        self._attr_native_value = STATE_OFFLINE
        self._attr_extra_state_attributes: dict[str, Any] = {"host": host}

    @callback
    def _handle_message(self, event) -> None:
        """Update status when we receive messages from this device."""
        if event.data.get("host") == self._host:
            self._attr_native_value = STATE_ONLINE
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register event listener."""
        self.async_on_remove(
            self._hass.bus.async_listen(f"{DOMAIN}_console", self._handle_message)
        )

    async def async_update(self) -> None:
        """Update sensor state."""
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        state_map = data.get(DATA_HOST_STATE, {})
        state = state_map.get(self._host, {})
        last_seen_text = state.get("last_seen")
        self._attr_extra_state_attributes = {
            "host": self._host,
            "last_seen": last_seen_text,
            "last_command": state.get("last_command"),
            "firmware_version": state.get("firmware_version"),
            "last_error": state.get("last_error"),
        }
        if not last_seen_text:
            self._attr_native_value = STATE_OFFLINE
            return
        try:
            last_seen = dt_util.parse_datetime(last_seen_text)
        except Exception:
            last_seen = None
        if last_seen is None:
            self._attr_native_value = STATE_OFFLINE
            return
        age = (dt_util.utcnow() - last_seen).total_seconds()
        self._attr_native_value = STATE_ONLINE if age <= HEALTH_STALE_SECONDS else "stale"


class UNiNUSLastSeenSensor(SensorEntity):
    """Track when a device last talked to the integration."""

    _attr_icon = "mdi:clock-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, host: str) -> None:
        self._hass = hass
        self._entry = entry
        self._host = host
        self._attr_name = f"UNiNUS {host} Last Seen"
        self._attr_unique_id = f"unircon_{entry.entry_id[:8]}_{host}_last_seen"
        self._attr_native_value = "never"

    @callback
    def _handle_message(self, event) -> None:
        if event.data.get("host") == self._host:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._hass.bus.async_listen(f"{DOMAIN}_console", self._handle_message)
        )

    async def async_update(self) -> None:
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        state = data.get(DATA_HOST_STATE, {}).get(self._host, {})
        self._attr_native_value = state.get("last_seen") or "never"
        self._attr_extra_state_attributes = {
            "host": self._host,
            "last_topic": state.get("last_topic"),
            "message_count": state.get("message_count", 0),
        }


class UNiNUSFirmwareSensor(SensorEntity):
    """Track discovered firmware version for a host."""

    _attr_icon = "mdi:chip"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, host: str) -> None:
        self._hass = hass
        self._entry = entry
        self._host = host
        self._attr_name = f"UNiNUS {host} Firmware"
        self._attr_unique_id = f"unircon_{entry.entry_id[:8]}_{host}_firmware"
        self._attr_native_value = "unknown"

    @callback
    def _handle_message(self, event) -> None:
        if event.data.get("host") == self._host:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._hass.bus.async_listen(f"{DOMAIN}_console", self._handle_message)
        )

    async def async_update(self) -> None:
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        state = data.get(DATA_HOST_STATE, {}).get(self._host, {})
        self._attr_native_value = state.get("firmware_version") or "unknown"
        self._attr_extra_state_attributes = {
            "host": self._host,
            "device_model": state.get("device_model"),
            "last_health_check_at": state.get("last_health_check_at"),
        }
