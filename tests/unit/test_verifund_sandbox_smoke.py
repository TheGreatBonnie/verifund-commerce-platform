from __future__ import annotations

import pytest

from scripts.verifund_sandbox_smoke import (
    SandboxSmokeConfig,
    smoke_config,
    wait_for_funding,
    wait_for_state,
)


class FakeSource:
    def __init__(self, states: list[str]) -> None:
        self.states = list(states)
        self.calls = 0

    def get_state(self, transaction_id: str) -> dict[str, object]:
        self.calls += 1
        if len(self.states) > 1:
            state = self.states.pop(0)
        else:
            state = self.states[0]
        return {"transaction_id": transaction_id, "state": state}


def test_smoke_config_requires_the_gate():
    with pytest.raises(RuntimeError, match="VERIFUND_SANDBOX_SMOKE"):
        smoke_config({"VERIFUND_MODE": "sandbox"})


def test_smoke_config_requires_sandbox_mode():
    with pytest.raises(RuntimeError, match="VERIFUND_MODE=sandbox"):
        smoke_config(
            {"VERIFUND_SANDBOX_SMOKE": "1", "VERIFUND_MODE": "fake"}
        )


def test_smoke_config_requires_an_ops_token():
    with pytest.raises(RuntimeError, match="VERIFUND_OPS_TOKEN"):
        smoke_config(
            {"VERIFUND_SANDBOX_SMOKE": "1", "VERIFUND_MODE": "sandbox"}
        )


def test_smoke_config_reads_overrides():
    config = smoke_config(
        {
            "VERIFUND_SANDBOX_SMOKE": "1",
            "VERIFUND_MODE": "sandbox",
            "VERIFUND_CONTROL_PLANE_URL": "https://control.example.com/",
            "VERIFUND_OPS_TOKEN": "ops-token",
            "VERIFUND_SANDBOX_RUN_ID": "run-sandbox",
            "VERIFUND_SANDBOX_FUND_TIMEOUT": "60",
            "VERIFUND_SANDBOX_POLL_SECONDS": "1.5",
        }
    )

    assert config == SandboxSmokeConfig(
        base_url="https://control.example.com",
        ops_token="ops-token",
        run_id="run-sandbox",
        fund_timeout_seconds=60.0,
        poll_seconds=1.5,
    )


def test_wait_for_state_returns_the_target_projection():
    source = FakeSource(["FUNDING_PENDING", "FUNDED"])

    result = wait_for_state(
        source,
        "vf_1",
        target="FUNDED",
        timeout=5,
        poll_seconds=0,
        stop_states={"CANCELED"},
    )

    assert result["state"] == "FUNDED"
    assert source.calls == 2


def test_wait_for_funding_stops_on_canceled():
    with pytest.raises(RuntimeError, match="CANCELED"):
        wait_for_funding(
            FakeSource(["CANCELED"]), "vf_1", timeout=5, poll_seconds=0
        )


def test_wait_for_state_times_out():
    with pytest.raises(TimeoutError, match="FUNDED"):
        wait_for_state(
            FakeSource(["FUNDING_PENDING"]),
            "vf_1",
            target="FUNDED",
            timeout=0.01,
            poll_seconds=0,
            stop_states={"CANCELED", "FAILED"},
        )
