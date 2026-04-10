"""Button platform for UNiNUS Remote Console."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HOSTS, DATA_TOKENS, DOMAIN

_LOGGER = logging.getLogger(__name__)

BUTTON_DEFINITIONS = [
    {"suffix": "enable", "name": "Enable", "command": "en {username} {password}", "icon": "mdi:key"},
    {"suffix": "show_version", "name": "Show Version", "command": "sh ver", "icon": "mdi:information"},
    {"suffix": "show_result", "name": "Show Result", "command": "sh result", "icon": "mdi:clipboard-text"},
    {"suffix": "health_check", "name": "Health Check", "command": None, "icon": "mdi:stethoscope"},
    {"suffix": "urcon_neighbors", "name": "URCON Neighbors", "command": "sh urcon/ne", "icon": "mdi:lan"},
    {"suffix": "backup", "name": "Backup", "command": "backup", "icon": "mdi:backup-restore"},
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up UNiNUS buttons from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    hosts = data.get(CONF_HOSTS, [])

    entities = []
    for host in hosts:
        for btn_def in BUTTON_DEFINITIONS:
            entities.append(
                UNiNUSCommandButton(hass, entry, host, btn_def)
            )

    async_add_entities(entities, update_before_add=True)


class UNiNUSCommandButton(ButtonEntity):
    """Button that sends a predefined command to a UNiNUS device."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        host: str,
        btn_def: dict,
    ) -> None:
        """Initialize the button."""
        self._hass = hass
        self._entry = entry
        self._host = host
        self._command_template = btn_def["command"]
        self._suffix = btn_def["suffix"]
        self._attr_name = f"UNiNUS {host} {btn_def['name']}"
        self._attr_unique_id = (
            f"unircon_{entry.entry_id[:8]}_{host}_{btn_def['suffix']}"
        )
        self._attr_icon = btn_def.get("icon", "mdi:play")

    async def async_press(self) -> None:
        """Press the button - send command to device."""
        if self._suffix == "health_check":
            await self._hass.services.async_call(
                DOMAIN,
                "run_health_check",
                {"hosts": [self._host], "delay": 1},
                blocking=True,
            )
            _LOGGER.info("Button pressed: %s → run_health_check", self._attr_name)
            return

        data = self._hass.data[DOMAIN][self._entry.entry_id]
        token = data.get(DATA_TOKENS, {}).get(self._host, "00000000")
        config = {**self._entry.data, **self._entry.options}

        # Build command from template
        cmd = self._command_template.format(
            username=config.get("username", "admin"),
            password=config.get("password", ""),
        )

        await self._hass.services.async_call(
            DOMAIN,
            "send_command",
            {"host": self._host, "command": cmd, "token": token},
            blocking=True,
        )
        _LOGGER.info("Button pressed: %s → %s", self._attr_name, cmd)
