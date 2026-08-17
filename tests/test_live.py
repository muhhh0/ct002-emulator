"""Online integration tests against a running Home Assistant instance.

Requires:
  - HA container running on localhost:8123
  - CT002 Grid Meter integration loaded with two instances
  - /tmp/opencode/auth.json with valid JWT credentials

Run:
  pytest tests/test_live.py -v -m live
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


# Known MACs from config entries
CT_MAC_1 = "02b25098781e"  # CT002 Grid Meter
CT_MAC_2 = "000000000000"  # CT002 Grid Meter 2
UNKNOWN_MAC = "ffffffffff"

ENTITY_POWER_1 = "sensor.ct002_grid_meter_zuletzt_gemeldete_leistung"
ENTITY_TS_1 = "sensor.ct002_grid_meter_zeitstempel_des_letzten_pakets"
ENTITY_ACTIVE_1 = "binary_sensor.ct002_grid_meter_server_aktiv"
ENTITY_SWITCH_1 = "switch.ct002_grid_meter_ct002_aktiviert"

ENTITY_POWER_2 = "sensor.ct002_grid_meter_2_zuletzt_gemeldete_leistung"
ENTITY_TS_2 = "sensor.ct002_grid_meter_2_zeitstempel_des_letzten_pakets"
ENTITY_ACTIVE_2 = "binary_sensor.ct002_grid_meter_2_server_aktiv"
ENTITY_SWITCH_2 = "switch.ct002_grid_meter_2_ct002_aktiviert"

ENTITY_INPUT_NUMBER = "input_number.dummy_grid_power"
ENTITY_TEMPLATE_SENSOR = "sensor.dummy_grid_power"


# ---------------------------------------------------------------------------
# A. Basis-Validierung
# ---------------------------------------------------------------------------


class TestBasisValidierung:
    """HA erreichbar, Integration geladen, Entities vorhanden."""

    async def test_ha_reachable(self, ha_client):
        states = await ha_client.get_states()
        assert len(states) > 0

    async def test_ct002_config_entries_loaded(self, ha_client):
        """Both CT002 instances should have entities."""
        states = await ha_client.get_states()
        ct_entities = [eid for eid in states if "ct002" in eid]
        assert len(ct_entities) >= 8, f"Expected >= 8 CT002 entities, got {len(ct_entities)}"

    async def test_all_entities_present(self, ha_client):
        states = await ha_client.get_states()
        required = [
            ENTITY_POWER_1, ENTITY_TS_1, ENTITY_ACTIVE_1, ENTITY_SWITCH_1,
            ENTITY_POWER_2, ENTITY_TS_2, ENTITY_ACTIVE_2, ENTITY_SWITCH_2,
            ENTITY_INPUT_NUMBER, ENTITY_TEMPLATE_SENSOR,
        ]
        for eid in required:
            assert eid in states, f"Missing entity: {eid}"

    async def test_switches_are_on(self, ha_client):
        s1 = await ha_client.get_entity(ENTITY_SWITCH_1)
        s2 = await ha_client.get_entity(ENTITY_SWITCH_2)
        assert s1["state"] == "on"
        assert s2["state"] == "on"

    async def test_server_active(self, ha_client):
        b1 = await ha_client.get_entity(ENTITY_ACTIVE_1)
        b2 = await ha_client.get_entity(ENTITY_ACTIVE_2)
        assert b1["state"] == "on"
        assert b2["state"] == "on"


# ---------------------------------------------------------------------------
# B. UDP-Paket-Test (ein CT002)
# ---------------------------------------------------------------------------


class TestUDPPacket:
    """Send a CT002 packet and verify entity updates."""

    async def test_send_packet_updates_power(self, ha_client):
        # Set known power value
        await ha_client.call_service("input_number", "set_value", ENTITY_INPUT_NUMBER, value=350)
        await asyncio.sleep(1)

        # Send packet to CT002 instance 1
        ha_client.send_ct002_packet(ct_mac=CT_MAC_1, power="0")
        await asyncio.sleep(2)

        power = await ha_client.get_entity(ENTITY_POWER_1)
        assert power["state"] == "350", f"Expected 350, got {power['state']}"

    async def test_send_packet_updates_timestamp(self, ha_client):
        before_ts = await ha_client.get_entity(ENTITY_TS_1)

        ha_client.send_ct002_packet(ct_mac=CT_MAC_1, power="0")
        await asyncio.sleep(2)

        after_ts = await ha_client.get_entity(ENTITY_TS_1)
        assert after_ts["state"] != "unknown", "Timestamp should be set after packet"
        assert after_ts["state"] != before_ts["state"] or before_ts["state"] == "unknown"

    async def test_response_contains_correct_mac(self, ha_client):
        """Verify the CT response echoes our CT MAC."""
        result = ha_client.send_ct002_packet(ct_mac=CT_MAC_1, response_port=0)
        assert result is not None, "No response received"

        from custom_components.ct002_emulator.coordinator import _parse_request
        data, addr = result
        fields, error = _parse_request(data)
        assert error is None, f"Response parse error: {error}"
        assert fields[0] == "HME-4"
        assert fields[1].lower() == CT_MAC_1.lower()


# ---------------------------------------------------------------------------
# C. Switch-Test
# ---------------------------------------------------------------------------


class TestSwitch:
    """Enable/disable CT002 server via switch."""

    async def test_disable_switch(self, ha_client):
        await ha_client.call_service("switch", "turn_off", ENTITY_SWITCH_1)
        await asyncio.sleep(1)

        sw = await ha_client.get_entity(ENTITY_SWITCH_1)
        assert sw["state"] == "off"

        active = await ha_client.get_entity(ENTITY_ACTIVE_1)
        assert active["state"] == "off"

    async def test_disabled_server_ignores_packets(self, ha_client):
        # Record current power value
        before = await ha_client.get_entity(ENTITY_POWER_1)
        before_power = before["state"]

        # Set a different power
        await ha_client.call_service("input_number", "set_value", ENTITY_INPUT_NUMBER, value=500)
        await asyncio.sleep(1)

        # Send packet — should be ignored
        ha_client.send_ct002_packet(ct_mac=CT_MAC_1, power="0")
        await asyncio.sleep(2)

        after = await ha_client.get_entity(ENTITY_POWER_1)
        # Power should NOT have changed to 500 because server is disabled
        assert after["state"] == before_power, (
            f"Power changed from {before_power} to {after['state']} — server should be disabled"
        )

    async def test_enable_switch(self, ha_client):
        await ha_client.call_service("switch", "turn_on", ENTITY_SWITCH_1)
        await asyncio.sleep(1)

        sw = await ha_client.get_entity(ENTITY_SWITCH_1)
        assert sw["state"] == "on"

        active = await ha_client.get_entity(ENTITY_ACTIVE_1)
        assert active["state"] == "on"


# ---------------------------------------------------------------------------
# D. Power-Passthrough
# ---------------------------------------------------------------------------


class TestPowerPassthrough:
    """Verify power values are passed through 1:1 without filtering."""

    async def test_small_power_value(self, ha_client):
        await ha_client.call_service("input_number", "set_value", ENTITY_INPUT_NUMBER, value=10)
        await asyncio.sleep(1)

        ha_client.send_ct002_packet(ct_mac=CT_MAC_1, power="0")
        await asyncio.sleep(2)

        power = await ha_client.get_entity(ENTITY_POWER_1)
        assert power["state"] == "10", f"Expected 10, got {power['state']}"

    async def test_negative_power_value(self, ha_client):
        await ha_client.call_service("input_number", "set_value", ENTITY_INPUT_NUMBER, value=-500)
        await asyncio.sleep(1)

        ha_client.send_ct002_packet(ct_mac=CT_MAC_1, power="0")
        await asyncio.sleep(2)

        power = await ha_client.get_entity(ENTITY_POWER_1)
        assert power["state"] == "-500", f"Expected -500, got {power['state']}"

    async def test_large_power_value(self, ha_client):
        await ha_client.call_service("input_number", "set_value", ENTITY_INPUT_NUMBER, value=5000)
        await asyncio.sleep(1)

        ha_client.send_ct002_packet(ct_mac=CT_MAC_1, power="0")
        await asyncio.sleep(2)

        power = await ha_client.get_entity(ENTITY_POWER_1)
        assert power["state"] == "5000", f"Expected 5000, got {power['state']}"


# ---------------------------------------------------------------------------
# E. Zwei CT002-Instanzen (MAC-Dispatch)
# ---------------------------------------------------------------------------


class TestTwoInstances:
    """Verify two CT002 instances are dispatched correctly by MAC."""

    async def test_dispatch_by_mac(self, ha_client):
        # Ensure switches are on
        await ha_client.call_service("switch", "turn_on", ENTITY_SWITCH_1)
        await ha_client.call_service("switch", "turn_on", ENTITY_SWITCH_2)
        await asyncio.sleep(1)

        # Set input_number for instance 1
        await ha_client.call_service("input_number", "set_value", ENTITY_INPUT_NUMBER, value=100)
        await asyncio.sleep(1)

        # Send to instance 1
        ha_client.send_ct002_packet(ct_mac=CT_MAC_1, power="0")
        await asyncio.sleep(2)

        p1 = await ha_client.get_entity(ENTITY_POWER_1)
        assert p1["state"] == "100", f"Instance 1 should show 100, got {p1['state']}"

        # Set input_number for instance 2
        await ha_client.call_service("input_number", "set_value", ENTITY_INPUT_NUMBER, value=200)
        await asyncio.sleep(1)

        # Send to instance 2
        ha_client.send_ct002_packet(ct_mac=CT_MAC_2, power="0")
        await asyncio.sleep(2)

        p2 = await ha_client.get_entity(ENTITY_POWER_2)
        assert p2["state"] == "200", f"Instance 2 should show 200, got {p2['state']}"

    async def test_instance1_not_affected_by_instance2_packet(self, ha_client):
        # Set power to 100 for instance 1
        await ha_client.call_service("input_number", "set_value", ENTITY_INPUT_NUMBER, value=100)
        await asyncio.sleep(1)
        ha_client.send_ct002_packet(ct_mac=CT_MAC_1, power="0")
        await asyncio.sleep(2)

        p1_before = await ha_client.get_entity(ENTITY_POWER_1)
        assert p1_before["state"] == "100"

        # Set power to 999 for instance 2
        await ha_client.call_service("input_number", "set_value", ENTITY_INPUT_NUMBER, value=999)
        await asyncio.sleep(1)
        ha_client.send_ct002_packet(ct_mac=CT_MAC_2, power="0")
        await asyncio.sleep(2)

        # Instance 1 should still show 100
        p1_after = await ha_client.get_entity(ENTITY_POWER_1)
        assert p1_after["state"] == "100", (
            f"Instance 1 should not change when instance 2 receives packet. "
            f"Was {p1_before['state']}, now {p1_after['state']}"
        )

    async def test_unknown_mac_ignored(self, ha_client):
        # Record current power
        before = await ha_client.get_entity(ENTITY_POWER_1)
        before_power = before["state"]

        # Send packet with unknown MAC
        ha_client.send_ct002_packet(ct_mac=UNKNOWN_MAC, power="0")
        await asyncio.sleep(2)

        after = await ha_client.get_entity(ENTITY_POWER_1)
        assert after["state"] == before_power, (
            f"Power should not change for unknown MAC. Was {before_power}, now {after['state']}"
        )
