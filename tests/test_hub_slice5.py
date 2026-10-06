"""Hub Slice 5: V1 presentation cleanup -- Teach output, mobile baseline,
filesystem/jargon cleanup, loading feedback, Check summary, Home empty-state.

Presentation-only changes: no new backend logic, no new external calls.
Synthetic fixtures only. Every external-capable route test explicitly
injects a fake provider/client -- the global ``tests/conftest.py`` socket
guard fails loudly if any test here ever fell through to a real resolver.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from university_jarvis import hub_service
from university_jarvis.hub_web import create_app
from university_jarvis.intake_ledger import new_ledger
from university_jarvis.reasoning import TokenUsage, generate_prepare_brief
from university_jarvis.sources import PDF_EXTRACTION_METHOD, PPTX_EXTRACTION_METHOD


PDF_SOURCE_ID = "syn101-w01-lecture-01-pdf"
PPTX_SOURCE_ID = "syn101-w01-slides-01-pptx"


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


def _two_source_context(workflow: str) -> dict:
    return {
        "workflow": workflow,
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
                "id": PDF_SOURCE_ID,
                "type": "lecture_pdf",
                "title": "Lecture 1 PDF",
                "availability": "content_available",
                "locator": "must-not-reach-provider.pdf",
                "extraction": {
                    "method": PDF_EXTRACTION_METHOD,
                    "page_count": 12, "nonempty_page_count": 12, "character_count": 2_000,
                    "fingerprint": {"algorithm": "sha256", "value": "a" * 64},
                },
            },
            {
                "id": PPTX_SOURCE_ID,
                "type": "lecture_slides",
                "title": "Lecture 1 slides",
                "availability": "content_available",
                "locator": "must-not-reach-provider.pptx",
                "extraction": {
                    "method": PPTX_EXTRACTION_METHOD,
                    "slide_count": 20, "nonempty_page_count": 20, "character_count": 1_500,
                    "fingerprint": {"algorithm": "sha256", "value": "b" * 64},
                },
            },
        ],
        "source_contexts": [
            {
                "source_id": PDF_SOURCE_ID, "source_type": "lecture_pdf",
                "character_limit": 8_000, "character_count": 20,
                "excerpts": [{"pdf_page": 3, "text": "Bounded PDF text.", "truncated": True}],
            },
            {
                "source_id": PPTX_SOURCE_ID, "source_type": "lecture_slides",
                "character_limit": 8_000, "character_count": 20,
                "excerpts": [{"pdf_page": 5, "text": "Bounded slide text.", "truncated": True}],
            },
        ],
    }


def _cached_prepare_brief() -> dict:
    fields = (
        "week_overview", "before_class", "core_concepts", "examples_cases",
        "lecture_attention", "after_class_questions", "assessment_connections",
    )
    return {
        field: [{"text": f"Grounded content for {field}.", "provenance": [{"source_id": PDF_SOURCE_ID, "pdf_page": 3}]}]
        for field in fields
    }


class SeedProvider:
    last_usage = TokenUsage(1_000, 500, 1_500)

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "cached-only-v1"}

    def generate_structured_output(self, context, instructions, output_format):
        return _cached_prepare_brief()


class NoCallProvider:
    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "cached-only-v1"}

    def generate_structured_output(self, *_a, **_kw):
        raise AssertionError("This test must not trigger a second model call")


class TwoSourceTeachProvider:
    def __init__(self) -> None:
        self.calls = 0

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "teach-v1"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls += 1
        both_sources = [
            {"source_id": PDF_SOURCE_ID, "pdf_page": 3},
            {"source_id": PPTX_SOURCE_ID, "pdf_page": 5},
        ]
        return {
            "direct_explanation": {"text": "A claim is a statement that can be examined.", "provenance": both_sources},
            "teaching_sequence": [
                {
                    "move_type": "build_understanding",
                    "title": "Start with identity",
                    "explanation": "Identity comes first.",
                    "why_it_follows": None,
                    "provenance": both_sources,
                }
            ],
            "mental_model": {"text": "Question framing guides what evidence may be relevant.", "provenance": both_sources},
            "check_questions": [
                {"text": "What is a brand?", "provenance": both_sources},
                {"text": "How does a question guide evidence selection?", "provenance": both_sources},
            ],
            "unknowns": [],
        }


class TeachOutputRenderingTests(unittest.TestCase):
    """Proves the audit's MUST-FIX defect (Teach showed no content) is fixed."""

    def _materialize(self, *, workspace_root: Path, cache_dir: Path) -> None:
        generate_prepare_brief(_two_source_context("PREPARE_ME"), SeedProvider(), cache_dir)
        app = create_app(
            state=_state_fixture(), ledger=new_ledger(), workspace_root=workspace_root,
            cache_dir=cache_dir, reasoning_provider=NoCallProvider(),
        )
        client = TestClient(app)
        with patch(
            "university_jarvis.workspace.build_prepare_context",
            return_value=_two_source_context("PREPARE_ME"),
        ):
            response = client.post("/modules/SYN101/weeks/1/build")
        self.assertEqual(response.status_code, 200)

    def test_teach_result_includes_the_actual_rendered_lesson_with_both_citation_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            self._materialize(workspace_root=workspace_root, cache_dir=cache_dir)

            provider = TwoSourceTeachProvider()
            app = create_app(
                state=_state_fixture(), ledger=new_ledger(), workspace_root=workspace_root,
                cache_dir=cache_dir, reasoning_provider=provider,
            )
            client = TestClient(app)
            with patch(
                "university_jarvis.workspace.build_week_context",
                return_value=_two_source_context("TEACH"),
            ):
                response = client.post(
                    "/modules/SYN101/weeks/1/teach", data={"topic": "what is a brand"}
                )

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertEqual(provider.calls, 1)  # rendering never triggers a second model call
        # The actual lesson content, not just metadata:
        self.assertIn("A claim is a statement that can be examined.", body)
        self.assertIn("Start with identity", body)
        self.assertIn("Question framing guides what evidence may be relevant.", body)
        self.assertIn("What is a brand?", body)
        # Provenance/citations, both formats preserved end to end:
        self.assertIn("PDF p. 3", body)
        self.assertIn("Slide 5", body)

    def test_teach_leaks_no_absolute_path_or_internal_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            self._materialize(workspace_root=workspace_root, cache_dir=cache_dir)

            provider = TwoSourceTeachProvider()
            app = create_app(
                state=_state_fixture(), ledger=new_ledger(), workspace_root=workspace_root,
                cache_dir=cache_dir, reasoning_provider=provider,
            )
            client = TestClient(app)
            with patch(
                "university_jarvis.workspace.build_week_context",
                return_value=_two_source_context("TEACH"),
            ):
                response = client.post(
                    "/modules/SYN101/weeks/1/teach", data={"topic": "what is a brand"}
                )

        body = response.text
        self.assertNotIn(str(workspace_root), body)
        self.assertNotIn("teach_id", body)
        self.assertNotIn("cache_status:", body)  # raw jargon key must not appear literally
        self.assertIn("Generation status", body)  # translated label does

    def test_build_leaks_no_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            self._materialize(workspace_root=workspace_root, cache_dir=cache_dir)

            app = create_app(
                state=_state_fixture(), ledger=new_ledger(), workspace_root=workspace_root,
                cache_dir=cache_dir, reasoning_provider=NoCallProvider(),
            )
            client = TestClient(app)
            with patch(
                "university_jarvis.workspace.build_prepare_context",
                return_value=_two_source_context("PREPARE_ME"),
            ):
                response = client.post("/modules/SYN101/weeks/1/build")

        body = response.text
        self.assertNotIn(str(workspace_root), body)
        self.assertIn("updated", body)  # friendly artifact confirmation still present
        self.assertIn("Reused a previously generated result", body)

    def test_after_lecture_leaks_no_absolute_path_or_capture_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            self._materialize(workspace_root=workspace_root, cache_dir=cache_dir)

            app = create_app(state=_state_fixture(), ledger=new_ledger(), workspace_root=workspace_root)
            client = TestClient(app)
            response = client.post(
                "/modules/SYN101/weeks/1/after-lecture", data={"notes": "Some free notes"}
            )

        body = response.text
        self.assertNotIn(str(workspace_root), body)
        self.assertNotIn("capture_id", body)
        self.assertIn("Saved at", body)


class MobileBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(state=_state_fixture(), ledger=new_ledger())
        self.client = TestClient(self.app)

    def test_every_page_has_viewport_meta_tag(self) -> None:
        for path in ("/", "/modules", "/modules/SYN101", "/assessments", "/check"):
            body = self.client.get(path).text
            self.assertIn('name="viewport"', body, path)
            self.assertIn("width=device-width", body, path)

    def test_tables_are_wrapped_for_narrow_screen_scrolling(self) -> None:
        # Modules is a card grid (post-V1-redesign); assessments still uses a
        # real data table, wrapped for narrow-screen horizontal scroll.
        body = self.client.get("/assessments").text
        self.assertIn("table-scroll", body)

    def test_week_page_material_table_is_scroll_wrapped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = {
                "schema_version": 1,
                "modules": {"SYN101": {"weeks": {"1": {"documents": {
                    "doc-1": {"title": "Slides", "last_seen_at": "2025-01-01T00:00:00+00:00", "attachments": {}}
                }}}}},
            }
            app = create_app(state=_state_fixture(), ledger=ledger, workspace_root=Path(tmp) / "workspace")
            client = TestClient(app)
            body = client.get("/modules/SYN101/weeks/1").text
        self.assertIn("table-scroll", body)


class LoadingFeedbackMarkupTests(unittest.TestCase):
    """The JS itself can't run under TestClient; this proves the markup the
    JS depends on (form inside .action-form, a submit button, #check-form)
    is actually present for the four model-backed actions plus Build."""

    def setUp(self) -> None:
        self.app = create_app(state=_state_fixture(), ledger=new_ledger())
        self.client = TestClient(self.app)

    def test_week_page_action_forms_are_wired_for_loading_feedback(self) -> None:
        body = self.client.get("/modules/SYN101/weeks/1").text
        self.assertGreaterEqual(body.count('class="action-form"'), 4)  # build/teach/quiz/revise/after-lecture
        self.assertIn('button type="submit"', body)
        self.assertIn("Working…", body)  # the feedback script's own literal text

    def test_module_page_assignment_form_is_wired_for_loading_feedback(self) -> None:
        body = self.client.get("/modules/SYN101").text
        self.assertIn('class="action-form"', body)
        self.assertIn("Working…", body)

    def test_check_form_has_stable_id_for_loading_feedback(self) -> None:
        body = self.client.get("/check").text
        self.assertIn('id="check-form"', body)

    def test_get_requests_never_trigger_any_action(self) -> None:
        def _boom(*_a, **_kw):
            raise AssertionError("GET must remain side-effect free")

        with patch("university_jarvis.hub_service.check_university", side_effect=_boom), \
             patch("university_jarvis.workspace.materialize_week_workspace", side_effect=_boom), \
             patch("university_jarvis.workspace.teach_week", side_effect=_boom), \
             patch("socket.socket.connect", side_effect=_boom):
            for path in ("/", "/modules", "/modules/SYN101", "/modules/SYN101/weeks/1", "/assessments", "/check"):
                self.assertEqual(self.client.get(path).status_code, 200, path)


