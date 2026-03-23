"""UNiNUS Remote Console integration for Home Assistant."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
import voluptuous as vol

from .const import (
    CONF_BROKER_HOST,
    CONF_BROKER_PORT,
    CONF_DOMAIN,
    CONF_HOSTS,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)
from .mqtt_helper import UNiNUSMQTT

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.TEXT]

# Store MQTT client and device state in hass.data[DOMAIN]
DATA_MQTT = "mqtt"
DATA_HOSTS = "hosts"
DATA_TOKENS = "tokens"
DATA_CONSOLE_HISTORY = "console_history"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up UNiNUS from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = entry.data
    broker_host = config[CONF_BROKER_HOST]
    broker_port = int(config.get("broker_port", 1884))
    username = config[CONF_USERNAME]
    password = config[CONF_PASSWORD]
    urcon_domain = config.get(CONF_DOMAIN, "uninus")
    hosts = config.get(CONF_HOSTS, [])

    # Create MQTT client (runs in executor)
    mqtt_client = UNiNUSMQTT(
        host=broker_host,
        port=broker_port,
        username=username,
        password=password,
        urcon_domain=urcon_domain,
        host_name=f"ha-unircon-{entry.entry_id[:8]}",
    )

    # Store state
    device_data = {
        DATA_MQTT: mqtt_client,
        DATA_HOSTS: hosts,
        DATA_TOKENS: {},
        DATA_CONSOLE_HISTORY: {h: [] for h in hosts},
    }
    hass.data[DOMAIN][entry.entry_id] = device_data

    # Connect MQTT
    def _connect_mqtt() -> None:
        mqtt_client.connect()

    await hass.async_add_executor_job(_connect_mqtt)

    # Subscribe to device topics
    def _subscribe() -> None:
        if hosts:
            mqtt_client.subscribe_devices(hosts)
        mqtt_client.subscribe_urcom()

    await hass.async_add_executor_job(_subscribe)

    # Set up message handler
    def _on_message(topic: str, payload: str) -> None:
        """Handle incoming MQTT messages."""
        try:
            # Try to parse JSON
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                data = {"raw": payload}

            # Route message to correct device based on topic
            for host in hosts:
                if f"/{host}/console/" in topic or f"pubrsp/{host}" in topic:
                    history = device_data[DATA_CONSOLE_HISTORY].get(host, [])
                    line = data.get("data", {}).get("output", payload) if isinstance(data, dict) else payload
                    history.append({"topic": topic, "data": data, "line": line})
                    # Keep last 500 lines
                    if len(history) > 500:
                        history[:] = history[-500:]
                    device_data[DATA_CONSOLE_HISTORY][host] = history

                    # Handle token response
                    if isinstance(data, dict) and "token" in data:
                        device_data[DATA_TOKENS][host] = data["token"]
                        _LOGGER.info("Got token for %s: %s", host, data.get("deviceid", ""))

                    # Fire event for card updates
                    hass.bus.async_fire(
                        f"{DOMAIN}_console",
                        {"host": host, "topic": topic, "data": data},
                    )
                    break
        except Exception as err:
            _LOGGER.error("Message handling error: %s", err)

    mqtt_client.on_message(_on_message)

    # Register services
    async def handle_send_command(call: ServiceCall) -> None:
        """Handle the send_command service."""
        host = call.data.get("host", "")
        command = call.data.get("command", "")
        token = call.data.get("token", "")
        # If no token provided, try from stored tokens
        if not token:
            token = device_data[DATA_TOKENS].get(host, "00000000")

        def _send() -> None:
            mqtt_client.send_command(host, token, command)

        await hass.async_add_executor_job(_send)
        _LOGGER.info("Service send_command: host=%s cmd=%s", host, command)

    async def handle_request_token(call: ServiceCall) -> None:
        """Handle the request_token service."""
        host = call.data.get("host", "")
        username = call.data.get("username", config.get(CONF_USERNAME, "admin"))
        password = call.data.get("password", config.get(CONF_PASSWORD, ""))

        def _req() -> None:
            mqtt_client.request_token(host, username, password)

        await hass.async_add_executor_job(_req)

    async def handle_mqtt_publish(call: ServiceCall) -> None:
        """Handle the mqtt_publish test service."""
        topic = call.data.get("topic", "")
        payload = call.data.get("payload", "")

        def _pub() -> None:
            mqtt_client.publish_test(topic, payload)

        await hass.async_add_executor_job(_pub)

    async def handle_collect_neighbors(call: ServiceCall) -> None:
        """Handle the collect_neighbors service."""

        def _collect() -> None:
            mqtt_client.collect_neighbors()

        await hass.async_add_executor_job(_collect)

    async def handle_batch_command(call: ServiceCall) -> None:
        """Handle batch command execution across multiple hosts."""
        hosts_list = call.data.get("hosts", [])
        commands = call.data.get("commands", [])
        delay = int(call.data.get("delay", 1))

        import asyncio

        for host in hosts_list:
            token = device_data[DATA_TOKENS].get(host, "00000000")
            for cmd in commands:
                def _send_batch(h=host, t=token, c=cmd) -> None:
                    mqtt_client.send_command(h, t, c)

                await hass.async_add_executor_job(_send_batch)
                await asyncio.sleep(delay)

    hass.services.async_register(DOMAIN, "send_command", handle_send_command)
    hass.services.async_register(DOMAIN, "request_token", handle_request_token)
    hass.services.async_register(DOMAIN, "mqtt_publish", handle_mqtt_publish)
    hass.services.async_register(DOMAIN, "collect_neighbors", handle_collect_neighbors)
    hass.services.async_register(DOMAIN, "batch_command", handle_batch_command)

    # Forward to platforms
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

    # Remove services if no more entries
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, "send_command")
        hass.services.async_remove(DOMAIN, "request_token")
        hass.services.async_remove(DOMAIN, "mqtt_publish")
        hass.services.async_remove(DOMAIN, "collect_neighbors")
        hass.services.async_remove(DOMAIN, "batch_command")

    return unload_ok
