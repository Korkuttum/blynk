"""Support for Blynk number inputs."""
from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging

from .const import (
    DOMAIN,
    PIN_TYPE_INPUT_NUMBER,
    INPUT_NUMBER_MIN,
    INPUT_NUMBER_MAX,
    INPUT_NUMBER_STEP,
)
from . import BlynkEntity

_LOGGER = logging.getLogger(__name__)

class BlynkNumber(BlynkEntity, NumberEntity):
    """Representation of a Blynk number input."""

    def __init__(self, coordinator, api, mqtt_client, use_mqtt, pin, config, pin_mapping=None):
        """Initialize the number input."""
        super().__init__(coordinator, pin, config["pin_name"])
        self._api = api
        self._mqtt_client = mqtt_client
        self._use_mqtt = use_mqtt
        self._pin_mapping = pin_mapping or {}
        self._attr_native_min_value = config.get("min", INPUT_NUMBER_MIN)
        self._attr_native_max_value = config.get("max", INPUT_NUMBER_MAX)
        self._attr_native_step = config.get("step", INPUT_NUMBER_STEP)
        self._attr_mode = config.get("mode", "slider")
        
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
    def native_value(self):
        """Return the current value."""
        if not self.coordinator.data or self._pin not in self.coordinator.data:
            return None
        
        value = self.coordinator.data[self._pin]
        _LOGGER.debug("Number input %s (MQTT: %s) value: %s", 
                     self._pin, self._get_mqtt_topic(), value)
        
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        try:
            _LOGGER.debug("Setting number input %s (MQTT: %s) to %s", 
                         self._pin, self._get_mqtt_topic(), value)
            
            # MQTT kullanılıyorsa MQTT ile gönder
            if self._use_mqtt and self._mqtt_client and self._mqtt_client.connected:
                await self._mqtt_client.async_publish(self._get_mqtt_topic(), str(value))
            else:
                # HTTP API ile gönder
                await self._api.set_pin_value(self._pin, value)
            
            # Yerel durumu hemen güncelle
            if self.coordinator.data:
                self.coordinator.data[self._pin] = value
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error("Error setting number value: %s", err)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Blynk number inputs based on config_entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    mqtt_client = hass.data[DOMAIN][entry.entry_id].get("mqtt_client")
    use_mqtt = hass.data[DOMAIN][entry.entry_id].get("use_mqtt", False)
    pins_config = entry.data.get("pins", {})
    pin_mapping = hass.data[DOMAIN][entry.entry_id].get("pin_mapping", {})
    
    entities = []
    for pin, config in pins_config.items():
        if config.get("pin_type") == PIN_TYPE_INPUT_NUMBER:
            entities.append(
                BlynkNumber(coordinator, api, mqtt_client, use_mqtt, pin, config, pin_mapping)
            )
    
    async_add_entities(entities)
