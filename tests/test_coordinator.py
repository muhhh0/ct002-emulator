"""Tests for the CT002 Grid Meter Emulator coordinator."""

from __future__ import annotations

import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.ct002_emulator.coordinator import (
    CT002EmulatorCoordinator,
    _SharedUDPServer,
    _build_payload,
    _compute_length,
    _get_power_from_state,
    _parse_request,
)
from custom_components.ct002_emulator.const import (
    ETX,
    SOH,
    STX,
    UDP_PORT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockState:
    def __init__(self, state: str) -> None:
        self.state = state


class _MockCoordinator:
    """Lightweight mock for SharedUDPServer dispatch tests."""

    def __init__(self, ct_mac: str) -> None:
        self.ct_mac = ct_mac
        self.enabled = True
        self._handle_request = AsyncMock()
        self._name = f"Mock-{ct_mac}"
        self.last_reported_power = 0
        self.last_packet_timestamp = None
        self.server_active = False
        self._info_idx = 0
        self.async_set_updated_data = MagicMock()
        self._ct_mac = ct_mac


class _MockHass:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.states = MagicMock()
        self.data: dict = {}


def _make_coordinator(ct_mac: str = "a020a6000001", enabled: bool = True) -> CT002EmulatorCoordinator:
    """Create a real CT002EmulatorCoordinator with mocked HA dependencies."""
    loop = asyncio.new_event_loop()
    hass = _MockHass(loop)

    entry = MagicMock()
    entry.data = {
        "name": "Test CT002",
        "ct_mac_address": ct_mac,
        "enabled": enabled,
    }
    entry.options = {
        "power_entity": "sensor.test_power",
    }
    entry.runtime_data = None
    entry.async_on_unload = MagicMock()

    coord = CT002EmulatorCoordinator(hass, entry)
    coord._shared_server = MagicMock()
    coord._shared_server.sendto = MagicMock()
    return coord


# ---------------------------------------------------------------------------
# A. Pure protocol function tests
# ---------------------------------------------------------------------------


class TestComputeLength:
    def test_small_payload(self) -> None:
        msg = b"|HMG-50|a020a6000001|HME-4|a020a6000002|1|0"
        length = _compute_length(msg)
        assert length == 1 + 1 + 2 + len(msg) + 1 + 2

    def test_length_digits_increase(self) -> None:
        msg = b"|" + b"x" * 990
        length = _compute_length(msg)
        assert length == 1 + 1 + 3 + len(msg) + 1 + 2

    def test_roundtrip_consistency(self) -> None:
        fields = ["HMG-50", "a020a6000001", "HME-4", "a020a6000002", "1", "0"]
        payload = _build_payload(fields)
        sep = payload.index(b"|")
        declared_len = int(payload[2:sep])
        assert declared_len == len(payload)


class TestBuildPayload:
    def test_structure(self) -> None:
        fields = ["HMG-50", "a020a6000001", "HME-4", "a020a6000002", "1", "0"]
        payload = _build_payload(fields)
        assert payload[0] == SOH
        assert payload[1] == STX
        assert payload[-3] == ETX
        xor = 0
        for b in payload[:-2]:
            xor ^= b
        assert payload[-2:] == f"{xor:02x}".encode()

    def test_message_fields(self) -> None:
        fields = ["A", "BB", "CCC"]
        payload = _build_payload(fields)
        sep = payload.index(b"|")
        message = payload[sep:-3].decode()
        parts = message.split("|")
        assert parts == ["", "A", "BB", "CCC"]

    def test_build_parse_roundtrip(self) -> None:
        fields = ["HMG-50", "a020a6326604", "HME-4", "02b25098781e", "1", "12345"]
        packet = _build_payload(fields)
        result, error = _parse_request(packet)
        assert error is None
        assert result == fields


class TestParseRequest:
    def test_valid_request(self) -> None:
        fields = ["HMG-50", "a020a6326604", "HME-4", "02b25098781e", "1", "0"]
        packet = _build_payload(fields)
        result, error = _parse_request(packet)
        assert error is None
        assert result == fields

    def test_too_short(self) -> None:
        result, error = _parse_request(b"\x01\x02")
        assert result is None
        assert "Too short" in error

    def test_missing_soh_stx(self) -> None:
        fields = ["HMG-50", "a020a6326604"]
        packet = bytearray(_build_payload(fields))
        packet[0] = 0xFF
        result, error = _parse_request(bytes(packet))
        assert result is None
        assert "Missing SOH/STX" in error

    def test_checksum_mismatch(self) -> None:
        fields = ["HMG-50", "a020a6326604", "HME-4", "02b25098781e", "1", "0"]
        packet = bytearray(_build_payload(fields))
        packet[-1] = ord("Z")
        result, error = _parse_request(bytes(packet))
        assert result is None
        assert "Checksum" in error

    def test_leading_space_checksum_tolerated(self) -> None:
        fields = ["HMG-50", "a020a6326604", "HME-4", "02b25098781e", "1", "0"]
        packet = bytearray(_build_payload(fields))
        xor = 0
        for b in packet[:-2]:
            xor ^= b
        expected = f"{xor:02x}".encode()
        packet[-2] = ord(" ")
        packet[-1] = expected[1]
        result, error = _parse_request(bytes(packet))
        assert error is None
        assert result is not None

    def test_length_mismatch(self) -> None:
        fields = ["HMG-50", "a020a6326604"]
        packet = bytearray(_build_payload(fields))
        packet = packet[:-1]
        result, error = _parse_request(bytes(packet))
        assert result is None
        assert "Length mismatch" in error

    def test_missing_etx(self) -> None:
        fields = ["HMG-50", "a020a6326604"]
        packet = bytearray(_build_payload(fields))
        packet[-3] = 0xFF
        result, error = _parse_request(bytes(packet))
        assert result is None
        assert "Missing ETX" in error

    def test_no_separator(self) -> None:
        result, error = _parse_request(b"\x01\x02" + b"x" * 20)
        assert result is None
        assert "No separator" in error


class TestGetPowerFromState:
    def test_none_state(self) -> None:
        assert _get_power_from_state(None) == 0

    def test_unknown(self) -> None:
        assert _get_power_from_state(_MockState("unknown")) == 0

    def test_unavailable(self) -> None:
        assert _get_power_from_state(_MockState("unavailable")) == 0

    def test_empty(self) -> None:
        assert _get_power_from_state(_MockState("")) == 0

    def test_valid_integer(self) -> None:
        assert _get_power_from_state(_MockState("350")) == 350

    def test_valid_float(self) -> None:
        assert _get_power_from_state(_MockState("-123.7")) == -123

    def test_negative(self) -> None:
        assert _get_power_from_state(_MockState("-500")) == -500

    def test_invalid_string(self) -> None:
        assert _get_power_from_state(_MockState("abc")) == 0


# ---------------------------------------------------------------------------
# B. SharedUDPServer tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    _SharedUDPServer._instance = None
    yield
    _SharedUDPServer._instance = None


class TestSharedUDPServerSingleton:
    def test_same_instance(self) -> None:
        loop = asyncio.new_event_loop()
        hass = _MockHass(loop)
        s1 = _SharedUDPServer.get_instance(hass)
        s2 = _SharedUDPServer.get_instance(hass)
        assert s1 is s2
        loop.close()

    def test_new_instance_after_reset(self) -> None:
        loop = asyncio.new_event_loop()
        hass = _MockHass(loop)
        s1 = _SharedUDPServer.get_instance(hass)
        _SharedUDPServer._instance = None
        s2 = _SharedUDPServer.get_instance(hass)
        assert s1 is not s2
        loop.close()


@pytest.mark.asyncio
class TestSharedUDPServerRegister:
    async def test_first_register_opens_socket(self) -> None:
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)
        coord = _MockCoordinator("a020a6000001")

        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_transport = MagicMock()
            mock_create.return_value = (mock_transport, MagicMock())
            result = await server.register(coord)

        assert result is True
        assert server._transport is mock_transport
        assert coord.ct_mac.lower() in server._coordinators

    async def test_second_register_reuses_socket(self) -> None:
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)
        coord1 = _MockCoordinator("a020a6000001")
        coord2 = _MockCoordinator("a020a6000002")

        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_transport = MagicMock()
            mock_create.return_value = (mock_transport, MagicMock())
            await server.register(coord1)
            result = await server.register(coord2)

        assert result is True
        assert mock_create.call_count == 1
        assert len(server._coordinators) == 2

    async def test_unregister_closes_socket_when_empty(self) -> None:
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)
        coord = _MockCoordinator("a020a6000001")

        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_transport = MagicMock()
            mock_create.return_value = (mock_transport, MagicMock())
            await server.register(coord)

        server.unregister(coord)
        mock_transport.close.assert_called_once()
        assert server._transport is None
        assert len(server._coordinators) == 0

    async def test_unregister_keeps_socket_when_others_registered(self) -> None:
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)
        coord1 = _MockCoordinator("a020a6000001")
        coord2 = _MockCoordinator("a020a6000002")

        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_transport = MagicMock()
            mock_create.return_value = (mock_transport, MagicMock())
            await server.register(coord1)
            await server.register(coord2)

        server.unregister(coord1)
        mock_transport.close.assert_not_called()
        assert server._transport is mock_transport
        assert len(server._coordinators) == 1

    async def test_register_failure(self) -> None:
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)
        coord = _MockCoordinator("a020a6000001")

        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = OSError("Address in use")
            result = await server.register(coord)

        assert result is False
        assert server._transport is None


