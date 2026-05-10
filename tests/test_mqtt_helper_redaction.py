import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

package_name = "custom_components.unircon"
package = types.ModuleType(package_name)
package.__path__ = [str(ROOT / "custom_components" / "unircon")]
sys.modules.setdefault(package_name, package)

from custom_components.unircon import mqtt_helper


def test_redact_command_payload_hides_token_only():
    payload = "/10112932/cmd/en/admin/uninus@99"

    redacted = mqtt_helper._redact_command_payload(payload)

    assert redacted == "/***/cmd/en/admin/uninus@99"
    assert "10112932" not in redacted


def test_redact_urcom_payload_hides_credentials_without_mutating_source():
    payload = {
        "host": "urcon",
        "user": "admin",
        "pass": "uninus@99",
        "type": 13,
        "ip": "192.168.1.226",
    }

    redacted = mqtt_helper._redact_urcom_payload(payload)

    assert redacted["user"] == "***"
    assert redacted["pass"] == "***"
    assert redacted["host"] == "urcon"
    assert payload["user"] == "admin"
    assert payload["pass"] == "uninus@99"
    assert "uninus@99" not in json.dumps(redacted)


def test_redact_urcom_payload_preserves_empty_values():
    payload = {"user": "", "pass": "", "host": "urcon"}

    redacted = mqtt_helper._redact_urcom_payload(payload)

    assert redacted == payload
    assert redacted is not payload


if __name__ == "__main__":
    test_redact_command_payload_hides_token_only()
    test_redact_urcom_payload_hides_credentials_without_mutating_source()
    test_redact_urcom_payload_preserves_empty_values()
    print("redaction tests ok")
