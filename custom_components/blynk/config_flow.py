"""Config flow for Blynk integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import logging
import homeassistant.helpers.config_validation as cv

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
        self._current_pin_index = 0

    async def async_step_user(self, user_input=None):
        """First step: Get token and scan interval."""
        errors = {}

        if user_input is not None:
            self._token = user_input[CONF_TOKEN].strip()
            self._scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

            if len(self._token) < 10:
                errors["base"] = "invalid_token_format"
            else:
                for entry in self._async_current_entries():
                    if entry.data.get(CONF_TOKEN) == self._token:
                        return self.async_abort(reason="already_configured")

                return await self.async_step_connection()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_TOKEN): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=5, max=1000000)),
            }),
            errors=errors,
        )

    async def async_step_connection(self, user_input=None):
        """Second step: test connection and discover pins."""
        errors = {}

        # Scan interval sadece ilk adımda alınır, burada tekrar sorulmaz
        api = BlynkCloudAPI(self._token)
        try:
            pins = await api.get_all_pins()
            if pins:
                self._discovered_pins = [
                    (pin.upper(), val) for pin, val in pins.items()
                    if val is not None
                ]
                _LOGGER.info("Discovered %d pins: %s", len(self._discovered_pins),
                             [pin for pin, _ in self._discovered_pins])

                if len(self._discovered_pins) == 1:
                    return await self.async_step_pin_config()
                else:
                    return await self.async_step_pin_selection()
            else:
                errors["base"] = "no_pins_found"
        except Exception as err:
            _LOGGER.error("Connection test failed: %s", err)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="connection",
            errors=errors,
        )

    async def async_step_pin_selection(self, user_input=None):
        """Pin selection step."""
        pin_options = {pin: f"{pin} (Value: {val})" for pin, val in self._discovered_pins}

        if user_input is not None:
            selected_pins = user_input.get("selected_pins", [])
            if isinstance(selected_pins, str):
                selected_pins = [selected_pins]
            if selected_pins:
                self._discovered_pins = [
                    (pin, val) for pin, val in self._discovered_pins
                    if pin in selected_pins
                ]
                return await self.async_step_pin_config()
            else:
                return self.async_show_form(
                    step_id="pin_selection",
                    data_schema=vol.Schema({
                        vol.Required("selected_pins", default=list(pin_options.keys())): cv.multi_select(pin_options),
                    }),
                    errors={"base": "no_pins_selected"}
                )

        return self.async_show_form(
            step_id="pin_selection",
            data_schema=vol.Schema({
                vol.Required("selected_pins", default=list(pin_options.keys())): cv.multi_select(pin_options),
            }),
            description_placeholders={
                "pin_count": len(self._discovered_pins)
            }
        )

    async def async_step_pin_config(self, user_input=None):
        """Handle pin configuration."""
        errors = {}
        current_pin, current_value = self._discovered_pins[self._current_pin_index]

        if user_input is not None:
            pin_type = user_input[CONF_PIN_TYPE]
            pin_name = user_input[CONF_PIN_NAME].strip()

            if not pin_name:
                errors["base"] = "invalid_pin_name"
            else:
                self._pin_configs[current_pin] = {
                    CONF_PIN_TYPE: pin_type,
                    CONF_PIN_NAME: pin_name,
                    CONF_DEVICE_CLASS: user_input.get(CONF_DEVICE_CLASS),
                    CONF_UNIT: user_input.get(CONF_UNIT),
                }

                self._current_pin_index += 1
                if self._current_pin_index < len(self._discovered_pins):
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

        suggested_type = self._suggest_pin_type(current_value)
        suggested_name = self._generate_pin_name(current_pin, current_value)

        if user_input and user_input.get(CONF_PIN_TYPE):
            pin_type = user_input[CONF_PIN_TYPE]
        else:
            pin_type = suggested_type

        device_classes = self._get_device_classes(pin_type)

        schema = {
            vol.Required(CONF_PIN_TYPE, default=suggested_type): vol.In(PIN_TYPES),
            vol.Required(CONF_PIN_NAME, default=suggested_name): str,
        }

        if device_classes:
            schema[vol.Optional(CONF_DEVICE_CLASS, default="none")] = vol.In(device_classes)

        if pin_type == PIN_TYPE_SENSOR:
            schema[vol.Optional(CONF_UNIT, default="none")] = vol.In(list(COMMON_UNITS.keys()))

        progress_text = f"Pin {self._current_pin_index + 1} / {len(self._discovered_pins)}"

        return self.async_show_form(
            step_id="pin_config",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "pin": current_pin,
                "value": current_value,
                "progress": progress_text,
            },
            errors=errors,
        )

    def _suggest_pin_type(self, value):
        """Suggest pin type based on value."""
        if isinstance(value, bool):
            return PIN_TYPE_BINARY_SENSOR
        elif isinstance(value, (int, float)):
            if value in [0, 1]:
                return PIN_TYPE_SWITCH
            else:
                return PIN_TYPE_SENSOR
        else:
            return PIN_TYPE_SENSOR

    def _generate_pin_name(self, pin, value):
        """Generate a default name based on pin and value."""
        if isinstance(value, bool):
            return f"{pin} Status"
        elif isinstance(value, (int, float)):
            if value in [0, 1]:
                return f"{pin} Switch"
            elif 0 <= value <= 100:
                return f"{pin} Level"
            else:
                return f"{pin} Sensor"
        else:
            return f"{pin} Data"

    def _get_device_classes(self, pin_type):
        """Return device class options based on pin type."""
        if pin_type == PIN_TYPE_SENSOR:
            return list(SENSOR_DEVICE_CLASSES.keys())
        elif pin_type == PIN_TYPE_BINARY_SENSOR:
            return list(BINARY_SENSOR_DEVICE_CLASSES.keys())
        elif pin_type == PIN_TYPE_SWITCH:
            return list(SWITCH_DEVICE_CLASSES.keys())
        return []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return BlynkOptionsFlowHandler(config_entry)


class BlynkOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(int, vol.Range(min=5, max=1000000)),
            })
        )
