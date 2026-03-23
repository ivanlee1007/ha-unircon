"""UNiNUS Remote Console integration for Home Assistant."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
import voluptuous as vol

from .const import (
    CARD_RESOURCE_URL,
    CARD_STATIC_URL,
    CONF_BROKER_HOST,
    CONF_BROKER_PORT,
    CONF_CALLBACK_IP,
    CONF_DISCOVERY_HOST_NAME,
    CONF_DOMAIN,
    CONF_HOSTS,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_BROKER_PORT,
    DEFAULT_DISCOVERY_HOST_NAME,
    DOMAIN,
)
from .mqtt_helper import UNiNUSMQTT

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.TEXT]

DATA_MQTT = "mqtt"
DATA_HOSTS = "hosts"
DATA_TOKENS = "tokens"
DATA_CONSOLE_HISTORY = "console_history"


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

    config = entry.data
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
    }
    hass.data[DOMAIN][entry.entry_id] = device_data

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
                    line = data.get("data", {}).get("output", payload) if isinstance(data, dict) else payload
                    history.append({"topic": topic, "data": data, "line": line})
                    if len(history) > 500:
                        history[:] = history[-500:]
                    device_data[DATA_CONSOLE_HISTORY][host] = history

                    if isinstance(data, dict) and "token" in data:
                        device_data[DATA_TOKENS][host] = data["token"]

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
    async def handle_send_command(call: ServiceCall) -> None:
        host = call.data.get("host", "")
        command = call.data.get("command", "")
        token = call.data.get("token", "")
        if not host or not command:
            return
        if not token:
            token = device_data[DATA_TOKENS].get(host, "00000000")

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

    async def handle_request_token(call: ServiceCall) -> None:
        host = call.data.get("host", "")
        user = call.data.get("username", config.get(CONF_USERNAME, "admin"))
        pw = call.data.get("password", config.get(CONF_PASSWORD, ""))
        if not host:
            return

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

    async def handle_mqtt_publish(call: ServiceCall) -> None:
        topic = call.data.get("topic", "")
        payload = call.data.get("payload", "")
        if not topic:
            return

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

    async def handle_collect_neighbors(call: ServiceCall) -> None:
        import asyncio

        ok, err_text = await _ensure_backend_mqtt_connected("collect_neighbors")
        if not ok:
            detail = f": {err_text}" if err_text else ""
            _fire_console_output(
                f"[ERROR] Backend MQTT reconnect failed; neighbor discovery not sent ({broker_host}:{broker_port}){detail}",
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
            _fire_console_output(
                f"[URCON] Neighbor discovery sent via backend MQTT ({broker_host}:{broker_port})",
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
            token = device_data[DATA_TOKENS].get(host, "00000000")
            for cmd in commands:
                def _send_batch(h=host, t=token, c=cmd) -> None:
                    mqtt_client.send_command(h, t, c)

                await hass.async_add_executor_job(_send_batch)
                await asyncio.sleep(delay)

    async def handle_generate_deploy(call: ServiceCall) -> None:
        """Generate deploy config and return as event."""
        config_text = generate_deploy_config(dict(call.data))
        hass.bus.async_fire(f"{DOMAIN}_deploy_generated", {"config": config_text})

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

        self_data = {**entry.data, CONF_HOSTS: updated_hosts}
        hass.config_entries.async_update_entry(entry, data=self_data)

        if mqtt_client.is_connected:
            def _sub_single() -> None:
                mqtt_client.subscribe_devices([new_host])

            await hass.async_add_executor_job(_sub_single)

        _fire_console_output(f"[INFO] Added device: {new_host}", "service/add_device")
        _LOGGER.info("Added new device: %s", new_host)

        # Reload platforms to create persistent entities for new device.
        await hass.config_entries.async_reload(entry.entry_id)

    if not hass.services.has_service(DOMAIN, "send_command"):
        hass.services.async_register(DOMAIN, "send_command", handle_send_command)
        hass.services.async_register(DOMAIN, "request_token", handle_request_token)
        hass.services.async_register(DOMAIN, "mqtt_publish", handle_mqtt_publish)
        hass.services.async_register(DOMAIN, "collect_neighbors", handle_collect_neighbors)
        hass.services.async_register(DOMAIN, "batch_command", handle_batch_command)
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
            "request_token",
            "mqtt_publish",
            "collect_neighbors",
            "batch_command",
            "generate_deploy",
            "add_device",
        ]:
            if hass.services.has_service(DOMAIN, svc):
                hass.services.async_remove(DOMAIN, svc)

    return unload_ok
