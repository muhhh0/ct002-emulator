"""Tests for the CT002 Grid Meter Emulator config, reconfigure, and options flows."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.ct002_emulator.config_flow import (
    CT002EmulatorConfigFlow,
    CT002EmulatorOptionsFlow,
    _get_current_power_entity,
    _is_valid_mac,
)
from custom_components.ct002_emulator.const import (
    CONF_CT_MAC_ADDRESS,
    CONF_EMAIL,
    CONF_ENABLED,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_POWER_ENTITY,
    CONF_SERVER,
    DEFAULT_NAME,
)
from custom_components.ct002_emulator.coordinator import CT002EmulatorCoordinator
from custom_components.ct002_emulator.marstek_cloud import MarstekError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    unique_id: str | None = "a020a6000001",
    entry_id: str = "entry_1",
    title: str = "Test CT002",
) -> MagicMock:
    """Create a mock ConfigEntry with realistic mutable dicts."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = title
    entry.unique_id = unique_id
    entry.data = dict(
        data
        if data is not None
        else {
            CONF_NAME: title,
            CONF_CT_MAC_ADDRESS: "a020a6000001",
            CONF_POWER_ENTITY: "sensor.old_power",
            CONF_ENABLED: True,
        }
    )
    entry.options = dict(options) if options is not None else {}
    return entry


def _make_hass(entry: MagicMock) -> MagicMock:
    """Create a mock HomeAssistant whose async_update_entry mutates entry."""
    hass = MagicMock()
    hass.loop = asyncio.new_event_loop()
    hass.states = MagicMock()
    hass.data = {}

    def _update_entry(
        target_entry: MagicMock,
        *,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        title: str | None = None,
        unique_id: str | None = None,
    ) -> bool:
        if data is not None:
            target_entry.data = dict(data)
        if options is not None:
            target_entry.options = dict(options)
        if title is not None:
            target_entry.title = title
        if unique_id is not None:
            target_entry.unique_id = unique_id
        return True

    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock(side_effect=_update_entry)
    hass.config_entries.async_reload = AsyncMock(return_value=True)
    return hass


def _make_reconfigure_flow(
    entry: MagicMock,
    hass: MagicMock | None = None,
) -> CT002EmulatorConfigFlow:
    """Instantiate CT002EmulatorConfigFlow bound to a reconfigure entry."""
    flow = CT002EmulatorConfigFlow()
    flow.hass = hass or _make_hass(entry)
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    return flow


def _make_options_flow(entry: MagicMock) -> CT002EmulatorOptionsFlow:
    """Instantiate CT002EmulatorOptionsFlow bound to a config entry."""
    flow = CT002EmulatorOptionsFlow()
    flow.config_entry = entry
    return flow


def _get_schema_markers(data_schema: vol.Schema) -> dict[str, Any]:
    """Return a dict mapping field name to its voluptuous marker."""
    return {getattr(key, "schema", key): key for key in data_schema.schema}


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestGetCurrentPowerEntity:
    def test_prefers_options_over_data(self) -> None:
        entry = _make_entry(
            data={CONF_POWER_ENTITY: "sensor.data_power"},
            options={CONF_POWER_ENTITY: "sensor.options_power"},
        )
        assert _get_current_power_entity(entry) == "sensor.options_power"

    def test_falls_back_to_data_when_options_missing(self) -> None:
        entry = _make_entry(
            data={CONF_POWER_ENTITY: "sensor.data_power"},
            options={},
        )
        assert _get_current_power_entity(entry) == "sensor.data_power"

    def test_falls_back_to_data_when_options_empty_or_none(self) -> None:
        entry_empty = _make_entry(
            data={CONF_POWER_ENTITY: "sensor.data_power"},
            options={CONF_POWER_ENTITY: ""},
        )
        entry_none = _make_entry(
            data={CONF_POWER_ENTITY: "sensor.data_power"},
            options={CONF_POWER_ENTITY: None},
        )
        assert _get_current_power_entity(entry_empty) == "sensor.data_power"
        assert _get_current_power_entity(entry_none) == "sensor.data_power"

    def test_returns_empty_when_absent_everywhere(self) -> None:
        entry = _make_entry(data={}, options={})
        assert _get_current_power_entity(entry) == ""


