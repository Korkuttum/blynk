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
    CONF_USE_MQTT,
    CONF_MQTT_BROKER,
    CONF_MQTT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_MQTT_BROKER,
    DEFAULT_MQTT_PORT,
    MANUFACTURER,
    VERSION,
    ATTRIBUTION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
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
    use_mqtt = entry.data.get(CONF_USE_MQTT, False)
    mqtt_client = None
    pin_mapping = entry.data.get("pin_mapping", {})

    # İlk veri çekme ve pin keşfi
    try:
        initial_data = await api.get_all_pins()
        if not initial_data:
            _LOGGER.error("No data received from Blynk API")
            raise ConfigEntryNotReady("No data received from device")
        _LOGGER.info("Initial data received: %s", initial_data)
    except Exception as err:
        _LOGGER.error("Error setting up Blynk integration: %s", str(err))
        raise ConfigEntryNotReady from err

    # MQTT kullanılacaksa
    if use_mqtt:
        try:
            from .mqtt_client import BlynkMQTTClient
            
            mqtt_broker = entry.data.get(CONF_MQTT_BROKER, DEFAULT_MQTT_BROKER)
            mqtt_port = entry.data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)
            
            _LOGGER.info("Setting up MQTT client: %s:%s", mqtt_broker, mqtt_port)
            
            # Pin mapping için geçici depolama
            discovered_pin_names = set()
            
            async def on_mqtt_message(topic: str, data: dict):
                """Handle MQTT message."""
                nonlocal pin_mapping
                
                # Topic'ten pin adını çıkar
                if "/ds/" in topic:
                    pin_name = topic.split("/ds/")[1].upper()
                    
                    # Bu pin adını kaydet
                    if pin_name not in discovered_pin_names:
                        discovered_pin_names.add(pin_name)
                        _LOGGER.debug("Discovered MQTT pin name: %s", pin_name)
                    
                    # Veriyi parse et
                    if isinstance(data, dict) and "value" in data:
                        value = data["value"]
                    else:
                        value = data
                    
                    # Pin mapping yapılmışsa ve coordinator varsa güncelle
                    if pin_name in pin_mapping and coordinator is not None:
                        pin_number = pin_mapping[pin_name]
                        # Pin numarasını düzelt
                        if not pin_number.startswith("V"):
                            pin_number = "V" + pin_number
                        elif pin_number.startswith("VV"):
                            pin_number = "V" + pin_number[2:]
                        
                        if coordinator.data is not None:
                            coordinator.data[pin_number] = value
                            coordinator.async_set_updated_data(coordinator.data)
                            _LOGGER.debug("MQTT updated pin %s (%s) to %s", pin_name, pin_number, value)
                    elif coordinator is not None:
                        # Mapping yoksa, değeri logla
                        _LOGGER.debug("MQTT message for unmapped pin %s: %s", pin_name, value)
            
            mqtt_client = BlynkMQTTClient(
                auth_token=entry.data[CONF_TOKEN],
                on_message_callback=on_mqtt_message,
                broker=mqtt_broker,
                port=mqtt_port,
            )
            
            # MQTT bağlantısını başlat
            connected = await mqtt_client.async_connect(hass.loop)
            if not connected:
                _LOGGER.warning("MQTT connection failed, falling back to HTTP polling")
                mqtt_client = None
                use_mqtt = False
            else:
                _LOGGER.info("MQTT client connected successfully")
                
                # Eğer pin mapping yoksa veya boşsa, otomatik discovery yap
                if not pin_mapping:
                    _LOGGER.info("No pin mapping found, starting automatic discovery")
                    await asyncio.sleep(2)
                    
                    # Discovery yap
                    pin_mapping = await _discover_pin_mapping(
                        api, mqtt_client, initial_data, discovered_pin_names
                    )
                    
                    # Pin mapping'i entry data'ya kaydet
                    if pin_mapping:
                        entry_data = dict(entry.data)
                        entry_data["pin_mapping"] = pin_mapping
                        hass.config_entries.async_update_entry(entry, data=entry_data)
                        _LOGGER.info("Pin mapping saved to config entry: %s", pin_mapping)
                else:
                    _LOGGER.info("Using existing pin mapping: %s", pin_mapping)
                
        except ImportError:
            _LOGGER.warning("paho-mqtt not installed, MQTT disabled")
            use_mqtt = False
        except Exception as err:
            _LOGGER.error("Error setting up MQTT: %s", err)
            use_mqtt = False

    # Coordinator oluştur
    coordinator = None
    
    async def async_update_data() -> dict[str, Any]:
        """Fetch data from API."""
        if use_mqtt and mqtt_client and mqtt_client.connected:
            _LOGGER.debug("Using MQTT, skipping HTTP poll")
            return coordinator.data if coordinator.data else initial_data
        
        # HTTP polling
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

    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    if use_mqtt and mqtt_client and mqtt_client.connected:
        scan_interval = max(scan_interval, 300)
        _LOGGER.info("MQTT enabled, using %s second poll interval for fallback", scan_interval)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.data[CONF_TOKEN][:8]}",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

    coordinator.data = initial_data

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "mqtt_client": mqtt_client,
        "use_mqtt": use_mqtt,
        "pin_mapping": pin_mapping,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    await coordinator.async_refresh()

    return True

