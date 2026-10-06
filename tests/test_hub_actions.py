"""Hub Slice 3: controlled, POST-only actions -- route tests.

Synthetic fixtures only; real (gitignored) academic/private data is never
touched. Extends the Slice 2 boundary proof: every action route is checked
for POST-only enforcement, cache-first/provider delegation, honest error
surfacing, and secret-safety (no credential value ever reaches the response).
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from university_jarvis.blackboard import (
    BlackboardClient,
    BlackboardError,
    BlackboardSession,
    HttpResponse,
)
from university_jarvis.hub_web import create_app
from university_jarvis.intake_ledger import new_ledger
from university_jarvis.reasoning import TokenUsage, generate_prepare_brief
from university_jarvis.workspace import capture_after_lecture, materialize_week_workspace


SOURCE_ID = "syn101-w01-lecture-01-pdf"
BASE = "https://blackboard.example.test/learn/api/public/v1"
SECRET_MARKER = "COOKIE-SECRET-DO-NOT-LEAK-9f2c"


def _minimal_mission() -> dict:
    return {
        "statement": "Graduate well.",
        "primary_objective": {"statement": "Graduate."},
        "stretch_objective": {"statement": "Excel."},
        "operating_principles": [{"id": "p1", "statement": "Learn genuinely."}],
        "constraints": [{"id": "c1", "statement": "No misconduct."}],
    }


def _state_fixture() -> dict:
    return {
        "schema_version": 1,
        "mission": _minimal_mission(),
        "student": {
            "university": "Test University",
            "programme": "BA Testing",
            "year_of_study": 2,
            "level": 5,
            "academic_year": "2025/26",
        },
        "modules": [
            {
                "code": "SYN101",
                "title": "State-only module",
                "semester": 1,
                "academic_year": "2025/26",
                "weeks": [{"week": 1, "date": None, "topic": "Intro", "progress": "unknown", "source_ids": []}],
                "assessments": [],
            }
        ],
        "sources": [],
    }


def prepare_context() -> dict:
    return {
        "workflow": "PREPARE_ME",
        "objective_context": {
            "version": 1,
            "primary_objective": "Build understanding toward the learners stated academic goals.",
            "stretch_objective": "Stretch only where evidence exists.",
            "operating_principles": ["Genuine learning over outsourcing thinking."],
            "hard_constraints": ["Maintain academic integrity."],
            "reliable_cohort_information_available": False,
        },
        "module": {"code": "SYN101", "title": "Introduction to Example Studies", "semester": 1, "academic_year": "2025/26"},
        "week": {"number": 1, "date": None, "topic": None, "progress": "unknown"},
        "assessments": [],
        "items": [],
        "sources": [
            {
                "id": SOURCE_ID,
                "type": "lecture_pdf",
                "title": "Lecture 1 PDF",
                "availability": "content_available",
                "locator": "must-not-enter-record.pdf",
                "extraction": {
                    "method": "test_extraction",
                    "page_count": 12,
                    "nonempty_page_count": 12,
                    "character_count": 2_000,
                    "fingerprint": {"algorithm": "sha256", "value": "a" * 64},
                },
            }
        ],
        "source_contexts": [
            {
                "source_id": SOURCE_ID,
                "source_type": "lecture_pdf",
                "title": "Lecture 1 PDF",
                "character_limit": 8_000,
                "character_count": 20,
                "excerpts": [{"pdf_page": 3, "text": "Bounded source text.", "truncated": True}],
            }
        ],
    }


def cached_brief() -> dict:
    fields = (
        "week_overview", "before_class", "core_concepts", "examples_cases",
        "lecture_attention", "after_class_questions", "assessment_connections",
    )
    return {
        field: [{"text": f"Grounded study content for {field}.", "provenance": [{"source_id": SOURCE_ID, "pdf_page": 3}]}]
        for field in fields
    }


class SeedProvider:
    last_usage = TokenUsage(1_000, 500, 1_500)

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "cached-only-v1"}

    def generate_structured_output(self, context, instructions, output_format):
        return cached_brief()


class NoCallProvider:
    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "cached-only-v1"}

    def generate_structured_output(self, context, instructions, output_format):
        raise AssertionError("Build action must never call the provider on a cache hit")


class TeachProvider:
    def __init__(self) -> None:
        self.calls = 0

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "teach-v1"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls += 1
        reference = [{"source_id": SOURCE_ID, "pdf_page": 3}]
        return {
            "direct_explanation": {"text": "Direct answer.", "provenance": reference},
            "teaching_sequence": [
                {
                    "move_type": "build_understanding",
                    "title": "Step one",
                    "explanation": "Explanation.",
                    "why_it_follows": None,
                    "provenance": reference,
                }
            ],
            "mental_model": {"text": "Model.", "provenance": reference},
            "check_questions": [
                {"text": "Check one?", "provenance": reference},
                {"text": "Check two?", "provenance": reference},
            ],
            "unknowns": [],
        }


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


class _FakeTransport:
    """Minimal one-module, one-week Blackboard transport for /check tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append(url)
        if url == f"{BASE}/users/me/courses":
            return _json_response({"results": [{"courseId": "_a_1"}]})
        if url == f"{BASE}/courses/_a_1":
            return _json_response({"id": "_a_1", "courseId": "ZZUNIC", "name": "Module C"})
        if url == f"{BASE}/courses/_a_1/contents":
            return _json_response(
                {
                    "results": [
                        {
                            "id": "_wk1",
                            "title": "Week 1",
                            "contentHandler": {"id": "resource/x-bb-lesson"},
                            "hasChildren": True,
                        }
                    ]
                }
            )
        if url == f"{BASE}/courses/_a_1/contents/_wk1/children":
            return _json_response({"results": []})
        raise AssertionError(f"Unexpected URL requested: {url}")


