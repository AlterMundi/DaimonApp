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
                    "native_handoff",
                    "private_projection",
                    "avatar_model_tests",
                    "voice_templates",
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
    def test_private_projection_adapter_uses_its_existing_python_gate(self):
        self.assertEqual(selected(['scripts/bitacora_refresh.py', 'tests/bitacora_refresh.py']), set())
        self.assertEqual(selected(['src/app/private_projection.rs']), {'text'})

    def test_contribution_guidance_keeps_owning_web_checks_without_native_rebuild(self):
        self.assertEqual(selected(['CONTRIBUTING.md','AGENTS.md']),set())
        self.assertEqual(selected(['CONTRIBUTING.md','dashboard/school_mission_host.py']),set())
        self.assertEqual(selected(['CONTRIBUTING.md.extra']),{'text','audio','activity'})
        self.assertIn('text',selected(['CONTRIBUTING.md','src/app.rs']))

    def test_inert_avatar_model_fixtures_use_dashboard_without_native_requalification(self):
        files=['tests/avatar_layer_model.mjs','tests/avatar_layer_model_browser.cjs']
        for path in files:
            self.assertEqual(selected([path,'dashboard/web/avatar-workshop/renderer.mjs']),set())
            self.assertIn('text',selected([path,'src/app.rs']))
            self.assertEqual(selected([path,'Cargo.toml']),{'text','audio','activity'})
            self.assertIn('text',selected([path+'.extra']))
        workflow=WORKFLOW.read_text()
        dashboard=workflow.split('  dashboard:\n',1)[1]
        self.assertIn('python -B tests/dashboard_avatar_workshop.py',dashboard)
        store=(WORKFLOW.parents[2]/'tests/dashboard_avatar_workshop.py').read_text()
        self.assertIn("with_name('avatar_layer_model.mjs')",store)
        self.assertNotIn('needs.scope.outputs',dashboard)

    def test_public_voice_briefs_use_web_gates_without_repeating_native_fixtures(self):
        templates = ['templates/public-live-voice-brief.txt',
                     'templates/public-live-native-voice-brief.txt']
        for path in templates:
            self.assertEqual(selected([path, 'dashboard/openai_live_api.py',
                                       'tests/dashboard_openai_live_api.py']), set())
            self.assertEqual(selected([path, 'Cargo.toml']), {'text', 'audio', 'activity'})
        for unknown in ('templates/new-voice-engine.py', templates[0] + '.extra'):
            self.assertEqual(selected([unknown]), {'text', 'audio', 'activity'})
        workflow = WORKFLOW.read_text()
        self.assertIn('tests/dashboard_openai_live_api.py', workflow)
        for job in ('dashboard', 'speech-rendering'):
            body = workflow.split('  ' + job + ':\n', 1)[1]
            body = re.split(r'^  [a-zA-Z0-9_-]+:\n', body, maxsplit=1, flags=re.M)[0]
            self.assertNotIn('needs.scope.outputs', body)

    def test_web_maintenance_helper_uses_web_gate_and_keeps_unknown_native_checks(self):
        helper='scripts/interaction_web_maintenance.py'
        self.assertEqual(selected([helper,'dashboard/voice_admission.py',
                                   'tests/dashboard_voice_admission.py']),set())
        self.assertEqual(selected([helper,'Cargo.toml']),{'text','audio','activity'})
        self.assertEqual(selected([helper+'-unknown']),{'text','audio','activity'})
        self.assertIn('python -B tests/dashboard_voice_admission.py',WORKFLOW.read_text())

    def test_native_operator_uses_always_run_process_boundary_gate(self):
        paths = ['scripts/native_package_handoff.py', 'tests/native_package_handoff.py',
                 'tests/native_package_handoff_unit.py', 'docs/interaction-matrix.md']
        self.assertEqual(selected(paths), set())
        workflow = WORKFLOW.read_text()
        always = workflow.split('  matrix-execution:\n', 1)[1].split('  matrix-host:\n', 1)[0]
        self.assertIn('python -B tests/native_package_handoff_unit.py -v', always)
        self.assertEqual(workflow.count('tests/native_package_handoff_unit.py -v'), 1)
        self.assertIn('text', selected(paths + ['src/app.rs']))
        self.assertIn('audio', selected(paths + ['src/transcribe.rs']))
        self.assertIn('text', selected(paths + ['tests/native_package_handoff_unit.py-extra']))
        self.assertIn('audio', selected(paths + ['unknown-operator.py']))

    def test_browser_native_voice_regression_uses_existing_dashboard_gate(self):
        self.assertEqual(selected([
            "dashboard/web/codex-conversation.js",
            "tests/codex_conversation_ui.js",
            "tests/session_workspace_browser.js",
            "tests/session_workspace_ui.js",
            "tests/ci_matrix_host_scope.py",
            ".github/workflows/ci.yml",
            "docs/interaction-native-codex-voice.md",
        ]), set())
        self.assertIn("node tests/codex_conversation_ui.js", WORKFLOW.read_text())
        self.assertIn("node tests/session_workspace_ui.js", WORKFLOW.read_text())
        self.assertIn("text", selected(["tests/session_workspace_ui.js", "src/app.rs"]))
        self.assertIn("text", selected(["tests/codex_conversation_ui.js", "src/app.rs"]))

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

    def test_owned_live_preview_runs_always_on_speech_checks_without_native_rebuild(self):
        self.assertEqual(selected(['scripts/openai_live_speech.py','tests/openai_live_speech.py']),set())
        self.assertIn('python3 -B tests/openai_live_speech.py',WORKFLOW.read_text())
        self.assertIn('text',selected(['scripts/unqualified-new-transport.py']))

    def test_unrelated_native_features_and_self_check_keep_their_owning_jobs(self):
        self.assertIn("audio", selected(["src/transcribe.rs"]))
        self.assertIn("activity", selected(["activity/src/main.rs"]))
        self.assertEqual(selected(["tests/ci_matrix_host_scope.py"]), set())
        self.assertEqual(selected(["docs/interaction-matrix.md"]), set())


if __name__ == "__main__":
    unittest.main()