# ---------------------------------------------------------------------------
# OptionsFlow tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOptionsFlow:
    async def test_shows_options_power_entity_over_stale_data(self) -> None:
        entry = _make_entry(
            data={CONF_POWER_ENTITY: "sensor.old_power"},
            options={CONF_POWER_ENTITY: "sensor.active_options_power"},
        )
        flow = _make_options_flow(entry)

        result = await flow.async_step_init()

        assert result["type"] == "form"
        assert result["step_id"] == "init"
        markers = _get_schema_markers(result["data_schema"])
        power_marker = markers[CONF_POWER_ENTITY]
        assert power_marker.description == {"suggested_value": "sensor.active_options_power"}
        assert power_marker.default is vol.UNDEFINED

    async def test_falls_back_to_data_when_options_empty(self) -> None:
        entry = _make_entry(
            data={CONF_POWER_ENTITY: "sensor.initial_power"},
            options={},
        )
        flow = _make_options_flow(entry)

        result = await flow.async_step_init()

        markers = _get_schema_markers(result["data_schema"])
        power_marker = markers[CONF_POWER_ENTITY]
        assert power_marker.description == {"suggested_value": "sensor.initial_power"}

    async def test_reopening_options_after_submit_shows_new_entity(self) -> None:
        entry = _make_entry(
            data={CONF_POWER_ENTITY: "sensor.initial_power"},
            options={},
        )
        flow = _make_options_flow(entry)

        submit_result = await flow.async_step_init(
            user_input={CONF_POWER_ENTITY: "sensor.new_power"}
        )
        assert submit_result["type"] == "create_entry"
        assert submit_result["data"] == {CONF_POWER_ENTITY: "sensor.new_power"}

        # Simulate Home Assistant storing OptionsFlow result in entry.options
        entry.options = dict(submit_result["data"])

        reopened = await _make_options_flow(entry).async_step_init()
        markers = _get_schema_markers(reopened["data_schema"])
        assert markers[CONF_POWER_ENTITY].description == {
            "suggested_value": "sensor.new_power"
        }

    async def test_omits_suggested_value_when_no_power_entity_set(self) -> None:
        entry = _make_entry(data={}, options={})
        flow = _make_options_flow(entry)

        result = await flow.async_step_init()

        markers = _get_schema_markers(result["data_schema"])
        power_marker = markers[CONF_POWER_ENTITY]
        assert power_marker.description is None


