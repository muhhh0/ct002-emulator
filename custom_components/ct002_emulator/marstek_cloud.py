"""Async Marstek Cloud API client for CT002 device registration."""

from __future__ import annotations

import hashlib
import logging
import random
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

MANAGED_MAC_PREFIX = "02b250"

USER_AGENT = "Dart/2.19 (dart:io)"
TIMEOUT = aiohttp.ClientTimeout(total=20)


class MarstekError(Exception):
    """Base error for Marstek Cloud API."""


class InvalidCredentials(MarstekError):
    """Wrong email or password."""


def _generate_managed_mac() -> str:
    """Generate a random managed MAC: 02b250 + 6 hex chars."""
    return MANAGED_MAC_PREFIX + f"{random.randint(0, 0xFFFFFF):06x}"


def _translate_message(code: Any, msg: Any) -> str:
    """Best-effort translation for common Marstek API messages."""
    msg_text = "" if msg is None else str(msg)
    code_text = "" if code is None else str(code)

    if code_text == "4" and ("\u5bc6\u7801\u9519\u8bef" in msg_text or "password" in msg_text.lower()):
        return "password incorrect"

    return msg_text


async def _http_get_json(
    session: aiohttp.ClientSession,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Make an async GET request and return parsed JSON."""
    _LOGGER.debug("API request: GET %s params=%s", url, params)
    try:
        async with session.get(url, params=params, headers=headers, timeout=TIMEOUT) as resp:
            body = await resp.text()
            _LOGGER.debug("API response: HTTP %s body=%s", resp.status, body[:500])
            if resp.status < 200 or resp.status >= 300:
                raise MarstekError(f"HTTP {resp.status} from {url}: {body[:200]}")
    except aiohttp.ClientError as exc:
        raise MarstekError(f"Network error calling {url}: {exc}") from exc

    try:
        result = __import__("json").loads(body)
    except Exception as exc:
        snippet = body[:200] if body else "<empty>"
        raise MarstekError(f"Non-JSON response from {url}: {snippet}") from exc

    _LOGGER.debug("API parsed: %s", result)
    return result


async def async_login(
    session: aiohttp.ClientSession,
    email: str,
    password: str,
    base_url: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Login to Marstek Cloud and return (token, merged_devices).

    Raises InvalidCredentials on wrong password, MarstekError on other failures.
    """
    pwd_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
    token_url = f"{base_url.rstrip('/')}/app/Solar/v2_get_device.php"
    token_resp = await _http_get_json(
        session, token_url, {"mailbox": email, "pwd": pwd_md5}
    )

    code = str(token_resp.get("code"))
    raw_msg = token_resp.get("msg")
    if code != "2" or not token_resp.get("token"):
        translated = _translate_message(code, raw_msg)
        if code == "4":
            raise InvalidCredentials(translated)
        raise MarstekError(f"Login failed (code={code}): {translated}")

    token = token_resp["token"]
    solar_devices = (
        token_resp.get("data") if isinstance(token_resp.get("data"), list) else []
    )

    # Fetch EMS device list for version/salt fields
    list_url = f"{base_url.rstrip('/')}/ems/api/v1/getDeviceList"
    list_resp = await _http_get_json(
        session,
        list_url,
        {"mailbox": email, "token": token},
        headers={"User-Agent": USER_AGENT},
    )
    ems_devices = (
        list_resp.get("data") if isinstance(list_resp.get("data"), list) else []
    )

    by_devid = {
        d.get("devid", ""): d
        for d in ems_devices
        if isinstance(d, dict) and d.get("devid")
    }

    merged = []
    for d in solar_devices:
        if not isinstance(d, dict):
            continue
        did = d.get("devid", "")
        e = by_devid.get(did, {})
        merged.append(
            {
                "devid": did,
                "name": d.get("name") or e.get("name"),
                "sn": d.get("sn"),
                "mac": d.get("mac") or e.get("mac"),
                "type": d.get("type") or e.get("type"),
                "access": d.get("access"),
                "bluetooth_name": d.get("bluetooth_name"),
                "version": e.get("version"),
                "salt": e.get("salt"),
            }
        )

    return token, merged


async def async_register_device(
    session: aiohttp.ClientSession,
    email: str,
    token: str,
    mac: str,
    base_url: str,
    timezone: str,
    name: str = "CT002 Emulator",
) -> None:
    """Register a new CT002 device in the Marstek Cloud."""
    add_url = f"{base_url.rstrip('/')}/app/Solar/v2_add_device.php"
    suffix = mac[-4:]
    params = {
        "name": name or "CT002 Emulator",
        "mailbox": email,
        "devid": mac,
        "mac": mac,
        "type": "HME-4",
        "token": token,
        "access": "1",
        "bluetooth_name": f"MST-SMR_{suffix}",
        "position": "{}",
        "timeZone": timezone,
        "version": "121",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "token": token,
        "User-Agent": USER_AGENT,
    }

    resp = await _http_get_json(session, add_url, params, headers=headers)
    code = str(resp.get("code", ""))
    _LOGGER.warning(
        "Marstek add_device response: code=%s msg=%s", code, resp.get("msg")
    )
    if code not in ("1", "2"):
        raise MarstekError(
            f"Registration failed (code={code}): {resp.get('msg', 'Unknown error')}"
        )


def filter_ct002_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter device list for CT002 (HME-4) devices."""
    return [d for d in devices if str(d.get("type", "")).upper() == "HME-4"]


def _generate_unique_mac(devices: list[dict[str, Any]]) -> str:
    """Generate a new managed MAC that doesn't collide with existing devices."""
    existing_ids = {
        str(d.get("devid", "")).lower()
        for d in devices
        if isinstance(d, dict) and d.get("devid")
    }
    existing_ids |= {
        str(d.get("mac", "")).lower()
        for d in devices
        if isinstance(d, dict) and d.get("mac")
    }

    mac = _generate_managed_mac()
    attempts = 0
    while mac in existing_ids and attempts < 200:
        mac = _generate_managed_mac()
        attempts += 1

    if mac in existing_ids:
        raise MarstekError("Could not generate unique MAC after 200 attempts")

    return mac


async def async_login_and_list_ct002(
    session: aiohttp.ClientSession,
    email: str,
    password: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """Login and return list of CT002 devices from the Marstek Cloud."""
    _token, devices = await async_login(session, email, password, base_url)
    ct002 = filter_ct002_devices(devices)
    _LOGGER.warning(
        "Found %d CT002 devices in cloud: %s",
        len(ct002),
        [(d.get("devid"), d.get("name")) for d in ct002],
    )
    return ct002


async def async_register_new_device(
    session: aiohttp.ClientSession,
    email: str,
    password: str,
    base_url: str,
    timezone: str,
    name: str = "CT002 Emulator",
) -> str:
    """Login, always create a NEW device, verify it was created. Returns MAC."""
    token, devices = await async_login(session, email, password, base_url)

    # Count devices before registration
    ct002_before = filter_ct002_devices(devices)
    _LOGGER.warning(
        "CT002 devices before registration: %d — %s",
        len(ct002_before),
        [(d.get("devid"), d.get("name")) for d in ct002_before],
    )

    # Generate unique MAC
    mac = _generate_unique_mac(devices)
    _LOGGER.warning("Registering NEW CT002 in Marstek Cloud: %s (name=%s)", mac, name)

    # Register
    await async_register_device(session, email, token, mac, base_url, timezone, name)

    # Re-fetch and verify
    _LOGGER.warning("Re-fetching device list to verify registration...")
    _, refreshed_devices = await async_login(session, email, password, base_url)
    ct002_after = filter_ct002_devices(refreshed_devices)
    _LOGGER.warning(
        "CT002 devices after registration: %d — %s",
        len(ct002_after),
        [(d.get("devid"), d.get("name")) for d in ct002_after],
    )

    # Verify: our new MAC should appear
    for d in ct002_after:
        if str(d.get("devid", "")).lower() == mac:
            _LOGGER.warning("Device %s CONFIRMED in cloud (name=%s)", mac, d.get("name"))
            return mac

    _LOGGER.warning(
        "Device %s NOT found in refreshed list — registration may have failed. "
        "Cloud has %d CT002 devices (was %d before)",
        mac, len(ct002_after), len(ct002_before),
    )
    return mac
