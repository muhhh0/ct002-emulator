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
    CONF_ENABLED,
    CONF_NAME,
    CONF_POWER_ENTITY,
    DEFAULT_ENABLED,
    DEFAULT_NAME,
    DOMAIN,
)


def _generate_mac() -> str:
    """Generate a random valid 12-char hex MAC (no colons, lowercase)."""
    return "a020a6" + f"{random.randint(0, 0xFFFFFF):06x}"


def _is_valid_mac(mac: str) -> bool:
    """Validate MAC format: 12 hex chars (no colons) or XX:XX:XX:XX:XX:XX."""
    return bool(re.match(r"^[0-9a-f]{12}$", mac) or re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac))


def _normalize_mac(mac: str) -> str:
    """Normalize MAC to 12 lowercase hex chars (no colons)."""
    return mac.replace(":", "").lower()


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Optional(CONF_CT_MAC_ADDRESS, default=""): str,
        vol.Required(CONF_POWER_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class="power",
            )
        ),
    }
)


class CT002EmulatorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CT002 Grid Meter Emulator."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ct_mac = user_input.get(CONF_CT_MAC_ADDRESS, "").strip()
            if ct_mac and not _is_valid_mac(ct_mac):
                errors[CONF_CT_MAC_ADDRESS] = "invalid_mac"
            else:
                if not ct_mac:
                    ct_mac = _generate_mac()
                else:
                    ct_mac = _normalize_mac(ct_mac)

                await self.async_set_unique_id(ct_mac)
                self._abort_if_unique_id_configured()

                data = {
                    CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                    CONF_CT_MAC_ADDRESS: ct_mac,
                    CONF_POWER_ENTITY: user_input[CONF_POWER_ENTITY],
                    CONF_ENABLED: DEFAULT_ENABLED,
                }
                return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
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
