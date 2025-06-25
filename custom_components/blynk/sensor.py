"""Support for Blynk sensors."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging

from .const import (
    DOMAIN,
    PIN_TYPE_SENSOR,
    SENSOR_DEVICE_CLASSES,
    COMMON_UNITS,
    CONF_DEVICE_CLASS,
    CONF_UNIT
)
from . import BlynkEntity

_LOGGER = logging.getLogger(__name__)

class BlynkSensor(BlynkEntity, SensorEntity):
    """Representation of a Blynk sensor."""

    def __init__(self, coordinator, pin, config):
        """Initialize the sensor."""
        super().__init__(coordinator, pin, config["pin_name"])
        
        # Set device class and unit from config
        device_class = config.get(CONF_DEVICE_CLASS)
        self._attr_device_class = SENSOR_DEVICE_CLASSES.get(device_class)
        self._attr_native_unit_of_measurement = COMMON_UNITS.get(config.get(CONF_UNIT))

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or self._pin not in self.coordinator.data:
            return None
        
        value = self.coordinator.data[self._pin]
        _LOGGER.debug("Pin %s value: %s (type: %s)", self._pin, value, type(value))
        return value

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Blynk sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    entities = []
    
    for pin, pin_config in entry.data["pins"].items():
        if pin_config["pin_type"] == PIN_TYPE_SENSOR:
            entities.append(
                BlynkSensor(
                    coordinator,
                    pin,
                    pin_config,
                )
            )
    
    async_add_entities(entities)