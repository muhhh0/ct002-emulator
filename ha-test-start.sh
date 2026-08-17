#!/bin/bash
# Start test Home Assistant instance with marstek_ct002 integration
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$SCRIPT_DIR/.ha-test-config"
CONTAINER_NAME="ha-test-marstek"

# Stop existing container if running
podman rm -f "$CONTAINER_NAME" 2>/dev/null || true

echo "Starting Home Assistant test instance..."
echo "Config: $CONFIG_DIR"
echo "Web UI: http://localhost:8123"
echo ""

podman run -d \
  --name "$CONTAINER_NAME" \
  -p 8123:8123 \
  -v "$CONFIG_DIR:/config:Z" \
  -e TZ=Europe/Berlin \
  --network host \
  ghcr.io/home-assistant/home-assistant:stable

echo "Container started. HA takes ~30-60s to boot."
echo "Logs: podman logs -f $CONTAINER_NAME"
echo "Stop: podman stop $CONTAINER_NAME"
