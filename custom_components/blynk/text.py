"""Support for Blynk text inputs."""
from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging

from .const import (
    DOMAIN,
    PIN_TYPE_INPUT_TEXT,
    INPUT_TEXT_MIN_LENGTH,
    INPUT_TEXT_MAX_LENGTH,
    CONF_PIN_TYPE,
    CONF_PIN_NAME,
)
from . import BlynkEntity

_LOGGER = logging.getLogger(__name__)

class BlynkText(BlynkEntity, TextEntity):
    """Representation of a Blynk text input."""

    def __init__(self, coordinator, api, mqtt_client, use_mqtt, pin, config, pin_mapping=None):
        """Initialize the text input."""
        super().__init__(coordinator, pin, config[CONF_PIN_NAME])
        self._api = api
        self._mqtt_client = mqtt_client
        self._use_mqtt = use_mqtt
        self._pin_mapping = pin_mapping or {}
        self._attr_native_min = config.get("min_length", INPUT_TEXT_MIN_LENGTH)
        self._attr_native_max = config.get("max_length", INPUT_TEXT_MAX_LENGTH)
        self._attr_mode = "text"
        self._attr_unique_id = f"{DOMAIN}_{self._pin}_text"
        self._attr_name = config[CONF_PIN_NAME]
        self._value = ""
        
        # Pin mapping için reversed mapping oluştur
        self._reversed_mapping = {v: k for k, v in self._pin_mapping.items()}

    def _get_mqtt_topic(self):
        """Get MQTT topic for this pin."""
        # Pin mapping varsa, mapped MQTT adını kullan
        if self._pin in self._reversed_mapping:
            return self._reversed_mapping[self._pin]
        # Yoksa pin numarasını kullan (V0, V1, vb.)
        return self._pin

    @property
    def native_value(self) -> str:
        """Return the current value."""
        if not self.coordinator.data or self._pin not in self.coordinator.data:
            return self._value
        
        value = str(self.coordinator.data[self._pin])
        _LOGGER.debug("Text input %s (MQTT: %s) value: %s", 
                     self._pin, self._get_mqtt_topic(), value)
        return value

    async def async_set_value(self, value: str) -> None:
        """Set new value."""
        try:
            _LOGGER.debug("Setting text input %s (MQTT: %s) to %s", 
                         self._pin, self._get_mqtt_topic(), value)
            
            # Önce yerel değeri güncelle
            self._value = value
            
            # MQTT kullanılıyorsa MQTT ile gönder
            if self._use_mqtt and self._mqtt_client and self._mqtt_client.connected:
                await self._mqtt_client.async_publish(self._get_mqtt_topic(), value)
            else:
                # HTTP API ile gönder
                await self._api.set_pin_value(self._pin, value)
            
            # Coordinator'ı güncelle
            if self.coordinator.data is not None:
                self.coordinator.data[self._pin] = value
            
            # Entity'yi güncelle
            self.async_write_ha_state()
            
            _LOGGER.debug("Text value set successfully to %s for pin %s", value, self._pin)
        except Exception as err:
            _LOGGER.error("Error setting text value: %s", err)
            raise

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Blynk text inputs based on config_entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    mqtt_client = hass.data[DOMAIN][entry.entry_id].get("mqtt_client")
    use_mqtt = hass.data[DOMAIN][entry.entry_id].get("use_mqtt", False)
    pins_config = entry.data.get("pins", {})
    pin_mapping = hass.data[DOMAIN][entry.entry_id].get("pin_mapping", {})
    
    entities = []
    for pin, config in pins_config.items():
        if config.get(CONF_PIN_TYPE) == PIN_TYPE_INPUT_TEXT:
            _LOGGER.debug("Setting up text input for pin %s with config: %s", pin, config)
            text_input = BlynkText(coordinator, api, mqtt_client, use_mqtt, pin, config, pin_mapping)
            entities.append(text_input)
    
    if entities:
        async_add_entities(entities)
        _LOGGER.debug("Added %d text input entities", len(entities))