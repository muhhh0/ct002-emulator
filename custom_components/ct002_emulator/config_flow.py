"""Config flow for CT002 Grid Meter Emulator integration."""

from __future__ import annotations

import random
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CT_MAC_ADDRESS,
    CONF_EMAIL,
    CONF_ENABLED,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_POWER_ENTITY,
    CONF_REGISTRATION_MODE,
    CONF_SELECTED_DEVICE,
    CONF_SERVER,
    DEFAULT_ENABLED,
    DEFAULT_NAME,
    DEFAULT_SERVER,
    DOMAIN,
    MARSTEK_SERVERS,
    REGISTRATION_MODE_EXISTING,
    REGISTRATION_MODE_NEW,
    REGISTRATION_MODE_NONE,
)
from .marstek_cloud import (
    InvalidCredentials,
    MarstekError,
    async_login,
    async_login_and_list_ct002,
    async_register_new_device,
    filter_ct002_devices,
)

_SERVER_OPTIONS = [
    selector.SelectOptionDict(value="eu", label="EU (eu.hamedata.com)"),
    selector.SelectOptionDict(value="us", label="US (us.hamedata.com)"),
]

_REGISTRATION_OPTIONS = [
    selector.SelectOptionDict(value=REGISTRATION_MODE_NONE, label="No cloud registration"),
    selector.SelectOptionDict(value=REGISTRATION_MODE_EXISTING, label="Use existing device from Marstek App"),
    selector.SelectOptionDict(value=REGISTRATION_MODE_NEW, label="Register new device in Marstek Cloud"),
]


def _generate_mac() -> str:
    """Generate a random valid 12-char hex MAC (no colons, lowercase)."""
    return "a020a6" + f"{random.randint(0, 0xFFFFFF):06x}"


def _is_valid_mac(mac: str) -> bool:
    """Validate MAC format: 12 hex chars (no colons) or XX:XX:XX:XX:XX:XX."""
    return bool(re.match(r"^[0-9a-f]{12}$", mac) or re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac))


def _normalize_mac(mac: str) -> str:
    """Normalize MAC to 12 lowercase hex chars (no colons)."""
    return mac.replace(":", "").lower()


