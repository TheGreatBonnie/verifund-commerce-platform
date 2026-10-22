import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_forbidden_runtime_references():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_standalone.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
