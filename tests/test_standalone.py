import subprocess
import sys
from pathlib import Path

from scripts.check_standalone import scan_text

ROOT = Path(__file__).resolve().parents[1]


def test_repository_has_no_parent_backend_references():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_standalone.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_guard_allows_verifund_names():
    assert scan_text(
        "apps/verifund_control_plane/app.py",
        "from verifund_contracts.models import AwardRequest\n"
        "import verifund_control_plane.settings\n",
    ) == []


def test_guard_rejects_parent_imports():
    assert scan_text(
        "apps/buyer_agent/settlement.py",
        "from verifund.platform import money\n",
    )
    assert scan_text(
        "apps/buyer_agent/settlement.py",
        "from verifund_platform_backend.services import capture\n",
    )
    assert scan_text(
        "apps/buyer_agent/settlement.py",
        "import src.verifund.ledger\n",
    )


def test_guard_rejects_parent_paths():
    assert scan_text(
        "Makefile",
        "PYTHONPATH=../verifund-platform-backend\n",
    )


def test_guard_ignores_binary_and_generated_paths():
    assert scan_text("data/verifund.db", "verifund-platform-backend") == []
    assert scan_text("apps/console/.next/trace", "verifund-platform-backend") == []
