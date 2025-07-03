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
DEFAULT_SCAN_INTERVAL: Final = 120
DEFAULT_TIMEOUT: Final = 10

# API
API_URL: Final = "https://blynk.cloud/external/api"
API_HEADERS: Final = {"Content-Type": "application/json"}

# Pin Types
PIN_TYPE_SENSOR: Final = "sensor"
PIN_TYPE_BINARY_SENSOR: Final = "binary_sensor"
PIN_TYPE_SWITCH: Final = "switch"
PIN_TYPE_INPUT_NUMBER: Final = "input_number"
PIN_TYPE_BUTTON: Final = "button"
PIN_TYPE_INPUT_TEXT: Final = "input_text"

PIN_TYPE_OPTIONS: Final = {
    PIN_TYPE_SENSOR: "Sensor",
    PIN_TYPE_BINARY_SENSOR: "Binary Sensor",
    PIN_TYPE_SWITCH: "Switch",
    PIN_TYPE_INPUT_NUMBER: "Input Number",
    PIN_TYPE_BUTTON: "Button",
    PIN_TYPE_INPUT_TEXT: "Text Input"
}

# Device Classes
SENSOR_DEVICE_CLASSES = {
    "none": None,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "humidity": SensorDeviceClass.HUMIDITY,
    "power": SensorDeviceClass.POWER,
    "current": SensorDeviceClass.CURRENT,
    "voltage": SensorDeviceClass.VOLTAGE,
    "energy": SensorDeviceClass.ENERGY,
    "battery": SensorDeviceClass.BATTERY
}

BINARY_SENSOR_DEVICE_CLASSES = {
    "none": None,
    "motion": BinarySensorDeviceClass.MOTION,
    "door": BinarySensorDeviceClass.DOOR,
    "window": BinarySensorDeviceClass.WINDOW,
    "light": BinarySensorDeviceClass.LIGHT
}

SWITCH_DEVICE_CLASSES = {
    "none": None,
    "switch": SwitchDeviceClass.SWITCH,
    "outlet": SwitchDeviceClass.OUTLET
}

COMMON_UNITS = {
    "none": None,
    "°C": "°C",
    "%": "%",
    "W": "W",
    "A": "A",
    "V": "V",
    "kWh": "kWh"
}

# Input Number Configuration
INPUT_NUMBER_MIN: Final = 0
INPUT_NUMBER_MAX: Final = 100
INPUT_NUMBER_STEP: Final = 1

# Input Text Configuration
INPUT_TEXT_MIN_LENGTH: Final = 0
INPUT_TEXT_MAX_LENGTH: Final = 100

# Integration Metadata
ATTRIBUTION: Final = "Data provided by Blynk Cloud"
INTEGRATION_CREATED: Final = "2025-07-01"
INTEGRATION_CREATOR: Final = "Korkuttum"

# Update coordinator parameters
SCAN_INTERVAL: Final = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
REQUEST_TIMEOUT: Final = 10
