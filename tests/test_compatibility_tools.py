import importlib.util
import ast
import pathlib
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


matrix_tools = load_module(
    "tarvos_compatibility_matrix", ROOT / "scripts" / "compatibility_matrix.py"
)
difftest = load_module("tarvos_difftest", ROOT / "benchmarks" / "difftest.py")
ast_export = load_module("tarvos_ast_export", ROOT / "python" / "ast_export.py")


class CompatibilityMatrixTests(unittest.TestCase):
    def test_generated_matrix_has_positive_and_rejection_evidence(self):
        self.assertEqual(matrix_tools.verify(matrix_tools.build()), [])

    def test_duplicate_feature_identifier_is_rejected(self):
        matrix = matrix_tools.build()
        matrix["features"][1]["id"] = matrix["features"][0]["id"]
        self.assertTrue(
            any("duplicate feature id" in item for item in matrix_tools.verify(matrix))
        )

    def test_supported_feature_without_test_mapping_is_rejected(self):
        matrix = matrix_tools.build()
        supported = next(item for item in matrix["features"] if item["status"] == "supported")
        supported["tests"] = []
        self.assertTrue(
            any("no positive differential test" in item for item in matrix_tools.verify(matrix))
        )

    def test_partial_feature_without_rejection_mapping_is_rejected(self):
        matrix = matrix_tools.build()
        partial = next(item for item in matrix["features"] if item["status"] == "partial")
        partial.pop("reject_tests", None)
        self.assertTrue(
            any("no explicit rejection test" in item for item in matrix_tools.verify(matrix))
        )


class DifferentialGateTests(unittest.TestCase):
    def test_expected_compiler_rejection_passes(self):
        with patch.object(difftest, "cpython", return_value=(0, "", "")), patch.object(
            difftest, "native", return_value=("REJECTED", "unsupported")
        ):
            verdict, _ = difftest.run_case("rejects/bare_raise", True)
        self.assertEqual(verdict, "EXPECTED_REJECTION")

    def test_compiler_rejection_fails_required_positive_case(self):
        with patch.object(difftest, "cpython", return_value=(0, "", "")), patch.object(
            difftest, "native", return_value=("REJECTED", "unsupported")
        ):
            verdict, _ = difftest.run_case("52_native_features", False)
        self.assertEqual(verdict, "FAIL")

    def test_rust_build_failure_is_not_an_expected_language_rejection(self):
        with patch.object(difftest, "cpython", return_value=(0, "", "")), patch.object(
            difftest, "native", return_value=("RUSTC_FAILED", "rustc error")
        ):
            verdict, _ = difftest.run_case("rejects/bare_raise", True)
        self.assertEqual(verdict, "FAIL")

    def test_native_runtime_failure_is_a_failure(self):
        with patch.object(difftest, "cpython", return_value=(0, "", "")), patch.object(
            difftest, "native", return_value=("BUILT", "")
        ), patch.object(difftest, "run_native", return_value=(1, "", "panic")):
            verdict, _ = difftest.run_case("52_native_features", False)
        self.assertEqual(verdict, "FAIL")

    def test_harness_failure_is_distinguished(self):
        with patch.object(
            difftest,
            "cpython",
            side_effect=difftest.HarnessInfrastructureError("python unavailable"),
        ):
            verdict, _ = difftest.run_case("52_native_features", False)
        self.assertEqual(verdict, "INFRA_ERROR")


class PythonAstExporterTests(unittest.TestCase):
    def export(self, source):
        return ast_export.PythonAstExporter().visit(ast.parse(source))

    def test_relative_import_level_is_preserved(self):
        result = self.export("from . import helper\n")
        imported = result["body"][0]
        self.assertEqual(imported["module"], "")
        self.assertEqual(imported["level"], 1)

    def test_function_defaults_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "default parameters"):
            self.export("def value(item=1):\n    return item\n")

    def test_loop_else_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "for-else"):
            self.export("for item in range(1):\n    pass\nelse:\n    pass\n")

    def test_method_keywords_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "keyword arguments"):
            self.export("values = []\nvalues.append(item=1)\n")

    def test_unhandled_python_syntax_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported Python syntax"):
            self.export("value = (item for item in range(2))\n")


if __name__ == "__main__":
    unittest.main()