class CheckSummaryTests(unittest.TestCase):
    def test_summary_counts_match_returned_items_exactly(self) -> None:
        from university_jarvis.blackboard import ContentRef, WEEK_DISCOVERED, WEEK_NOT_YET_PUBLISHED
        from university_jarvis.reconcile import (
            CHANGED, NEW, UNCHANGED, ReconcileItemResult, WeekReconcileResult,
        )
        from university_jarvis.university import ModuleCheckResult, UniversityCheckResult

        result_obj = UniversityCheckResult(
            modules=[
                ModuleCheckResult("SYN101", [
                    WeekReconcileResult("SYN101", 1, WEEK_DISCOVERED, [
                        ReconcileItemResult(status=NEW, source_path=(ContentRef("c1", "A", "x"),), file_name="a.pdf"),
                        ReconcileItemResult(status=NEW, source_path=(ContentRef("c2", "B", "x"),), file_name="b.pdf"),
                        ReconcileItemResult(status=UNCHANGED, source_path=(ContentRef("c3", "C", "x"),), file_name="c.pdf"),
                    ]),
                ]),
                ModuleCheckResult("SYN102", [
                    WeekReconcileResult("SYN102", 1, WEEK_DISCOVERED, [
                        ReconcileItemResult(status=CHANGED, source_path=(ContentRef("c4", "D", "x"),), file_name="d.pptx"),
                    ]),
                    WeekReconcileResult("SYN102", 2, WEEK_NOT_YET_PUBLISHED, []),
                ]),
            ],
            scope_issues=[],
        )
        result = hub_service._jsonable(result_obj)

        summary = hub_service.summarize_university_check(result)

        self.assertEqual(summary["new"], 2)
        self.assertEqual(summary["unchanged"], 1)
        self.assertEqual(summary["changed"], 1)
        self.assertEqual(summary["not_yet_published"], 1)
        # Zero-count statuses must be absent, not zero-valued.
        self.assertNotIn("failed", summary)
        self.assertNotIn("ambiguous", summary)
        self.assertNotIn("missing", summary)
        self.assertNotIn("metadata_changed", summary)
        # The detail rows must still be independently derivable from `result`.
        self.assertEqual(len(result["modules"][0]["weeks"][0]["items"]), 3)

    def test_check_page_renders_summary_agreeing_with_detail_rows(self) -> None:
        from university_jarvis.blackboard import ContentRef, WEEK_DISCOVERED
        from university_jarvis.reconcile import NEW, UNCHANGED, ReconcileItemResult, WeekReconcileResult
        from university_jarvis.university import ModuleCheckResult, UniversityCheckResult
        import contextlib

        result = UniversityCheckResult(
            modules=[
                ModuleCheckResult("SYN101", [
                    WeekReconcileResult("SYN101", 1, WEEK_DISCOVERED, [
                        ReconcileItemResult(status=NEW, source_path=(ContentRef("c1", "A", "x"),), file_name="a.pdf"),
                        ReconcileItemResult(status=UNCHANGED, source_path=(ContentRef("c2", "B", "x"),), file_name="b.pdf"),
                    ]),
                ]),
            ],
            scope_issues=[],
        )
        app = create_app(
            state=_state_fixture(), ledger=new_ledger(),
            blackboard_client_factory=lambda: contextlib.nullcontext(object()),
        )
        with patch("university_jarvis.hub_service.check_university", return_value=result):
            client = TestClient(app)
            body = client.post("/check").text

        self.assertIn(">New<", body)
        self.assertIn(">Unchanged<", body)
        self.assertIn("1 item", body)
        self.assertIn("a.pdf", body)
        self.assertIn("b.pdf", body)


