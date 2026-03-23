"""Config flow for UNiNUS Remote Console integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_BROKER_HOST,
    CONF_BROKER_PORT,
    CONF_DOMAIN,
    CONF_HOSTS,
    CONF_PASSWORD,
    CONF_SUBSCRIBE_TOPIC,
    CONF_USERNAME,
    DEFAULT_BROKER_PORT,
    DEFAULT_DOMAIN,
    DEFAULT_SUBSCRIBE_TOPIC,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class UNiNUSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UNiNUS Remote Console."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step - MQTT broker connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate MQTT connection
            try:
                def _test_mqtt() -> tuple[bool, str]:
                    import paho.mqtt.client as mqtt

                    # Use v2 API if available (paho-mqtt >= 2.0), fallback to v1
                    try:
                        client = mqtt.Client(
                            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                            client_id="ha-unircon-setup",
                        )
                    except AttributeError:
                        client = mqtt.Client(
                            client_id="ha-unircon-setup",
                        )

                    client.username_pw_set(
                        user_input.get(CONF_USERNAME, ""),
                        user_input.get(CONF_PASSWORD, ""),
                    )
                    try:
                        client.connect(
                            user_input[CONF_BROKER_HOST],
                            int(user_input.get(CONF_BROKER_PORT, DEFAULT_BROKER_PORT)),
                            timeout=10,
                        )
                        client.disconnect()
                        return True, ""
                    except ConnectionRefusedError:
                        return False, "cannot_connect"
                    except TimeoutError:
                        return False, "cannot_connect"
                    except Exception as err:
                        return False, str(err)

                ok, err = await self.hass.async_add_executor_job(_test_mqtt)
                if not ok:
                    errors["base"] = "cannot_connect" if err == "cannot_connect" else "unknown"
                    _LOGGER.warning("MQTT test failed: %s", err)
            except Exception as err:
                _LOGGER.error("MQTT validation error: %s", err)
                errors["base"] = "unknown"

            if not errors:
                self._broker_config = user_input
                return await self.async_step_devices()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BROKER_HOST, default="192.168.1.222"): str,
                    vol.Required(CONF_BROKER_PORT, default=DEFAULT_BROKER_PORT): int,
                    vol.Required(CONF_USERNAME, default="admin"): str,
                    vol.Required(CONF_PASSWORD, default="uninus@99"): str,
                    vol.Optional(CONF_DOMAIN, default=DEFAULT_DOMAIN): str,
                }
            ),
            errors=errors,
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle device list step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            hosts_raw = user_input.get(CONF_HOSTS, "")
            hosts = [
                h.strip()
                for h in hosts_raw.replace("\r\n", "\n").split("\n")
                if h.strip()
            ]

            return self.async_create_entry(
                title=f"UNiNUS ({self._broker_config[CONF_BROKER_HOST]})",
                data={
                    **self._broker_config,
                    CONF_HOSTS: hosts,
                    CONF_SUBSCRIBE_TOPIC: DEFAULT_SUBSCRIBE_TOPIC,
                },
            )

        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_HOSTS, default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> config_entries.ConfigFlowResult:
        """Handle reauthorization."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm reauth."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            if entry:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, **user_input},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
