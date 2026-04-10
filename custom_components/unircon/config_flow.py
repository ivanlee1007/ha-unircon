"""Config flow for UNiNUS Remote Console integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_APPROVAL_WINDOW_SECONDS,
    CONF_BROKER_HOST,
    CONF_BROKER_PORT,
    CONF_CALLBACK_IP,
    CONF_DISCOVERY_HOST_NAME,
    CONF_DOMAIN,
    CONF_HOSTS,
    CONF_PASSWORD,
    CONF_REQUIRE_CONFIRM_DANGEROUS,
    CONF_SUBSCRIBE_TOPIC,
    CONF_USERNAME,
    DEFAULT_APPROVAL_WINDOW_SECONDS,
    DEFAULT_BROKER_PORT,
    DEFAULT_DISCOVERY_HOST_NAME,
    DEFAULT_DOMAIN,
    DEFAULT_REQUIRE_CONFIRM_DANGEROUS,
    DEFAULT_SUBSCRIBE_TOPIC,
    DOMAIN,
)
from .mqtt_helper import UNiNUSMQTT

_LOGGER = logging.getLogger(__name__)


class UNiNUSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UNiNUS Remote Console."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return UNiNUSOptionsFlow()

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._broker_config: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step - MQTT broker connection."""
        errors: dict[str, str] = {}

        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            try:
                broker_host = user_input[CONF_BROKER_HOST]
                broker_port = int(user_input.get(CONF_BROKER_PORT, DEFAULT_BROKER_PORT))
                username = user_input.get(CONF_USERNAME, "")
                password = user_input.get(CONF_PASSWORD, "")
                urcon_domain = user_input.get(CONF_DOMAIN, DEFAULT_DOMAIN)
                discovery_host_name = user_input.get(
                    CONF_DISCOVERY_HOST_NAME, DEFAULT_DISCOVERY_HOST_NAME
                )
                callback_ip = user_input.get(CONF_CALLBACK_IP, "")

                def _test_mqtt() -> None:
                    client = UNiNUSMQTT(
                        host=broker_host,
                        port=broker_port,
                        username=username,
                        password=password,
                        urcon_domain=urcon_domain,
                        host_name="ha-unircon-setup",
                        discovery_host_name=discovery_host_name,
                        default_callback_ip=callback_ip,
                    )
                    try:
                        client.connect()
                    finally:
                        client.disconnect()

                await self.hass.async_add_executor_job(_test_mqtt)
            except Exception as err:
                _LOGGER.warning("MQTT validation error: %s", err)
                errors["base"] = "cannot_connect"

            if not errors:
                self._broker_config = dict(user_input)
                return await self.async_step_devices()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BROKER_HOST, default="192.168.1.222"): str,
                    vol.Required(CONF_BROKER_PORT, default=DEFAULT_BROKER_PORT): int,
                    vol.Optional(CONF_USERNAME, default="admin"): str,
                    vol.Optional(CONF_PASSWORD, default=""): str,
                    vol.Optional(CONF_DOMAIN, default=DEFAULT_DOMAIN): str,
                    vol.Optional(
                        CONF_DISCOVERY_HOST_NAME,
                        default=DEFAULT_DISCOVERY_HOST_NAME,
                    ): str,
                    vol.Optional(CONF_CALLBACK_IP, default=""): str,
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

            broker_host = self._broker_config.get(CONF_BROKER_HOST, "unknown")

            return self.async_create_entry(
                title=f"UNiNUS ({broker_host})",
                data={
                    **self._broker_config,
                    CONF_HOSTS: hosts,
                    CONF_SUBSCRIBE_TOPIC: DEFAULT_SUBSCRIBE_TOPIC,
                    CONF_REQUIRE_CONFIRM_DANGEROUS: DEFAULT_REQUIRE_CONFIRM_DANGEROUS,
                    CONF_APPROVAL_WINDOW_SECONDS: DEFAULT_APPROVAL_WINDOW_SECONDS,
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

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle reauthorization."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm reauth."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(
                self.context["entry_id"]
            )
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


class UNiNUSOptionsFlow(config_entries.OptionsFlow):
    """Options flow for UNiNUS Remote Console."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            approval_window = int(user_input.get(CONF_APPROVAL_WINDOW_SECONDS, DEFAULT_APPROVAL_WINDOW_SECONDS))
            if approval_window < 30:
                errors[CONF_APPROVAL_WINDOW_SECONDS] = "invalid_approval_window"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_REQUIRE_CONFIRM_DANGEROUS: bool(
                            user_input.get(
                                CONF_REQUIRE_CONFIRM_DANGEROUS,
                                DEFAULT_REQUIRE_CONFIRM_DANGEROUS,
                            )
                        ),
                        CONF_APPROVAL_WINDOW_SECONDS: approval_window,
                    },
                )

        options = self.config_entry.options
        data = self.config_entry.data
        require_confirm = options.get(
            CONF_REQUIRE_CONFIRM_DANGEROUS,
            data.get(CONF_REQUIRE_CONFIRM_DANGEROUS, DEFAULT_REQUIRE_CONFIRM_DANGEROUS),
        )
        approval_window = options.get(
            CONF_APPROVAL_WINDOW_SECONDS,
            data.get(CONF_APPROVAL_WINDOW_SECONDS, DEFAULT_APPROVAL_WINDOW_SECONDS),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REQUIRE_CONFIRM_DANGEROUS,
                        default=bool(require_confirm),
                    ): bool,
                    vol.Required(
                        CONF_APPROVAL_WINDOW_SECONDS,
                        default=int(approval_window),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                }
            ),
            errors=errors,
        )
