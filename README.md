# CT002 Grid Meter Emulator

A Home Assistant custom component that emulates a CT002 Smart Meter for Marstek storage devices (B2500, B2500D).

> **Early Stage / Vibe Coded**
> This project was developed with AI assistance ("vibe coding") and is in an early, experimental stage. It works for the author's specific setup but may lack edge-case handling, comprehensive error recovery, or production-grade robustness. Use at your own risk and please report issues.

## Features

- Responds to battery polling requests on UDP port 12345
- Passes through configured power sensor values 1:1
- Single-phase emulation (Phase A only, B/C = 0)
- Configurable CT MAC address (auto-generated if not specified)
- Enable/disable switch per instance
- Supports multiple CT002 instances (shared UDP server, MAC-based dispatch)

## Installation

### HACS (Home Assistant Community Store)

1. Add this repository as a custom repository in HACS
2. Install "CT002 Grid Meter Emulator"
3. Restart Home Assistant

### Manual Installation

1. Copy `custom_components/ct002_emulator/` to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Marstek App Setup

The emulated CT002 device must first be registered via [AstraMeter](https://github.com/tomquist/AstraMeter) so it appears in the Marstek app. This feature is not yet built into the integration — AstraMeter is currently required for the initial device registration. Once registered, switch to the CT002 Grid Meter Emulator integration and the B2500 will discover it automatically via UDP broadcast.

## Network Configuration

The B2500 battery discovers the CT002 meter via UDP broadcast on port 12345. No IP configuration is needed — the battery automatically finds the emulator on your network.

### Docker / Podman

Both approaches work:

**Option A: Host network mode**

```bash
docker run --network host ...
```

**Option B: Port forwarding**

```bash
docker run -p 12345:12345/udp ...
```

### Home Assistant OS / Supervised

No network configuration needed — the integration listens on all interfaces by default.

## Configuration

1. Go to Settings -> Devices & Services -> Add Integration
2. Search for "CT002 Grid Meter Emulator"
3. Configure:
   - **Name**: Display name for this CT002 instance
   - **CT MAC Address**: MAC address of the CT002 (auto-generated if left empty, format: `a020a6010203` or `A0:20:A6:01:02:03`)
   - **Power Sensor Entity**: The sensor entity providing power values in watts

## Options

After setup, you can configure:
- **Power Sensor Entity**: Change the power source sensor

## Entities

The integration creates:
- **Sensor**: Last Reported Power (W), Last Packet Timestamp
- **Binary Sensor**: Server Active
- **Switch**: CT002 Enabled

## Protocol

The integration implements the CT002 HME-4 protocol:
- Responds to UDP requests on port 12345
- Validates incoming packets (SOH/STX/Length/Fields/ETX/XOR checksum)
- Returns 24-field HME-4 response with power values
- Only responds to requests with matching CT MAC address

## Testing

### Unit Tests

```bash
pytest tests/test_coordinator.py -v
```

### Live Tests (requires running HA instance)

```bash
pytest tests/test_live.py -v -m live
```

## License

MIT
