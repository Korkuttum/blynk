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

    def __init__(self, coordinator, api, pin, config):
        """Initialize the number input."""
        super().__init__(coordinator, pin, config["pin_name"])
        self._api = api
        self._attr_native_min_value = config.get("min", INPUT_NUMBER_MIN)
        self._attr_native_max_value = config.get("max", INPUT_NUMBER_MAX)
        self._attr_native_step = config.get("step", INPUT_NUMBER_STEP)
        self._attr_mode = config.get("mode", "slider")

    @property
    def native_value(self):
        """Return the current value."""
        if not self.coordinator.data or self._pin not in self.coordinator.data:
            return None
        return float(self.coordinator.data[self._pin])

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self._api.set_pin_value(self._pin, value)
        if self.coordinator.data:
            self.coordinator.data[self._pin] = value
        self.async_write_ha_state()

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Blynk number inputs based on config_entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    pins_config = entry.data.get("pins", {})
    
    entities = []
    for pin, config in pins_config.items():
        if config.get("pin_type") == PIN_TYPE_INPUT_NUMBER:
            entities.append(BlynkNumber(coordinator, api, pin, config))
    
    async_add_entities(entities)