@pytest.mark.asyncio
class TestSharedUDPServerDispatch:
    async def test_dispatch_to_matching_mac(self) -> None:
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)

        mac1 = "a020a6000001"
        mac2 = "a020a6000002"
        coord1 = _MockCoordinator(mac1)
        coord2 = _MockCoordinator(mac2)

        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_transport = MagicMock()
            mock_create.return_value = (mock_transport, MagicMock())
            await server.register(coord1)
            await server.register(coord2)

        request_fields = ["HMG-50", "bat_mac", "HME-4", mac1, "1", "0"]
        packet = _build_payload(request_fields)
        server._dispatch(packet, ("192.168.1.100", 5000))

        await asyncio.sleep(0.1)
        coord1._handle_request.assert_awaited_once()
        coord2._handle_request.assert_not_awaited()

    async def test_dispatch_unknown_mac_ignored(self) -> None:
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)

        coord = _MockCoordinator("a020a6000001")
        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_transport = MagicMock()
            mock_create.return_value = (mock_transport, MagicMock())
            await server.register(coord)

        request_fields = ["HMG-50", "bat_mac", "HME-4", "a020a6ffffff", "1", "0"]
        packet = _build_payload(request_fields)
        server._dispatch(packet, ("192.168.1.100", 5000))

        await asyncio.sleep(0.1)
        coord._handle_request.assert_not_awaited()

    async def test_dispatch_invalid_packet_ignored(self) -> None:
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)

        coord = _MockCoordinator("a020a6000001")
        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_transport = MagicMock()
            mock_create.return_value = (mock_transport, MagicMock())
            await server.register(coord)

        server._dispatch(b"garbage", ("192.168.1.100", 5000))
        await asyncio.sleep(0.1)
        coord._handle_request.assert_not_awaited()

    async def test_dispatch_correct_data_and_addr(self) -> None:
        """Verify dispatch passes correct data and addr to coordinator."""
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)

        mac1 = "a020a6111111"
        mac2 = "a020a6222222"
        coord1 = _MockCoordinator(mac1)
        coord2 = _MockCoordinator(mac2)

        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_transport = MagicMock()
            mock_create.return_value = (mock_transport, MagicMock())
            await server.register(coord1)
            await server.register(coord2)

        request_fields = ["HMG-50", "bat_mac", "HME-4", mac2, "1", "0"]
        packet = _build_payload(request_fields)
        server._dispatch(packet, ("10.1.0.10", 5000))

        await asyncio.sleep(0.1)
        coord1._handle_request.assert_not_awaited()
        coord2._handle_request.assert_awaited_once()

        call_args = coord2._handle_request.call_args
        assert call_args[0][0] == packet
        assert call_args[0][1] == ("10.1.0.10", 5000)

    async def test_case_insensitive_mac_matching(self) -> None:
        loop = asyncio.get_event_loop()
        hass = _MockHass(loop)
        server = _SharedUDPServer.get_instance(hass)

        mac = "a020a6000001"
        coord = _MockCoordinator(mac)

        with patch.object(hass.loop, "create_datagram_endpoint", new_callable=AsyncMock) as mock_create:
            mock_transport = MagicMock()
            mock_create.return_value = (mock_transport, MagicMock())
            await server.register(coord)

        request_fields = ["HMG-50", "bat_mac", "HME-4", "A020A6000001", "1", "0"]
        packet = _build_payload(request_fields)
        server._dispatch(packet, ("10.1.0.10", 5000))

        await asyncio.sleep(0.1)
        coord._handle_request.assert_awaited_once()


