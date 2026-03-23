"""Text platform for UNiNUS Remote Console (token display)."""

from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HOSTS, DATA_TOKENS, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up UNiNUS text entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    hosts = data.get(CONF_HOSTS, [])

    entities = []
    for host in hosts:
        entities.append(UNiNUSTokenText(hass, entry, host))

    async_add_entities(entities, update_before_add=True)


class UNiNUSTokenText(TextEntity):
    """Text entity showing device token/serial number."""

    _attr_icon = "mdi:identifier"
    _attr_native_value = ""
    _attr_native_min = 0
    _attr_native_max = 128
    _attr_native_mode = "text"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, host: str) -> None:
        """Initialize the text entity."""
        self._hass = hass
        self._entry = entry
        self._host = host
        self._attr_name = f"UNiNUS {host} Token"
        self._attr_unique_id = f"unircon_{entry.entry_id[:8]}_{host}_token"
        self._attr_extra_state_attributes = {"host": host}

    @callback
    def _handle_message(self, event) -> None:
        """Update token when received from device."""
        if event.data.get("host") != self._host:
            return
        data = event.data.get("data", {})
        if isinstance(data, dict) and "token" in data:
            token = data["token"]
            self._attr_native_value = token
            device_id = data.get("deviceid", "")
            if device_id:
                self._attr_extra_state_attributes["device_id"] = device_id
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register event listener."""
        self.async_on_remove(
            self._hass.bus.async_listen(f"{DOMAIN}_console", self._handle_message)
        )

    async def async_update(self) -> None:
        """Update from stored data."""
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        token = data.get(DATA_TOKENS, {}).get(self._host, "")
        if token:
            self._attr_native_value = token

    async def async_set_value(self, value: str) -> None:
        """Set token value manually (stored in memory only)."""
        self._attr_native_value = value
        data = self._hass.data[DOMAIN][self._entry.entry_id]
        data.setdefault(DATA_TOKENS, {})[self._host] = value
        self.async_write_ha_state()
