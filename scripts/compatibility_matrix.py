"""Generate and verify the machine-readable compatibility matrix.

`docs/compatibility.json` is the single source of truth for what Tarvos
supports. This script regenerates it and verifies that every entry claiming
coverage names a differential case that actually exists, so the matrix cannot
claim more than the corpus proves.

    python scripts/compatibility_matrix.py --write
    python scripts/compatibility_matrix.py --check
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
MATRIX = ROOT / "docs" / "compatibility.json"
VERSION = "1.3.1"


def workspace_version() -> str | None:
    """Read the version from the workspace manifest.

    Kept in step with Cargo.toml so the matrix cannot describe a release that
    does not exist. Returns None when the manifest cannot be read, in which case
    the check is skipped rather than guessed.
    """
    import re

    manifest = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"', manifest)
    return match.group(1) if match else None

# (category, feature, status, tests, note)
# status: supported | partial | unsupported | planned
ROWS: list[tuple[str, str, str, list[str], str]] = [
    # --- language basics -------------------------------------------------
    ("syntax", "variables and assignment", "supported", ["03_integer", "19_scope"], ""),
    ("syntax", "arithmetic + - * / // % **", "supported", ["03_integer"], ""),
    ("syntax", "floats", "supported", ["04_float"], ""),
    ("syntax", "comparisons", "supported", ["06_comparison"], ""),
    ("syntax", "boolean logic and/or", "partial", ["06_comparison"],
     "Non-bool operands are rejected: Python returns an operand, not a bool. Use bool()."),
    ("syntax", "f-strings", "partial", ["52_native_features"],
     "Literal parts and simple interpolation; a dynamic format spec is rejected."),
    ("syntax", "ternary expression", "supported", ["52_native_features"], ""),
    ("syntax", "pass statement", "supported", ["51_pass"], ""),
    ("syntax", "membership (in/not in)", "supported", ["50_membership"], ""),
    ("syntax", "list comprehension", "partial", ["52_native_features"], "Single generator only."),
    ("syntax", "heterogeneous ternary branches", "unsupported", [],
     "The native IR does not yet represent branch values with different Rust types."),
    ("syntax", "classes", "unsupported", [],
     "The default Ruff front end does not lower class definitions; the alternate "
     "AST path has not been validated as a production route."),
    ("syntax", "lambda", "unsupported", [], "Parsed by the front end, not lowered natively."),
    ("syntax", "generators / decorators / async", "unsupported", [],
     "Not lowered natively; the front end rejects them."),
    ("syntax", "global/nonlocal/del", "unsupported", [],
     "Scope mutation and deletion are rejected because the native IR does not model them."),
    # --- control flow ----------------------------------------------------
    ("control_flow", "if / elif / else", "supported", ["08_control_flow"], ""),
    ("control_flow", "while", "supported", ["08_control_flow"], ""),
    ("control_flow", "for", "supported", ["08_control_flow", "22_data_pipeline"], ""),
    ("control_flow", "break / continue", "supported", ["08_control_flow"], ""),
    ("control_flow", "nested control flow", "supported", ["08_control_flow", "19_scope"], ""),
    ("control_flow", "for-else / while-else", "unsupported", [],
     "Loop else suites are rejected because the current IR does not preserve them."),
    # --- functions -------------------------------------------------------
    ("functions", "definition and calls", "supported", ["19_scope"], ""),
    ("functions", "multiple return paths", "supported", ["19_scope"], ""),
    ("functions", "default and annotated parameters", "partial", ["52_native_features"],
     "Annotated parameters are exercised; default arguments are explicitly rejected."),
    ("functions", "*args / **kwargs", "unsupported", [], "A variadic call signature is not modelled in the IR."),
    ("functions", "recursion", "supported", ["52_native_features"], ""),
    # --- collections -----------------------------------------------------
    ("collections", "list literals and methods", "supported", ["12_lists"], ""),
    ("collections", "empty list", "supported", ["12_lists"], ""),
    ("collections", "negative indexing", "supported", ["13_indexing"], ""),
    ("collections", "list conversion list(...)", "partial", ["14_list_conversion"],
     "list, tuple, range, str sources. dict is rejected: HashMap order is not Python insertion order."),
    ("collections", "tuple", "supported", ["52_native_features"], ""),
    ("collections", "dict", "partial", ["52_native_features"],
     "Homogeneous values, key access, and mutation are supported. Heterogeneous values are rejected; insertion order is not preserved."),
    ("collections", "set", "unsupported", [], "Set literals are rejected because the native backend has no set runtime."),
    ("collections", "slicing", "partial", ["52_native_features"], "Slices without an explicit step; any slice step is rejected."),
    # --- strings ---------------------------------------------------------
    ("strings", "concatenation, length, indexing", "supported", ["13_indexing", "17_strings"], ""),
    ("strings", "str methods", "supported", ["17_strings"], ""),
    ("strings", "unicode indexing", "supported", ["13_indexing"], "Indexed by character, not byte."),
    # --- integers / floats -----------------------------------------------
    ("integers", "bounded native arithmetic", "supported", ["03_integer"], ""),
    ("integers", "arbitrary precision", "unsupported", [],
     "Runtime integers are i64. Compile-time reductions widen to u128, but a runtime value cannot exceed i64."),
    ("integers", "floored modulo and division", "supported", ["03_integer"], ""),
    ("integers", "true division yields float", "supported", ["03_integer", "04_float"], ""),
    ("integers", "bitwise and shift", "supported", ["03_integer"], ""),
    ("integers", "numeric promotion int/float", "supported", ["03_integer", "04_float"],
     "Promoted by the inferred result type, not by scattered casts in codegen."),
    ("conversions", "int() and float() from str", "supported", ["04_float"],
     "Parses the string and raises ValueError when it cannot; Rust's `as` cannot convert a String at all."),
    ("conversions", "int()/float()/str() from scalars", "supported", ["04_float"],
     "Type-directed: a bool becomes True/False, an integral float keeps its .0."),
    ("conversions", "bool() truthiness", "supported", ["04_float"],
     "Emptiness for str/list/dict, zero for numbers; a single named operation rather than `!= 0` per type."),
    ("iterators", "sum()", "supported", ["43_sum_iteration"], ""),
    # --- modules and packages --------------------------------------------
    ("imports", "from module import name", "supported", ["project_acceptance"], "Project acceptance fixture."),
    ("imports", "from package import submodule", "supported", ["project_acceptance"],
     "Direct and qualified call forms. Project acceptance fixture."),
    ("imports", "relative imports", "partial", ["project_acceptance"],
     "Resolved against the importing module's package; more dots than depth is rejected."),
    ("imports", "import *", "unsupported", [], "The exported name set is not statically known."),
    ("imports", "import module (bare)", "partial", ["52_native_features"], "Stdlib only: math, time, os, os.path, json."),
    ("imports", "dynamic import (importlib)", "unsupported", [], "The module cannot be resolved statically."),
    ("imports", "circular imports", "unsupported", [], "Reported rather than mis-inlined."),
    # --- exceptions ---------------------------------------------------------
    # `41_exceptions` compares caught/uncaught, typed and bare handlers, `else`,
    # `finally`, nesting, propagation, and superclass matching against CPython.
    ("exceptions", "try / except", "supported", ["41_exceptions"],
     "Compiles to a labelled block holding a real Result, not a caught panic. A "
     "closure was rejected because its `let` bindings would leave scope, so a "
     "variable assigned inside the try would be missing after it."),
    ("exceptions", "except <Type>", "supported", ["41_exceptions"],
     "Matches the Python hierarchy, so `except ValueError` catches a "
     "StatisticsError. Handlers are tried in order and an unmatched one "
     "propagates to the enclosing try."),
    ("exceptions", "except ... as <name>", "supported", ["41_exceptions"],
     "Binds the exception message, which is what str(e) yields for the error "
     "classes the native backend raises."),
    ("exceptions", "else", "supported", ["41_exceptions"],
     "Runs only when the body completed normally, never after a raise and never "
     "after a return that left the try."),
    ("exceptions", "finally", "supported", ["41_exceptions"],
     "Runs on every path: normal completion, a caught exception, and a return "
     "from inside the try, which is deferred so finally still runs."),
    ("exceptions", "raise", "supported", ["41_exceptions"],
     "Propagates from a function through the caller's try. A function that can "
     "raise returns a Result and its call sites unwrap it."),
    ("exceptions", "nested try", "supported", ["41_exceptions"],
     "An uncaught inner error propagates after the inner finally has run."),
    ("exceptions", "bare raise / re-raise", "unsupported", [],
     "A native error is not a first-class exception object, so the active "
     "exception cannot yet be re-raised faithfully."),
    ("exceptions", "exception attributes (args, __class__)", "unsupported", [],
     "The native error is a class name plus a message; a raised exception is not "
     "a first-class value with attributes."),
    ("exceptions", "str(KeyError) quoting", "unsupported", [],
     "KeyError's per-class string representation is not modeled; explicit "
     "KeyError raises are rejected rather than misreported."),
    ("exceptions", "break / continue inside try inside a loop", "unsupported", [],
     "Not lowered. Reported rather than miscompiled, because a plain Rust break "
     "would skip finally."),
    ("language", "keyword arguments", "partial", ["52_native_features"],
     "Known user-function parameters can be passed by name. Keyword expansion, "
     "unknown signatures, duplicate values, and print keywords are rejected."),
    ("language", "print sep/end", "unsupported", [],
     "print() keyword arguments are rejected rather than silently discarded."),
    # --- stdlib ------------------------------------------------------------
    ("stdlib", "math", "supported", ["52_native_features"], ""),
    ("stdlib", "time", "supported", ["52_native_features"], ""),
    ("stdlib", "json", "supported", ["52_native_features"], "dumps only; loads is unsupported."),
    ("stdlib", "json.dumps on a literal", "supported", ["52_native_features"], "Rendered during lowering; no runtime needed."),
    ("stdlib", "json.dumps on a runtime value", "partial", ["04_float", "52_native_features"],
     "Serializes int, float, bool, str, list, and dict. A dict must have one "
     "value type, so heterogeneous values are rejected. A HashMap cannot "
     "reproduce Python insertion order, so keys are emitted sorted."),
    ("stdlib", "os / os.path", "partial", ["52_native_features", "53_os_listdir"],
     "Selected path operations and os.listdir are supported; os.environ is rejected."),
    # statistics. `40_statistics` compares 35 output lines against CPython for
    # int, float, negative, zero, repeated, singleton, and odd/even-length data.
    ("stdlib", "statistics.mean / fmean", "supported", ["40_statistics"],
     "mean reduces through exact integer arithmetic and returns an int when all "
     "input is int and the quotient is whole, matching CPython; fmean always "
     "returns a float."),
    ("stdlib", "statistics.harmonic_mean / geometric_mean", "supported", ["40_statistics"],
     "geometric_mean reduces through logarithms, matching CPython's accuracy. "
     "harmonic_mean returns 0 as soon as it sees a zero, as CPython does, rather "
     "than raising."),
    ("stdlib", "statistics.median", "supported", ["40_statistics"],
     "Odd-length input returns the middle element with its original type, so an "
     "int list yields an int; even-length input returns a float."),
    ("stdlib", "statistics.median_low / median_high", "supported", ["40_statistics"],
     "Return an element of the input, preserving int vs float."),
    ("stdlib", "statistics.mode / multimode", "supported", ["40_statistics"],
     "Return input elements; multimode preserves CPython's first-appearance order."),
    ("stdlib", "statistics.pvariance / pstdev", "supported", ["40_statistics"],
     "pstdev requires at least one data point; pvariance of a singleton is 0.0."),
    ("stdlib", "statistics.variance / stdev", "supported", ["40_statistics"],
     "variance and stdev require at least two data points, as in CPython."),
    ("stdlib", "statistics.median_grouped / quantiles / correlation / covariance / "
     "linear_regression", "partial", ["42_statistics_paired"],
     "median_grouped follows the CPython 3.13 formulation: it finds the value at "
     "the midpoint, counts the points at or below it, then interpolates across "
     "the class interval. The older 'nudge the two central values' algorithm "
     "disagrees whenever the median value is repeated. quantiles implements "
     "CPython's exact integer rescaling (j = i*m//n, delta = i*m - j*n), which "
     "deliberately extrapolates outside the observed range. correlation, "
     "covariance, and linear_regression validate pair length, minimum sample "
     "size, and constant input."),
    ("stdlib", "statistics.quantiles n= / method=", "unsupported", [],
     "CPython declares n and method keyword-only, and the native backend does "
     "not yet lower keyword arguments, so only the default n=4, "
     "method='exclusive' form is reachable natively."),
    ("stdlib", "statistics.linear_regression result attributes", "partial",
     ["42_statistics_paired"],
     "Returns (slope, intercept) as a 2-tuple. CPython returns a "
     "LinearRegression named tuple, so `result.slope` is not yet available; use "
     "result[0] and result[1]."),
    ("stdlib", "statistics.StatisticsError", "supported", ["41_exceptions"],
     "Catchable. Every statistics call reports an empty sequence, a too-small "
     "sample, and a negative geometric product through a Result carrying the "
     "StatisticsError class, and `except ValueError` catches it because "
     "StatisticsError is a ValueError subclass in CPython."),
    ("stdlib", "collections / itertools / functools", "unsupported", [], "Not in the supported stdlib list."),
    ("stdlib", "file I/O (open)", "unsupported", [], "No filesystem runtime is emitted into generated code."),
    ("stdlib", "dataclasses / enum / typing", "unsupported", [], "Not lowered natively; annotations are parsed but not enforced."),
    # --- numerical ecosystem ----------------------------------------------
    ("numpy", "ndarray", "unsupported", [],
     "No implementation. Future compatibility target; no claim is made."),
    ("pandas", "DataFrame", "unsupported", [],
     "No implementation. Future compatibility target; no claim is made."),
    ("pytorch", "Tensor", "unsupported", [],
     "No implementation. Future compatibility target; no claim is made."),
    # --- concurrency / io --------------------------------------------------
    ("concurrency", "threading / multiprocessing", "unsupported", [], "Generated code is single-threaded."),
    ("concurrency", "asyncio", "unsupported", [], "The event loop has no native equivalent here."),
    ("networking", "socket / http", "unsupported", [], "No network runtime is emitted into generated code."),
    ("serialization", "pickle", "unsupported", [], "Depends on CPython object layout, which is not reproduced."),
    # --- project builds ----------------------------------------------------
    ("project", "single file compilation", "supported", ["03_integer", "10_range"], ""),
    ("project", "multi-module project compilation", "supported", ["project_acceptance"], "Project acceptance fixture."),
    ("project", "package directories with __init__.py", "supported", ["project_acceptance"], ""),
    ("project", "entry point selection (--entry)", "supported", ["project_acceptance"], ""),
    ("project", "Cargo project export", "supported", ["project_acceptance"], ""),
    ("project", "pyproject.toml metadata", "unsupported", [],
     "Present on disk but not consumed. No dependency resolution is performed."),
    ("project", "tarvos.toml manifest", "planned", [],
     "Not introduced; deliberately avoided until a real need is demonstrated."),
    ("project", "resource bundling", "unsupported", [], "Assets are not embedded; open() is unsupported."),
]

VALID_STATUS = {"supported", "partial", "unsupported", "planned"}

REJECTION_TESTS: dict[str, list[str]] = {
    "syntax.boolean-logic-and-or": ["rejects/non_bool_short_circuit"],
    "syntax.f-strings": ["rejects/dynamic_fstring_spec"],
    "syntax.heterogeneous-ternary-branches": ["rejects/heterogeneous_ternary"],
    "syntax.list-comprehension": ["rejects/listcomp_tuple_target"],
    "syntax.classes": ["rejects/class_definition", "rejects/class_inheritance"],
    "syntax.generators-decorators-async": [
        "rejects/async_function",
        "rejects/function_decorator",
        "rejects/escaping_generator",
    ],
    "syntax.global-nonlocal-del": [
        "rejects/global_declaration",
        "rejects/nonlocal_declaration",
        "rejects/delete_statement",
    ],
    "syntax.lambda": ["rejects/lambda_value"],
    "control_flow.for-else-while-else": ["rejects/loop_else"],
    "functions.default-and-annotated-parameters": ["rejects/default_parameter"],
    "collections.list-conversion-list": ["rejects/list_from_dict"],
    "collections.set": ["rejects/set_literal"],
    "collections.dict": ["rejects/heterogeneous_dict"],
    "collections.slicing": ["rejects/slice_step"],
    "imports.relative-imports": ["rejects/deep_relative_import"],
    "imports.import-module-bare": ["rejects/unsupported_bare_import"],
    "exceptions.bare-raise-re-raise": ["rejects/bare_raise"],
    "exceptions.str-keyerror-quoting": ["rejects/keyerror_string"],
    "exceptions.break-continue-inside-try-inside-a-loop": ["rejects/break_in_try_loop"],
    "language.keyword-arguments": ["rejects/kwargs_expansion"],
    "language.print-sep-end": ["rejects/print_sep", "rejects/print_end"],
    "stdlib.json-dumps-on-a-runtime-value": ["rejects/heterogeneous_dict"],
    "stdlib.os-os-path": ["rejects/os_environ"],
    "stdlib.statistics-median-grouped-quantiles-correlation-covariance-linear-regression": [
        "rejects/statistics_quantiles_keyword"
    ],
    "stdlib.statistics-linear-regression-result-attributes": [
        "rejects/regression_result_attribute"
    ],
    "stdlib.statistics-quantiles-n-method": [
        "rejects/statistics_quantiles_keyword"
    ],
}

MARKDOWN_START = "<!-- compatibility-matrix:start -->"
MARKDOWN_END = "<!-- compatibility-matrix:end -->"


def feature_id(category: str, feature: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", feature.lower()).strip("-")
    return f"{category}.{slug}"


def build() -> dict:
    features = []
    for category, feature, status, tests, note in ROWS:
        identifier = feature_id(category, feature)
        entry = {
            "id": identifier,
            "category": category,
            "feature": feature,
            "status": status,
            "tests": tests,
        }
        rejection_tests = REJECTION_TESTS.get(identifier, [])
        if rejection_tests:
            entry["reject_tests"] = rejection_tests
        if note:
            entry["note"] = note
        features.append(entry)
    return {
        "schema": 1,
        "tarvos_version": VERSION,
        "note": (
            "Generated by scripts/compatibility_matrix.py. Do not edit by hand. "
            "'supported' means a differential case compares CPython against a "
            "compiled native executable; the case is named in 'tests'."
        ),
        "features": features,
    }


def verify(matrix: dict) -> list[str]:
    """Check the matrix against the rules it claims to enforce."""
    problems: list[str] = []
    available = {
        path.relative_to(CORPUS).with_suffix("").as_posix()
        for path in CORPUS.rglob("*.py")
    }
    available.add("project_acceptance")
    identifiers: set[str] = set()

    for entry in matrix["features"]:
        status = entry.get("status")
        label = entry.get("feature", "<unnamed>")
        identifier = entry.get("id", "<missing>")
        expected_id = feature_id(entry.get("category", ""), label)
        if identifier != expected_id:
            problems.append(f"{label}: feature id {identifier!r} must be {expected_id!r}")
        if identifier in identifiers:
            problems.append(f"{label}: duplicate feature id {identifier!r}")
        identifiers.add(identifier)
        if status not in VALID_STATUS:
            problems.append(f"{label}: invalid status {status!r}")
            continue
        if status in {"unsupported", "planned"} and not entry.get("note"):
            problems.append(f"{label}: {status} without an explanatory note")
        tests = entry.get("tests", [])
        reject_tests = entry.get("reject_tests", [])
        if status in {"supported", "partial"} and not tests:
            problems.append(f"{label}: {status} feature has no positive differential test")
        if status == "partial" and not reject_tests:
            problems.append(f"{label}: partial feature has no explicit rejection test")
        if any(name.startswith("rejects/") for name in tests):
            problems.append(f"{label}: rejection fixture cannot be positive evidence")
        if any(not name.startswith("rejects/") for name in reject_tests):
            problems.append(f"{label}: rejection evidence must use tests/corpus/rejects/")
        if "project_acceptance" in reject_tests:
            problems.append(f"{label}: project_acceptance cannot be a rejection test")
        for name in [*tests, *reject_tests]:
            if name not in available:
                if name == "project_acceptance":
                    problems.append(f"{label}: project_acceptance runner is missing")
                else:
                    problems.append(
                        f"{label}: claims test {name!r} but "
                        f"tests/corpus/{name}.py does not exist"
                    )

    for identifier in REJECTION_TESTS:
        if not any(entry.get("id") == identifier for entry in matrix["features"]):
            problems.append(f"rejection evidence references unknown feature id {identifier!r}")

    # The matrix must describe the version the workspace is actually on.
    current = workspace_version()
    if current is not None and matrix["tarvos_version"] != current:
        problems.append(
            f"matrix targets version {matrix['tarvos_version']!r} but the workspace "
            f"is {current!r}; update VERSION in this script"
        )
    return problems


def markdown_block(matrix: dict) -> str:
    features = matrix["features"]
    counts = {
        status: sum(entry["status"] == status for entry in features)
        for status in sorted(VALID_STATUS)
    }
    lines = [
        MARKDOWN_START,
        f"{len(features)} classified features: "
        + ", ".join(f"**{counts[status]} {status}**" for status in sorted(counts))
        + ".",
        "",
        "| ID | Category | Feature | Status | Evidence |",
        "|---|---|---|---|---|",
    ]
    for entry in features:
        evidence = []
        if entry["tests"]:
            evidence.append("parity: " + ", ".join(f"`{name}`" for name in entry["tests"]))
        if entry.get("reject_tests"):
            evidence.append(
                "rejection: "
                + ", ".join(f"`{name}`" for name in entry["reject_tests"])
            )
        lines.append(
            f"| `{entry['id']}` | {entry['category']} | {entry['feature']} | "
            f"{entry['status']} | {'; '.join(evidence) or '—'} |"
        )
    lines.append(MARKDOWN_END)
    return "\n".join(lines)


def update_markdown(text: str, block: str) -> str:
    if MARKDOWN_START in text and MARKDOWN_END in text:
        start = text.index(MARKDOWN_START)
        end = text.index(MARKDOWN_END, start) + len(MARKDOWN_END)
        return text[:start] + block + text[end:]
    marker = "## Current summary\n"
    if marker not in text:
        raise ValueError("docs/COMPATIBILITY.md is missing the current summary section")
    start = text.index(marker) + len(marker)
    end = text.find("\n## ", start)
    if end == -1:
        end = len(text)
    return text[:start] + block + "\n" + text[end:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="regenerate the file")
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args()

    matrix = build()
    problems = verify(matrix)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1

    if args.write:
        MATRIX.parent.mkdir(parents=True, exist_ok=True)
        MATRIX.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
        doc = ROOT / "docs" / "COMPATIBILITY.md"
        doc.write_text(
            update_markdown(doc.read_text(encoding="utf-8"), markdown_block(matrix)),
            encoding="utf-8",
        )
        print(f"wrote {MATRIX.relative_to(ROOT)} ({len(matrix['features'])} features)")
    if args.check:
        if not MATRIX.exists():
            print("ERROR: docs/compatibility.json is missing", file=sys.stderr)
            return 1
        if json.loads(MATRIX.read_text(encoding="utf-8")) != matrix:
            print("ERROR: docs/compatibility.json is stale; run --write", file=sys.stderr)
            return 1
        doc = ROOT / "docs" / "COMPATIBILITY.md"
        expected_doc = update_markdown(doc.read_text(encoding="utf-8"), markdown_block(matrix))
        if expected_doc != doc.read_text(encoding="utf-8"):
            print("ERROR: docs/COMPATIBILITY.md matrix is stale; run --write", file=sys.stderr)
            return 1
        print("compatibility matrix is current")
    if not args.write and not args.check:
        counts: dict[str, int] = {}
        for entry in matrix["features"]:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        print(f"{len(matrix['features'])} features: "
              + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