# ---------------------------------------------------------------------------
# ReconfigureFlow tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReconfigureFlow:
    async def test_shows_options_override_instead_of_stale_data(self) -> None:
        entry = _make_entry(
            data={
                CONF_NAME: "Grid Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.old_data_power",
            },
            options={CONF_POWER_ENTITY: "sensor.current_options_power"},
        )
        flow = _make_reconfigure_flow(entry)

        result = await flow.async_step_reconfigure()

        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"
        markers = _get_schema_markers(result["data_schema"])
        assert markers[CONF_NAME].description == {"suggested_value": "Grid Meter"}
        assert markers[CONF_CT_MAC_ADDRESS].description == {"suggested_value": "a020a6000001"}
        assert markers[CONF_POWER_ENTITY].description == {
            "suggested_value": "sensor.current_options_power"
        }
        assert markers[CONF_POWER_ENTITY].default is vol.UNDEFINED

    async def test_falls_back_to_data_when_options_empty(self) -> None:
        entry = _make_entry(
            data={
                CONF_NAME: "Grid Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.initial_power",
            },
            options={},
        )
        flow = _make_reconfigure_flow(entry)

        result = await flow.async_step_reconfigure()

        markers = _get_schema_markers(result["data_schema"])
        assert markers[CONF_POWER_ENTITY].description == {
            "suggested_value": "sensor.initial_power"
        }

    async def test_submit_updates_data_clears_power_option_and_syncs_flows_and_coordinator(
        self,
    ) -> None:
        entry = _make_entry(
            data={
                CONF_NAME: "Old Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.very_old_power",
                CONF_ENABLED: True,
            },
            options={
                CONF_POWER_ENTITY: "sensor.previous_option_power",
                "other_option": "keep_me",
            },
            unique_id="a020a6000001",
            title="Old Meter",
        )
        hass = _make_hass(entry)
        flow = _make_reconfigure_flow(entry, hass)

        result = await flow.async_step_reconfigure(
            user_input={
                CONF_NAME: "Updated Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000099",
                CONF_POWER_ENTITY: "sensor.brand_new_power",
            }
        )

        assert result["type"] == "abort"
        assert result["reason"] == "reconfigure_successful"
        hass.config_entries.async_update_entry.assert_called_once()
        hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)

        assert entry.title == "Updated Meter"
        assert entry.unique_id == "a020a6000099"
        assert entry.data[CONF_NAME] == "Updated Meter"
        assert entry.data[CONF_CT_MAC_ADDRESS] == "a020a6000099"
        assert entry.data[CONF_POWER_ENTITY] == "sensor.brand_new_power"
        assert entry.data[CONF_ENABLED] is True
        assert CONF_POWER_ENTITY not in entry.options
        assert entry.options["other_option"] == "keep_me"

        # Reopening reconfigure, reopening options, and initializing coordinator all agree
        reopened_reconf = await _make_reconfigure_flow(entry, hass).async_step_reconfigure()
        reconf_markers = _get_schema_markers(reopened_reconf["data_schema"])
        assert reconf_markers[CONF_POWER_ENTITY].description == {
            "suggested_value": "sensor.brand_new_power"
        }

        reopened_options = await _make_options_flow(entry).async_step_init()
        opt_markers = _get_schema_markers(reopened_options["data_schema"])
        assert opt_markers[CONF_POWER_ENTITY].description == {
            "suggested_value": "sensor.brand_new_power"
        }

        coord = CT002EmulatorCoordinator(hass, entry)
        assert coord._power_entity == "sensor.brand_new_power"
        hass.loop.close()

    async def test_invalid_mac_preserves_submitted_inputs(self) -> None:
        entry = _make_entry(
            data={
                CONF_NAME: "Old Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.old_power",
            },
            options={},
        )
        hass = _make_hass(entry)
        flow = _make_reconfigure_flow(entry, hass)

        result = await flow.async_step_reconfigure(
            user_input={
                CONF_NAME: "Edited Name",
                CONF_CT_MAC_ADDRESS: "invalid-mac",
                CONF_POWER_ENTITY: "sensor.chosen_power",
            }
        )

        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"
        assert result["errors"] == {CONF_CT_MAC_ADDRESS: "invalid_mac"}
        assert result["description_placeholders"] == {"name": "Old Meter"}
        markers = _get_schema_markers(result["data_schema"])
        assert markers[CONF_NAME].description == {"suggested_value": "Edited Name"}
        assert markers[CONF_CT_MAC_ADDRESS].description == {"suggested_value": "invalid-mac"}
        assert markers[CONF_POWER_ENTITY].description == {
            "suggested_value": "sensor.chosen_power"
        }
        hass.config_entries.async_update_entry.assert_not_called()

    async def test_empty_mac_generates_new_mac(self) -> None:
        entry = _make_entry(
            data={
                CONF_NAME: "Grid Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.old_power",
            },
            unique_id="a020a6000001",
        )
        hass = _make_hass(entry)
        flow = _make_reconfigure_flow(entry, hass)
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        result = await flow.async_step_reconfigure(
            user_input={
                CONF_NAME: "Grid Meter",
                CONF_CT_MAC_ADDRESS: "",
                CONF_POWER_ENTITY: "sensor.new_power",
            }
        )

        assert result["type"] == "abort"
        assert result["reason"] == "reconfigure_successful"
        new_mac = entry.data[CONF_CT_MAC_ADDRESS]
        assert len(new_mac) == 12
        assert new_mac.startswith("a020a6")
        assert entry.unique_id == new_mac
        flow.async_set_unique_id.assert_awaited_once_with(new_mac)
        flow._abort_if_unique_id_configured.assert_called_once()

    async def test_same_mac_with_colons_and_uppercase_does_not_abort(self) -> None:
        entry = _make_entry(
            data={
                CONF_NAME: "Grid Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.old_power",
            },
            unique_id="a020a6000001",
        )
        hass = _make_hass(entry)
        flow = _make_reconfigure_flow(entry, hass)
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        result = await flow.async_step_reconfigure(
            user_input={
                CONF_NAME: "Grid Meter",
                CONF_CT_MAC_ADDRESS: "A0:20:A6:00:00:01",
                CONF_POWER_ENTITY: "sensor.new_power",
            }
        )

        assert result["type"] == "abort"
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_CT_MAC_ADDRESS] == "a020a6000001"
        assert entry.unique_id == "a020a6000001"
        flow.async_set_unique_id.assert_not_awaited()
        flow._abort_if_unique_id_configured.assert_not_called()

    async def test_blank_name_falls_back_to_existing_name(self) -> None:
        entry = _make_entry(
            data={
                CONF_NAME: "Existing Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.old_power",
            },
            unique_id="a020a6000001",
            title="Existing Meter",
        )
        hass = _make_hass(entry)
        flow = _make_reconfigure_flow(entry, hass)

        result = await flow.async_step_reconfigure(
            user_input={
                CONF_NAME: "   ",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.new_power",
            }
        )

        assert result["type"] == "abort"
        assert entry.data[CONF_NAME] == "Existing Meter"
        assert entry.title == "Existing Meter"

    async def test_omits_power_suggested_value_when_empty_everywhere(self) -> None:
        entry = _make_entry(
            data={CONF_NAME: DEFAULT_NAME, CONF_CT_MAC_ADDRESS: "a020a6000001"},
            options={},
        )
        flow = _make_reconfigure_flow(entry)

        result = await flow.async_step_reconfigure()

        markers = _get_schema_markers(result["data_schema"])
        assert markers[CONF_POWER_ENTITY].description is None

    async def test_uppercase_mac_without_colons_accepted(self) -> None:
        entry = _make_entry(
            data={
                CONF_NAME: "Grid Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.old_power",
            },
            unique_id="a020a6000001",
        )
        hass = _make_hass(entry)
        flow = _make_reconfigure_flow(entry, hass)

        result = await flow.async_step_reconfigure(
            user_input={
                CONF_NAME: "Grid Meter",
                CONF_CT_MAC_ADDRESS: "A020A60000FF",
                CONF_POWER_ENTITY: "sensor.new_power",
            }
        )

        assert result["type"] == "abort"
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_CT_MAC_ADDRESS] == "a020a60000ff"
        assert entry.unique_id == "a020a60000ff"

    async def test_invalid_mac_with_none_optional_fields(self) -> None:
        entry = _make_entry(
            data={
                CONF_NAME: "Grid Meter",
                CONF_CT_MAC_ADDRESS: "a020a6000001",
                CONF_POWER_ENTITY: "sensor.old_power",
            },
        )
        flow = _make_reconfigure_flow(entry)

        result = await flow.async_step_reconfigure(
            user_input={
                CONF_NAME: None,
                CONF_CT_MAC_ADDRESS: "not-valid",
                CONF_POWER_ENTITY: "sensor.chosen",
            }
        )

        assert result["type"] == "form"
        assert result["errors"] == {CONF_CT_MAC_ADDRESS: "invalid_mac"}
        markers = _get_schema_markers(result["data_schema"])
        assert markers[CONF_NAME].description == {"suggested_value": ""}
        assert markers[CONF_CT_MAC_ADDRESS].description == {"suggested_value": "not-valid"}
        assert markers[CONF_POWER_ENTITY].description == {"suggested_value": "sensor.chosen"}


