"""Support for Blynk button with visual feedback."""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging
import asyncio
from datetime import datetime

from .const import (
    DOMAIN,
    PIN_TYPE_BUTTON,
    CONF_PIN_TYPE,
    CONF_PIN_NAME,
)
from . import BlynkEntity

_LOGGER = logging.getLogger(__name__)

class BlynkButton(BlynkEntity, ButtonEntity):
    """Representation of a Blynk button with visual press feedback."""

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
        
        # Button state tracking
        self._is_visually_pressed = False
        self._reset_timer = None
        self._last_press_time = None
        
        # Normal icon
        self._normal_icon = "mdi:gesture-tap"
        self._pressed_icon = "mdi:gesture-tap-button"
        
        # Başlangıç icon'u
        self._attr_icon = self._normal_icon
        
        # Extra attributes
        self._attr_extra_state_attributes = {
            "pin": self._pin,
            "mqtt_topic": self._get_mqtt_topic(),
            "last_pressed": None,
            "press_count": 0
        }

    def _get_mqtt_topic(self):
        """Get MQTT topic for this pin."""
        if self._pin in self._reversed_mapping:
            return self._reversed_mapping[self._pin]
        return self._pin

    async def async_added_to_hass(self):
        """Register MQTT callback when added to hass."""
        await super().async_added_to_hass()
        
        # Mevcut MQTT callback'ini kaydet
        self._original_mqtt_callback = self._mqtt_client.on_message_callback if self._mqtt_client else None
        
        # Kendi callback'imizi ekle
        if self._use_mqtt and self._mqtt_client:
            @callback
            async def mqtt_message_handler(topic: str, data: dict):
                """Handle MQTT messages for button visual feedback."""
                try:
                    if "/ds/" in topic:
                        pin_name = topic.split("/ds/")[1].upper()
                        
                        # Bu butonun MQTT adı mı?
                        if pin_name == self._get_mqtt_topic():
                            value = data.get("value") if isinstance(data, dict) else data
                            value_str = str(value)
                            
                            if value_str == "1":
                                # Buton Blynk'ten basıldı - GÖRSEL FEEDBACK VER!
                                await self._show_visual_press()
                
                except Exception as e:
                    _LOGGER.error("Error in button MQTT handler: %s", e)
                
                # Orijinal callback'i de çağır
                if self._original_mqtt_callback:
                    await self._original_mqtt_callback(topic, data)
            
            # Callback'i ayarla
            self._mqtt_client.on_message_callback = mqtt_message_handler

    async def _show_visual_press(self):
        """Show visual feedback when button is pressed."""
        # Önceki timer'ı temizle
        if self._reset_timer:
            self._reset_timer.cancel()
        
        # Güncelle
        self._is_visually_pressed = True
        self._attr_icon = self._pressed_icon
        self._last_press_time = datetime.now()
        self._attr_extra_state_attributes["last_pressed"] = self._last_press_time.isoformat()
        self._attr_extra_state_attributes["press_count"] = self._attr_extra_state_attributes.get("press_count", 0) + 1
        
        # Entity'yi güncelle
        self.async_write_ha_state()
        
        _LOGGER.info(
            "🎯 BUTTON VISUAL FEEDBACK: %s pressed (Pin: %s, MQTT: %s)",
            self.name, self._pin, self._get_mqtt_topic()
        )
        
        # 1 saniye sonra eski haline getir
        self._reset_timer = asyncio.create_task(self._reset_visual_state())

    async def _reset_visual_state(self):
        """Reset visual state after delay."""
        await asyncio.sleep(1)  # 1 saniye basılı göster
        
        self._is_visually_pressed = False
        self._attr_icon = self._normal_icon
        
        # Entity'yi güncelle
        self.async_write_ha_state()
        
        _LOGGER.debug(
            "Button %s visual state reset",
            self.name
        )

    async def async_press(self) -> None:
        """Handle the button press from HA."""
        try:
            _LOGGER.info("Button pressed from HA: %s", self.name)
            
            # Görsel feedback göster (hemen)
            await self._show_visual_press()
            
            # MQTT kullanılıyorsa MQTT ile gönder
            if self._use_mqtt and self._mqtt_client and self._mqtt_client.connected:
                await self._mqtt_client.async_publish(self._get_mqtt_topic(), "1")
                await asyncio.sleep(0.1)
                await self._mqtt_client.async_publish(self._get_mqtt_topic(), "0")
            else:
                # HTTP API ile gönder
                await self._api.set_pin_value(self._pin, "1")
                await asyncio.sleep(0.1)
                await self._api.set_pin_value(self._pin, "0")
            
        except Exception as err:
            _LOGGER.error("Error pressing button: %s", err)
            # Hata durumunda da resetle
            if self._is_visually_pressed:
                await self._reset_visual_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return self._attr_extra_state_attributes

    async def async_will_remove_from_hass(self):
        """Clean up when removing from hass."""
        if self._reset_timer:
            self._reset_timer.cancel()
        
        # Orijinal callback'i geri yükle
        if hasattr(self, '_original_mqtt_callback') and self._original_mqtt_callback:
            self._mqtt_client.on_message_callback = self._original_mqtt_callback
        
        await super().async_will_remove_from_hass()

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
            _LOGGER.info("Setting up visual feedback button for pin %s: %s", pin, config[CONF_PIN_NAME])
            button = BlynkButton(coordinator, api, mqtt_client, use_mqtt, pin, config, pin_mapping)
            entities.append(button)
    
    if entities:
        async_add_entities(entities, update_before_add=True)
        _LOGGER.info("✅ Added %d button entities with VISUAL FEEDBACK", len(entities))
