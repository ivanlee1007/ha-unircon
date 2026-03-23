"""Constants for UNiNUS Remote Console integration."""

DOMAIN = "unircon"

CARD_JS_FILENAME = "unircon-console-card.js"
CARD_STATIC_URL = f"/{DOMAIN}_static/{CARD_JS_FILENAME}"
CARD_RESOURCE_VERSION = "1.0.24"
CARD_RESOURCE_URL = f"{CARD_STATIC_URL}?v={CARD_RESOURCE_VERSION}"

# Config keys
CONF_BROKER_HOST = "broker_host"
CONF_BROKER_PORT = "broker_port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DOMAIN = "urcon_domain"
CONF_HOSTS = "hosts"
CONF_SUBSCRIBE_TOPIC = "subscribe_topic"
CONF_DISCOVERY_HOST_NAME = "discovery_host_name"
CONF_CALLBACK_IP = "callback_ip"

# Defaults
DEFAULT_BROKER_PORT = 1883
DEFAULT_DOMAIN = "uninus"
DEFAULT_SUBSCRIBE_TOPIC = "ha/pubrsp/#"
DEFAULT_DISCOVERY_HOST_NAME = "urcon"

# MQTT topics
TOPIC_COMMAND = "ha/sub/{host}"
TOPIC_CONSOLE = "ha/pub/{host}/console/#"
TOPIC_RESPONSE = "ha/pubrsp/{host}/#"
TOPIC_URCOM = "urcom/{domain}"
TOPIC_HOST_COLLECT = "ha/sub/{host_name}"

# Platform
PLATFORMS = ["sensor", "button", "text"]

# Device state
STATE_ONLINE = "online"
STATE_OFFLINE = "offline"

# Runtime data keys
DATA_CONSOLE_HISTORY = "console_history"
DATA_TOKENS = "tokens"
