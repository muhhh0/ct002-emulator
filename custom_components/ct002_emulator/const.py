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
CONF_REGISTRATION_MODE = "registration_mode"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SERVER = "server"
CONF_SELECTED_DEVICE = "selected_device"

# Registration modes
REGISTRATION_MODE_NONE = "none"
REGISTRATION_MODE_EXISTING = "existing"
REGISTRATION_MODE_NEW = "new"

# Marstek Cloud servers
MARSTEK_SERVERS = {
    "eu": "https://eu.hamedata.com",
    "us": "https://us.hamedata.com",
}

# Defaults
DEFAULT_NAME = "CT002 Grid Meter"
DEFAULT_WIFI_RSSI = -50
DEFAULT_ENABLED = True
DEFAULT_SERVER = "eu"