async def _discover_pin_mapping(api, mqtt_client, initial_data, discovered_pin_names):
    """Effective pin mapping with smart strategies."""
    _LOGGER.info("Starting smart pin mapping discovery...")
    pin_mapping = {}
    
    original_callback = mqtt_client.on_message_callback
    
    received_messages = []
    
    async def on_mqtt_message_discovery(topic: str, data: dict):
        """Handle MQTT message during discovery."""
        try:
            if "/ds/" in topic:
                pin_name = topic.split("/ds/")[1].upper()
                
                if isinstance(data, dict) and "value" in data:
                    value = str(data["value"])
                else:
                    value = str(data)
                
                received_messages.append({
                    "pin_name": pin_name,
                    "value": value,
                    "timestamp": asyncio.get_event_loop().time()
                })
                _LOGGER.debug("Discovery MQTT: %s = %s", pin_name, value)
        except Exception as e:
            _LOGGER.error("Error in discovery callback: %s", e)
    
    mqtt_client.on_message_callback = on_mqtt_message_discovery
    
    try:
        original_values = {}
        for pin_number, value in initial_data.items():
            original_values[pin_number] = value
        
        # Phase 1: Quick passive listening (3 seconds)
        _LOGGER.info("Phase 1: Quick passive listening (3 seconds)...")
        await asyncio.sleep(3)
        
        # Phase 2: Smart testing for each pin
        for pin_number, current_value in initial_data.items():
            try:
                current_str = str(current_value)
                original_value = current_value
                
                # Determine pin type based on value
                is_binary = current_str in ["0", "1"]
                is_numeric = isinstance(current_value, (int, float))
                is_string = isinstance(current_value, str) and not is_binary
                
                # Test value calculation
                test_value = None
                if is_binary:
                    # Binary pins: toggle value
                    test_value = "1" if current_str == "0" else "0"
                    _LOGGER.info("Testing binary pin %s: %s -> %s", 
                               pin_number, current_value, test_value)
                    
                    # Send test value
                    success = await api.set_pin_value(pin_number, test_value)
                    if success:
                        # Wait for MQTT
                        await asyncio.sleep(2)
                        
                        # Check recent messages
                        recent_messages = [
                            msg for msg in received_messages 
                            if msg["timestamp"] > asyncio.get_event_loop().time() - 3
                        ]
                        
                        # Look for matching message
                        for msg in recent_messages:
                            if msg["value"] == test_value:
                                pin_name = msg["pin_name"]
                                if pin_name not in pin_mapping:
                                    pin_mapping[pin_name] = pin_number
                                    _LOGGER.info("✅ Binary mapping: MQTT %s → %s", 
                                               pin_name, pin_number)
                                    break
                        
                        # Restore original value
                        await api.set_pin_value(pin_number, original_value)
                        await asyncio.sleep(0.5)
                
                elif is_numeric:
                    # Numeric pins: small safe change
                    current_num = float(current_value)
                    if current_num == 0:
                        test_value = 5
                    elif current_num < 50:
                        test_value = current_num + 5
                    else:
                        test_value = current_num - 5
                    
                    _LOGGER.info("Testing numeric pin %s: %s -> %s", 
                               pin_number, current_value, test_value)
                    
                    # Send test value
                    success = await api.set_pin_value(pin_number, test_value)
                    if success:
                        # Wait longer for numeric pins
                        await asyncio.sleep(3)
                        
                        # Check recent messages
                        recent_messages = [
                            msg for msg in received_messages 
                            if msg["timestamp"] > asyncio.get_event_loop().time() - 4
                        ]
                        
                        # Look for matching message (with tolerance)
                        for msg in recent_messages:
                            try:
                                msg_value = float(str(msg["value"]))
                                if abs(msg_value - test_value) <= 0.1:  # 0.1 tolerance
                                    pin_name = msg["pin_name"]
                                    if pin_name not in pin_mapping:
                                        pin_mapping[pin_name] = pin_number
                                        _LOGGER.info("✅ Numeric mapping: MQTT %s → %s", 
                                                   pin_name, pin_number)
                                        break
                            except (ValueError, TypeError):
                                continue
                        
                        # Restore original value
                        await api.set_pin_value(pin_number, original_value)
                        await asyncio.sleep(0.5)
                
                elif is_string:
                    # String pins: append test marker
                    test_value = current_str + "_TEST"
                    if len(test_value) > 100:  # Truncate if too long
                        test_value = current_str[:90] + "_TEST"
                    
                    _LOGGER.info("Testing string pin %s: '%s' -> '%s'", 
                               pin_number, current_str[:20], test_value[:20])
                    
                    # Send test value
                    success = await api.set_pin_value(pin_number, test_value)
                    if success:
                        # Wait for MQTT
                        await asyncio.sleep(2)
                        
                        # Check recent messages
                        recent_messages = [
                            msg for msg in received_messages 
                            if msg["timestamp"] > asyncio.get_event_loop().time() - 3
                        ]
                        
                        # Look for matching message
                        for msg in recent_messages:
                            if msg["value"] == test_value:
                                pin_name = msg["pin_name"]
                                if pin_name not in pin_mapping:
                                    pin_mapping[pin_name] = pin_number
                                    _LOGGER.info("✅ String mapping: MQTT %s → %s", 
                                               pin_name, pin_number)
                                    break
                        
                        # Restore original value
                        await api.set_pin_value(pin_number, original_value)
                        await asyncio.sleep(0.5)
                
            except Exception as pin_err:
                _LOGGER.debug("Error testing pin %s: %s", pin_number, pin_err)
                # Try to restore original value
                try:
                    await api.set_pin_value(pin_number, original_values[pin_number])
                except:
                    pass
                continue
        
        # Phase 3: Final passive matching for any unmapped pins
        unmapped_pins = [pin for pin in initial_data.keys() if pin not in pin_mapping.values()]
        if unmapped_pins and received_messages:
            _LOGGER.info("Phase 3: Passive matching for %d unmapped pins", len(unmapped_pins))
            
            for pin_number in unmapped_pins:
                pin_value = str(initial_data[pin_number])
                
                # Find messages with matching values
                matching_messages = []
                for msg in received_messages:
                    if msg["value"] == pin_value:
                        matching_messages.append(msg)
                    else:
                        # Try numeric match
                        try:
                            msg_num = float(str(msg["value"]))
                            pin_num = float(pin_value)
                            if abs(msg_num - pin_num) <= 0.1:
                                matching_messages.append(msg)
                        except (ValueError, TypeError):
                            pass
                
                if matching_messages:
                    # Use most frequent MQTT pin name
                    from collections import Counter
                    pin_names = [msg["pin_name"] for msg in matching_messages]
                    most_common = Counter(pin_names).most_common(1)[0][0]
                    if most_common not in pin_mapping:
                        pin_mapping[most_common] = pin_number
                        _LOGGER.info("✅ Passive mapping: MQTT %s → %s", most_common, pin_number)
        
    except Exception as err:
        _LOGGER.error("Error during pin mapping discovery: %s", err)
    finally:
        mqtt_client.on_message_callback = original_callback
    
    _LOGGER.info("Smart pin mapping completed: %s", pin_mapping)
    
    # Log unmapped pins
    mapped_pins = set(pin_mapping.values())
    all_pins = set(initial_data.keys())
    unmapped_pins = all_pins - mapped_pins
    
    if unmapped_pins:
        _LOGGER.warning("Unmapped pins: %s", unmapped_pins)
        for pin in unmapped_pins:
            _LOGGER.info("  - %s: %s", pin, initial_data[pin])
    
    # Verify all original values are restored
    for pin_number, original_value in original_values.items():
        try:
            current = await api.get_pin_value(pin_number)
            if str(current) != str(original_value):
                _LOGGER.debug("Restoring original value for %s: %s -> %s", 
                            pin_number, current, original_value)
                await api.set_pin_value(pin_number, original_value)
        except:
            pass
    
    return pin_mapping

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if entry.entry_id in hass.data[DOMAIN]:
        mqtt_client = hass.data[DOMAIN][entry.entry_id].get("mqtt_client")
        if mqtt_client:
            await mqtt_client.async_disconnect()
    
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
        
        if not pin.startswith("V"):
            self._pin = "V" + pin
        elif pin.startswith("VV"):
            self._pin = "V" + pin[2:]
        else:
            self._pin = pin
            
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{self._pin}"
        
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
