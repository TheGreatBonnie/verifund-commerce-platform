"""Fail when runtime files reference unrelated platform code or payment flows."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FORBIDDEN = (
    "veri" + "fund",
    "transaction coordinator",
    "escrow",
    "payment intent",
    "stripe",
)

ALLOWED = {
    "docs/superpowers/specs/2026-10-21-marketmesh-a2a-commerce-design.md",
    "scripts/check_standalone.py",
    "tests/test_standalone.py",
}


def main() -> int:
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        text=True,
    ).splitlines()
    offenders: list[tuple[str, str]] = []
    for name in files:
        if name in ALLOWED or name.startswith("docs/"):
            continue
        path = Path(name)
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore").lower()
        except OSError:
            continue
        for word in FORBIDDEN:
            if word in text:
                offenders.append((name, word))
    if not offenders:
        print("standalone check passed")
        return 0
    for name, word in offenders:
        print(f"{name}: forbidden reference {word!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
