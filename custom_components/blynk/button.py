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

    def __init__(self, coordinator, api, mqtt_client, use_mqtt, pin, config, pin_mapping=None):
        """Initialize the button."""
        super().__init__(coordinator, pin, config[CONF_PIN_NAME])
        self._api = api
        self._mqtt_client = mqtt_client
        self._use_mqtt = use_mqtt
        self._pin_mapping = pin_mapping or {}
        self._attr_name = config[CONF_PIN_NAME]
        self._attr_unique_id = f"{DOMAIN}_{self._pin}_button"
        
        # Pin mapping için reversed mapping oluştur
        self._reversed_mapping = {v: k for k, v in self._pin_mapping.items()}

    def _get_mqtt_topic(self):
        """Get MQTT topic for this pin."""
        # Pin mapping varsa, mapped MQTT adını kullan
        if self._pin in self._reversed_mapping:
            return self._reversed_mapping[self._pin]
        # Yoksa pin numarasını kullan (V0, V1, vb.)
        return self._pin

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.debug("Pressing button %s (MQTT: %s)", self._pin, self._get_mqtt_topic())
            
            # MQTT kullanılıyorsa MQTT ile gönder
            if self._use_mqtt and self._mqtt_client and self._mqtt_client.connected:
                # Button için 1 gönder, sonra 0 (pulse)
                await self._mqtt_client.async_publish(self._get_mqtt_topic(), "1")
                await asyncio.sleep(0.1)
                await self._mqtt_client.async_publish(self._get_mqtt_topic(), "0")
            else:
                # HTTP API ile gönder
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
    mqtt_client = hass.data[DOMAIN][entry.entry_id].get("mqtt_client")
    use_mqtt = hass.data[DOMAIN][entry.entry_id].get("use_mqtt", False)
    pins_config = entry.data.get("pins", {})
    pin_mapping = hass.data[DOMAIN][entry.entry_id].get("pin_mapping", {})
    
    entities = []
    for pin, config in pins_config.items():
        pin_type = config.get(CONF_PIN_TYPE)
        if pin_type == PIN_TYPE_BUTTON:
            _LOGGER.debug("Setting up button for pin %s with config: %s", pin, config)
            button = BlynkButton(coordinator, api, mqtt_client, use_mqtt, pin, config, pin_mapping)
            entities.append(button)
    
    if entities:
        async_add_entities(entities)
        _LOGGER.debug("Added %d button entities", len(entities))
