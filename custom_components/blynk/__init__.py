"""The Blynk integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .blynk_api import BlynkCloudAPI
from .const import (
    DOMAIN,
    CONF_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    MANUFACTURER,
    VERSION,
    ATTRIBUTION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,  # input_number yerine number kullanıyoruz
    Platform.BUTTON,
    Platform.TEXT,
]
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Blynk component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Blynk from a config entry."""
    api = BlynkCloudAPI(entry.data[CONF_TOKEN])

    # Koordinatör oluşturmadan önce bağlantıyı test edelim
    try:
        # İlk veri çekme denemesi
        initial_data = await api.get_all_pins()
        if not initial_data:
            _LOGGER.error("No data received from Blynk API")
            raise ConfigEntryNotReady("No data received from device")

    except Exception as err:
        _LOGGER.error("Error setting up Blynk integration: %s", str(err))
        raise ConfigEntryNotReady from err

    async def async_update_data() -> dict[str, Any]:
        """Fetch data from API."""
        try:
            data = await api.get_all_pins()
            _LOGGER.debug(
                "Received data from Blynk device %s: %s",
                entry.data[CONF_TOKEN][:8],
                data,
            )
            if not data:
                raise UpdateFailed("No data received")
            return data
        except Exception as err:
            _LOGGER.error(
                "Error communicating with Blynk API: %s",
                str(err),
            )
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.data[CONF_TOKEN][:8]}",
        update_method=async_update_data,
        update_interval=timedelta(
            seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        ),
    )

    # İlk veriyi koordinatöre yükleyelim
    coordinator.data = initial_data

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # İlk güncellemeyi başlat
    await coordinator.async_refresh()

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

class BlynkEntity(CoordinatorEntity):
    """Represents a Blynk entity."""

    _attr_has_entity_name = True
    
    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        pin: str,
        name: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        
        self._pin = pin
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{pin}"
        
        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.name)},
            "name": f"Blynk Device ({coordinator.name})",
            "manufacturer": MANUFACTURER,
            "model": "Cloud Device",
            "sw_version": VERSION,
        }
        
        self._attr_attribution = ATTRIBUTION

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self._pin in self.coordinator.data
        )
