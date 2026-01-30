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
    
    def __init__(self, coordinator, api, mqtt_client, use_mqtt, pin, config, pin_mapping=None):
        """Initialize the switch."""
        super().__init__(coordinator, pin, config["pin_name"])
        self._api = api
        self._mqtt_client = mqtt_client
        self._use_mqtt = use_mqtt
        self._pin_mapping = pin_mapping or {}
        self._last_command_time = 0
        self._command_in_progress = False
        
        device_class = config.get(CONF_DEVICE_CLASS)
        self._attr_device_class = SWITCH_DEVICE_CLASSES.get(device_class)
        
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
    def is_on(self):
        """Return true if device is on."""
        if not self.coordinator.data or self._pin not in self.coordinator.data:
            return None
        
        value = self.coordinator.data[self._pin]
        _LOGGER.debug("Switch %s (MQTT: %s) value: %s (type: %s)", 
                     self._pin, self._get_mqtt_topic(), value, type(value))
        
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'on', 'yes')
        return False

    async def async_turn_on(self, **kwargs):
        """Turn the device on."""
        if self.is_on and self._command_in_progress:
            _LOGGER.debug("Switch %s already on, skipping command", self._pin)
            return
            
        _LOGGER.debug("Turning on switch %s (MQTT: %s)", self._pin, self._get_mqtt_topic())
        self._command_in_progress = True
        
        try:
            # MQTT kullanılıyorsa MQTT ile gönder
            if self._use_mqtt and self._mqtt_client and self._mqtt_client.connected:
                await self._mqtt_client.async_publish(self._get_mqtt_topic(), "1")
            else:
                # HTTP API ile gönder
                await self._api.set_pin_value(self._pin, "1")
            
            # Yerel durumu hemen güncelle
            if self.coordinator.data:
                self.coordinator.data[self._pin] = 1
            self.async_write_ha_state()
            
            # MQTT kullanılmıyorsa kısa bekleme sonrası refresh
            if not (self._use_mqtt and self._mqtt_client and self._mqtt_client.connected):
                await asyncio.sleep(0.5)
                await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error turning on switch %s: %s", self._pin, e)
        finally:
            self._command_in_progress = False

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        if not self.is_on and self._command_in_progress:
            _LOGGER.debug("Switch %s already off, skipping command", self._pin)
            return
            
        _LOGGER.debug("Turning off switch %s (MQTT: %s)", self._pin, self._get_mqtt_topic())
        self._command_in_progress = True
        
        try:
            # MQTT kullanılıyorsa MQTT ile gönder
            if self._use_mqtt and self._mqtt_client and self._mqtt_client.connected:
                await self._mqtt_client.async_publish(self._get_mqtt_topic(), "0")
            else:
                # HTTP API ile gönder
                await self._api.set_pin_value(self._pin, "0")
            
            # Yerel durumu hemen güncelle
            if self.coordinator.data:
                self.coordinator.data[self._pin] = 0
            self.async_write_ha_state()
            
            # MQTT kullanılmıyorsa kısa bekleme sonrası refresh
            if not (self._use_mqtt and self._mqtt_client and self._mqtt_client.connected):
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
    mqtt_client = hass.data[DOMAIN][entry.entry_id].get("mqtt_client")
    use_mqtt = hass.data[DOMAIN][entry.entry_id].get("use_mqtt", False)
    pin_mapping = hass.data[DOMAIN][entry.entry_id].get("pin_mapping", {})
    
    entities = []
    
    for pin, pin_config in entry.data["pins"].items():
        if pin_config["pin_type"] == PIN_TYPE_SWITCH:
            entities.append(
                BlynkSwitch(
                    coordinator,
                    api,
                    mqtt_client,
                    use_mqtt,
                    pin,
                    pin_config,
                    pin_mapping,
                )
            )
    
    async_add_entities(entities)
