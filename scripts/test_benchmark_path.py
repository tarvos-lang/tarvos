#!/usr/bin/env python3
"""Verify benchmark PATH sanitization retains trusted system tool directories."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmarks.common import resolve_tool_path, sanitize_environment, safe_tool_roots


def main() -> int:
    if os.name == "nt":
        system_bin = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    else:
        system_bin = Path("/usr/bin")
    if not system_bin.is_dir():
        raise RuntimeError(f"expected system tool directory does not exist: {system_bin}")
    system_bin = system_bin.resolve()
    if not any(root == system_bin or root in system_bin.parents for root in safe_tool_roots()):
        raise AssertionError(f"system tool directory is not trusted: {system_bin}")

    with tempfile.TemporaryDirectory() as unsafe_dir:
        env = sanitize_environment(
            {"PATH": os.pathsep.join([unsafe_dir, str(system_bin)])}
        )
        entries = {
            Path(entry).resolve()
            for entry in env["PATH"].split(os.pathsep)
            if entry
        }
        if system_bin not in entries:
            raise AssertionError(f"sanitized PATH dropped {system_bin}")
        if Path(unsafe_dir).resolve() in entries:
            raise AssertionError("sanitized PATH retained an untrusted temporary directory")

    if os.name != "nt" and resolve_tool_path("cc") is None:
        raise AssertionError("system cc is installed but unavailable through safe PATH resolution")

    print("benchmark PATH safety checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
