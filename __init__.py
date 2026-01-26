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
    pin_mapping = entry.data.get("pin_mapping", {})  # Config'ten pin mapping'i al

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
                # Örnek topic: downlink/ds/switch
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
                        # Pin numarasını düzelt (V0, V1, vb.)
                        if not pin_number.startswith("V"):
                            pin_number = "V" + pin_number
                        elif pin_number.startswith("VV"):  # VV0 -> V0
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
                    await asyncio.sleep(2)  # MQTT mesajlarının gelmesi için bekle
                    
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
    coordinator = None  # Forward reference
    
    async def async_update_data() -> dict[str, Any]:
        """Fetch data from API."""
        # MQTT kullanılıyorsa, sadece initial data'yı döndür
        # Güncellemeler MQTT'den gelecek
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

    # MQTT kullanılıyorsa daha uzun interval (MQTT real-time olduğu için)
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    if use_mqtt and mqtt_client and mqtt_client.connected:
        scan_interval = max(scan_interval, 300)  # Minimum 5 dakika
        _LOGGER.info("MQTT enabled, using %s second poll interval for fallback", scan_interval)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.data[CONF_TOKEN][:8]}",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

    # İlk veriyi yükle
    coordinator.data = initial_data

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "mqtt_client": mqtt_client,
        "use_mqtt": use_mqtt,
        "pin_mapping": pin_mapping,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # İlk güncellemeyi başlat
    await coordinator.async_refresh()

    return True

