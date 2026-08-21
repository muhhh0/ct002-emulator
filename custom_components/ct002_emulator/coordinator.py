"""Coordinator for CT002 Grid Meter Emulator UDP server."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_CT_MAC_ADDRESS,
    CONF_ENABLED,
    CONF_POWER_ENTITY,
    CT_TYPE,
    DEFAULT_ENABLED,
    DEFAULT_WIFI_RSSI,
    DOMAIN,
    ETX,
    SOH,
    STX,
    UDP_PORT,
)

_LOGGER = logging.getLogger(__name__)


def _get_power_from_state(state: State | None) -> int:
    """Safely extract power value from a HA state object."""
    if state is None:
        return 0
    if state.state in ("unknown", "unavailable", "None", ""):
        return 0
    try:
        return int(float(state.state))
    except (ValueError, TypeError):
        return 0


def _generate_mac() -> str:
    """Generate a random valid 12-char hex MAC (no colons, lowercase)."""
    return "a020a6" + f"{random.randint(0, 0xFFFFFF):06x}"


def _compute_length(payload_without_length: bytes) -> int:
    """Compute the total packet length including the length field digits."""
    base_size = 1 + 1 + len(payload_without_length) + 1 + 2  # SOH + STX + body + ETX + checksum
    for length_digits in range(1, 5):
        total_length = base_size + length_digits
        if len(str(total_length)) == length_digits:
            return total_length
    raise ValueError("Payload length too large")


def _build_payload(fields: list[str]) -> bytes:
    """Build a CT002 wire-format payload from response fields."""
    message_str = "|" + "|".join(fields)
    message_bytes = message_str.encode("ascii")
    total_length = _compute_length(message_bytes)
    payload = bytearray([SOH, STX])
    payload.extend(str(total_length).encode("ascii"))
    payload.extend(message_bytes)
    payload.append(ETX)
    xor = 0
    for b in payload:
        xor ^= b
    checksum = f"{xor:02x}".encode("ascii")
    payload.extend(checksum)
    return bytes(payload)


def _parse_request(data: bytes) -> tuple[list[str] | None, str | None]:
    """Parse a CT002 wire-format request. Returns (fields, error)."""
    if len(data) < 10:
        return None, "Too short"
    if data[0] != SOH or data[1] != STX:
        return None, "Missing SOH/STX"
    sep_index = data.find(b"|", 2)
    if sep_index == -1:
        return None, "No separator after length"
    try:
        length = int(data[2:sep_index].decode("ascii"))
    except ValueError:
        return None, "Invalid length field"
    if len(data) != length:
        return None, f"Length mismatch (expected {length}, got {len(data)})"
    if data[-3] != ETX:
        return None, "Missing ETX"
    xor = 0
    for b in data[: length - 2]:
        xor ^= b
    expected_checksum = f"{xor:02x}".encode("ascii")
    actual_checksum = data[-2:]
    if actual_checksum.lower() != expected_checksum:
        if (
            actual_checksum[0:1] == b" "
            and actual_checksum[1:2].lower() == expected_checksum[1:2]
        ):
            pass  # tolerate leading space
        else:
            return None, f"Checksum mismatch (expected {expected_checksum}, got {actual_checksum})"
    try:
        message = data[sep_index:-3].decode("ascii")
    except UnicodeDecodeError:
        return None, "Invalid ASCII encoding"
    fields = message.split("|")[1:]  # skip leading empty string
    return fields, None


class _SharedUDPServer:
    """Singleton UDP server shared by all CT002 emulator coordinators.

    Listens on port 12345 and dispatches incoming packets to the correct
    coordinator based on the CT MAC in the request payload.
    """

    _instance: _SharedUDPServer | None = None

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _SharedUDPProtocol | None = None
        self._coordinators: dict[str, CT002EmulatorCoordinator] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls, hass: HomeAssistant) -> _SharedUDPServer:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls(hass)
        return cls._instance

    async def register(self, coordinator: CT002EmulatorCoordinator) -> bool:
        """Register a coordinator. Opens socket if first registration."""
        async with self._lock:
            mac = coordinator.ct_mac.lower()
            self._coordinators[mac] = coordinator

            if self._transport is not None:
                return True

            try:
                self._protocol = _SharedUDPProtocol(self)
                self._transport, _ = await self._hass.loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    local_addr=("0.0.0.0", UDP_PORT),
                )
                _LOGGER.info("Shared CT002 UDP server started on port %s", UDP_PORT)
                return True
            except OSError as err:
                _LOGGER.error("Failed to start shared CT002 UDP server on port %s: %s", UDP_PORT, err)
                return False

    def unregister(self, coordinator: CT002EmulatorCoordinator) -> None:
        """Unregister a coordinator. Closes socket if last registration."""
        mac = coordinator.ct_mac.lower()
        self._coordinators.pop(mac, None)

        if not self._coordinators and self._transport is not None:
            self._transport.close()
            self._transport = None
            self._protocol = None
            _LOGGER.info("Shared CT002 UDP server stopped (no more coordinators)")

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        """Send a UDP datagram."""
        if self._transport is not None:
            self._transport.sendto(data, addr)

    def _dispatch(self, data: bytes, addr: tuple[str, int]) -> None:
        """Parse CT MAC from request and dispatch to matching coordinator."""
        fields, _error = _parse_request(data)
        if fields is None or len(fields) < 4:
            return

        req_ct_mac = fields[3].lower()
        coordinator = self._coordinators.get(req_ct_mac)
        if coordinator is None:
            _LOGGER.debug(
                "No CT002 coordinator registered for MAC %s (from %s)",
                req_ct_mac, addr,
            )
            return

        asyncio.ensure_future(coordinator._handle_request(data, addr))


class _SharedUDPProtocol(asyncio.DatagramProtocol):
    """Protocol for the shared UDP server."""

    def __init__(self, server: _SharedUDPServer) -> None:
        self._server = server

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        pass

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._server._dispatch(data, addr)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.warning("CT002 shared UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc:
            _LOGGER.warning("CT002 shared UDP connection lost: %s", exc)


class CT002EmulatorCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that manages the CT002 UDP server."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self._name: str = entry.data[CONF_NAME]
        self._ct_mac: str = entry.data.get(CONF_CT_MAC_ADDRESS, "") or _generate_mac()
        self._power_entity: str = entry.options.get(
            CONF_POWER_ENTITY, entry.data.get(CONF_POWER_ENTITY, "")
        )

        self.enabled: bool = entry.data.get(CONF_ENABLED, DEFAULT_ENABLED)
        self.last_reported_power: int = 0
        self.last_packet_timestamp: datetime | None = None
        self.server_active: bool = False
        self._info_idx: int = 0
        self._shared_server = _SharedUDPServer.get_instance(hass)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self._name}",
            update_interval=None,
        )

    @property
    def ct_mac(self) -> str:
        """Return the CT MAC address."""
        return self._ct_mac

    @property
    def wifi_rssi(self) -> int:
        """Return the configured WiFi RSSI."""
        return DEFAULT_WIFI_RSSI

    def update_options(self) -> None:
        """Update settings from config entry options."""
        self._power_entity = self.entry.options.get(
            CONF_POWER_ENTITY, self.entry.data.get(CONF_POWER_ENTITY, "")
        )

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the CT002 server."""
        self.enabled = enabled
        self.async_set_updated_data(self._build_data())
        _LOGGER.info("CT002 server %s for %s", "enabled" if enabled else "disabled", self._name)

    def _get_power(self) -> int:
        """Read the power from the HA entity."""
        state: State | None = self.hass.states.get(self._power_entity)
        return _get_power_from_state(state)

    def _build_response(self, request_fields: list[str], power: int) -> bytes:
        """Build a CT002 HME-4 response payload."""
        bat_type = request_fields[0] if len(request_fields) > 0 else ""
        bat_mac = request_fields[1] if len(request_fields) > 1 else ""

        # Phase A = power, B/C = 0 (single-phase emulation)
        phase_a = power
        phase_b = 0
        phase_c = 0
        total = phase_a + phase_b + phase_c

        # Determine which bucket the power goes into
        # Phase A -> A bucket
        a_chrg = str(power) if power < 0 else "0"
        a_dchrg = str(power) if power > 0 else "0"

        response_fields = [
            CT_TYPE,                    # meter_dev_type
            self._ct_mac,               # meter_mac_code
            bat_type,                   # hhm_dev_type (echo request)
            bat_mac,                    # hhm_mac_code (echo request)
            str(phase_a),               # A_phase_power
            str(phase_b),               # B_phase_power
            str(phase_c),               # C_phase_power
            str(total),                 # total_power
            "1" if power != 0 else "0", # A_chrg_nb
            "0",                        # B_chrg_nb
            "0",                        # C_chrg_nb
            "0",                        # ABC_chrg_nb
            str(self.wifi_rssi),        # wifi_rssi
            str(self._info_idx),        # info_idx
            "0",                        # x_chrg_power
            a_chrg,                     # A_chrg_power
            "0",                        # B_chrg_power
            "0",                        # C_chrg_power
            "0",                        # ABC_chrg_power
            "0",                        # x_dchrg_power
            a_dchrg,                    # A_dchrg_power
            "0",                        # B_dchrg_power
            "0",                        # C_dchrg_power
            "0",                        # ABC_dchrg_power
        ]

        self._info_idx = (self._info_idx + 1) % 256
        return _build_payload(response_fields)

    def _build_data(self) -> dict[str, Any]:
        """Build current data dict for the coordinator."""
        return {
            "last_reported_power": self.last_reported_power,
            "last_packet_timestamp": self.last_packet_timestamp,
            "server_active": self.server_active and self.enabled,
            "ct_mac": self._ct_mac,
        }

    async def _handle_request(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle an incoming CT002 request from a battery."""
        if not self.enabled:
            return

        fields, error = _parse_request(data)
        if error:
            _LOGGER.debug("Invalid CT002 request from %s: %s", addr, error)
            return
        if len(fields) < 4:
            _LOGGER.debug("CT002 request from %s missing required fields", addr)
            return

        # Validate CT MAC: respond only if request targets our MAC or wildcard
        req_ct_mac = fields[3] if len(fields) > 3 else ""
        if self._ct_mac and req_ct_mac:
            if req_ct_mac.lower() != self._ct_mac.lower():
                _LOGGER.debug(
                    "Ignoring CT002 request from %s: CT MAC mismatch (req=%s, ours=%s)",
                    addr, req_ct_mac, self._ct_mac,
                )
                return

        power = self._get_power()
        response = self._build_response(fields, power)

        self._shared_server.sendto(response, addr)
        self.last_reported_power = power
        self.last_packet_timestamp = datetime.now(tz=timezone.utc)
        _LOGGER.debug(
            "CT002 response to %s - power=%sW",
            addr, power,
        )
        self.async_set_updated_data(self._build_data())

    async def async_start(self) -> None:
        """Register with the shared UDP server."""
        success = await self._shared_server.register(self)
        self.server_active = success
        self.async_set_updated_data(self._build_data())
        if success:
            _LOGGER.info(
                "CT002 server started for %s on port %s (MAC: %s)",
                self._name, UDP_PORT, self._ct_mac,
            )

    async def async_stop(self) -> None:
        """Unregister from the shared UDP server."""
        self._shared_server.unregister(self)
        self.server_active = False
        self.async_set_updated_data(self._build_data())
        _LOGGER.info("CT002 server stopped for %s", self._name)

    async def _async_update_data(self) -> dict[str, Any]:
        """Return current data."""
        return self._build_data()
