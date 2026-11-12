import inspect

from orchestrator_agent.agent import _build_mediation_tool
from orchestrator_agent.settings import Settings


def test_mediation_tool_accepts_seller_name() -> None:
    tool = _build_mediation_tool(Settings(_env_file=None))
    parameters = inspect.signature(tool.func).parameters
    assert "seller_name" in parameters
    assert parameters["seller_name"].default is None
