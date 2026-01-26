"""Config flow for Blynk."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import logging
import asyncio
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_PIN_TYPE,
    CONF_PIN_NAME,
    CONF_DEVICE_CLASS,
    CONF_UNIT,
    CONF_USE_MQTT,
    CONF_MQTT_BROKER,
    CONF_MQTT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_MQTT_BROKER,
    DEFAULT_MQTT_PORT,
    PIN_TYPE_OPTIONS,
    SENSOR_DEVICE_CLASSES,
    BINARY_SENSOR_DEVICE_CLASSES,
    SWITCH_DEVICE_CLASSES,
    COMMON_UNITS,
    PIN_TYPE_SENSOR,
    PIN_TYPE_BINARY_SENSOR,
    PIN_TYPE_SWITCH,
    PIN_TYPE_INPUT_NUMBER,
    PIN_TYPE_BUTTON,
    PIN_TYPE_INPUT_TEXT,
    INPUT_NUMBER_MIN,
    INPUT_NUMBER_MAX,
    INPUT_NUMBER_STEP,
    INPUT_TEXT_MIN_LENGTH,
    INPUT_TEXT_MAX_LENGTH,
)
from .blynk_api import BlynkCloudAPI
from .mqtt_client import BlynkMQTTClient

_LOGGER = logging.getLogger(__name__)

class BlynkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Blynk."""

    VERSION = 9

    def __init__(self):
        """Initialize the config flow."""
        self._token = None
        self._scan_interval = DEFAULT_SCAN_INTERVAL
        self._use_mqtt = False
        self._mqtt_broker = DEFAULT_MQTT_BROKER
        self._mqtt_port = DEFAULT_MQTT_PORT
        self._discovered_pins = []
        self._pin_values = {}
        self._pin_selection = []
        self._pin_types = {}
        self._pin_configs = {}
        self._pin_config_order = []
        self._current_pin_index = 0
        self._pin_mapping = {}
        self._mqtt_client = None
        self._api = None

    async def async_step_user(self, user_input=None):
        """Step 1: Token, MQTT and scan interval."""
        errors = {}
        if user_input is not None:
            self._token = user_input[CONF_TOKEN].strip()
            self._scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            self._use_mqtt = user_input.get(CONF_USE_MQTT, False)
            
            if self._use_mqtt:
                self._mqtt_broker = user_input.get(CONF_MQTT_BROKER, DEFAULT_MQTT_BROKER)
                self._mqtt_port = user_input.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)
            
            if len(self._token) < 10:
                errors["base"] = "invalid_token_format"
            else:
                for entry in self._async_current_entries():
                    if entry.data.get(CONF_TOKEN) == self._token:
                        return self.async_abort(reason="already_configured")
                
                self._api = BlynkCloudAPI(self._token)
                return await self.async_step_connection()

        schema = {
            vol.Required(CONF_TOKEN): str,
            vol.Optional(CONF_USE_MQTT, default=False): selector.BooleanSelector(
                selector.BooleanSelectorConfig(),
            ),
        }
        
        if self._use_mqtt or (user_input and user_input.get(CONF_USE_MQTT, False)):
            schema[vol.Optional(CONF_MQTT_BROKER, default=DEFAULT_MQTT_BROKER)] = str
            schema[vol.Optional(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=65535,
                    mode=selector.NumberSelectorMode.BOX
                ),
            )
        
        schema[vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL)] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=5,
                max=1000000,
                mode=selector.NumberSelectorMode.BOX
            ),
        )
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def async_step_connection(self, user_input=None):
        """Step 2: Discover pins with effective MQTT mapping."""
        errors = {}
        
        if self._use_mqtt and not self._mqtt_broker:
            self._mqtt_broker = DEFAULT_MQTT_BROKER
        if self._use_mqtt and not self._mqtt_port:
            self._mqtt_port = DEFAULT_MQTT_PORT
            
        try:
            if isinstance(self._mqtt_port, str):
                self._mqtt_port = int(float(self._mqtt_port))
            else:
                self._mqtt_port = int(self._mqtt_port)
        except (ValueError, TypeError):
            self._mqtt_port = DEFAULT_MQTT_PORT
        
        try:
            pins = await self._api.get_all_pins()
            if pins:
                self._discovered_pins = []
                self._pin_values = {}
                for pin, value in pins.items():
                    pin_name = pin.upper()
                    self._discovered_pins.append(pin_name)
                    self._pin_values[pin_name] = value
                
                if self._use_mqtt:
                    _LOGGER.info("Starting effective MQTT pin mapping with broker %s:%s...", 
                                self._mqtt_broker, self._mqtt_port)
                    
                    from .mqtt_client import BlynkMQTTClient
                    
                    discovered_pin_names = set()
                    received_messages = []
                    
                    async def on_mqtt_message(topic: str, data: dict):
                        """Handle MQTT message during discovery."""
                        if "/ds/" in topic:
                            pin_name = topic.split("/ds/")[1].upper()
                            discovered_pin_names.add(pin_name)
                            
                            if isinstance(data, dict) and "value" in data:
                                value = data["value"]
                            else:
                                value = data
                            
                            received_messages.append({
                                "pin_name": pin_name,
                                "value": value,
                                "timestamp": asyncio.get_event_loop().time()
                            })
                    
                    self._mqtt_client = BlynkMQTTClient(
                        auth_token=self._token,
                        on_message_callback=on_mqtt_message,
                        broker=self._mqtt_broker,
                        port=self._mqtt_port,
                    )
                    
                    connected = await self._mqtt_client.async_connect(asyncio.get_event_loop())
                    if not connected:
                        _LOGGER.warning("MQTT connection failed during discovery")
                        return await self.async_step_pin_selection()
                    
                    _LOGGER.info("Phase 1: Quick listening for MQTT messages (3 seconds)...")
                    await asyncio.sleep(3)
                    
                    # Store original values
                    original_values = self._pin_values.copy()
                    
                    # Test each pin with smart strategy
                    for pin_number, current_value in self._pin_values.items():
                        try:
                            current_str = str(current_value)
                            
                            # Determine strategy based on value type
                            is_binary = current_str in ["0", "1"]
                            is_numeric = isinstance(current_value, (int, float))
                            is_string = isinstance(current_value, str) and not is_binary
                            
                            test_value = None
                            
                            if is_binary:
                                # Binary pins: safe toggle
                                test_value = "1" if current_str == "0" else "0"
                                _LOGGER.info("Testing binary pin %s: %s -> %s", 
                                           pin_number, current_value, test_value)
                                
                                success = await self._api.set_pin_value(pin_number, test_value)
                                if success:
                                    await asyncio.sleep(2)
                                    
                                    # Check for matching MQTT messages
                                    recent_messages = [
                                        msg for msg in received_messages 
                                        if msg["timestamp"] > asyncio.get_event_loop().time() - 3
                                    ]
                                    
                                    for msg in recent_messages:
                                        if str(msg["value"]) == test_value:
                                            if msg["pin_name"] not in self._pin_mapping:
                                                self._pin_mapping[msg["pin_name"]] = pin_number
                                                _LOGGER.info("✅ MQTT %s → %s", msg["pin_name"], pin_number)
                                                break
                                    
                                    # Restore
                                    await self._api.set_pin_value(pin_number, current_str)
                                    await asyncio.sleep(0.5)
                            
                            elif is_numeric:
                                # Numeric pins: small change
                                current_num = float(current_value)
                                if current_num == 0:
                                    test_value = 10
                                elif current_num < 50:
                                    test_value = current_num + 5
                                else:
                                    test_value = current_num - 5
                                
                                _LOGGER.info("Testing numeric pin %s: %s -> %s", 
                                           pin_number, current_value, test_value)
                                
                                success = await self._api.set_pin_value(pin_number, test_value)
                                if success:
                                    await asyncio.sleep(3)
                                    
                                    recent_messages = [
                                        msg for msg in received_messages 
                                        if msg["timestamp"] > asyncio.get_event_loop().time() - 4
                                    ]
                                    
                                    for msg in recent_messages:
                                        try:
                                            msg_value = float(str(msg["value"]))
                                            if abs(msg_value - test_value) <= 0.5:
                                                if msg["pin_name"] not in self._pin_mapping:
                                                    self._pin_mapping[msg["pin_name"]] = pin_number
                                                    _LOGGER.info("✅ MQTT %s → %s", msg["pin_name"], pin_number)
                                                    break
                                        except (ValueError, TypeError):
                                            continue
                                    
                                    # Restore
                                    await self._api.set_pin_value(pin_number, current_str)
                                    await asyncio.sleep(0.5)
                            
                            elif is_string:
                                # String pins: append marker
                                test_value = current_str + "_MAP"
                                if len(test_value) > 50:
                                    test_value = current_str[:40] + "_MAP"
                                
                                _LOGGER.info("Testing string pin %s", pin_number)
                                
                                success = await self._api.set_pin_value(pin_number, test_value)
                                if success:
                                    await asyncio.sleep(2)
                                    
                                    recent_messages = [
                                        msg for msg in received_messages 
                                        if msg["timestamp"] > asyncio.get_event_loop().time() - 3
                                    ]
                                    
                                    for msg in recent_messages:
                                        if str(msg["value"]) == test_value:
                                            if msg["pin_name"] not in self._pin_mapping:
                                                self._pin_mapping[msg["pin_name"]] = pin_number
                                                _LOGGER.info("✅ MQTT %s → %s", msg["pin_name"], pin_number)
                                                break
                                    
                                    # Restore
                                    await self._api.set_pin_value(pin_number, current_str)
                                    await asyncio.sleep(0.5)
                        
                        except Exception as pin_err:
                            _LOGGER.debug("Error testing pin %s: %s", pin_number, pin_err)
                            continue
                    
                    # Passive matching for any remaining pins
                    unmapped_pins = [p for p in self._discovered_pins if p not in self._pin_mapping.values()]
                    if unmapped_pins and received_messages:
                        _LOGGER.info("Passive matching for %d unmapped pins", len(unmapped_pins))
                        
                        for pin_number in unmapped_pins:
                            pin_value = str(self._pin_values[pin_number])
                            
                            matching_msgs = []
                            for msg in received_messages:
                                if str(msg["value"]) == pin_value:
                                    matching_msgs.append(msg)
                                else:
                                    try:
                                        msg_num = float(str(msg["value"]))
                                        pin_num = float(pin_value)
                                        if abs(msg_num - pin_num) <= 1.0:
                                            matching_msgs.append(msg)
                                    except (ValueError, TypeError):
                                        pass
                            
                            if matching_msgs:
                                from collections import Counter
                                pin_names = [msg["pin_name"] for msg in matching_msgs]
                                most_common = Counter(pin_names).most_common(1)[0][0]
                                if most_common not in self._pin_mapping:
                                    self._pin_mapping[most_common] = pin_number
                                    _LOGGER.info("✅ Passive: MQTT %s → %s", most_common, pin_number)
                    
                    # Final verification
                    for pin_number, original_value in original_values.items():
                        try:
                            current = await self._api.get_pin_value(pin_number)
                            if str(current) != str(original_value):
                                _LOGGER.debug("Final restore for %s", pin_number)
                                await self._api.set_pin_value(pin_number, original_value)
                        except:
                            pass
                    
                    if self._mqtt_client:
                        await self._mqtt_client.async_disconnect()
                    
                    _LOGGER.info("Effective pin mapping completed: %s", self._pin_mapping)
                
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
        """Step 3: Pin selection and type with MQTT names."""
        errors = {}
        pin_schema = {}

        reversed_mapping = {v: k for k, v in self._pin_mapping.items()}
        
        for pin in self._discovered_pins:
            display_name = reversed_mapping.get(pin, pin)
            
            pin_schema[vol.Optional(f"enable_{pin}", default=True)] = selector.BooleanSelector(
                selector.BooleanSelectorConfig(),
            )
            pin_schema[vol.Optional(f"type_{pin}", default="sensor")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="sensor", label="Sensor"),
                        selector.SelectOptionDict(value="binary_sensor", label="Binary Sensor"),
                        selector.SelectOptionDict(value="switch", label="Switch"),
                        selector.SelectOptionDict(value="input_number", label="Input Number"),
                        selector.SelectOptionDict(value="button", label="Button"),
                        selector.SelectOptionDict(value="input_text", label="Text Input"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN
                ),
            )

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

        pin_descriptions = []
        for pin in self._discovered_pins:
            display_name = reversed_mapping.get(pin, pin)
            value = self._pin_values.get(pin, "N/A")
            pin_descriptions.append(f"{pin} → {display_name} (Value: {value})")
        
        return self.async_show_form(
            step_id="pin_selection",
            data_schema=vol.Schema(pin_schema),
            errors=errors,
            description_placeholders={
                "pin_info": "\n".join(pin_descriptions)
            }
        )

    async def async_step_pin_config(self, user_input=None):
        """Step 4+: Configure each selected pin in turn."""
        errors = {}
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
            
            if self._pin_types[prev_pin] == PIN_TYPE_INPUT_NUMBER:
                conf.update({
                    "min": user_input.get("min", INPUT_NUMBER_MIN),
                    "max": user_input.get("max", INPUT_NUMBER_MAX),
                    "step": user_input.get("step", INPUT_NUMBER_STEP),
                    "mode": user_input.get("mode", "slider"),
                })
            elif self._pin_types[prev_pin] == PIN_TYPE_INPUT_TEXT:
                conf.update({
                    "min_length": user_input.get("min_length", INPUT_TEXT_MIN_LENGTH),
                    "max_length": user_input.get("max_length", INPUT_TEXT_MAX_LENGTH),
                    "pattern": user_input.get("pattern"),
                })
            
            self._pin_configs[prev_pin] = conf

        if self._current_pin_index >= len(self._pin_config_order):
            config_data = {
                CONF_TOKEN: self._token,
                CONF_SCAN_INTERVAL: self._scan_interval,
                CONF_USE_MQTT: self._use_mqtt,
                "pins": self._pin_configs,
            }
            
            if self._use_mqtt:
                config_data[CONF_MQTT_BROKER] = self._mqtt_broker
                config_data[CONF_MQTT_PORT] = self._mqtt_port
            
            if self._pin_mapping:
                config_data["pin_mapping"] = self._pin_mapping
            
            return self.async_create_entry(
                title=f"Blynk Device ({self._token[:8]}...) - {'MQTT' if self._use_mqtt else 'HTTP'}",
                data=config_data,
            )

        pin = self._pin_config_order[self._current_pin_index]
        pin_type = self._pin_types[pin]
        
        reversed_mapping = {v: k for k, v in self._pin_mapping.items()}
        display_name = reversed_mapping.get(pin, pin)
        
        default_name = display_name

        schema = {
            vol.Required(CONF_PIN_NAME, default=default_name): str,
        }

        if pin_type == PIN_TYPE_SENSOR:
            schema[vol.Optional(CONF_DEVICE_CLASS, default="none")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[{"value": k, "label": k} for k in SENSOR_DEVICE_CLASSES.keys()],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            )
            schema[vol.Optional(CONF_UNIT, default="none")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[{"value": k, "label": k} for k in COMMON_UNITS.keys()],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            )
        elif pin_type == PIN_TYPE_BINARY_SENSOR:
            schema[vol.Optional(CONF_DEVICE_CLASS, default="none")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[{"value": k, "label": k} for k in BINARY_SENSOR_DEVICE_CLASSES.keys()],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            )
        elif pin_type == PIN_TYPE_SWITCH:
            schema[vol.Optional(CONF_DEVICE_CLASS, default="none")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[{"value": k, "label": k} for k in SWITCH_DEVICE_CLASSES.keys()],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            )
        elif pin_type == PIN_TYPE_INPUT_NUMBER:
            schema.update({
                vol.Optional("min", default=INPUT_NUMBER_MIN): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-1000000,
                        max=1000000,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Optional("max", default=INPUT_NUMBER_MAX): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-1000000,
                        max=1000000,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Optional("step", default=INPUT_NUMBER_STEP): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.001,
                        max=1000,
                        step=0.001,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Optional("mode", default="slider"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "slider", "label": "Slider"},
                            {"value": "box", "label": "Box"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
            })
        elif pin_type == PIN_TYPE_INPUT_TEXT:
            schema.update({
                vol.Optional("min_length", default=INPUT_TEXT_MIN_LENGTH): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=255,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Optional("max_length", default=INPUT_TEXT_MAX_LENGTH): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=255,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Optional("pattern"): str,
            })

        self._current_pin_index += 1

        return self.async_show_form(
            step_id="pin_config",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "pin_number": pin,
                "mqtt_name": display_name if display_name != pin else "Not mapped (using pin number)",
                "current_value": str(self._pin_values.get(pin, "N/A"))
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return BlynkOptionsFlowHandler(config_entry)


class BlynkOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Blynk options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self.options = dict(config_entry.options)
        if not self.options:
            self.options = {
                CONF_SCAN_INTERVAL: config_entry.data.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                )
            }

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    )
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5,
                        max=1000000,
                        mode=selector.NumberSelectorMode.BOX
                    ),
                ),
            })
        )