# ---------------------------------------------------------------------------
# C. Coordinator _handle_request tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCoordinatorHandleRequest:
    async def test_sends_response_with_correct_mac(self) -> None:
        coord = _make_coordinator("a020a6000001")

        with patch.object(coord, "_get_power", return_value=500):
            with patch.object(coord, "async_set_updated_data"):
                request = _build_payload(["HMG-50", "bat_mac", "HME-4", "a020a6000001", "1", "0"])
                await coord._handle_request(request, ("10.1.0.10", 5000))

        coord._shared_server.sendto.assert_called_once()
        response_data = coord._shared_server.sendto.call_args[0][0]
        response_addr = coord._shared_server.sendto.call_args[0][1]
        assert response_addr == ("10.1.0.10", 5000)

        fields, error = _parse_request(response_data)
        assert error is None
        assert fields[0] == "HME-4"
        assert fields[1] == "a020a6000001"
        assert fields[4] == "500"

    async def test_disabled_ignores_request(self) -> None:
        coord = _make_coordinator("a020a6000001", enabled=False)

        request = _build_payload(["HMG-50", "bat_mac", "HME-4", "a020a6000001", "1", "0"])
        await coord._handle_request(request, ("10.1.0.10", 5000))

        coord._shared_server.sendto.assert_not_called()

    async def test_mac_mismatch_ignored(self) -> None:
        coord = _make_coordinator("a020a6000001")

        request = _build_payload(["HMG-50", "bat_mac", "HME-4", "a020a6fffff", "1", "0"])
        await coord._handle_request(request, ("10.1.0.10", 5000))

        coord._shared_server.sendto.assert_not_called()

    async def test_updates_last_reported_power(self) -> None:
        coord = _make_coordinator("a020a6000001")

        with patch.object(coord, "_get_power", return_value=-300):
            with patch.object(coord, "async_set_updated_data"):
                request = _build_payload(["HMG-50", "bat_mac", "HME-4", "a020a6000001", "1", "0"])
                await coord._handle_request(request, ("10.1.0.10", 5000))

        assert coord.last_reported_power == -300
        assert coord.last_packet_timestamp is not None

    async def test_positive_power_in_dchrg_field(self) -> None:
        coord = _make_coordinator("a020a6000001")

        with patch.object(coord, "_get_power", return_value=350):
            with patch.object(coord, "async_set_updated_data"):
                request = _build_payload(["HMG-50", "bat_mac", "HME-4", "a020a6000001", "1", "0"])
                await coord._handle_request(request, ("10.1.0.10", 5000))

        response_data = coord._shared_server.sendto.call_args[0][0]
        fields, _ = _parse_request(response_data)
        assert fields[15] == "0"   # A_chrg_power
        assert fields[20] == "350" # A_dchrg_power

    async def test_negative_power_in_chrg_field(self) -> None:
        coord = _make_coordinator("a020a6000001")

        with patch.object(coord, "_get_power", return_value=-350):
            with patch.object(coord, "async_set_updated_data"):
                request = _build_payload(["HMG-50", "bat_mac", "HME-4", "a020a6000001", "1", "0"])
                await coord._handle_request(request, ("10.1.0.10", 5000))

        response_data = coord._shared_server.sendto.call_args[0][0]
        fields, _ = _parse_request(response_data)
        assert fields[15] == "-350" # A_chrg_power
        assert fields[20] == "0"    # A_dchrg_power

    async def test_invalid_packet_no_response(self) -> None:
        coord = _make_coordinator("a020a6000001")

        await coord._handle_request(b"garbage", ("10.1.0.10", 5000))
        coord._shared_server.sendto.assert_not_called()

    async def test_info_idx_increments(self) -> None:
        coord = _make_coordinator("a020a6000001")

        with patch.object(coord, "_get_power", return_value=100):
            with patch.object(coord, "async_set_updated_data"):
                request = _build_payload(["HMG-50", "bat", "HME-4", "a020a6000001", "1", "0"])

                await coord._handle_request(request, ("10.1.0.10", 5000))
                resp1 = coord._shared_server.sendto.call_args[0][0]
                fields1, _ = _parse_request(resp1)
                idx1 = int(fields1[13])

                await coord._handle_request(request, ("10.1.0.10", 5000))
                resp2 = coord._shared_server.sendto.call_args[0][0]
                fields2, _ = _parse_request(resp2)
                idx2 = int(fields2[13])

        assert idx2 == (idx1 + 1) % 256


