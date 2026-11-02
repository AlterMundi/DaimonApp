"""Qualify the actual workflow scope program's native/Matrix dependency boundary."""

import ast
import re
from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
source = (
    WORKFLOW.read_text().split("python3 - <<'PY'", 1)[1].split("\n          PY", 1)[0]
)
program = ast.parse(
    "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in source.splitlines()
    )
)


def selected(paths, previous=None):
    current = WORKFLOW.read_text()
    scope = dict(re=re, files=paths, current=current, previous=previous or current)
    for node in program.body:
        if (
            isinstance(node, ast.FunctionDef)
            or isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id
                in {
                    "common",
                    "header_changed",
                    "text_ci_changed",
                    "text",
                    "audio",
                    "activity",
                    "matrix_host",
                    "matrix_only",
                }
                for target in node.targets
            )
        ):
            exec(
                compile(
                    ast.Module(body=[node], type_ignores=[]),
                    "<actual-workflow-scope>",
                    "exec",
                ),
                scope,
            )
    return {key for key in ("text", "audio", "activity", "matrix_host") if scope[key]}


class MatrixHostScope(unittest.TestCase):
    def test_host_changes_keep_the_real_canonical_consumer_without_unrelated_native_suites(
        self,
    ):
        for path in (
            "scripts/matrix_execution.py",
            "scripts/matrix_operator.py",
            "tests/matrix_execution.py",
            "tests/matrix_conversation_http_io.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    selected([path, "docs/interaction-matrix.md"]), {"matrix_host"}
                )

    def test_native_dependency_unknown_and_workflow_changes_preserve_full_qualification(
        self,
    ):
        for path in (
            "src/app/matrix.rs",
            "src/store/matrix.rs",
            "Cargo.lock",
            "Cargo.toml",
            "build.rs",
            "new-host-program.py",
            "tests/new_native_io.py",
        ):
            with self.subTest(path=path):
                self.assertIn("text", selected(["scripts/matrix_operator.py", path]))
                self.assertNotIn(
                    "matrix_host", selected(["scripts/matrix_operator.py", path])
                )
        changed = WORKFLOW.read_text().replace(
            "  text:\n", "  text:\n    # Changed owning job\n", 1
        )
        self.assertIn("text", selected([".github/workflows/ci.yml"], previous=changed))
        self.assertNotIn(
            "matrix_host",
            selected(["scripts/matrix_operator.py", ".github/workflows/ci.yml"]),
        )

    def test_changed_profile_is_itself_exercised_without_repeating_unchanged_native_code(
        self,
    ):
        changed = WORKFLOW.read_text().replace(
            "  matrix-host:\n", "  matrix-host:\n    # Previous profile\n", 1
        )
        self.assertEqual(
            selected([".github/workflows/ci.yml"], previous=changed), {"matrix_host"}
        )

    def test_unrelated_native_features_and_self_check_keep_their_owning_jobs(self):
        self.assertIn("audio", selected(["src/transcribe.rs"]))
        self.assertIn("activity", selected(["activity/src/main.rs"]))
        self.assertEqual(selected(["tests/ci_matrix_host_scope.py"]), set())
        self.assertEqual(selected(["docs/interaction-matrix.md"]), set())


if __name__ == "__main__":
    unittest.main()
