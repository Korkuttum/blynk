"""Config flow for Blynk with pins default selected and per-pin type dropdown (fixed, no description)."""
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

    VERSION = 8

    def __init__(self):
        self._token = None
        self._scan_interval = DEFAULT_SCAN_INTERVAL
        self._discovered_pins = []
        self._pin_values = {}
        self._pin_selection = []
        self._pin_types = {}
        self._pin_configs = {}
        self._pin_config_order = []
        self._current_pin_index = 0

    async def async_step_user(self, user_input=None):
        """Step 1: Token and scan interval."""
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
        """Step 2: Discover pins and go to selection."""
        errors = {}
        api = BlynkCloudAPI(self._token)
        try:
            pins = await api.get_all_pins()
            if pins:
                self._discovered_pins = []
                self._pin_values = {}
                for pin, value in pins.items():
                    pin_name = pin.upper()
                    self._discovered_pins.append(pin_name)
                    self._pin_values[pin_name] = value
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
        """Step 3: Pin selection and type (all selected by default, type dropdown under each)."""
        errors = {}
        pin_schema = {}
        for pin in self._discovered_pins:
            pin_schema[vol.Optional(f"enable_{pin}", default=True, description=f"{pin} ekle?")] = bool
            pin_schema[vol.Optional(f"type_{pin}", default=PIN_TYPE_SENSOR, description=f"{pin} türü")] = vol.In(PIN_TYPES)

        if user_input is not None:
            self._pin_selection = []
            self._pin_types = {}
            for pin in self._discovered_pins:
                if user_input.get(f"enable_{pin}", True):
                    self._pin_selection.append(pin)
                    self._pin_types[pin] = user_input.get(f"type_{pin}", PIN_TYPE_SENSOR)
            if not self._pin_selection:
                errors["base"] = "no_pins_selected"
            else:
                self._pin_config_order = list(self._pin_selection)
                self._pin_configs = {}
                self._current_pin_index = 0
                return await self.async_step_pin_config()
        return self.async_show_form(
            step_id="pin_selection",
            data_schema=vol.Schema(pin_schema),
            errors=errors,
        )

    async def async_step_pin_config(self, user_input=None):
        """Step 4+: Configure each selected pin in turn (name, class/unit)."""
        errors = {}
        # Save previous pin config
        if user_input is not None and self._current_pin_index > 0:
            prev_pin = self._pin_config_order[self._current_pin_index - 1]
            conf = {
                CONF_PIN_TYPE: self._pin_types[prev_pin],
                CONF_PIN_NAME: user_input.get(CONF_PIN_NAME, prev_pin).strip(),
            }
            if CONF_DEVICE_CLASS in user_input:
                conf[CONF_DEVICE_CLASS] = user_input[CONF_DEVICE_CLASS]
            if CONF_UNIT in user_input:
                conf[CONF_UNIT] = user_input[CONF_UNIT]
            self._pin_configs[prev_pin] = conf

        # Hepsi bitti mi?
        if self._current_pin_index >= len(self._pin_config_order):
            return self.async_create_entry(
                title=f"Blynk Device ({self._token[:8]}...)",
                data={
                    CONF_TOKEN: self._token,
                    CONF_SCAN_INTERVAL: self._scan_interval,
                    "pins": self._pin_configs,
                }
            )

        # Sıradaki pini yapılandır
        pin = self._pin_config_order[self._current_pin_index]
        pin_type = self._pin_types[pin]
        value = self._pin_values.get(pin, "-")

        schema = {
            vol.Required(CONF_PIN_NAME, default=pin, description="Pin adı"): str,
        }
        # Class/unit seçenekleri tipine göre
        if pin_type == PIN_TYPE_SENSOR:
            schema[vol.Optional(CONF_DEVICE_CLASS, default="none", description="Sensör class seçin")] = vol.In(list(SENSOR_DEVICE_CLASSES.keys()))
            schema[vol.Optional(CONF_UNIT, default="none", description="Sensör birimi seçin")] = vol.In(list(COMMON_UNITS.keys()))
        elif pin_type == PIN_TYPE_BINARY_SENSOR:
            schema[vol.Optional(CONF_DEVICE_CLASS, default="none", description="Binary sensor class seçin")] = vol.In(list(BINARY_SENSOR_DEVICE_CLASSES.keys()))
        elif pin_type == PIN_TYPE_SWITCH:
            schema[vol.Optional(CONF_DEVICE_CLASS, default="none", description="Switch class seçin")] = vol.In(list(SWITCH_DEVICE_CLASSES.keys()))

        self._current_pin_index += 1

        return self.async_show_form(
            step_id="pin_config",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BlynkOptionsFlowHandler(config_entry)

class BlynkOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry):
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
