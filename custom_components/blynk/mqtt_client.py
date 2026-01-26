"""Blynk MQTT Client implementation."""
import asyncio
import logging
import ssl
import json
from typing import Callable, Optional, Dict, Any
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

_LOGGER = logging.getLogger(__name__)

MQTT_KEEPALIVE = 45
MQTT_QOS = 0


class BlynkMQTTClient:
    """Blynk MQTT Client."""

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
        self.broker = str(broker)  # Ensure string
        self.port = int(port)  # Ensure int
        self.on_message_callback = on_message_callback
        
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self.redirect_received = False
        self._loop = None
        self._running = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Handle MQTT connection."""
        connection_status = {
            0: "Successful",
            1: "Protocol version error",
            2: "Invalid client ID",
            3: "Server unavailable",
            4: "Bad username/password",
            5: "Unauthorized",
        }

        if rc == 0:
            self.connected = True
            _LOGGER.info("MQTT connection successful")
            
            # Subscribe to downlink messages
            client.subscribe("downlink/#", qos=MQTT_QOS)
            _LOGGER.debug("Subscribed to downlink messages")
            
            # Publish device info
            self._publish_device_info()
        else:
            error_msg = connection_status.get(rc, f"Unknown error: {rc}")
            _LOGGER.error("MQTT connection failed: %s", error_msg)
            self.connected = False

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8")
            
            # Handle redirect
            if topic == "downlink/redirect" and not self.redirect_received:
                self.redirect_received = True
                _LOGGER.info("Received server redirect: %s", payload)
                self._handle_redirect(payload)
                return
            
            # Parse message
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"value": payload}
            
            _LOGGER.debug("MQTT message received - Topic: %s, Data: %s", topic, data)
            
            # Call callback if set
            if self.on_message_callback:
                asyncio.run_coroutine_threadsafe(
                    self.on_message_callback(topic, data),
                    self._loop
                )
                
        except Exception as err:
            _LOGGER.error("Error processing MQTT message: %s", err)

    def _on_disconnect(self, client, userdata, rc, properties=None):
        """Handle MQTT disconnection."""
        self.connected = False
        if rc != 0:
            _LOGGER.warning("MQTT disconnected unexpectedly, will reconnect")
        else:
            _LOGGER.info("MQTT disconnected")

    def _publish_device_info(self):
        """Publish device information to Blynk."""
        if self.connected and self.client:
            info = {
                "tmpl": "HomeAssistant",
                "ver": "1.0.0",
                "build": datetime.now().strftime("%b %d %Y %H:%M:%S"),
                "type": "HomeAssistant",
                "rxbuff": 1024,
            }
            
            self.client.publish("info/mcu", json.dumps(info))
            _LOGGER.debug("Device info published")

    def _handle_redirect(self, uri: str):
        """Handle server redirect."""
        try:
            # Parse URI: mqtts://fra1.blynk.cloud:8883
            if uri.startswith(("mqtts://", "mqtt://")):
                server = uri.split("://")[1].split(":")[0]
                port = int(uri.split(":")[-1])
                
                _LOGGER.info("Redirecting to new server: %s:%s", server, port)
                
                # Disconnect and reconnect
                if self.client:
                    self.client.disconnect()
                
                self.broker = str(server)
                self.port = int(port)
                self._start_connection()
                
        except Exception as err:
            _LOGGER.error("Error handling redirect: %s", err)

    def _start_connection(self):
        """Start MQTT connection."""
        try:
            # Create MQTT client
            self.client = mqtt.Client(
                client_id="",
                protocol=mqtt.MQTTv311,
                clean_session=True,
            )
            
            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect
            
            # SSL configuration
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            self.client.tls_set_context(context)
            
            # Authentication
            self.client.username_pw_set(
                username="device",
                password=self.auth_token,
            )
            
            _LOGGER.info(
                "Connecting to MQTT broker %s:%s",
                self.broker,
                self.port,
            )
            
            # Connect - Ensure port is int
            self.client.connect(
                str(self.broker),
                int(self.port),
                keepalive=MQTT_KEEPALIVE,
            )
            
        except Exception as err:
            _LOGGER.error("MQTT connection error: %s", err)
            raise

    async def async_connect(self, loop):
        """Connect to MQTT broker (async)."""
        self._loop = loop
        self._running = True
        
        try:
            # Start connection in executor
            await loop.run_in_executor(None, self._start_connection)
            
            # Start loop in separate thread
            def mqtt_loop():
                while self._running:
                    if self.client:
                        self.client.loop(timeout=1.0)
            
            loop.run_in_executor(None, mqtt_loop)
            
            # Wait for connection
            for _ in range(30):  # 30 second timeout
                if self.connected:
                    return True
                await asyncio.sleep(1)
            
            _LOGGER.error("MQTT connection timeout")
            return False
            
        except Exception as err:
            _LOGGER.error("Failed to connect to MQTT: %s", err)
            return False

    async def async_disconnect(self):
        """Disconnect from MQTT broker."""
        self._running = False
        if self.client:
            await self._loop.run_in_executor(None, self.client.disconnect)
            self.client = None
        self.connected = False

    async def async_publish(self, topic: str, value: Any) -> bool:
        """Publish value to a topic."""
        if not self.connected or not self.client:
            _LOGGER.error("MQTT not connected, cannot publish")
            return False
        
        try:
            # Topic'in başına downlink/ds/ ekle
            full_topic = f"ds/{topic}" if not topic.startswith("ds/") else topic
            
            payload = str(value)
            
            await self._loop.run_in_executor(
                None,
                self.client.publish,
                full_topic,
                payload,
                MQTT_QOS,
            )
            
            _LOGGER.debug("Published to %s: %s", full_topic, payload)
            return True
            
        except Exception as err:
            _LOGGER.error("Error publishing to MQTT: %s", err)
            return False