def _fake_blackboard_client() -> BlackboardClient:
    transport = _FakeTransport()
    session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header=SECRET_MARKER)
    return BlackboardClient(session, http_get=transport)


class CheckActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        # check_university() calls save_ledger(ledger) with no path on every
        # successful week, which falls back to default_ledger_path() -- the
        # REAL, gitignored data/intake-ledger.json -- unless JARVIS_LEDGER_FILE
        # points elsewhere. test_post_check_runs_and_renders_result below
        # exercises the real check_university (only the Blackboard client is
        # faked), so every test in this class must be isolated from it, the
        # same way test_university.py's CheckUniversityTests already is.
        previous_ledger_file = os.environ.get("JARVIS_LEDGER_FILE")
        os.environ["JARVIS_LEDGER_FILE"] = str(Path(self.tmp.name) / "intake-ledger.json")

        def _restore_ledger_file() -> None:
            if previous_ledger_file is None:
                os.environ.pop("JARVIS_LEDGER_FILE", None)
            else:
                os.environ["JARVIS_LEDGER_FILE"] = previous_ledger_file

        self.addCleanup(_restore_ledger_file)

        self.client_holder = {"client": _fake_blackboard_client(), "raise_error": None}

        def factory():
            if self.client_holder["raise_error"] is not None:
                raise self.client_holder["raise_error"]
            return contextlib.nullcontext(self.client_holder["client"])

        self.app = create_app(
            state=_state_fixture(),
            ledger=new_ledger(),
            workspace_root=Path(self.tmp.name) / "workspace",
            blackboard_client_factory=factory,
        )
        self.test_client = TestClient(self.app)

    def test_get_check_never_runs_the_check(self) -> None:
        with patch("university_jarvis.university.check_university") as spy:
            response = self.test_client.get("/check")
        self.assertEqual(response.status_code, 200)
        spy.assert_not_called()
        self.assertNotIn(SECRET_MARKER, response.text)

    def test_post_check_runs_and_renders_result(self) -> None:
        response = self.test_client.post("/check")
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("ZZUNIC", body)
        self.assertIn("Week 1", body)
        self.assertNotIn(SECRET_MARKER, body)

    def test_post_check_never_passes_sync_to_drive_true(self) -> None:
        from university_jarvis.university import UniversityCheckResult

        with patch(
            "university_jarvis.hub_service.check_university",
            return_value=UniversityCheckResult(modules=[], scope_issues=[]),
        ) as spy:
            self.test_client.post("/check")
        args, kwargs = spy.call_args
        self.assertFalse(kwargs.get("sync_to_drive", True))
        self.assertIsNone(args[1])  # drive_client positional arg

    def test_check_error_is_rendered_without_leaking_the_client(self) -> None:
        self.client_holder["raise_error"] = BlackboardError("No Blackboard session found.")
        response = self.test_client.post("/check")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No Blackboard session found.", response.text)
        self.assertNotIn(SECRET_MARKER, response.text)


