"""Support for Blynk switches."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging
import asyncio
from .const import (
    DOMAIN,
    PIN_TYPE_SWITCH,
    SWITCH_DEVICE_CLASSES,
    CONF_DEVICE_CLASS,
)
from . import BlynkEntity

_LOGGER = logging.getLogger(__name__)

class BlynkSwitch(BlynkEntity, SwitchEntity):
    """Representation of a Blynk switch."""
    
    def __init__(self, coordinator, api, pin, config):
        """Initialize the switch."""
        super().__init__(coordinator, pin, config["pin_name"])
        self._api = api
        self._last_command_time = 0
        self._command_in_progress = False
        
        device_class = config.get(CONF_DEVICE_CLASS)
        self._attr_device_class = SWITCH_DEVICE_CLASSES.get(device_class)

    @property
    def is_on(self):
        """Return true if device is on."""
        if not self.coordinator.data or self._pin not in self.coordinator.data:
            return None
        
        value = self.coordinator.data[self._pin]
        _LOGGER.debug("Switch %s value: %s (type: %s)", self._pin, value, type(value))
        
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'on', 'yes')
        return False

    async def async_turn_on(self, **kwargs):
        """Turn the device on."""
        # Eğer zaten açıksa ve yakın zamanda komut gönderdiyse, işlem yapma
        if self.is_on and self._command_in_progress:
            _LOGGER.debug("Switch %s already on, skipping command", self._pin)
            return
            
        _LOGGER.debug("Turning on switch %s", self._pin)
        self._command_in_progress = True
        
        try:
            await self._api.set_pin_value(self._pin, "1")
            # Yerel durumu hemen güncelle
            if self.coordinator.data:
                self.coordinator.data[self._pin] = 1
            self.async_write_ha_state()
            
            # Kısa bir bekleme sonrası refresh
            await asyncio.sleep(0.5)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error turning on switch %s: %s", self._pin, e)
        finally:
            self._command_in_progress = False

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        # Eğer zaten kapalıysa ve yakın zamanda komut gönderdiyse, işlem yapma
        if not self.is_on and self._command_in_progress:
            _LOGGER.debug("Switch %s already off, skipping command", self._pin)
            return
            
        _LOGGER.debug("Turning off switch %s", self._pin)
        self._command_in_progress = True
        
        try:
            await self._api.set_pin_value(self._pin, "0")
            # Yerel durumu hemen güncelle
            if self.coordinator.data:
                self.coordinator.data[self._pin] = 0
            self.async_write_ha_state()
            
            # Kısa bir bekleme sonrası refresh
            await asyncio.sleep(0.5)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error turning off switch %s: %s", self._pin, e)
        finally:
            self._command_in_progress = False

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Blynk switches."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    
    entities = []
    
    for pin, pin_config in entry.data["pins"].items():
        if pin_config["pin_type"] == PIN_TYPE_SWITCH:
            entities.append(
                BlynkSwitch(
                    coordinator,
                    api,
                    pin,
                    pin_config,
                )
            )
    
    async_add_entities(entities)
