from __future__ import annotations

import os

from gateway.__main__ import configure_adk_telemetry


def test_adk_message_content_capture_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", raising=False)

    configure_adk_telemetry()

    assert os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] == "false"


def test_explicit_capture_setting_is_respected(monkeypatch) -> None:
    monkeypatch.setenv("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "true")

    configure_adk_telemetry()

    assert os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] == "true"
