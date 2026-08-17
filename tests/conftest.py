"""Mock homeassistant modules before any imports."""
import sys
import types

# Create mock modules
_mock_mods = {}
for mod_name in [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.data_entry_flow",
    "homeassistant.helpers",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.selector",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.components",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
]:
    m = types.ModuleType(mod_name)
    m.__path__ = []
    m.__package__ = mod_name
    _mock_mods[mod_name] = m
    sys.modules[mod_name] = m

ha = _mock_mods["homeassistant"]
ha_const = _mock_mods["homeassistant.const"]
ha_core = _mock_mods["homeassistant.core"]
ha_cfg = _mock_mods["homeassistant.config_entries"]
ha_helpers = _mock_mods["homeassistant.helpers"]
ha_entity = _mock_mods["homeassistant.helpers.entity"]
ha_entity_platform = _mock_mods["homeassistant.helpers.entity_platform"]
ha_uc = _mock_mods["homeassistant.helpers.update_coordinator"]
ha_bin = _mock_mods["homeassistant.components.binary_sensor"]
ha_sensor = _mock_mods["homeassistant.components.sensor"]
ha_switch = _mock_mods["homeassistant.components.switch"]

# DataUpdateCoordinator stub
class FakeDataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name=None, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None

    def async_set_updated_data(self, data):
        self.data = data

ha_uc.DataUpdateCoordinator = FakeDataUpdateCoordinator

# CoordinatorEntity stub
ha_uc.CoordinatorEntity = type("CoordinatorEntity", (), {
    "__init__": lambda self, coord: None,
})

# CONF_NAME
ha_const.CONF_NAME = "name"

# ConfigEntry
ha_cfg.ConfigEntry = type("ConfigEntry", (), {})

# HomeAssistant
ha.HomeAssistant = type("HomeAssistant", (), {})

# State + HomeAssistant (both live in homeassistant.core)
ha_core.State = type("State", (), {})
ha_core.HomeAssistant = type("HomeAssistant", (), {})

# Platform enum
ha_const.Platform = type("Platform", (), {"SENSOR": "sensor", "BINARY_SENSOR": "binary_sensor", "SWITCH": "switch"})()

# Binary sensor
ha_bin.BinarySensorDeviceClass = type("BinarySensorDeviceClass", (), {"RUNNING": "running"})()
ha_bin.BinarySensorEntity = type("BinarySensorEntity", (), {})

# Sensor
ha_sensor.SensorDeviceClass = type("SensorDeviceClass", (), {"POWER": "power", "TIMESTAMP": "timestamp"})()
ha_sensor.SensorStateClass = type("SensorStateClass", (), {"MEASUREMENT": "measurement"})()
ha_sensor.SensorEntity = type("SensorEntity", (), {})

# Switch
ha_switch.SwitchDeviceClass = type("SwitchDeviceClass", (), {"SWITCH": "switch"})()
ha_switch.SwitchEntity = type("SwitchEntity", (), {})

# UnitOfPower
ha_const.UnitOfPower = type("UnitOfPower", (), {"WATT": "W"})()

# Entity helpers
ha_entity.DeviceInfo = type("DeviceInfo", (), {"__init__": lambda self, **kw: None})
ha_entity_platform.AddEntitiesCallback = type("AddEntitiesCallback", (), {})

# config_flow helpers
ha_core.callback = lambda func: func  # decorator passthrough
_mock_mods["homeassistant.data_entry_flow"].FlowResult = type("FlowResult", (), {})
_mock_mods["homeassistant.helpers"].selector = type("selector", (), {"SelectOptionDict": type("SelectOptionDict", (), {}), "SelectSelector": type("SelectSelector", (), {}), "SelectSelectorConfig": type("SelectSelectorConfig", (), {}), "SelectSelectorMode": type("SelectSelectorMode", (), {"DROPDOWN": "dropdown"})()})()


# ---------------------------------------------------------------------------
# Live test support (--live marker)
# ---------------------------------------------------------------------------

import asyncio
import json
import socket
import time
from pathlib import Path

import aiohttp
import jwt
import pytest
import pytest_asyncio

AUTH_FILE = Path("/tmp/opencode/auth.json")
HA_URL = "http://localhost:8123"
HA_WS_URL = "ws://localhost:8123/api/websocket"
CT_UDP_PORT = 12345
LIVE_TIMEOUT = 5.0


