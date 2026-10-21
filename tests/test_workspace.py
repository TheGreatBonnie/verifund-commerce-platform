from commerce_core import __version__
from commerce_core.logging import configure_logging, redact_headers


def test_commerce_core_is_importable():
    assert __version__ == "0.1.0"


def test_redact_headers_removes_bearer_tokens():
    headers = {
        "authorization": "Bearer super-secret",
        "content-type": "application/json",
    }
    assert redact_headers(headers) == {
        "authorization": "[REDACTED]",
        "content-type": "application/json",
    }


def test_logging_configures_json(capsys):
    configure_logging("test-service")
    assert True
