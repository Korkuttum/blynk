"""Constants for the Blynk integration."""
from datetime import timedelta
from typing import Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
)
from homeassistant.components.switch import (
    SwitchDeviceClass,
)

DOMAIN: Final = "blynk"
VERSION: Final = "1.0.0"
MANUFACTURER: Final = "Blynk"

# Configuration
CONF_TOKEN: Final = "token"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_PIN_TYPE: Final = "pin_type"
CONF_PIN_NAME: Final = "pin_name"
CONF_DEVICE_CLASS: Final = "device_class"
CONF_UNIT: Final = "unit"

# Defaults
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_TIMEOUT: Final = 10

# API
API_URL: Final = "https://blynk.cloud/external/api"
API_HEADERS: Final = {"Content-Type": "application/json"}

# Pin Types
PIN_TYPE_SENSOR: Final = "sensor"
PIN_TYPE_BINARY_SENSOR: Final = "binary_sensor"
PIN_TYPE_SWITCH: Final = "switch"

PIN_TYPES: Final = [
    PIN_TYPE_SENSOR,
    PIN_TYPE_BINARY_SENSOR,
    PIN_TYPE_SWITCH,
]

# Device Classes
SENSOR_DEVICE_CLASSES = {
    "temperature": SensorDeviceClass.TEMPERATURE,
    "humidity": SensorDeviceClass.HUMIDITY,
    "power": SensorDeviceClass.POWER,
    "current": SensorDeviceClass.CURRENT,
    "voltage": SensorDeviceClass.VOLTAGE,
    "energy": SensorDeviceClass.ENERGY,
    "battery": SensorDeviceClass.BATTERY,
    "none": None
}

BINARY_SENSOR_DEVICE_CLASSES = {
    "motion": BinarySensorDeviceClass.MOTION,
    "door": BinarySensorDeviceClass.DOOR,
    "window": BinarySensorDeviceClass.WINDOW,
    "light": BinarySensorDeviceClass.LIGHT,
    "none": None
}

SWITCH_DEVICE_CLASSES = {
    "switch": SwitchDeviceClass.SWITCH,
    "outlet": SwitchDeviceClass.OUTLET,
    "none": None
}

# Common Units
COMMON_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "power": "W",
    "current": "A",
    "voltage": "V",
    "energy": "kWh",
    "battery": "%",
    "none": None
}

# Error Constants
ERROR_CANNOT_CONNECT: Final = "cannot_connect"
ERROR_INVALID_AUTH: Final = "invalid_auth"
ERROR_NO_PINS_FOUND: Final = "no_pins_found"

# Integration Metadata
ATTRIBUTION: Final = "Data provided by Blynk Cloud"
INTEGRATION_CREATED: Final = "2025-06-25"
INTEGRATION_CREATOR: Final = "Korkuttum"

# Update coordinator parameters
SCAN_INTERVAL: Final = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
REQUEST_TIMEOUT: Final = 10