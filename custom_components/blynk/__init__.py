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
    Platform.LIGHT,
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
                    
                    # Discovery yap - GÜVENLİ SÜRÜM: mevcut değerleri kullan
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
    """Güvenli pin mapping: Mevcut değerleri kullanarak eşleme yap."""
    _LOGGER.info("Starting safe pin mapping discovery...")
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
        # Phase 1: Pasif dinleme (5 saniye)
        _LOGGER.info("Phase 1: Passive listening for initial MQTT messages (5 seconds)...")
        await asyncio.sleep(5)
        
        # Phase 2: Her pin için mevcut değeri gönder ve MQTT cevabını dinle
        _LOGGER.info("Phase 2: Sending current pin values for mapping...")
        for pin_number, current_value in initial_data.items():
            try:
                # Mevcut değeri string'e çevir
                current_str = str(current_value)
                
                # Pin tipini belirle
                is_binary = current_str in ["0", "1"]
                is_numeric = isinstance(current_value, (int, float))
                is_string = isinstance(current_value, str) and not is_binary
                
                _LOGGER.debug("Processing pin %s: %s (binary: %s, numeric: %s, string: %s)",
                            pin_number, current_value, is_binary, is_numeric, is_string)
                
                # Mevcut değeri gönder - GÜVENLİ: cihaz durumunu değiştirmeden
                success = await api.set_pin_value(pin_number, current_str)
                if success:
                    _LOGGER.debug("Sent current value for pin %s: %s", pin_number, current_str)
                    
                    # MQTT cevabını bekle
                    if is_binary:
                        wait_time = 2  # Binary pin'ler için kısa bekleme
                    elif is_numeric:
                        wait_time = 3  # Numeric pin'ler için orta bekleme
                    else:
                        wait_time = 3  # String pin'ler için orta bekleme
                    
                    await asyncio.sleep(wait_time)
                    
                    # Son mesajları kontrol et
                    recent_messages = [
                        msg for msg in received_messages 
                        if msg["timestamp"] > asyncio.get_event_loop().time() - (wait_time + 2)
                    ]
                    
                    # MQTT mesajlarında aynı değeri ara
                    for msg in recent_messages:
                        if msg["value"] == current_str:
                            pin_name = msg["pin_name"]
                            if pin_name not in pin_mapping:
                                pin_mapping[pin_name] = pin_number
                                _LOGGER.info("✅ Direct mapping: MQTT %s → %s (value: %s)", 
                                           pin_name, pin_number, current_str)
                                break
                        elif is_numeric:
                            # Sayısal değerler için toleranslı karşılaştırma
                            try:
                                msg_value = float(str(msg["value"]))
                                pin_value_num = float(current_str)
                                # %1 tolerans veya minimum 0.1
                                tolerance = abs(pin_value_num * 0.01)
                                if abs(msg_value - pin_value_num) <= max(tolerance, 0.1):
                                    pin_name = msg["pin_name"]
                                    if pin_name not in pin_mapping:
                                        pin_mapping[pin_name] = pin_number
                                        _LOGGER.info("✅ Numeric mapping: MQTT %s → %s (value: %s ≈ %s)", 
                                                   pin_name, pin_number, msg_value, pin_value_num)
                                        break
                            except (ValueError, TypeError):
                                continue
                
                # Her pin arasında kısa bekleme
                await asyncio.sleep(1)
                
            except Exception as pin_err:
                _LOGGER.warning("Error processing pin %s: %s", pin_number, pin_err)
                continue
        
        # Phase 3: Pasif eşleştirme - eşleşmeyen pin'ler için
        if received_messages:
            _LOGGER.info("Phase 3: Passive matching for remaining pins...")
            
            # Tüm mesajları değerlerine göre grupla
            value_to_messages = {}
            for msg in received_messages:
                value = msg["value"]
                if value not in value_to_messages:
                    value_to_messages[value] = []
                value_to_messages[value].append(msg)
            
            # Eşleşmeyen pin'leri kontrol et
            unmapped_pins = [pin for pin in initial_data.keys() if pin not in pin_mapping.values()]
            if unmapped_pins:
                _LOGGER.info("Found %d unmapped pins for passive matching", len(unmapped_pins))
                
                for pin_number in unmapped_pins:
                    pin_value = str(initial_data[pin_number])
                    
                    if pin_value in value_to_messages:
                        # En sık görülen MQTT pin adını bul
                        from collections import Counter
                        messages = value_to_messages[pin_value]
                        pin_names = [msg["pin_name"] for msg in messages]
                        if pin_names:
                            most_common = Counter(pin_names).most_common(1)[0][0]
                            if most_common not in pin_mapping:
                                pin_mapping[most_common] = pin_number
                                _LOGGER.info("✅ Passive mapping: MQTT %s → %s (value: %s)", 
                                           most_common, pin_number, pin_value)
                    else:
                        # Sayısal değerler için yakın eşleşme ara
                        try:
                            pin_value_num = float(pin_value)
                            for value_str, messages in value_to_messages.items():
                                try:
                                    msg_value_num = float(value_str)
                                    # %5 tolerans
                                    if abs(msg_value_num - pin_value_num) <= abs(pin_value_num * 0.05):
                                        from collections import Counter
                                        pin_names = [msg["pin_name"] for msg in messages]
                                        if pin_names:
                                            most_common = Counter(pin_names).most_common(1)[0][0]
                                            if most_common not in pin_mapping:
                                                pin_mapping[most_common] = pin_number
                                                _LOGGER.info("✅ Approximate mapping: MQTT %s → %s (%s ≈ %s)", 
                                                           most_common, pin_number, msg_value_num, pin_value_num)
                                                break
                                except (ValueError, TypeError):
                                    continue
                        except (ValueError, TypeError):
                            # Sayısal değilse, string karşılaştırma
                            pass
        
        # Sonuçları logla
        _LOGGER.info("Safe pin mapping completed: %s", pin_mapping)
        
        # Eşleşmemiş pin'leri logla
        mapped_pins = set(pin_mapping.values())
        all_pins = set(initial_data.keys())
        unmapped_pins = all_pins - mapped_pins
        
        if unmapped_pins:
            _LOGGER.warning("Could not map %d pins:", len(unmapped_pins))
            for pin in unmapped_pins:
                _LOGGER.info("  - %s: %s", pin, initial_data[pin])
        else:
            _LOGGER.info("✅ All pins mapped successfully!")
        
    except Exception as err:
        _LOGGER.error("Error during pin mapping discovery: %s", err)
    finally:
        mqtt_client.on_message_callback = original_callback
    
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
