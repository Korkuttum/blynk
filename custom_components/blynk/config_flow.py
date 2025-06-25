"""Config flow for Blynk integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import logging

from .const import (
    DOMAIN,
    CONF_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_PIN_TYPE,
    CONF_PIN_NAME,
    CONF_DEVICE_CLASS,
    CONF_UNIT,
    DEFAULT_SCAN_INTERVAL,
    PIN_TYPES,
    SENSOR_DEVICE_CLASSES,
    BINARY_SENSOR_DEVICE_CLASSES,
    SWITCH_DEVICE_CLASSES,
    COMMON_UNITS,
    PIN_TYPE_SENSOR,
    PIN_TYPE_BINARY_SENSOR,
    PIN_TYPE_SWITCH,
)
from .blynk_api import BlynkCloudAPI

_LOGGER = logging.getLogger(__name__)

class BlynkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Blynk."""

    VERSION = 1
    
    def __init__(self):
        """Initialize the config flow."""
        self._token = None
        self._scan_interval = DEFAULT_SCAN_INTERVAL
        self._discovered_pins = []
        self._pin_configs = {}
        self._current_pin = None

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            self._token = user_input[CONF_TOKEN]
            self._scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

            api = BlynkCloudAPI(self._token)
            try:
                pins = await api.get_all_pins()
                if pins:
                    self._discovered_pins = [
                        (pin.upper(), val) for pin, val in pins.items() 
                        if val is not None
                    ]
                    self._current_pin = self._discovered_pins[0][0]
                    return await self.async_step_pin_config()
                else:
                    errors["base"] = "no_pins_found"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_TOKEN): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }),
            errors=errors,
        )

    async def async_step_pin_config(self, user_input=None):
        """Handle pin configuration."""
        errors = {}

        if user_input is not None:
            pin_type = user_input[CONF_PIN_TYPE]
            
            # Pin yapılandırmasını kaydet
            self._pin_configs[self._current_pin] = {
                CONF_PIN_TYPE: pin_type,
                CONF_PIN_NAME: user_input[CONF_PIN_NAME],
                CONF_DEVICE_CLASS: user_input.get(CONF_DEVICE_CLASS),
                CONF_UNIT: user_input.get(CONF_UNIT),
            }

            # Sıradaki pine geç veya kurulumu tamamla
            remaining_pins = [pin for pin, _ in self._discovered_pins if pin not in self._pin_configs]
            if remaining_pins:
                self._current_pin = remaining_pins[0]
                return await self.async_step_pin_config()
            else:
                return self.async_create_entry(
                    title=f"Blynk Device ({self._token[:8]}...)",
                    data={
                        CONF_TOKEN: self._token,
                        CONF_SCAN_INTERVAL: self._scan_interval,
                        "pins": self._pin_configs,
                    }
                )

        # Pin tipine göre device class seçeneklerini belirle
        device_classes = {}
        if user_input and CONF_PIN_TYPE in user_input:
            if user_input[CONF_PIN_TYPE] == PIN_TYPE_SENSOR:
                device_classes = SENSOR_DEVICE_CLASSES
            elif user_input[CONF_PIN_TYPE] == PIN_TYPE_BINARY_SENSOR:
                device_classes = BINARY_SENSOR_DEVICE_CLASSES
            elif user_input[CONF_PIN_TYPE] == PIN_TYPE_SWITCH:
                device_classes = SWITCH_DEVICE_CLASSES

        # Şema oluştur
        schema = {
            vol.Required(CONF_PIN_TYPE): vol.In(PIN_TYPES),
            vol.Required(CONF_PIN_NAME, default=f"Blynk {self._current_pin}"): str,
        }

        # Device class seçeneği ekle
        if device_classes:
            schema[vol.Optional(CONF_DEVICE_CLASS, default="none")] = vol.In(
                list(device_classes.keys())
            )

        # Sensör tipi için birim seçeneği ekle
        if user_input and user_input.get(CONF_PIN_TYPE) == PIN_TYPE_SENSOR:
            schema[vol.Optional(CONF_UNIT, default="none")] = vol.In(
                list(COMMON_UNITS.keys())
            )

        current_value = next((val for pin, val in self._discovered_pins if pin == self._current_pin), None)

        return self.async_show_form(
            step_id="pin_config",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "pin": self._current_pin,
                "value": current_value,
            },
            errors=errors,
        )