class CT002EmulatorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CT002 Grid Meter Emulator."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._name: str = DEFAULT_NAME
        self._registration_mode: str = REGISTRATION_MODE_NONE
        self._ct_mac: str = ""
        self._cloud_email: str = ""
        self._cloud_password: str = ""
        self._cloud_server: str = DEFAULT_SERVER
        self._cloud_token: str = ""
        self._cloud_devices: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step — name only."""
        if user_input is not None:
            self._name = user_input.get(CONF_NAME, DEFAULT_NAME).strip() or DEFAULT_NAME
            return await self.async_step_registration()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            ),
        )

    async def async_step_registration(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the registration mode selection."""
        if user_input is not None:
            self._registration_mode = user_input[CONF_REGISTRATION_MODE]

            if self._registration_mode == REGISTRATION_MODE_NONE:
                return await self.async_step_manual_mac()
            if self._registration_mode == REGISTRATION_MODE_EXISTING:
                return await self.async_step_cloud_login()
            if self._registration_mode == REGISTRATION_MODE_NEW:
                return await self.async_step_cloud_login()

        return self.async_show_form(
            step_id="registration",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REGISTRATION_MODE, default=REGISTRATION_MODE_NONE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_REGISTRATION_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_manual_mac(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual MAC entry (no cloud registration)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ct_mac = user_input.get(CONF_CT_MAC_ADDRESS, "").strip()
            if ct_mac and not _is_valid_mac(ct_mac):
                errors[CONF_CT_MAC_ADDRESS] = "invalid_mac"
            else:
                if not ct_mac:
                    self._ct_mac = _generate_mac()
                else:
                    self._ct_mac = _normalize_mac(ct_mac)

                await self.async_set_unique_id(self._ct_mac)
                self._abort_if_unique_id_configured()

                data = {
                    CONF_NAME: self._name,
                    CONF_CT_MAC_ADDRESS: self._ct_mac,
                    CONF_POWER_ENTITY: user_input[CONF_POWER_ENTITY],
                    CONF_ENABLED: DEFAULT_ENABLED,
                }
                return self.async_create_entry(title=self._name, data=data)

        return self.async_show_form(
            step_id="manual_mac",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_CT_MAC_ADDRESS, default=""): str,
                    vol.Required(CONF_POWER_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor",
                            device_class="power",
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_cloud_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Marstek Cloud login (email, password, server)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._cloud_email = user_input[CONF_EMAIL].strip()
            self._cloud_password = user_input[CONF_PASSWORD]
            self._cloud_server = user_input[CONF_SERVER]

            if not self._cloud_email:
                errors[CONF_EMAIL] = "required"
            elif not self._cloud_password:
                errors[CONF_PASSWORD] = "required"
            else:
                base_url = MARSTEK_SERVERS[self._cloud_server]

                try:
                    import aiohttp
                    async with aiohttp.ClientSession() as session:
                        token, devices = await async_login(
                            session, self._cloud_email, self._cloud_password, base_url
                        )
                except InvalidCredentials:
                    errors["base"] = "invalid_credentials"
                except MarstekError as exc:
                    errors["base"] = "marstek_error"
                    errors["marstek_detail"] = str(exc)
                else:
                    self._cloud_token = token
                    self._cloud_devices = devices

                    if self._registration_mode == REGISTRATION_MODE_EXISTING:
                        return await self.async_step_select_device()
                    if self._registration_mode == REGISTRATION_MODE_NEW:
                        return await self.async_step_new_device()

        return self.async_show_form(
            step_id="cloud_login",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_SERVER, default=DEFAULT_SERVER): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_SERVER_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle selection of an existing CT002 device from the cloud."""
        errors: dict[str, str] = {}

        ct002_devices = filter_ct002_devices(self._cloud_devices)

        if not ct002_devices:
            errors["base"] = "no_devices_found"
            return self.async_show_form(
                step_id="select_device",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        if user_input is not None:
            selected_devid = user_input[CONF_SELECTED_DEVICE]
            self._ct_mac = _normalize_mac(selected_devid)

            await self.async_set_unique_id(self._ct_mac)
            self._abort_if_unique_id_configured()

            return await self.async_step_sensor()

        device_options = [
            selector.SelectOptionDict(
                value=d["devid"],
                label=f"{d.get('name', 'CT002')} ({d['devid']})",
            )
            for d in ct002_devices
            if d.get("devid")
        ]

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SELECTED_DEVICE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=device_options,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_new_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle registration of a new CT002 device in the cloud."""
        errors: dict[str, str] = {}

        base_url = MARSTEK_SERVERS[self._cloud_server]
        tz = self.hass.config.time_zone or "UTC"

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                self._ct_mac = await async_register_new_device(
                    session,
                    self._cloud_email,
                    self._cloud_password,
                    base_url,
                    tz,
                    self._name,
                )
        except InvalidCredentials:
            errors["base"] = "invalid_credentials"
        except MarstekError as exc:
            errors["base"] = "marstek_error"
            errors["marstek_detail"] = str(exc)
        else:
            await self.async_set_unique_id(self._ct_mac)
            self._abort_if_unique_id_configured()
            return await self.async_step_sensor()

        return self.async_show_form(
            step_id="cloud_login",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=self._cloud_email): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_SERVER, default=self._cloud_server): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_SERVER_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the final step — power sensor selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not self._ct_mac:
                self._ct_mac = _generate_mac()

            await self.async_set_unique_id(self._ct_mac)
            self._abort_if_unique_id_configured()

            data = {
                CONF_NAME: self._name,
                CONF_CT_MAC_ADDRESS: self._ct_mac,
                CONF_POWER_ENTITY: user_input[CONF_POWER_ENTITY],
                CONF_ENABLED: DEFAULT_ENABLED,
            }
            return self.async_create_entry(title=self._name, data=data)

        return self.async_show_form(
            step_id="sensor",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POWER_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor",
                            device_class="power",
                        )
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CT002EmulatorOptionsFlow:
        """Get the options flow for this handler."""
        return CT002EmulatorOptionsFlow()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            ct_mac = user_input.get(CONF_CT_MAC_ADDRESS, "").strip()
            if ct_mac and not _is_valid_mac(ct_mac):
                errors[CONF_CT_MAC_ADDRESS] = "invalid_mac"
            else:
                if not ct_mac:
                    ct_mac = _generate_mac()
                else:
                    ct_mac = _normalize_mac(ct_mac)

                new_data = {
                    **entry.data,
                    CONF_NAME: user_input.get(CONF_NAME, entry.data.get(CONF_NAME, DEFAULT_NAME)),
                    CONF_CT_MAC_ADDRESS: ct_mac,
                    CONF_POWER_ENTITY: user_input[CONF_POWER_ENTITY],
                }

                if ct_mac.lower() != entry.unique_id:
                    await self.async_set_unique_id(ct_mac)
                    self._abort_if_unique_id_configured()

                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        current_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
        current_mac = entry.data.get(CONF_CT_MAC_ADDRESS, "")
        current_power_entity = entry.data.get(CONF_POWER_ENTITY, "")

        reconfigure_schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=current_name): str,
                vol.Optional(CONF_CT_MAC_ADDRESS, default=current_mac): str,
                vol.Required(CONF_POWER_ENTITY, default=current_power_entity): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="power",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=reconfigure_schema,
            errors=errors,
            description_placeholders={"name": current_name},
        )


class CT002EmulatorOptionsFlow(config_entries.OptionsFlow):
    """Handle options for CT002 Grid Meter Emulator."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_power_entity = self.config_entry.data.get(CONF_POWER_ENTITY, "")

        options_schema = vol.Schema(
            {
                vol.Required(CONF_POWER_ENTITY, default=current_power_entity): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="power",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