class TestCoordinatorBuildResponse:
    def test_phase_b_c_zero(self) -> None:
        coord = _make_coordinator("a020a6000001")
        fields = ["HMG-50", "bat_mac", "HME-4", "a020a6000001", "1", "0"]
        response = coord._build_response(fields, 500)
        parsed, error = _parse_request(response)
        assert error is None
        assert parsed[5] == "0"  # Phase B
        assert parsed[6] == "0"  # Phase C
        assert parsed[7] == "500"  # Total

    def test_total_matches_phase_a(self) -> None:
        coord = _make_coordinator("a020a6000001")
        fields = ["HMG-50", "bat_mac", "HME-4", "a020a6000001", "1", "0"]
        for power in [-800, 0, 400, 800]:
            response = coord._build_response(fields, power)
            parsed, _ = _parse_request(response)
            assert parsed[4] == str(power)
            assert parsed[7] == str(power)


class TestCoordinatorSetEnabled:
    def test_disable_updates_state(self) -> None:
        coord = _make_coordinator("a020a6000001")
        with patch.object(coord, "async_set_updated_data"):
            coord.set_enabled(False)
        assert coord.enabled is False

    def test_enable_updates_state(self) -> None:
        coord = _make_coordinator("a020a6000001", enabled=False)
        with patch.object(coord, "async_set_updated_data"):
            coord.set_enabled(True)
        assert coord.enabled is True


class TestCoordinatorBuildData:
    def test_server_active_respects_enabled(self) -> None:
        coord = _make_coordinator("a020a6000001")
        coord.server_active = True
        coord.enabled = True
        data = coord._build_data()
        assert data["server_active"] is True

    def test_server_active_false_when_disabled(self) -> None:
        coord = _make_coordinator("a020a6000001")
        coord.server_active = True
        coord.enabled = False
        data = coord._build_data()
        assert data["server_active"] is False

    def test_server_active_false_when_not_running(self) -> None:
        coord = _make_coordinator("a020a6000001")
        coord.server_active = False
        coord.enabled = True
        data = coord._build_data()
        assert data["server_active"] is False
