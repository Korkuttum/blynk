"""Blynk Cloud API implementation."""
import aiohttp
import logging
from typing import Optional, Dict, Any

from .const import API_URL, DEFAULT_TIMEOUT

_LOGGER = logging.getLogger(__name__)

class BlynkCloudAPI:
    """Blynk Cloud API."""
    
    def __init__(self, token: str):
        """Initialize the API."""
        self.token = token
        self.base_url = API_URL

    async def _make_request(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Make a request to the Blynk API."""
        url = f"{self.base_url}/{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=DEFAULT_TIMEOUT) as response:
                    _LOGGER.debug("API request to %s, status: %s", url, response.status)
                    if response.status == 200:
                        try:
                            return await response.json()
                        except aiohttp.ContentTypeError:
                            text = await response.text()
                            return {"value": text}
                    _LOGGER.error("API request failed: %s", response.status)
                    return None
        except Exception as err:
            _LOGGER.error("API request error: %s", str(err))
            return None

    async def get_all_pins(self) -> Dict[str, Any]:
        """Get all pins from the device."""
        response = await self._make_request(f"getAll?token={self.token}")
        if not response:
            return {}
        
        processed_data = {}
        for pin, value in response.items():
            if value is not None:
                # Pin isimlerini standartlaştır
                pin_name = pin.upper()
                # Değerleri uygun formata çevir
                try:
                    # Önce float dönüşümünü dene
                    processed_value = float(value)
                    # Eğer tam sayıysa, int'e çevir
                    if processed_value.is_integer():
                        processed_value = int(processed_value)
                except (ValueError, TypeError):
                    # Sayısal değilse string olarak bırak
                    processed_value = str(value)
                
                processed_data[pin_name] = processed_value
        
        _LOGGER.debug("Processed pin data: %s", processed_data)
        return processed_data

    async def set_pin_value(self, pin: str, value: Any) -> bool:
        """Set pin value."""
        # Pin ismini düzelt
        pin = pin.upper()
        # Değeri string'e çevir
        str_value = str(value)
        response = await self._make_request(f"update?token={self.token}&{pin}={str_value}")
        success = response is not None
        if success:
            _LOGGER.debug("Successfully set pin %s to %s", pin, str_value)
        else:
            _LOGGER.error("Failed to set pin %s to %s", pin, str_value)
        return success