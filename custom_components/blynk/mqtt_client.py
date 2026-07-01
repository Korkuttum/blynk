"""Blynk MQTT Client implementation - Okuma çalışıyor, yazma için topic küçük harf + virtual düzeltmesi."""
import asyncio
import logging
import ssl
import json
from typing import Callable, Optional, Any
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

_LOGGER = logging.getLogger(__name__)

MQTT_KEEPALIVE = 60
MQTT_QOS = 0                    # Gönderme başarılı olan orijinal kodda QoS=0 idi
RECONNECT_MIN_DELAY = 1
RECONNECT_MAX_DELAY = 120


class BlynkMQTTClient:
    """Blynk MQTT Client with auto-reconnect."""

    def __init__(
        self,
        auth_token: str,
        on_message_callback: Optional[Callable] = None,
        broker: str = "blynk.cloud",
        port: int = 8883,
    ):
        """Initialize MQTT client."""
        if mqtt is None:
            raise ImportError("paho-mqtt is not installed")

        self.auth_token = auth_token
        self.broker = str(broker)
        self.port = int(port)
        self.on_message_callback = on_message_callback

        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self.redirect_received = False
        self._loop = None
        self._running = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Handle MQTT connection."""
        if rc == 0:
            self.connected = True
            _LOGGER.info("MQTT connected to %s:%s", self.broker, self.port)
            client.subscribe("downlink/#", qos=MQTT_QOS)
            _LOGGER.debug("Subscribed to downlink/#")
            self._publish_device_info()
        else:
            error_msg = {
                1: "Incorrect protocol version",
                2: "Invalid client identifier",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized",
            }.get(rc, f"Unknown error ({rc})")
            _LOGGER.error("MQTT connection failed: %s", error_msg)
            self.connected = False

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            topic = msg.topic
            try:
                payload = msg.payload.decode("utf-8")
            except UnicodeDecodeError:
                payload = "<binary or invalid utf-8>"

            _LOGGER.debug("MQTT message - Topic: %s | Payload: %s", topic, payload[:200])

            if topic == "downlink/redirect" and not self.redirect_received:
                self.redirect_received = True
                _LOGGER.info("Received redirect to: %s", payload)
                self._handle_redirect(payload)
                return

            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"value": payload}

            if self.on_message_callback:
                asyncio.run_coroutine_threadsafe(
                    self.on_message_callback(topic, data),
                    self._loop
                )

        except Exception as err:
            _LOGGER.exception("Error in MQTT message handler: %s", err)

    def _on_disconnect(self, client, userdata, rc, properties=None):
        """Handle disconnection."""
        self.connected = False
        if rc != 0:
            _LOGGER.warning("MQTT disconnected unexpectedly (rc=%s) - auto-reconnect enabled", rc)
        else:
            _LOGGER.info("MQTT disconnected cleanly")

    def _publish_device_info(self):
        if not self.connected or not self.client:
            return
        info = {
            "tmpl": "HomeAssistant",
            "ver": "1.0.0",
            "build": datetime.now().strftime("%b %d %Y %H:%M:%S"),
            "type": "HomeAssistant Integration",
            "rxbuff": 2048,
        }
        try:
            self.client.publish("info/mcu", json.dumps(info), qos=0)
            _LOGGER.debug("Device info published")
        except Exception as e:
            _LOGGER.warning("Failed to publish device info: %s", e)

    def _handle_redirect(self, uri: str):
        try:
            if uri.startswith(("mqtts://", "mqtt://")):
                parts = uri.split("://")[1].split(":")
                new_broker = parts[0]
                new_port = int(parts[1]) if len(parts) > 1 else 8883
                _LOGGER.info("Redirecting to %s:%s", new_broker, new_port)
                if self.client:
                    self.client.disconnect()
                self.broker = new_broker
                self.port = new_port
                self._start_connection()
        except Exception as e:
            _LOGGER.error("Redirect handling failed: %s", e)

    def _start_connection(self):
        if self.client:
            try:
                self.client.disconnect()
            except:
                pass

        self.client = mqtt.Client(
            client_id="",
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )

        self.client.reconnect_delay_set(
            min_delay=RECONNECT_MIN_DELAY,
            max_delay=RECONNECT_MAX_DELAY
        )

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.client.tls_set_context(context)

        self.client.username_pw_set(
            username="device",
            password=self.auth_token
        )

        _LOGGER.info("Connecting to MQTT %s:%s (auto-reconnect enabled)", self.broker, self.port)
        self.client.connect(str(self.broker), int(self.port), keepalive=MQTT_KEEPALIVE)

    def loop_start(self):
        if self.client:
            self.client.loop_start()

    async def async_connect(self, loop):
        if mqtt is None:
            _LOGGER.error("paho-mqtt not installed")
            return False

        self._loop = loop
        self._running = True
        self.redirect_received = False

        try:
            await loop.run_in_executor(None, self._start_connection)
            await loop.run_in_executor(None, self.loop_start)

            for _ in range(60):
                if self.connected:
                    _LOGGER.info("MQTT initial connection successful")
                    return True
                await asyncio.sleep(1)

            _LOGGER.error("MQTT connection timeout after 60 seconds")
            return False

        except Exception as err:
            _LOGGER.error("MQTT connection setup failed: %s", err)
            return False

    async def async_disconnect(self):
        self._running = False
        if self.client:
            await self._loop.run_in_executor(None, self.client.loop_stop)
            await self._loop.run_in_executor(None, self.client.disconnect)
            self.client = None
        self.connected = False
        _LOGGER.info("MQTT client disconnected")

    async def async_publish(self, topic: str, value: Any) -> bool:
        """Publish value to topic - datastream adını küçük harfe çevir ve virtual ekle."""
        if not self.connected or not self.client:
            _LOGGER.debug("Cannot publish - MQTT not connected (topic: %s)", topic)
            return False

        try:
            # Topic temizleme mantığı:
            # V0 → virtual0
            # VIRTUAL0 → virtual0
            # v0 → virtual0
            # virtual0 → virtual0 (zaten küçükse kalır)
            clean = str(topic).lower()
            if clean.startswith(('v', 'virtual')):
                # V/v/virtual/VIRTUAL öneklerini kaldır
                clean = clean.lstrip('virtualv')
                # Eğer sadece sayı kaldıysa virtual + sayı yap
                if clean.isdigit():
                    clean = f"virtual{clean}"
                else:
                    # custom isim varsa küçük harf olarak bırak
                    pass
            else:
                # Pin V ile başlamıyorsa olduğu gibi küçük harf yap
                clean = clean

            full_topic = f"ds/{clean}"
            payload = str(value)

            result = await self._loop.run_in_executor(
                None,
                lambda: self.client.publish(full_topic, payload, qos=MQTT_QOS)
            )

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.info("YAZMA BAŞARILI → %s → %s", full_topic, payload)
                return True
            else:
                _LOGGER.warning("Publish failed (rc=%s): %s → %s", result.rc, full_topic, payload)
                return False

        except Exception as err:
            _LOGGER.error("MQTT publish error: %s", err)
            return False
