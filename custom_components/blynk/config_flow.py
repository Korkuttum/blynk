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
    PIN_TYPE_INPUT_LIGHT,
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

    VERSION = 10

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
        """Step 1: Token and MQTT selection only."""
        errors = {}
        if user_input is not None:
            self._token = user_input[CONF_TOKEN].strip()
            self._use_mqtt = user_input.get(CONF_USE_MQTT, False)
            
            if len(self._token) < 10:
                errors["base"] = "invalid_token_format"
            else:
                # Check if already configured
                for entry in self._async_current_entries():
                    if entry.data.get(CONF_TOKEN) == self._token:
                        return self.async_abort(reason="already_configured")
                
                # Create API instance
                self._api = BlynkCloudAPI(self._token)
                
                # Route to appropriate next step based on MQTT selection
                if self._use_mqtt:
                    return await self.async_step_mqtt_config()
                else:
                    return await self.async_step_http_config()

        # Simple schema: only token and MQTT checkbox
        schema = {
            vol.Required(CONF_TOKEN): str,
            vol.Optional(CONF_USE_MQTT, default=False): selector.BooleanSelector(
                selector.BooleanSelectorConfig(),
            ),
        }
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def async_step_mqtt_config(self, user_input=None):
        """Step 2A: MQTT broker configuration (if MQTT selected)."""
        errors = {}
        if user_input is not None:
            self._mqtt_broker = user_input.get(CONF_MQTT_BROKER, DEFAULT_MQTT_BROKER)
            self._mqtt_port = user_input.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)
            # Set default scan interval for MQTT mode (not used but needed for config)
            self._scan_interval = DEFAULT_SCAN_INTERVAL
            return await self.async_step_connection()

        schema = {
            vol.Optional(CONF_MQTT_BROKER, default=DEFAULT_MQTT_BROKER): str,
            vol.Optional(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=65535,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
        }
        
        return self.async_show_form(
            step_id="mqtt_config",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def async_step_http_config(self, user_input=None):
        """Step 2B: HTTP polling configuration (if HTTP selected)."""
        errors = {}
        if user_input is not None:
            self._scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            
            # Validate scan interval
            if not (10 <= self._scan_interval <= 3600):
                errors["base"] = "invalid_scan_interval"
            else:
                return await self.async_step_connection()

        schema = {
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10,
                    max=3600,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="seconds",
                ),
            ),
        }
        
        return self.async_show_form(
            step_id="http_config",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def async_step_connection(self, user_input=None):
        """Step 3: Discover pins - SEND CURRENT VALUES ONLY."""
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
                    _LOGGER.info("Pin %s current value: %s", pin_name, value)
                
                if self._use_mqtt:
                    _LOGGER.info("Starting MQTT pin mapping (SENDING CURRENT VALUES ONLY)...")
                    
                    from .mqtt_client import BlynkMQTTClient
                    
                    received_messages = []
                    
                    async def on_mqtt_message(topic: str, data: dict):
                        """Handle MQTT message during discovery."""
                        if "/ds/" in topic:
                            pin_name = topic.split("/ds/")[1].upper()
                            
                            if isinstance(data, dict) and "value" in data:
                                value = data["value"]
                            else:
                                value = data
                            
                            received_messages.append({
                                "pin_name": pin_name,
                                "value": value,
                                "timestamp": asyncio.get_event_loop().time()
                            })
                            _LOGGER.debug("MQTT received: %s = %s", pin_name, value)
                    
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
                    
                    # Phase 1: Passive listening (5 seconds)
                    _LOGGER.info("Phase 1: Passive listening for 5 seconds...")
                    await asyncio.sleep(5)
                    
                    _LOGGER.info("Passive listening captured %d MQTT messages", len(received_messages))
                    for msg in received_messages:
                        _LOGGER.info("  MQTT: %s = %s", msg["pin_name"], msg["value"])
                    
                    # Phase 2: Send each pin's CURRENT value
                    _LOGGER.info("Phase 2: Sending current pin values (NO VALUE CHANGES)...")
                    
                    for pin_number, current_value in self._pin_values.items():
                        try:
                            current_str = str(current_value)
                            
                            # Değer tipini belirle
                            is_binary = current_str in ("0", "1", "true", "false", "True", "False")
                            is_numeric = False
                            is_string = False
                            
                            try:
                                float(current_str)
                                is_numeric = True
                            except (ValueError, TypeError):
                                is_string = True
                            
                            _LOGGER.debug("Processing pin %s: %s (binary: %s, numeric: %s, string: %s)",
                                        pin_number, current_value, is_binary, is_numeric, is_string)
                            
                            # Mevcut değeri gönder - GÜVENLİ: cihaz durumunu değiştirmeden
                            success = await self._api.set_pin_value(pin_number, current_str)
                            if success:
                                _LOGGER.debug("Sent current value for pin %s: %s", pin_number, current_str)
                                
                                # MQTT cevabını bekle
                                if is_binary:
                                    wait_time = 2
                                elif is_numeric:
                                    wait_time = 3
                                else:
                                    wait_time = 3
                                
                                await asyncio.sleep(wait_time)
                                
                                # Son mesajları kontrol et
                                recent_messages = [
                                    msg for msg in received_messages 
                                    if msg["timestamp"] > asyncio.get_event_loop().time() - (wait_time + 2)
                                ]
                                
                                # MQTT mesajlarında aynı değeri ara
                                for msg in recent_messages:
                                    if msg["value"] == current_str:
                                        pin_name = msg["pin_name"]
                                        if pin_name not in self._pin_mapping:
                                            self._pin_mapping[pin_name] = pin_number
                                            _LOGGER.info("✅ Direct mapping: MQTT %s → %s (value: %s)", 
                                                       pin_name, pin_number, current_str)
                                            break
                                    elif is_numeric:
                                        # Sayısal değerler için toleranslı karşılaştırma
                                        try:
                                            msg_value = float(str(msg["value"]))
                                            pin_value_num = float(current_str)
                                            tolerance = abs(pin_value_num * 0.01)
                                            if abs(msg_value - pin_value_num) <= max(tolerance, 0.1):
                                                pin_name = msg["pin_name"]
                                                if pin_name not in self._pin_mapping:
                                                    self._pin_mapping[pin_name] = pin_number
                                                    _LOGGER.info("✅ Numeric mapping: MQTT %s → %s (value: %s ≈ %s)", 
                                                               pin_name, pin_number, msg_value, pin_value_num)
                                                    break
                                        except (ValueError, TypeError):
                                            continue
                            
                            await asyncio.sleep(1)
                            
                        except Exception as pin_err:
                            _LOGGER.warning("Error processing pin %s: %s", pin_number, pin_err)
                            continue
                    
                    # Disconnect MQTT after mapping
                    await self._mqtt_client.async_disconnect()
                    self._mqtt_client = None
                
                return await self.async_step_pin_selection()
            else:
                errors["base"] = "no_pins_found"
        except Exception as err:
            _LOGGER.error("Error during connection test: %s", err)
            errors["base"] = "cannot_connect"
        
        return self.async_show_form(
            step_id="connection",
            errors=errors,
        )

    async def async_step_pin_selection(self, user_input=None):
        """Step 4: Select pins to configure."""
        errors = {}
        
        if user_input is not None:
            self._pin_selection = []
            self._pin_types = {}
            
            for pin in self._discovered_pins:
                enable_key = f"enable_{pin}"
                type_key = f"type_{pin}"
                
                if user_input.get(enable_key, False):
                    self._pin_selection.append(pin)
                    self._pin_types[pin] = user_input.get(type_key, PIN_TYPE_SENSOR)
            
            if not self._pin_selection:
                errors["base"] = "no_pins_selected"
            else:
                self._pin_config_order = self._pin_selection.copy()
                self._current_pin_index = 0
                return await self.async_step_pin_config()
        
        schema = {}
        for pin in sorted(self._discovered_pins):
            reversed_mapping = {v: k for k, v in self._pin_mapping.items()}
            display_name = reversed_mapping.get(pin, pin)
            current_value = self._pin_values.get(pin, "N/A")
            
            # Pin label with value
            if self._use_mqtt and display_name != pin:
                pin_label = f"{pin} (MQTT: {display_name}) = {current_value}"
            else:
                pin_label = f"{pin} = {current_value}"
            
            schema[vol.Optional(f"enable_{pin}", default=False)] = selector.BooleanSelector(
                selector.BooleanSelectorConfig()
            )
            schema[vol.Optional(f"type_{pin}", default=PIN_TYPE_SENSOR)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in PIN_TYPE_OPTIONS.items()],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        
        return self.async_show_form(
            step_id="pin_selection",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def async_step_pin_config(self, user_input=None):
        """Step 5: Configure individual pins."""
        errors = {}
        
        if user_input is not None:
            prev_pin = self._pin_config_order[self._current_pin_index - 1]
            
            conf = {
                CONF_PIN_TYPE: self._pin_types[prev_pin],
                CONF_PIN_NAME: user_input[CONF_PIN_NAME],
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

        # Format MQTT name for display
        mqtt_name_display = ""
        if self._use_mqtt and display_name != pin:
            mqtt_name_display = f" (MQTT: {display_name})"

        return self.async_show_form(
            step_id="pin_config",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "pin_number": pin,
                "mqtt_name": mqtt_name_display,
                "current_value": str(self._pin_values.get(pin, "N/A"))
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return BlynkOptionsFlowHandler(config_entry)


class BlynkOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Blynk options - Dynamic based on MQTT/HTTP mode."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._use_mqtt = config_entry.data.get(CONF_USE_MQTT, False)
        
        # Initialize options from config entry
        self.options = dict(config_entry.options)
        if not self.options:
            # Set default options based on current config
            self.options = {}
            if not self._use_mqtt:
                self.options[CONF_SCAN_INTERVAL] = config_entry.data.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                )
            else:
                self.options[CONF_MQTT_BROKER] = config_entry.data.get(
                    CONF_MQTT_BROKER, DEFAULT_MQTT_BROKER
                )
                self.options[CONF_MQTT_PORT] = config_entry.data.get(
                    CONF_MQTT_PORT, DEFAULT_MQTT_PORT
                )

    async def async_step_init(self, user_input=None):
        """Manage the options - Dynamic schema based on MQTT/HTTP."""
        errors = {}
        
        if user_input is not None:
            # Validate and save based on mode
            if not self._use_mqtt:
                # HTTP mode - validate scan interval
                scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                if not (10 <= scan_interval <= 3600):
                    errors["base"] = "invalid_scan_interval"
                else:
                    # Update entry data with new scan interval
                    new_data = dict(self._config_entry.data)
                    new_data[CONF_SCAN_INTERVAL] = scan_interval
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data=new_data
                    )
                    return self.async_create_entry(title="", data={CONF_SCAN_INTERVAL: scan_interval})
            else:
                # MQTT mode - update broker settings
                mqtt_broker = user_input.get(CONF_MQTT_BROKER, DEFAULT_MQTT_BROKER)
                mqtt_port = user_input.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)
                
                # Update entry data with new MQTT settings
                new_data = dict(self._config_entry.data)
                new_data[CONF_MQTT_BROKER] = mqtt_broker
                new_data[CONF_MQTT_PORT] = mqtt_port
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=new_data
                )
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_MQTT_BROKER: mqtt_broker,
                        CONF_MQTT_PORT: mqtt_port
                    }
                )

        # Build schema based on mode
        if self._use_mqtt:
            # MQTT mode - show broker and port options
            schema = {
                vol.Optional(
                    CONF_MQTT_BROKER,
                    default=self.options.get(CONF_MQTT_BROKER, DEFAULT_MQTT_BROKER)
                ): str,
                vol.Optional(
                    CONF_MQTT_PORT,
                    default=self.options.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=65535,
                        mode=selector.NumberSelectorMode.BOX
                    ),
                ),
            }
        else:
            # HTTP mode - show scan interval option
            schema = {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=3600,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    ),
                ),
            }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
        )