# ---------------------------------------------------------------------------
# MAC validation & cloud error placeholder tests
# ---------------------------------------------------------------------------


class TestMacValidation:
    def test_valid_mac_formats(self) -> None:
        assert _is_valid_mac("a020a6010203") is True
        assert _is_valid_mac("A020A6010203") is True
        assert _is_valid_mac("A020a60102Ff") is True
        assert _is_valid_mac("a0:20:a6:01:02:03") is True
        assert _is_valid_mac("A0:20:A6:01:02:03") is True

    def test_invalid_mac_formats(self) -> None:
        assert _is_valid_mac("a020a6") is False
        assert _is_valid_mac("G020A6010203") is False
        assert _is_valid_mac("a0-20-a6-01-02-03") is False


@pytest.mark.asyncio
class TestCloudErrorPlaceholders:
    async def test_cloud_login_marstek_error_uses_description_placeholders(self) -> None:
        flow = CT002EmulatorConfigFlow()
        fake_session_cm = MagicMock()
        fake_session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        fake_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=fake_session_cm):
            with patch(
                "custom_components.ct002_emulator.config_flow.async_login",
                new_callable=AsyncMock,
                side_effect=MarstekError("server timeout"),
            ):
                result = await flow.async_step_cloud_login(
                    user_input={
                        CONF_EMAIL: "user@example.com",
                        CONF_PASSWORD: "secret",
                        CONF_SERVER: "eu",
                    }
                )

        assert result["type"] == "form"
        assert result["errors"] == {"base": "marstek_error"}
        assert result["description_placeholders"] == {"marstek_detail": "server timeout"}

    async def test_new_device_marstek_error_uses_description_placeholders(self) -> None:
        flow = CT002EmulatorConfigFlow()
        flow.hass = MagicMock()
        flow.hass.config.time_zone = "Europe/Berlin"
        flow._cloud_email = "user@example.com"
        flow._cloud_password = "secret"
        flow._cloud_server = "eu"

        fake_session_cm = MagicMock()
        fake_session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        fake_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=fake_session_cm):
            with patch(
                "custom_components.ct002_emulator.config_flow.async_register_new_device",
                new_callable=AsyncMock,
                side_effect=MarstekError("quota exceeded"),
            ):
                result = await flow.async_step_new_device()

        assert result["type"] == "form"
        assert result["errors"] == {"base": "marstek_error"}
        assert result["description_placeholders"] == {"marstek_detail": "quota exceeded"}


