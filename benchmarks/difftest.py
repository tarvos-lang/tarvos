"""Differential test harness: CPython vs Tarvos-native.

Positive cases must compile, build, run, and match CPython. Explicit rejection
cases must be valid Python and rejected by the native compiler. Build failures,
runtime failures, and harness failures are never skips.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
MATRIX = ROOT / "docs" / "compatibility.json"
PROJECT_ACCEPTANCE = ROOT / "benchmarks" / "project_acceptance.py"
WORK = ROOT / ".build-tmp" / "difftest"
EXE_SUFFIX = ".exe" if os.name == "nt" else ""
CLI = ROOT / "target" / "debug" / f"tarvos{EXE_SUFFIX}"
EXE = EXE_SUFFIX


class HarnessInfrastructureError(RuntimeError):
    """The test harness could not execute a required process."""


def run(cmd, cwd=None, timeout=180):
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
    except subprocess.TimeoutExpired as error:
        raise HarnessInfrastructureError(
            f"timed out after {timeout}s: {cmd!r}"
        ) from error
    except OSError as error:
        raise HarnessInfrastructureError(f"could not execute {cmd!r}: {error}") from error


def normalize(text: str) -> str:
    """Normalize only what is genuinely nondeterministic."""
    out = []
    for line in text.splitlines():
        if line.startswith("0x") and " at " in line:
            line = "<address>"
        out.append(line)
    return "\n".join(out)


def cpython(case: pathlib.Path) -> tuple[int, str, str]:
    proc = run([sys.executable, str(case)], cwd=case.parent, timeout=120)
    return proc.returncode, normalize(proc.stdout), normalize(proc.stderr)


def native(case: pathlib.Path, tag: str) -> tuple[str, str]:
    """Transpile and build; report compiler rejection separately from failures."""
    build_dir = WORK / tag.replace("/", "_")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    rust = build_dir / "main.rs"
    proc = run(
        [
            str(CLI),
            "build",
            str(case),
            "--source-only",
            "--strict-native",
            "-o",
            str(build_dir / "main.exe"),
        ],
        timeout=300,
    )
    if proc.returncode != 0:
        return "REJECTED", (proc.stdout + proc.stderr).strip()

    manifest = build_dir / "Cargo.toml"
    manifest.write_text(
        "[workspace]\n\n"
        "[package]\n"
        'name = "case"\n'
        'version = "0.0.0"\n'
        'edition = "2021"\n\n'
        "[[bin]]\n"
        'name = "case"\n'
        'path = "main.rs"\n\n'
        "[profile.release]\n"
        'panic = "abort"\n'
        "opt-level = 1\n",
        encoding="utf-8",
    )
    proc = run(
        ["cargo", "build", "--release", "--offline"],
        cwd=build_dir,
        timeout=600,
    )
    if proc.returncode != 0:
        return "RUSTC_FAILED", (proc.stdout + proc.stderr).strip()[-2000:]
    return "BUILT", ""


def run_native(tag: str) -> tuple[int, str, str]:
    case = CORPUS / (tag + ".py")
    build_dir = WORK / tag.replace("/", "_")
    exe = build_dir / "target" / "release" / f"case{EXE}"
    if not exe.exists():
        raise HarnessInfrastructureError(f"native artifact is missing: {exe}")
    proc = run([str(exe)], cwd=case.parent, timeout=60)
    return proc.returncode, normalize(proc.stdout), normalize(proc.stderr)


def compare(cpy, nat) -> tuple[bool, str]:
    ccode, cout, cerr = cpy
    ncode, nout, nerr = nat
    if ccode != ncode:
        return False, f"exit code: CPython={ccode} native={ncode}"
    if cout != nout:
        return False, f"stdout differs\n  CPython: {cout!r}\n  native : {nout!r}"
    if cerr != nerr:
        return False, f"stderr differs\n  CPython: {cerr!r}\n  native : {nerr!r}"
    return True, ""


def load_matrix() -> dict:
    try:
        return json.loads(MATRIX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HarnessInfrastructureError(
            f"cannot read compatibility evidence from {MATRIX}: {error}"
        ) from error


def selected_cases(matrix: dict) -> tuple[list[str], list[str]]:
    positives = {
        name
        for entry in matrix["features"]
        for name in entry.get("tests", [])
        if name != "project_acceptance"
    }
    rejections = {
        name
        for entry in matrix["features"]
        for name in entry.get("reject_tests", [])
    }
    if any(
        "project_acceptance" in entry.get("tests", [])
        for entry in matrix["features"]
    ):
        positives.add("project_acceptance")
    return sorted(positives), sorted(rejections)


def run_project_acceptance() -> tuple[str, str]:
    proc = run([sys.executable, str(PROJECT_ACCEPTANCE)], timeout=1800)
    if proc.returncode != 0:
        return "FAIL", (proc.stdout + proc.stderr).strip()[-2000:]
    return "PASS", (proc.stdout + proc.stderr).strip()[-1000:]


def run_case(name: str, expected_rejection: bool) -> tuple[str, str]:
    if name == "project_acceptance":
        if expected_rejection:
            return "FAIL", "project acceptance cannot be an expected rejection case"
        return run_project_acceptance()

    case = CORPUS / (name + ".py")
    try:
        source = case.read_text(encoding="utf-8-sig")
        compile(source, str(case), "exec")
    except (OSError, SyntaxError, UnicodeError) as error:
        return "FAIL", f"invalid differential fixture: {error}"

    try:
        cpy = cpython(case)
        status, detail = native(case, name)
        if expected_rejection:
            if status == "REJECTED":
                return "EXPECTED_REJECTION", detail
            if status == "RUSTC_FAILED":
                return "FAIL", f"Rust compilation failed (not a language rejection): {detail}"
            if status == "BUILT":
                native_result = run_native(name)
                matched, reason = compare(cpy, native_result)
                if matched:
                    return "FAIL", "unsupported case compiled and matched CPython"
                return "FAIL", f"unsupported case compiled with semantic difference: {reason}"
            return "INFRA_ERROR", detail

        if status == "REJECTED":
            return "FAIL", f"required native case was rejected: {detail}"
        if status == "RUSTC_FAILED":
            return "FAIL", f"Rust compilation failed: {detail}"
        if status != "BUILT":
            return "INFRA_ERROR", detail
        native_result = run_native(name)
        if native_result[0] != 0:
            return "FAIL", f"native program exited with status {native_result[0]}"
        matched, reason = compare(cpy, native_result)
        return ("PASS", "") if matched else ("FAIL", reason)
    except HarnessInfrastructureError as error:
        return "INFRA_ERROR", str(error)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--filter", default="", help="substring filter on case name")
    ap.add_argument("--keep", action="store_true", help="keep build dirs")
    ap.add_argument("--json", default="", help="write a JSON report here")
    args = ap.parse_args()

    if not CLI.exists():
        print(f"INFRA_ERROR: CLI not built: {CLI}", file=sys.stderr)
        return 2

    try:
        matrix = load_matrix()
        positive_cases, rejection_cases = selected_cases(matrix)
    except (HarnessInfrastructureError, KeyError, TypeError) as error:
        print(f"INFRA_ERROR: {error}", file=sys.stderr)
        return 2

    if args.filter:
        positive_cases = [name for name in positive_cases if args.filter in name]
        rejection_cases = [name for name in rejection_cases if args.filter in name]

    WORK.mkdir(parents=True, exist_ok=True)
    results = []
    counts = {
        "PASS": 0,
        "EXPECTED_REJECTION": 0,
        "FAIL": 0,
        "INFRA_ERROR": 0,
    }
    start = time.time()
    all_cases = [(name, False) for name in positive_cases] + [
        (name, True) for name in rejection_cases
    ]

    for name, expected_rejection in all_cases:
        verdict, detail = run_case(name, expected_rejection)
        counts[verdict] += 1
        results.append(
            {
                "name": name,
                "expected_rejection": expected_rejection,
                "verdict": verdict,
                "reason": detail,
            }
        )
        mark = "PASS" if verdict in {"PASS", "EXPECTED_REJECTION"} else verdict
        suffix = " (rejected as expected)" if verdict == "EXPECTED_REJECTION" else ""
        line = f"[{mark:14s}] {name}{suffix}"
        if verdict not in {"PASS", "EXPECTED_REJECTION"} and detail:
            line += f"  -- {detail.splitlines()[0]}"
        print(line, flush=True)

        if not args.keep and verdict in {"PASS", "EXPECTED_REJECTION"}:
            shutil.rmtree(WORK / name.replace("/", "_"), ignore_errors=True)

    elapsed = time.time() - start
    print("=" * 68)
    print(
        f"cases={len(all_cases)}  pass={counts['PASS']}  "
        f"expected_rejection={counts['EXPECTED_REJECTION']}  "
        f"fail={counts['FAIL']}  infra_error={counts['INFRA_ERROR']}  "
        f"{elapsed:.1f}s"
    )

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps({"counts": counts, "results": results}, indent=2),
            encoding="utf-8",
        )
    return 1 if counts["FAIL"] or counts["INFRA_ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main())
