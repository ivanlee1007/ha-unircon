"""MQTT helper for UNiNUS Remote Console integration."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .const import (
    TOPIC_COMMAND,
    TOPIC_CONSOLE,
    TOPIC_HOST_COLLECT,
    TOPIC_RESPONSE,
    TOPIC_URCOM,
)

_LOGGER = logging.getLogger(__name__)


class UNiNUSMQTT:
    """MQTT wrapper for UNiNUS device communication."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        urcon_domain: str = "uninus",
        host_name: str = "ha-unircon",
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._domain = urcon_domain
        self._host_name = host_name
        self._client: mqtt.Client | None = None
        self._on_message_callbacks: list[Callable[[str, str], None]] = []
        self._on_connect_callbacks: list[Callable[[bool], None]] = []

    def connect(self) -> None:
        """Connect to MQTT broker."""
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ha-unircon-{self._host_name}",
        )
        self._client.username_pw_set(self._username, self._password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        try:
            self._client.connect(self._host, self._port, keepalive=60)
            self._client.loop_start()
            _LOGGER.info("UNiNUS MQTT connected to %s:%s", self._host, self._port)
        except Exception as err:
            _LOGGER.error("UNiNUS MQTT connect failed: %s", err)
            raise

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None

    def subscribe_devices(self, hosts: list[str]) -> None:
        """Subscribe to console and response topics for given hosts."""
        if not self._client:
            return
        topics = []
        for host in hosts:
            topics.append((TOPIC_CONSOLE.format(host=host), 1))
            topics.append((TOPIC_RESPONSE.format(host=host), 1))
        # Subscribe response wildcard for batch discovery
        topics.append(("ha/pubrsp/#", 1))
        # Subscribe console wildcard
        topics.append(("ha/pub/+/console/#", 1))
        for topic, qos in topics:
            self._client.subscribe(topic, qos)
            _LOGGER.debug("Subscribed to: %s", topic)

    def subscribe_urcom(self) -> None:
        """Subscribe to URCOM neighbor discovery topic."""
        if not self._client:
            return
        topic = TOPIC_URCOM.format(domain=self._domain)
        self._client.subscribe(topic, 1)
        # Also subscribe to host collection topic
        collect_topic = TOPIC_HOST_COLLECT.format(host_name=self._host_name)
        self._client.subscribe(collect_topic, 1)
        _LOGGER.debug("Subscribed to URCOM topics: %s, %s", topic, collect_topic)

    def send_command(self, host: str, token: str, command: str) -> None:
        """Send a command to a UNiNUS device.

        Args:
            host: Target hostname
            token: Device token/serial number
            command: Command string (spaces replaced with / by device)
        """
        if not self._client or not self._client.is_connected:
            _LOGGER.error("MQTT not connected, cannot send command")
            return
        topic = TOPIC_COMMAND.format(host=host)
        sanitized = command.replace(" ", "/")
        payload = f"/{token}/cmd/{sanitized}"
        self._client.publish(topic, payload, qos=1)
        _LOGGER.info("Sent command to %s: %s", host, payload)

    def request_token(self, host: str, username: str, password: str) -> None:
        """Request token from a device.

        Args:
            host: Target hostname
            username: Login username
            password: Login password
        """
        if not self._client or not self._client.is_connected:
            _LOGGER.error("MQTT not connected, cannot request token")
            return
        topic = TOPIC_COMMAND.format(host=host)
        payload = f"/request/token/{username}:{password}@{host}"
        self._client.publish(topic, payload, qos=1)
        _LOGGER.info("Token request sent to %s", host)

    def publish_test(self, topic: str, payload: str) -> None:
        """Publish a test message to an arbitrary topic."""
        if not self._client or not self._client.is_connected:
            _LOGGER.error("MQTT not connected")
            return
        self._client.publish(topic, payload, qos=1)
        _LOGGER.info("Test publish: %s → %s", topic, payload)

    def collect_neighbors(self) -> None:
        """Publish URCOM neighbor discovery message."""
        if not self._client or not self._client.is_connected:
            _LOGGER.error("MQTT not connected")
            return
        topic = TOPIC_URCOM.format(domain=self._domain)
        payload = json.dumps({
            "host": self._host_name,
            "user": self._username,
            "pass": self._password,
            "plen": 0,
            "type": 13,
            "domain": self._domain,
            "ip": "127.0.0.1",
            "rch": f"ha/sub/{self._host_name}",
            "payload": "",
        })
        self._client.publish(topic, payload, qos=0)
        _LOGGER.info("URCOM neighbor collection sent to %s", topic)

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected()

    def on_message(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for incoming messages: (topic, payload)."""
        self._on_message_callbacks.append(callback)

    def on_connect(self, callback: Callable[[bool], None]) -> None:
        """Register a callback for connection state changes."""
        self._on_connect_callbacks.append(callback)

    def _on_connect(
        self, client: mqtt.Client, userdata: Any, flags: Any, rc: Any, properties: Any = None
    ) -> None:
        """Handle MQTT connect event."""
        success = rc == 0
        _LOGGER.info("UNiNUS MQTT on_connect: rc=%s success=%s", rc, success)
        for cb in self._on_connect_callbacks:
            cb(success)

    def _on_disconnect(
        self, client: mqtt.Client, userdata: Any, flags: Any = None, rc: Any = 0, properties: Any = None
    ) -> None:
        """Handle MQTT disconnect event."""
        _LOGGER.warning("UNiNUS MQTT disconnected: rc=%s", rc)
        for cb in self._on_connect_callbacks:
            cb(False)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Handle incoming MQTT message."""
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:
            payload = str(msg.payload)
        _LOGGER.debug("MQTT msg [%s]: %s", msg.topic, payload[:200])
        for cb in self._on_message_callbacks:
            try:
                cb(msg.topic, payload)
            except Exception as err:
                _LOGGER.error("Message callback error: %s", err)