class CheckPageItemStatusRenderingTests(unittest.TestCase):
    """The check page must expose real per-item reconciliation status, not
    just the week/container discovery status. Uses a synthetic
    UniversityCheckResult (no real Blackboard call) so this is pure
    rendering verification.

    ``blackboard_client_factory`` MUST be overridden here: ``check_run``
    always calls the factory before ``hub_service.check_university`` (which
    these tests patch), so leaving it at its real default would resolve the
    real Auth V2 browser client -- launching an actual browser and
    navigating to the real Blackboard host even though the reconciliation
    itself is mocked. A plain ``contextlib.nullcontext`` placeholder avoids
    that entirely.
    """

    def setUp(self) -> None:
        self.app = create_app(
            state=_state_fixture(),
            ledger=new_ledger(),
            blackboard_client_factory=lambda: contextlib.nullcontext(object()),
        )
        self.client = TestClient(self.app)

    def _render(self, result) -> str:
        with patch("university_jarvis.hub_service.check_university", return_value=result):
            response = self.client.post("/check")
        self.assertEqual(response.status_code, 200)
        return response.text

    def _week_result(self, items):
        from university_jarvis.blackboard import WEEK_DISCOVERED
        from university_jarvis.reconcile import WeekReconcileResult
        from university_jarvis.university import ModuleCheckResult, UniversityCheckResult

        return UniversityCheckResult(
            modules=[ModuleCheckResult("SYN101", [WeekReconcileResult("SYN101", 1, WEEK_DISCOVERED, items)])],
            scope_issues=[],
        )

    def test_new_item_is_rendered_as_new(self) -> None:
        from university_jarvis.blackboard import ContentRef
        from university_jarvis.reconcile import NEW, ReconcileItemResult

        body = self._render(
            self._week_result(
                [ReconcileItemResult(status=NEW, source_path=(ContentRef("c1", "Lecture", "x"),), file_name="a.pdf")]
            )
        )
        self.assertIn(">NEW<", body)
        self.assertIn("a.pdf", body)

    def test_unchanged_item_is_rendered_as_unchanged(self) -> None:
        from university_jarvis.blackboard import ContentRef
        from university_jarvis.reconcile import ReconcileItemResult, UNCHANGED

        body = self._render(
            self._week_result(
                [ReconcileItemResult(status=UNCHANGED, source_path=(ContentRef("c1", "Lecture", "x"),), file_name="a.pdf")]
            )
        )
        self.assertIn(">UNCHANGED<", body)

    def test_changed_item_is_rendered_as_changed(self) -> None:
        from university_jarvis.blackboard import ContentRef
        from university_jarvis.reconcile import CHANGED, ReconcileItemResult

        body = self._render(
            self._week_result(
                [ReconcileItemResult(status=CHANGED, source_path=(ContentRef("c1", "Lecture", "x"),), file_name="a.pdf")]
            )
        )
        self.assertIn(">CHANGED<", body)

    def test_failed_item_surfaces_error_text_without_inventing_anything(self) -> None:
        from university_jarvis.blackboard import ContentRef
        from university_jarvis.reconcile import FAILED, ReconcileItemResult

        body = self._render(
            self._week_result(
                [
                    ReconcileItemResult(
                        status=FAILED,
                        source_path=(ContentRef("c1", "Broken", "x"),),
                        file_name="broken.pdf",
                        error="HTTP 500",
                    )
                ]
            )
        )
        self.assertIn(">FAILED<", body)
        self.assertIn("HTTP 500", body)

    def test_ambiguous_item_surfaces_reason_text(self) -> None:
        from university_jarvis.blackboard import ContentRef
        from university_jarvis.reconcile import AMBIGUOUS, ReconcileItemResult

        body = self._render(
            self._week_result(
                [
                    ReconcileItemResult(
                        status=AMBIGUOUS,
                        source_path=(ContentRef("c1", "Dup", "x"),),
                        reason="multiple candidates",
                    )
                ]
            )
        )
        self.assertIn(">AMBIGUOUS<", body)
        self.assertIn("multiple candidates", body)

    def test_week_discovery_status_stays_distinct_from_item_status(self) -> None:
        from university_jarvis.blackboard import ContentRef
        from university_jarvis.reconcile import NEW, ReconcileItemResult

        body = self._render(
            self._week_result(
                [ReconcileItemResult(status=NEW, source_path=(ContentRef("c1", "Lecture", "x"),), file_name="a.pdf")]
            )
        )
        self.assertIn("week status: DISCOVERED", body)
        self.assertIn(">NEW<", body)
        # DISCOVERED must never be presented as if it were the item's own status tag.
        self.assertNotIn('<span class="tag">DISCOVERED</span></td>', body)

    def test_not_yet_published_week_renders_honestly_with_no_item_statuses(self) -> None:
        from university_jarvis.blackboard import WEEK_NOT_YET_PUBLISHED
        from university_jarvis.reconcile import WeekReconcileResult
        from university_jarvis.university import ModuleCheckResult, UniversityCheckResult

        result = UniversityCheckResult(
            modules=[
                ModuleCheckResult("SYN101", [WeekReconcileResult("SYN101", 2, WEEK_NOT_YET_PUBLISHED, [])])
            ],
            scope_issues=[],
        )
        body = self._render(result)
        self.assertIn("WEEK_NOT_YET_PUBLISHED", body)
        self.assertIn("not reconciled", body)

    def test_get_check_page_causes_no_external_call_or_mutation(self) -> None:
        def _boom(*_a, **_kw):
            raise AssertionError("GET /check must never run the check or write anything")

        with patch("university_jarvis.hub_service.check_university", side_effect=_boom), \
             patch("socket.socket.connect", side_effect=_boom):
            response = self.client.get("/check")
        self.assertEqual(response.status_code, 200)


