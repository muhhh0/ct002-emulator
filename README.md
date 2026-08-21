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
- Built-in Marstek Cloud registration (no AstraMeter needed)
- Server selection: EU / US

## Installation

### HACS (Home Assistant Community Store)

1. Add this repository as a custom repository in HACS
2. Install "CT002 Grid Meter Emulator"
3. Restart Home Assistant

### Manual Installation

1. Copy `custom_components/ct002_emulator/` to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Marstek App Setup

The emulated CT002 device needs to be registered in the Marstek Cloud so the B2500 battery can discover it and the Marstek app can display it. This integration now handles registration directly.

During setup, you can choose one of three registration modes:

- **No cloud registration**: Skip cloud setup. You enter the CT MAC address manually. Useful for testing or if you handle registration separately.
- **Use existing device**: Log in to your Marstek Cloud account and select an existing CT002 device from the list.
- **Register new device**: Log in to your Marstek Cloud account. The integration creates a new CT002 device with a unique MAC address, verifies it was created, and uses it for emulation.

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
3. Follow the setup steps:

**Step 1 — Name**: Display name for this CT002 instance.

**Step 2 — Registration Mode**:
   - **No cloud registration** → Step 4
   - **Use existing device** → Step 3
   - **Register new device** → Step 3

**Step 3 — Marstek Cloud Login** (only if registration mode is not "None"):
   - **Email**: Your Marstek account email
   - **Password**: Your Marstek account password (sent as MD5 hash)
   - **Server**: EU (`eu.hamedata.com`) or US (`us.hamedata.com`)
   - **Note**: Only the EU server has been tested so far. US server support is untested — please report results if you try it.
   - For "Use existing device": select a CT002 device from the list
   - For "Register new device": a new device is created automatically

**Step 4 — Power Sensor Entity**: Select the sensor entity that provides grid power values in watts.

## Reconfiguration

After setup, you can reconfigure an existing entry (Settings -> Devices & Services -> CT002 Grid Meter Emulator -> Configure):
- **Name**: Change the display name
- **CT MAC Address**: Change the CT MAC address
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

## Acknowledgments

This project builds on the work of [AstraMeter](https://github.com/tomquist/AstraMeter). The CT002/CT003 protocol documentation and much of the Marstek Cloud API reverse-engineering were derived from that project. Thank you to the AstraMeter contributors for making this possible.

## License

MIT