class HomeEmptyStateTests(unittest.TestCase):
    def _app(self, *, state=None, ledger=None, workspace_root=None) -> TestClient:
        app = create_app(state=state or _state_fixture(), ledger=ledger or new_ledger(), workspace_root=workspace_root)
        return TestClient(app)

    def test_no_material_observed_state_is_distinguishable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(workspace_root=Path(tmp) / "workspace")
            body = client.get("/").text
        self.assertIn("No material has been observed yet", body)
        self.assertNotIn("all studying complete", body.lower())
        self.assertNotIn("complete", body.lower())

    def test_material_observed_no_gaps_state_is_distinguishable(self) -> None:
        ledger = {
            "schema_version": 1,
            "modules": {"SYN101": {"weeks": {"1": {"documents": {
                "doc-1": {"title": "Slides", "last_seen_at": "2025-01-01T00:00:00+00:00", "attachments": {}}
            }}}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            # A matching academic-record.json means no STUDY_STATE_UNKNOWN gap.
            record_dir = Path(tmp) / "workspace" / "SYN101" / "week-01"
            record_dir.mkdir(parents=True)
            import json
            record = {
                "workspace_schema_version": 3, "record_type": "academic_week",
                "module": {"code": "SYN101", "title": "Introduction to Example Studies", "semester": 1, "academic_year": "2025/26"},
                "week": {"number": 1, "date": None, "topic": None, "declared_progress": "unknown"},
                "sources": [],
                "workflows": {
                    "prepare_me": {"status": "completed", "result": {}},
                    "after_lecture": {"status": "not_recorded", "captures": []},
                    "teach": {"status": "not_recorded", "interactions": []},
                    "quiz": {"status": "not_recorded"}, "revise": {"status": "not_recorded"},
                },
                "learning": {"unresolved_items": {"status": "none_recorded", "items": []}},
            }
            (record_dir / "academic-record.json").write_text(json.dumps(record), encoding="utf-8")

            client = self._app(ledger=ledger, workspace_root=Path(tmp) / "workspace")
            body = client.get("/").text

        self.assertIn("Observed material exists", body)
        self.assertIn("no study-state gaps are currently identified", body)
        self.assertNotIn("all studying complete", body.lower())
        self.assertNotIn("complete", body.lower())

    def test_gaps_exist_state_still_renders_the_real_gap(self) -> None:
        ledger = {
            "schema_version": 1,
            "modules": {"SYN101": {"weeks": {"1": {"documents": {
                "doc-1": {"title": "Slides", "last_seen_at": "2025-01-01T00:00:00+00:00", "attachments": {}}
            }}}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(ledger=ledger, workspace_root=Path(tmp) / "workspace")
            body = client.get("/").text

        self.assertIn("Slides", body)
        self.assertNotIn("No material has been observed yet", body)
        self.assertNotIn("no study-state gaps are currently identified", body)


if __name__ == "__main__":
    unittest.main()
