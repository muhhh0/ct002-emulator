"""Constants for the CT002 Grid Meter Emulator integration."""

DOMAIN = "ct002_emulator"

# Protocol
UDP_PORT = 12345
CT_TYPE = "HME-4"
SOH = 0x01
STX = 0x02
ETX = 0x03

# Config keys
CONF_NAME = "name"
CONF_CT_MAC_ADDRESS = "ct_mac_address"
CONF_POWER_ENTITY = "power_entity"
CONF_ENABLED = "enabled"

# Defaults
DEFAULT_NAME = "CT002 Grid Meter"
DEFAULT_WIFI_RSSI = -50
DEFAULT_ENABLED = True
