"""Constants for UNiNUS Remote Console integration."""

DOMAIN = "unircon"

# Config keys
CONF_BROKER_HOST = "broker_host"
CONF_BROKER_PORT = "broker_port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DOMAIN = "urcon_domain"
CONF_HOSTS = "hosts"
CONF_SUBSCRIBE_TOPIC = "subscribe_topic"

# Defaults
DEFAULT_BROKER_PORT = 1884
DEFAULT_DOMAIN = "uninus"
DEFAULT_SUBSCRIBE_TOPIC = "ha/pubrsp/#"

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
