"""Support for Blynk button."""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging
import asyncio

from .const import (
    DOMAIN,
    PIN_TYPE_BUTTON,
    CONF_PIN_TYPE,
    CONF_PIN_NAME,
)
from . import BlynkEntity

_LOGGER = logging.getLogger(__name__)

class BlynkButton(BlynkEntity, ButtonEntity):
    """Representation of a Blynk button."""

    def __init__(self, coordinator, api, pin, config):
        """Initialize the button."""
        super().__init__(coordinator, pin, config[CONF_PIN_NAME])
        self._api = api
        self._attr_name = config[CONF_PIN_NAME]
        self._attr_unique_id = f"{DOMAIN}_{pin}_button"

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            await self._api.set_pin_value(self._pin, "1")
            await asyncio.sleep(0.1)
            await self._api.set_pin_value(self._pin, "0")
            self.async_write_ha_state()
            _LOGGER.debug("Button pressed successfully for pin %s", self._pin)
        except Exception as err:
            _LOGGER.error("Error pressing button: %s", err)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Blynk button based on config_entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    pins_config = entry.data.get("pins", {})
    
    entities = []
    for pin, config in pins_config.items():
        pin_type = config.get(CONF_PIN_TYPE)
        if pin_type == PIN_TYPE_BUTTON:
            _LOGGER.debug("Setting up button for pin %s with config: %s", pin, config)
            button = BlynkButton(coordinator, api, pin, config)
            entities.append(button)
    
    if entities:
        async_add_entities(entities)
        _LOGGER.debug("Added %d button entities", len(entities))
