from __future__ import annotations

import subprocess
import sys


def test_litellm_is_imported_when_the_agent_module_loads() -> None:
    """ADK imports litellm lazily on the first LLM call.

    That import takes seconds on the free Render container and blocks the
    shared event loop, so it must be paid at process startup instead.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import orchestrator_agent.agent, sys; print('litellm' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "True"
