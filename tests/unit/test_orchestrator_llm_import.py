from __future__ import annotations

import subprocess
import sys


def test_litellm_completion_path_is_warm_when_the_agent_module_loads() -> None:
    """Both litellm and its deferred acompletion helper block the loop.

    ADK imports litellm lazily on the first LLM call, and litellm in turn
    imports its GitHub Copilot auth helper inside acompletion. Each import
    takes seconds on the free Render container, so both are paid at startup.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import orchestrator_agent.agent, sys; "
                "print('litellm' in sys.modules, "
                "'litellm.llms.github_copilot.per_user_auth' in sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "True True"