class WorkspaceActionTests(unittest.TestCase):
    def _app(self, *, workspace_root: Path, cache_dir: Path, reasoning_provider=None) -> TestClient:
        app = create_app(
            state={},
            ledger=new_ledger(),
            workspace_root=workspace_root,
            cache_dir=cache_dir,
            reasoning_provider=reasoning_provider,
        )
        return TestClient(app)

    def test_get_build_route_is_not_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = self._app(workspace_root=root / "workspace", cache_dir=root / "cache")
            response = client.get("/modules/SYN101/weeks/1/build")
        self.assertEqual(response.status_code, 405)

    def test_build_action_reports_error_when_no_cache_and_module_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_root = root / "workspace"
            client = self._app(
                workspace_root=workspace_root, cache_dir=root / "cache", reasoning_provider=NoCallProvider()
            )
            response = client.post("/modules/SYN101/weeks/1/build")
        self.assertEqual(response.status_code, 404)  # module unknown to empty picture

    def test_unknown_module_or_week_fails_safely_on_every_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = self._app(workspace_root=root / "workspace", cache_dir=root / "cache")
            for path in (
                "/modules/ZZFAKE/weeks/1/build",
                "/modules/ZZFAKE/weeks/1/teach",
                "/modules/ZZFAKE/weeks/1/after-lecture",
                "/modules/SYN101/weeks/99/build",
            ):
                response = client.post(path)
                self.assertEqual(response.status_code, 404, path)

    def test_get_teach_and_after_lecture_routes_are_not_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = self._app(workspace_root=root / "workspace", cache_dir=root / "cache")
            self.assertEqual(client.get("/modules/SYN101/weeks/1/teach").status_code, 405)
            self.assertEqual(client.get("/modules/SYN101/weeks/1/after-lecture").status_code, 405)


