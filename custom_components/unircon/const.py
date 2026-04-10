"""Constants for UNiNUS Remote Console integration."""

DOMAIN = "unircon"

CARD_JS_FILENAME = "unircon-console-card.js"
CARD_STATIC_URL = f"/{DOMAIN}_static/{CARD_JS_FILENAME}"
CARD_RESOURCE_VERSION = "1.3.0"
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
CONF_REQUIRE_CONFIRM_DANGEROUS = "require_confirm_dangerous"
CONF_APPROVAL_WINDOW_SECONDS = "approval_window_seconds"

# Site manager (multi-broker persistence in config_entry.options)
CONF_SITES = "sites"          # list[dict] - [{host, port, username, password, domain, discovery_host_name, callback_ip, name}]
CONF_ACTIVE_SITE = "active_site"  # str - currently selected site name

# Defaults
DEFAULT_BROKER_PORT = 1883
DEFAULT_DOMAIN = "uninus"
DEFAULT_SUBSCRIBE_TOPIC = "ha/pubrsp/#"
DEFAULT_DISCOVERY_HOST_NAME = "urcon"
DEFAULT_REQUIRE_CONFIRM_DANGEROUS = True
DEFAULT_APPROVAL_WINDOW_SECONDS = 180

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
DATA_HOST_STATE = "host_state"
DATA_AUDIT_LOG = "audit_log"
DATA_APPROVALS = "approvals"

MAX_AUDIT_LOG = 300
HEALTH_STALE_SECONDS = 15 * 60
