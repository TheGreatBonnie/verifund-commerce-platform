"""Reject runtime references to the parent Verifund backend."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORTS = (
    re.compile(r"^\s*(from|import)\s+verifund(\.|\s|$)"),
    re.compile(r"^\s*(from|import)\s+verifund_platform_backend(\.|\s|$)"),
    re.compile(r"^\s*(from|import)\s+src\.verifund(\.|\s|$)"),
)
FORBIDDEN_PATH_FRAGMENTS = (
    "verifund-platform-backend",
    "../verifund-platform-backend",
    "/verifund-platform-backend/",
)
SKIP_PREFIXES = (
    "docs/",
    "data/",
    "apps/console/.next/",
    "apps/console/node_modules/",
    ".venv/",
    "uv.lock",
)
# These files necessarily contain the forbidden patterns as test fixtures and
# guard definitions; they are not runtime code.
SKIP_FILES = {
    "scripts/check_standalone.py",
    "tests/test_standalone.py",
}
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
    ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".woff",
    ".woff2", ".ttf", ".zip", ".gz",
}


def scan_text(name: str, text: str) -> list[str]:
    if name.startswith(SKIP_PREFIXES) or Path(name).suffix.lower() in BINARY_SUFFIXES:
        return []
    findings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in FORBIDDEN_IMPORTS:
            if pattern.search(line):
                findings.append(f"{name}:{line_number}: parent backend import")
        for fragment in FORBIDDEN_PATH_FRAGMENTS:
            if fragment in line:
                findings.append(f"{name}:{line_number}: parent backend path")
    return findings


def main() -> int:
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        text=True,
    ).splitlines()
    findings: list[str] = []
    for name in files:
        if name in SKIP_FILES:
            continue
        path = Path(name)
        if not path.is_file():
            continue
        if name.startswith(SKIP_PREFIXES) or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        findings.extend(scan_text(name, text))
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
