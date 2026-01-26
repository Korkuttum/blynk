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
        self._pin_mapping = {}  # {pin_name: pin_number, ...}
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
                
                # API'yi başlat
                self._api = BlynkCloudAPI(self._token)
                return await self.async_step_connection()

        schema = {
            vol.Required(CONF_TOKEN): str,
            vol.Optional(CONF_USE_MQTT, default=False): selector.BooleanSelector(
                selector.BooleanSelectorConfig(),
            ),
        }
        
        # MQTT seçiliyse ekstra alanlar göster
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
        """Step 2: Discover pins with MQTT mapping."""
        errors = {}
        
        # Eğer MQTT seçildiyse ama broker/port ayarlanmadıysa, user step'ten al
        if self._use_mqtt and not self._mqtt_broker:
            self._mqtt_broker = DEFAULT_MQTT_BROKER
        if self._use_mqtt and not self._mqtt_port:
            self._mqtt_port = DEFAULT_MQTT_PORT
            
        # Port'u integer'a çevir (logdaki hata için: blynk.cloud:8883.0)
        try:
            if isinstance(self._mqtt_port, str):
                self._mqtt_port = int(float(self._mqtt_port))  # 8883.0 -> 8883
            else:
                self._mqtt_port = int(self._mqtt_port)
        except (ValueError, TypeError):
            self._mqtt_port = DEFAULT_MQTT_PORT
        
        try:
            # HTTP API ile pin keşfi
            pins = await self._api.get_all_pins()
            if pins:
                self._discovered_pins = []
                self._pin_values = {}
                for pin, value in pins.items():
                    pin_name = pin.upper()  # V0, V1, V2 şeklinde
                    self._discovered_pins.append(pin_name)
                    self._pin_values[pin_name] = value
                
                # MQTT kullanılıyorsa, MQTT ile pin mapping yap
                if self._use_mqtt:
                    _LOGGER.info("Starting MQTT pin mapping discovery with broker %s:%s...", 
                                self._mqtt_broker, self._mqtt_port)
                    
                    # MQTT client oluştur
                    from .mqtt_client import BlynkMQTTClient
                    
                    # MQTT mesajlarını dinlemek için
                    discovered_pin_names = set()
                    received_messages = []
                    
                    async def on_mqtt_message(topic: str, data: dict):
                        """Handle MQTT message during discovery."""
                        if "/ds/" in topic:
                            pin_name = topic.split("/ds/")[1].upper()
                            discovered_pin_names.add(pin_name)
                            
                            # Veriyi parse et
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
                    
                    # MQTT bağlantısını başlat
                    connected = await self._mqtt_client.async_connect(asyncio.get_event_loop())
                    if not connected:
                        _LOGGER.warning("MQTT connection failed during discovery")
                        # MQTT olmadan devam et
                        return await self.async_step_pin_selection()
                    
                    # MQTT mesajlarının gelmesi için bekle
                    await asyncio.sleep(3)
                    
                    # Her pin için test sinyali gönder
                    for pin_number, current_value in self._pin_values.items():
                        try:
                            # Received messages listesini temizle
                            received_messages.clear()
                            
                            # Test değeri hesapla - daha iyi bir algoritma
                            test_value = None
                            
                            # Pin tipine göre farklı test stratejileri
                            if pin_number in ["V2", "V3"]:
                                # Sensor ve number için büyük değişiklik
                                if isinstance(current_value, (int, float)):
                                    current_num = float(current_value)
                                    if current_num == 0:
                                        test_value = 999
                                    elif current_num < 100:
                                        test_value = current_num + 100
                                    else:
                                        test_value = current_num / 2
                                else:
                                    test_value = "SENSOR_TEST_" + pin_number
                            else:
                                # Diğer pinler için binary değişim
                                if isinstance(current_value, (int, float)):
                                    test_value = 1 if float(current_value) == 0 else 0
                                elif isinstance(current_value, str):
                                    test_value = "TEST_ON" if str(current_value).lower() in ("0", "off", "false") else "TEST_OFF"
                                else:
                                    test_value = "TEST_" + pin_number
                            
                            _LOGGER.info("Sending test signal to %s: %s", pin_number, test_value)
                            
                            # API üzerinden test sinyalini gönder
                            success = await self._api.set_pin_value(pin_number, test_value)
                            
                            if success:
                                # Sensor ve number için daha uzun bekle
                                wait_time = 4 if pin_number in ["V2", "V3"] else 2
                                await asyncio.sleep(wait_time)
                                
                                # Bu süre içinde gelen MQTT mesajlarını filtrele
                                recent_messages = [
                                    msg for msg in received_messages 
                                    if msg["timestamp"] > asyncio.get_event_loop().time() - (wait_time + 1)
                                ]
                                
                                _LOGGER.debug("Recent MQTT messages after test to %s: %s", pin_number, recent_messages)
                                
                                # Eşleşen mesaj bul
                                for msg in recent_messages:
                                    msg_value = str(msg["value"])
                                    test_str = str(test_value)
                                    
                                    # Tam eşleşme kontrol et
                                    if msg_value == test_str:
                                        pin_name = msg["pin_name"]
                                        if pin_name not in self._pin_mapping:
                                            self._pin_mapping[pin_name] = pin_number
                                            _LOGGER.info("✅ Mapped MQTT pin %s to %s", pin_name, pin_number)
                                            break
                                    # Numeric değerler için yakın eşleşme
                                    elif pin_number in ["V2", "V3"]:
                                        try:
                                            msg_num = float(msg_value)
                                            test_num = float(test_str)
                                            # %5 tolerans ile eşleşme
                                            if abs(msg_num - test_num) <= (abs(test_num) * 0.05):
                                                pin_name = msg["pin_name"]
                                                if pin_name not in self._pin_mapping:
                                                    self._pin_mapping[pin_name] = pin_number
                                                    _LOGGER.info("✅ Numeric mapped MQTT pin %s to %s (msg: %s, test: %s)", 
                                                                pin_name, pin_number, msg_value, test_str)
                                                    break
                                        except (ValueError, TypeError):
                                            pass
                                
                                # Test değerini geri al
                                await self._api.set_pin_value(pin_number, current_value)
                                await asyncio.sleep(0.5)
                                    
                        except Exception as err:
                            _LOGGER.debug("Error in pin mapping for %s: %s", pin_number, err)
                            continue
                    
                    # MQTT client'ı kapat
                    if self._mqtt_client:
                        await self._mqtt_client.async_disconnect()
                    
                    _LOGGER.info("Pin mapping discovery completed: %s", self._pin_mapping)
                
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

        # Pin mapping varsa, pin isimlerini mapping'den al
        # Önce reversed mapping oluştur: {pin_number: pin_name, ...}
        reversed_mapping = {v: k for k, v in self._pin_mapping.items()}
        
        for pin in self._discovered_pins:
            # Eğer bu pin için mapping varsa, mapped ismi kullan
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

        # Description için pin listesi hazırla
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
        """Step 4+: Configure each selected pin in turn (name, class/unit)."""
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
            
            # Pin mapping'i de kaydet
            if self._pin_mapping:
                config_data["pin_mapping"] = self._pin_mapping
            
            return self.async_create_entry(
                title=f"Blynk Device ({self._token[:8]}...) - {'MQTT' if self._use_mqtt else 'HTTP'}",
                data=config_data,
            )

        pin = self._pin_config_order[self._current_pin_index]
        pin_type = self._pin_types[pin]
        
        # Pin için display name belirle - reversed mapping kullan
        reversed_mapping = {v: k for k, v in self._pin_mapping.items()}
        display_name = reversed_mapping.get(pin, pin)
        
        # Default pin name olarak mapped name'i kullan
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