async def _discover_pin_mapping(api, mqtt_client, initial_data, discovered_pin_names):
    """Discover pin mapping by sending test signals and monitoring MQTT responses."""
    _LOGGER.info("Starting pin mapping discovery...")
    pin_mapping = {}
    
    # Original callback'ı sakla
    original_callback = mqtt_client.on_message_callback
    
    # MQTT mesajlarını toplamak için liste
    received_messages = []
    
    async def on_mqtt_message_discovery(topic: str, data: dict):
        """Handle MQTT message during discovery."""
        try:
            if "/ds/" in topic:
                pin_name = topic.split("/ds/")[1].upper()
                
                # Veriyi parse et
                if isinstance(data, dict):
                    if "value" in data:
                        value = str(data["value"])
                    else:
                        # Dictionary içinde value yoksa tüm dictionary'yi string'e çevir
                        import json
                        value = json.dumps(data)
                else:
                    value = str(data)
                
                # Mesajı kaydet
                received_messages.append({
                    "pin_name": pin_name,
                    "value": value,
                    "timestamp": asyncio.get_event_loop().time()
                })
                _LOGGER.debug("Discovery: Received MQTT message for %s: %s", pin_name, value)
        except Exception as e:
            _LOGGER.error("Error in discovery callback: %s", e)
    
    # Callback'i geçici olarak değiştir
    mqtt_client.on_message_callback = on_mqtt_message_discovery
    
    try:
        # Tüm pin değerlerini kaydet
        original_values = {}
        for pin_number, value in initial_data.items():
            original_values[pin_number] = value
        
        # Her pin için test sinyali gönder
        for pin_number, current_value in initial_data.items():
            try:
                # Received messages listesini temizle
                received_messages.clear()
                
                # TEST için daha net bir değer belirle
                test_value = None
                
                if isinstance(current_value, (int, float)):
                    current_num = float(current_value)
                    
                    # Mevcut değere göre farklı bir test değeri
                    if current_num == 0:
                        test_value = 100  # 0'dan 100'e büyük değişiklik
                    elif current_num < 50:
                        test_value = current_num + 50  # +50 ekle
                    else:
                        test_value = current_num - 30  # -30 çıkar
                        
                    # Eğer test değeri current_value ile aynıysa farklı bir değer seç
                    if test_value == current_num:
                        test_value = current_num + 1
                        
                elif isinstance(current_value, str):
                    # String için benzersiz bir test değeri
                    test_value = f"TEST_{pin_number}_{asyncio.get_event_loop().time():.0f}"
                else:
                    test_value = f"TEST_{pin_number}"
                
                _LOGGER.info("Sending test signal to %s: %s (was: %s)", 
                            pin_number, test_value, current_value)
                
                # API üzerinden test sinyalini gönder
                success = await api.set_pin_value(pin_number, test_value)
                
                if success:
                    # MQTT mesajının gelmesi için daha uzun bekle (sensor/number için daha uzun)
                    wait_time = 5 if pin_number in ["V2", "V3"] else 3
                    await asyncio.sleep(wait_time)
                    
                    # Bu süre içinde gelen MQTT mesajlarını filtrele
                    recent_messages = [
                        msg for msg in received_messages 
                        if msg["timestamp"] > asyncio.get_event_loop().time() - (wait_time + 1)
                    ]
                    
                    _LOGGER.debug("Recent MQTT messages after test to %s: %s", pin_number, recent_messages)
                    
                    # Eşleşen mesaj bul
                    matched_pin_name = None
                    for msg in recent_messages:
                        msg_value = str(msg["value"]).strip()
                        test_str = str(test_value).strip()
                        
                        # Değerler eşleşiyor mu kontrol et (tam eşleşme)
                        if msg_value == test_str:
                            matched_pin_name = msg["pin_name"]
                            _LOGGER.debug("Exact match found for pin %s: MQTT pin %s", 
                                         pin_number, matched_pin_name)
                            break
                    
                    # Tam eşleşme yoksa kısmi eşleşme ara
                    if not matched_pin_name:
                        for msg in recent_messages:
                            msg_value = str(msg["value"]).strip()
                            test_str = str(test_value).strip()
                            
                            # Numeric değerler için sayısal eşleşme kontrol et
                            try:
                                msg_num = float(msg_value)
                                test_num = float(test_str)
                                # %10 tolerans ile eşleşme
                                if abs(msg_num - test_num) <= (abs(test_num) * 0.1):
                                    matched_pin_name = msg["pin_name"]
                                    _LOGGER.debug("Numeric match found for pin %s: MQTT pin %s (msg: %s, test: %s)", 
                                                 pin_number, matched_pin_name, msg_value, test_str)
                                    break
                            except (ValueError, TypeError):
                                # Sayısal değilse string içinde pin numarası ara
                                if pin_number.replace("V", "") in msg_value or pin_number in msg_value:
                                    matched_pin_name = msg["pin_name"]
                                    _LOGGER.debug("Partial match found for pin %s: MQTT pin %s", 
                                                 pin_number, matched_pin_name)
                                    break
                    
                    # Eşleşme bulunduysa kaydet
                    if matched_pin_name and matched_pin_name not in pin_mapping:
                        pin_mapping[matched_pin_name] = pin_number
                        _LOGGER.info("✅ Mapped MQTT pin %s to %s", matched_pin_name, pin_number)
                        
                    # Test değerini geri al (orijinal değere)
                    try:
                        await api.set_pin_value(pin_number, original_values[pin_number])
                        await asyncio.sleep(0.5)
                    except Exception as restore_err:
                        _LOGGER.warning("Failed to restore original value for %s: %s", 
                                       pin_number, restore_err)
                        
            except Exception as err:
                _LOGGER.debug("Error in pin mapping for %s: %s", pin_number, err)
                # Hata olsa bile test değerini geri almaya çalış
                try:
                    await api.set_pin_value(pin_number, original_values[pin_number])
                except:
                    pass
                continue
        
        # Tüm değerleri orijinal haline geri döndür (ekstra güvenlik için)
        for pin_number, original_value in original_values.items():
            try:
                await api.set_pin_value(pin_number, original_value)
                await asyncio.sleep(0.1)
            except:
                pass
        
    except Exception as err:
        _LOGGER.error("Error during pin mapping discovery: %s", err)
    finally:
        # Original callback'ı geri yükle
        mqtt_client.on_message_callback = original_callback
    
    _LOGGER.info("Pin mapping discovery completed: %s", pin_mapping)
    
    # Mapping sonuçlarını kontrol et
    if not pin_mapping:
        _LOGGER.warning("No pin mapping discovered! MQTT messages may not be processed correctly.")
    else:
        # Hangi pinlerin mapped edilmediğini göster
        mapped_pins = set(pin_mapping.values())
        all_pins = set(initial_data.keys())
        unmapped_pins = all_pins - mapped_pins
        if unmapped_pins:
            _LOGGER.info("Unmapped pins: %s", unmapped_pins)
            
        # Eğer V2 veya V3 unmapped kaldıysa, manuel mapping öner
        for pin in ["V2", "V3"]:
            if pin in unmapped_pins:
                _LOGGER.warning("Pin %s could not be automatically mapped. "
                              "MQTT pin names detected: %s. "
                              "Please check Blynk app datastream names.",
                              pin, list(discovered_pin_names))
    
    return pin_mapping

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # MQTT client'ı kapat
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
        
        # Pin numarasını düzelt (V0, V1, vb.)
        if not pin.startswith("V"):
            self._pin = "V" + pin
        elif pin.startswith("VV"):  # VV0 -> V0
            self._pin = "V" + pin[2:]
        else:
            self._pin = pin
            
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{self._pin}"
        
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