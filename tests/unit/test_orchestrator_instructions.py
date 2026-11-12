from __future__ import annotations

from pathlib import Path

from orchestrator_agent import agent

ROOT = Path(__file__).resolve().parents[2]
CONSOLE_INSTRUCTION = ROOT / "apps" / "console" / "app" / "api" / "copilotkit" / "[[...slug]]" / "route.ts"

# Both instruction blocks must describe the same retrieval contract: the
# middleware appends its copy after the agent's, so drift changes behavior.
DENSE_RETRIEVAL_ANCHORS = (
    "natural language",
    "hard filters",
    "influence ranking",
    "product type",
    "no matches were found",
    "retrieval_unavailable",
    "marketplace_unavailable",
    "raw similarity scores",
)


def test_agent_instruction_describes_dense_retrieval_behavior():
    instruction = agent.MARKETMESH_ORCHESTRATOR_INSTRUCTION

    for anchor in DENSE_RETRIEVAL_ANCHORS:
        assert anchor in instruction, f"missing guidance: {anchor}"
    assert "filler" not in instruction.casefold()


def test_console_instruction_stays_aligned_with_the_agent():
    source = CONSOLE_INSTRUCTION.read_text(encoding="utf-8")

    for anchor in DENSE_RETRIEVAL_ANCHORS:
        assert anchor in source, f"console instruction is missing: {anchor}"
    assert "filler" not in source.casefold()