def pytest_configure(config):
    config.addinivalue_line("markers", "live: mark test as requiring a running HA instance")


class HAClient:
    """Async WebSocket client for Home Assistant."""

    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._msg_id = 0

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(HA_WS_URL)
        msg = await self._ws.receive_json()
        assert msg["type"] == "auth_required"

        token = self._make_jwt()
        await self._ws.send_json({"type": "auth", "access_token": token})
        msg = await self._ws.receive_json()
        assert msg["type"] == "auth_ok", f"Auth failed: {msg}"

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _make_jwt(self) -> str:
        with open(AUTH_FILE) as f:
            auth_data = json.load(f)
        admin_user = None
        for u in auth_data["data"]["users"]:
            if u.get("is_owner"):
                admin_user = u["id"]
                break
        for rt in auth_data["data"]["refresh_tokens"]:
            if rt.get("user_id") != admin_user:
                continue
            payload = {
                "iss": rt["id"],
                "iat": int(time.time()),
                "exp": int(time.time()) + 86400,
                "sub": rt["user_id"],
            }
            return jwt.encode(payload, rt["jwt_key"], algorithm="HS256")
        raise RuntimeError("No admin refresh token found")

    async def get_states(self) -> dict[str, dict]:
        """Return all entity states as {entity_id: {state, attributes}}."""
        rid = self._next_id()
        await self._ws.send_json({"id": rid, "type": "get_states"})
        msg = await self._ws.receive_json()
        assert msg.get("id") == rid
        return {
            s["entity_id"]: {"state": s["state"], "attributes": s.get("attributes", {})}
            for s in msg.get("result", [])
        }

    async def get_entity(self, entity_id: str) -> dict:
        """Get state of a single entity."""
        states = await self.get_states()
        return states.get(entity_id, {"state": None, "attributes": {}})

    async def call_service(self, domain: str, service: str, entity_id: str, **kwargs) -> dict:
        """Call a HA service and return the result."""
        rid = self._next_id()
        await self._ws.send_json({
            "id": rid,
            "type": "call_service",
            "domain": domain,
            "service": service,
            "target": {"entity_id": entity_id},
            "service_data": kwargs or {},
        })
        msg = await self._ws.receive_json()
        return msg

    async def wait_for_state(
        self,
        entity_id: str,
        expected_state: str | None = None,
        timeout: float = LIVE_TIMEOUT,
        poll_interval: float = 0.5,
    ) -> dict:
        """Poll until entity reaches expected state or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            entity = await self.get_entity(entity_id)
            if expected_state is None or entity["state"] == expected_state:
                return entity
            await asyncio.sleep(poll_interval)
        # Return final state even if not matching
        return await self.get_entity(entity_id)

    def send_ct002_packet(
        self,
        ct_mac: str,
        bat_mac: str = "a020a6326604",
        power: str = "0",
        response_port: int | None = None,
    ) -> tuple[bytes, tuple[str, int]] | None:
        """Send a CT002 UDP request.

        If response_port is given, binds to that port (0 = random free port)
        and waits for a response. Returns (response_data, sender_addr) or None.
        """
        from custom_components.ct002_emulator.coordinator import _build_payload

        fields = ["HMG-50", bat_mac, "HME-4", ct_mac, "1", power]
        packet = _build_payload(fields)

        if response_port is not None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", response_port))
            sock.settimeout(LIVE_TIMEOUT)
            try:
                sock.sendto(bytes(packet), ("127.0.0.1", CT_UDP_PORT))
                data, addr = sock.recvfrom(2048)
                return data, addr
            except socket.timeout:
                return None
            finally:
                sock.close()
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(bytes(packet), ("127.0.0.1", CT_UDP_PORT))
            sock.close()
            return None


@pytest.fixture(scope="session")
def _ha_reachable():
    """One-time check if HA is reachable; skip all live tests if not."""
    try:
        import urllib.request
        urllib.request.urlopen(HA_URL, timeout=3)
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def ha_client(_ha_reachable):
    """Per-test HA WebSocket client (fresh connection each test)."""
    if not _ha_reachable:
        pytest.skip("HA not reachable at " + HA_URL)
    client = HAClient()
    await client.connect()
    yield client
    await client.close()
