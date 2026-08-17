#!/bin/bash
# Stop test Home Assistant instance
podman stop ha-test-marstek 2>/dev/null && echo "Stopped." || echo "Not running."
podman rm ha-test-marstek 2>/dev/null || true
