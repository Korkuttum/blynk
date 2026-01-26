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

    def _parse_value(self, value):
        """Parse value from Blynk, handling different formats."""
        if value is None:
            return None
            
        _LOGGER.debug("Raw value from Blynk: %s (type: %s)", value, type(value))
        
        # Eğer zaten numeric ise direkt döndür
        if isinstance(value, (int, float)):
            return value
            
        # String ise parse et
        if isinstance(value, str):
            # Boş string kontrolü
            value = value.strip()
            if not value:
                return None
                
            try:
                # Önce virgülü noktaya çevir (Türkçe format)
                if ',' in value and '.' not in value:
                    value = value.replace(',', '.')
                    _LOGGER.debug("Converted comma to dot: %s", value)
                
                # Eğer hem virgül hem nokta varsa (örn: 1,234.56)
                elif ',' in value and '.' in value:
                    # Son noktadan önce virgül varsa, binlik ayracı olarak kabul et
                    last_dot = value.rfind('.')
                    if ',' in value[:last_dot]:
                        # Virgülleri kaldır (binlik ayracı)
                        value = value.replace(',', '')
                        _LOGGER.debug("Removed thousand separators: %s", value)
                
                # Float'a çevir
                parsed_value = float(value)
                _LOGGER.debug("Parsed value: %s", parsed_value)
                return parsed_value
                
            except ValueError as e:
                _LOGGER.warning("Could not parse sensor value '%s': %s", value, e)
                return value  # Parse edilemezse orijinal değeri döndür
        
        # Diğer türler için
        return value

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or self._pin not in self.coordinator.data:
            return None
        
        raw_value = self.coordinator.data[self._pin]
        parsed_value = self._parse_value(raw_value)
        
        _LOGGER.debug("Pin %s - Raw: %s, Parsed: %s", self._pin, raw_value, parsed_value)
        return parsed_value

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
