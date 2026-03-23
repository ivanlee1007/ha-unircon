"""Sensor platform for UNiNUS Remote Console."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_HOSTS,
    DATA_CONSOLE_HISTORY,
    DATA_TOKENS,
    DOMAIN,
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
    for host in hosts:
        entities.append(UNiNUSConsoleSensor(hass, entry, host))
        entities.append(UNiNUSStatusSensor(hass, entry, host))

    async_add_entities(entities, update_before_add=True)


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
        self._hass.bus.async_listen(f"{DOMAIN}_console", self._handle_message)

    async def async_update(self) -> None:
        """Update sensor state."""
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        history = data.get(DATA_CONSOLE_HISTORY, {}).get(self._host, [])
        if history:
            last = history[-1]
            line = last.get("line", "")
            if isinstance(line, dict):
                line = json.dumps(line, ensure_ascii=False)
            self._attr_native_value = str(line)[:200]
            self._attr_extra_state_attributes["history_count"] = len(history)


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
        self._hass.bus.async_listen(f"{DOMAIN}_console", self._handle_message)

    async def async_update(self) -> None:
        """Update sensor state."""
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        history = data.get(DATA_CONSOLE_HISTORY, {}).get(self._host, [])
        if history:
            self._attr_native_value = STATE_ONLINE
