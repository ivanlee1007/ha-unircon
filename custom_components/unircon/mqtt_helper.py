"""MQTT helper for UNiNUS Remote Console integration."""

from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Any, Callable

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
        discovery_host_name: str = "urcon",
        default_callback_ip: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._domain = urcon_domain
        self._host_name = host_name
        self._discovery_host_name = (discovery_host_name or "urcon").strip() or "urcon"
        self._default_callback_ip = (default_callback_ip or "").strip() or None
        self._client = None
        self._on_message_callbacks: list[Callable[[str, str], None]] = []
        self._on_connect_callbacks: list[Callable[[bool], None]] = []
        self._connect_event = threading.Event()
        self._connect_success = False
        self._last_connect_error: str | None = None

    def connect(self) -> None:
        """Connect to MQTT broker and wait for on_connect result."""
        import paho.mqtt.client as mqtt

        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

        self._connect_event.clear()
        self._connect_success = False
        self._last_connect_error = None

        # Use v2 API if available (paho-mqtt >= 2.0), fallback to v1
        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"ha-unircon-{self._host_name}",
            )
        except AttributeError:
            # paho-mqtt 1.x
            self._client = mqtt.Client(
                client_id=f"ha-unircon-{self._host_name}",
            )

        if self._username:
            self._client.username_pw_set(self._username, self._password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        try:
            self._client.connect(self._host, self._port, keepalive=60)
            self._client.loop_start()
            if not self._connect_event.wait(timeout=5):
                raise RuntimeError(f"MQTT connect timeout to {self._host}:{self._port}")
            if not self._connect_success:
                raise RuntimeError(self._last_connect_error or f"MQTT connect rejected by {self._host}:{self._port}")
            _LOGGER.info("UNiNUS MQTT connected to %s:%s", self._host, self._port)
        except Exception as err:
            self._last_connect_error = str(err)
            _LOGGER.error("UNiNUS MQTT connect failed: %s", err)
            try:
                if self._client:
                    self._client.loop_stop()
                    self._client.disconnect()
            except Exception:
                pass
            self._client = None
            raise

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def reconnect_to(
        self,
        host: str,
        port: int,
        username: str = "",
        password: str = "",
    ) -> tuple[str, int, str, str]:
        """Temporarily reconnect to a different broker.

        Returns (old_host, old_port, old_username, old_password) for reconnecting back.
        """
        old = (self._host, self._port, self._username, self._password)
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self.connect()
        return old  # type: ignore[return-value]

    def subscribe_devices(self, hosts: list[str]) -> None:
        """Subscribe to console and response topics for given hosts."""
        if not self._client:
            return
        topics = []
        for host in hosts:
            topics.append((TOPIC_CONSOLE.format(host=host), 1))
            topics.append((TOPIC_RESPONSE.format(host=host), 1))
        topics.append(("ha/pubrsp/#", 1))
        topics.append(("ha/pub/+/console/#", 1))
        for topic, qos in topics:
            try:
                self._client.subscribe(topic, qos)
            except Exception as err:
                _LOGGER.warning("Subscribe failed for %s: %s", topic, err)

    def subscribe_urcom(self) -> None:
        """Subscribe to URCOM neighbor discovery topic."""
        if not self._client:
            return
        topic = TOPIC_URCOM.format(domain=self._domain)
        collect_topics = {
            TOPIC_HOST_COLLECT.format(host_name=self._host_name),
            TOPIC_HOST_COLLECT.format(host_name=self._discovery_host_name),
            "ha/sub/urcon",
            "ha/sub/#",
        }
        try:
            self._client.subscribe(topic, 1)
            for collect_topic in collect_topics:
                self._client.subscribe(collect_topic, 1)
        except Exception as err:
            _LOGGER.warning("URCOM subscribe failed: %s", err)

    def send_command(self, host: str, token: str, command: str) -> None:
        """Send a command to a UNiNUS device."""
        if not self._client or not self._client.is_connected:
            _LOGGER.error("MQTT not connected, cannot send command")
            return
        topic = TOPIC_COMMAND.format(host=host)
        sanitized = command.replace(" ", "/")
        payload = f"/{token}/cmd/{sanitized}"
        self._client.publish(topic, payload, qos=1)
        _LOGGER.info("Sent command to %s: %s", host, payload)

    def request_token(self, host: str, username: str, password: str) -> None:
        """Request token from a device."""
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

    def _resolve_callback_ip(self, callback_ip: str | None = None) -> str:
        """Resolve backend callback IP/host to mimic browser context as closely as possible."""
        value = (callback_ip or self._default_callback_ip or "").strip()
        if value:
            return value
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((self._host, self._port))
                resolved = sock.getsockname()[0]
                if resolved:
                    return resolved
        except Exception as err:
            _LOGGER.debug("Failed to resolve source IP via broker route: %s", err)
        try:
            hostname = socket.gethostname()
            resolved = socket.gethostbyname(hostname)
            if resolved:
                return resolved
        except Exception as err:
            _LOGGER.debug("Failed to resolve callback host via gethostbyname: %s", err)
        return "127.0.0.1"

    def collect_neighbors(
        self,
        *,
        host_name: str | None = None,
        callback_ip: str | None = None,
        domain: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Publish URCOM neighbor discovery message."""
        if not self._client or not self._client.is_connected:
            _LOGGER.error("MQTT not connected")
            raise RuntimeError("MQTT not connected")
        effective_host = (host_name or self._discovery_host_name or "urcon").strip() or "urcon"
        effective_domain = (domain or self._domain or "uninus").strip() or "uninus"
        effective_callback_ip = self._resolve_callback_ip(callback_ip)
        topic = TOPIC_URCOM.format(domain=effective_domain)
        payload_obj: dict[str, Any] = {
            "host": effective_host,
            "user": self._username,
            "pass": self._password,
            "plen": 0,
            "type": 13,
            "domain": effective_domain,
            "ip": effective_callback_ip,
            "rch": f"ha/sub/{effective_host}",
            "payload": "",
        }
        payload = json.dumps(payload_obj)
        self._client.publish(topic, payload, qos=0, retain=False)
        _LOGGER.info("URCOM neighbor collection sent to %s payload=%s", topic, payload)
        return topic, payload_obj

    @property
    def is_connected(self) -> bool:
        try:
            return self._client is not None and self._client.is_connected()
        except Exception:
            return False

    @property
    def last_connect_error(self) -> str | None:
        return self._last_connect_error

    def on_message(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for incoming messages."""
        self._on_message_callbacks.append(callback)

    def on_connect(self, callback: Callable[[bool], None]) -> None:
        """Register a callback for connection state changes."""
        self._on_connect_callbacks.append(callback)

    def _on_connect(self, client, userdata, flags, rc, *args) -> None:
        """Handle MQTT connect event."""
        success = rc == 0
        self._connect_success = success
        if success:
            self._last_connect_error = None
        else:
            self._last_connect_error = f"MQTT broker rejected connection rc={rc}"
        self._connect_event.set()
        _LOGGER.info("UNiNUS MQTT on_connect: rc=%s success=%s", rc, success)
        for cb in self._on_connect_callbacks:
            try:
                cb(success)
            except Exception as err:
                _LOGGER.error("Connect callback error: %s", err)

    def _on_disconnect(self, client, userdata, rc=0, *args) -> None:
        """Handle MQTT disconnect event."""
        self._connect_success = False
        if rc not in (0, None):
            self._last_connect_error = f"MQTT disconnected rc={rc}"
        _LOGGER.warning("UNiNUS MQTT disconnected: rc=%s", rc)
        for cb in self._on_connect_callbacks:
            try:
                cb(False)
            except Exception:
                pass

    def _on_message(self, client, userdata, msg) -> None:
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