# ---------------------------------------------------------------------------
# Coordinator power_entity precedence tests
# ---------------------------------------------------------------------------


class TestCoordinatorPowerEntityPrecedence:
    def test_options_overrides_data(self) -> None:
        entry = _make_entry(
            data={CONF_NAME: "Test", CONF_CT_MAC_ADDRESS: "a020a6000001", CONF_POWER_ENTITY: "sensor.data"},
            options={CONF_POWER_ENTITY: "sensor.options"},
        )
        hass = _make_hass(entry)
        coord = CT002EmulatorCoordinator(hass, entry)
        assert coord._power_entity == "sensor.options"
        hass.loop.close()

    def test_empty_options_falls_back_to_data(self) -> None:
        entry = _make_entry(
            data={CONF_NAME: "Test", CONF_CT_MAC_ADDRESS: "a020a6000001", CONF_POWER_ENTITY: "sensor.data"},
            options={CONF_POWER_ENTITY: ""},
        )
        hass = _make_hass(entry)
        coord = CT002EmulatorCoordinator(hass, entry)
        assert coord._power_entity == "sensor.data"
        hass.loop.close()

    def test_update_options_picks_up_changes_and_fallback(self) -> None:
        entry = _make_entry(
            data={CONF_NAME: "Test", CONF_CT_MAC_ADDRESS: "a020a6000001", CONF_POWER_ENTITY: "sensor.data"},
            options={},
        )
        hass = _make_hass(entry)
        coord = CT002EmulatorCoordinator(hass, entry)
        assert coord._power_entity == "sensor.data"

        entry.options = {CONF_POWER_ENTITY: "sensor.updated_option"}
        coord.update_options()
        assert coord._power_entity == "sensor.updated_option"

        entry.data = {**entry.data, CONF_POWER_ENTITY: "sensor.reconfigured_data"}
        entry.options = {}
        coord.update_options()
        assert coord._power_entity == "sensor.reconfigured_data"
        hass.loop.close()
