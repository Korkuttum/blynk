"""Support for Blynk lights."""
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging
import asyncio

from .const import (
    DOMAIN,
    PIN_TYPE_INPUT_LIGHT,
)
from . import BlynkEntity

_LOGGER = logging.getLogger(__name__)


class BlynkLight(BlynkEntity, LightEntity):
    """Representation of a Blynk light."""

    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, coordinator, api, mqtt_client, use_mqtt, pin, config, pin_mapping=None):
        """Initialize the light."""
        super().__init__(coordinator, pin, config["pin_name"])

        self._api = api
        self._mqtt_client = mqtt_client
        self._use_mqtt = use_mqtt
        self._pin_mapping = pin_mapping or {}

        self._reversed_mapping = {v: k for k, v in self._pin_mapping.items()}

    def _get_mqtt_topic(self):
        """Get MQTT topic for this pin."""
        if self._pin in self._reversed_mapping:
            return self._reversed_mapping[self._pin]

        return self._pin

    @property
    def brightness(self):
        """Return brightness."""
        if not self.coordinator.data or self._pin not in self.coordinator.data:
            return None

        value = self.coordinator.data[self._pin]

        try:
            value = float(value)
            return int((value / 100) * 255)
        except (ValueError, TypeError):
            return 0

    @property
    def is_on(self):
        """Return true if light is on."""
        brightness = self.brightness
        return brightness is not None and brightness > 0

    async def async_turn_on(self, **kwargs):
        """Turn on light."""
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)

        # Convert HA brightness (0-255) -> Blynk (0-100)
        blynk_value = int((brightness / 255) * 100)

        try:
            _LOGGER.debug(
                "Turning on light %s (MQTT: %s) brightness=%s blynk=%s",
                self._pin,
                self._get_mqtt_topic(),
                brightness,
                blynk_value,
            )

            if self._use_mqtt and self._mqtt_client and self._mqtt_client.connected:
                await self._mqtt_client.async_publish(
                    self._get_mqtt_topic(),
                    str(blynk_value),
                )
            else:
                await self._api.set_pin_value(self._pin, blynk_value)

            if self.coordinator.data:
                self.coordinator.data[self._pin] = blynk_value

            self.async_write_ha_state()

            if not (self._use_mqtt and self._mqtt_client and self._mqtt_client.connected):
                await asyncio.sleep(0.5)
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Error turning on light %s: %s", self._pin, e)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        try:
            _LOGGER.debug(
                "Turning off light %s (MQTT: %s)",
                self._pin,
                self._get_mqtt_topic(),
            )

            if self._use_mqtt and self._mqtt_client and self._mqtt_client.connected:
                await self._mqtt_client.async_publish(
                    self._get_mqtt_topic(),
                    "0",
                )
            else:
                await self._api.set_pin_value(self._pin, 0)

            if self.coordinator.data:
                self.coordinator.data[self._pin] = 0

            self.async_write_ha_state()

            if not (self._use_mqtt and self._mqtt_client and self._mqtt_client.connected):
                await asyncio.sleep(0.5)
                await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Error turning off light %s: %s", self._pin, e)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Blynk lights."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    mqtt_client = hass.data[DOMAIN][entry.entry_id].get("mqtt_client")
    use_mqtt = hass.data[DOMAIN][entry.entry_id].get("use_mqtt", False)
    pin_mapping = hass.data[DOMAIN][entry.entry_id].get("pin_mapping", {})

    entities = []

    for pin, pin_config in entry.data["pins"].items():
        if pin_config["pin_type"] == PIN_TYPE_INPUT_LIGHT:
            entities.append(
                BlynkLight(
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