class FullWorkspaceLifecycleTests(unittest.TestCase):
    """End-to-end through real routes: state fixture that actually knows SYN101."""

    def _state(self) -> dict:
        return {
            "schema_version": 1,
            "mission": _minimal_mission(),
            "student": {
                "university": "Test University", "programme": "BA Testing",
                "year_of_study": 2, "level": 5, "academic_year": "2025/26",
            },
            "modules": [
                {
                    "code": "SYN101",
                    "title": "Introduction to Example Studies",
                    "semester": 1,
                    "academic_year": "2025/26",
                    "weeks": [{"week": 1, "date": None, "topic": None, "progress": "unknown", "source_ids": []}],
                    "assessments": [],
                }
            ],
            "sources": [],
        }

    def test_build_then_teach_then_after_lecture_through_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            generate_prepare_brief(prepare_context(), SeedProvider(), cache_dir)

            app = create_app(
                state=self._state(),
                ledger=new_ledger(),
                workspace_root=workspace_root,
                cache_dir=cache_dir,
                reasoning_provider=NoCallProvider(),
            )
            client = TestClient(app)

            with patch(
                "university_jarvis.workspace.build_prepare_context", return_value=prepare_context()
            ):
                build_response = client.post("/modules/SYN101/weeks/1/build")
            self.assertEqual(build_response.status_code, 200)
            self.assertIn("Reused a previously generated result", build_response.text)
            self.assertIn("Action succeeded", build_response.text)
            self.assertNotIn(str(workspace_root), build_response.text)  # no absolute path leaked

            after_lecture_response = client.post(
                "/modules/SYN101/weeks/1/after-lecture",
                data={"uncertainty": "I don't understand accrual accounting"},
            )
            self.assertEqual(after_lecture_response.status_code, 200)
            self.assertIn("Saved at:", after_lecture_response.text)
            self.assertNotIn("capture_id", after_lecture_response.text)
            self.assertNotIn(str(workspace_root), after_lecture_response.text)

            teach_provider = TeachProvider()
            app.state.hub_reasoning_provider = teach_provider
            teach_week_context = {**prepare_context(), "workflow": "TEACH"}
            with patch(
                "university_jarvis.workspace.build_week_context", return_value=teach_week_context
            ):
                teach_response = client.post(
                    "/modules/SYN101/weeks/1/teach", data={"topic": "accrual accounting"}
                )
            self.assertEqual(teach_response.status_code, 200)
            self.assertEqual(teach_provider.calls, 1)
            self.assertIn("Action succeeded", teach_response.text)
            self.assertIn("Topic: accrual accounting", teach_response.text)
            # The actual generated lesson must be visible, not just metadata.
            self.assertIn("Direct answer.", teach_response.text)
            self.assertIn("Step one", teach_response.text)
            self.assertIn("PDF p. 3", teach_response.text)
            self.assertNotIn(str(workspace_root), teach_response.text)
            self.assertNotIn("teach_id", teach_response.text)

            # The week page now reflects the real, updated workflow state.
            week_page = client.get("/modules/SYN101/weeks/1").text
            self.assertIn("prepare_me", week_page)
            self.assertIn("completed", week_page)
            self.assertIn("teach", week_page)
            self.assertIn("recorded", week_page)

    def test_after_lecture_before_any_build_reports_honest_error_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            app = create_app(state=self._state(), ledger=new_ledger(), workspace_root=workspace_root)
            client = TestClient(app)

            response = client.post(
                "/modules/SYN101/weeks/1/after-lecture", data={"notes": "Some free notes"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Action failed", response.text)
        self.assertIn("run workspace first", response.text)
        self.assertFalse(workspace_root.exists())  # no partial/corrupt write

    def test_after_lecture_with_no_fields_reports_honest_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            generate_prepare_brief(prepare_context(), SeedProvider(), cache_dir)
            app = create_app(
                state=self._state(), ledger=new_ledger(), workspace_root=workspace_root,
                cache_dir=cache_dir, reasoning_provider=NoCallProvider(),
            )
            client = TestClient(app)
            with patch(
                "university_jarvis.workspace.build_prepare_context", return_value=prepare_context()
            ):
                client.post("/modules/SYN101/weeks/1/build")

            response = client.post("/modules/SYN101/weeks/1/after-lecture", data={})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Action failed", response.text)
        self.assertIn("requires notes or at least one reported item", response.text)


class ReadRoutesStillExternallyInertTests(unittest.TestCase):
    """Re-proves the Slice 2 boundary still holds with Slice 3 actions present."""

    def test_get_routes_never_touch_workspace_materialize_teach_or_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            app = create_app(
                state=FullWorkspaceLifecycleTests()._state(),
                ledger=new_ledger(),
                workspace_root=workspace_root,
            )
            client = TestClient(app)

            def _boom(*_a, **_kw):
                raise AssertionError("GET routes must never trigger an external/write action")

            with patch("university_jarvis.workspace.materialize_week_workspace", side_effect=_boom), \
                 patch("university_jarvis.workspace.teach_week", side_effect=_boom), \
                 patch("university_jarvis.workspace.capture_after_lecture", side_effect=_boom), \
                 patch("university_jarvis.university.check_university", side_effect=_boom), \
                 patch("socket.socket.connect", side_effect=_boom):
                for path in ("/", "/modules", "/modules/SYN101", "/modules/SYN101/weeks/1", "/assessments", "/check"):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200, path)
            self.assertFalse(workspace_root.exists())


if __name__ == "__main__":
    unittest.main()
