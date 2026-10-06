"""Hub Slice 4: Quiz, Revise, and Assignment Coach -- ephemeral MODEL CALL
actions, cache-first, never touching the workspace record.

Synthetic fixtures only. Every route test explicitly injects a fake
``reasoning_provider`` and never relies on ``create_app``'s real defaults --
the global ``tests/conftest.py`` socket guard also fails loudly if any test
here ever fell through to a real network call.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from university_jarvis.hub_web import create_app
from university_jarvis.intake_ledger import new_ledger
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


def _week_context(workflow: str) -> dict:
    """One PDF source + one PPTX source, so citation-format tests can prove
    both ", PDF p. N" and ", Slide N" survive the Hub boundary unchanged."""
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


def _assignment_context() -> dict:
    context = _week_context("ASSIGNMENT_COACH")
    context.pop("week")
    context.pop("items")
    context["weeks"] = [
        {"number": 1, "topic": None, "items": [], "source_ids": [PDF_SOURCE_ID, PPTX_SOURCE_ID]}
    ]
    return context


class FakeWorkflowProvider:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "fake-v1"}

    def generate_structured_output(self, context: dict, instructions: str, output_format: dict) -> dict:
        self.requests.append({"context": context, "instructions": instructions, "format": output_format})
        both_sources = [
            {"source_id": PDF_SOURCE_ID, "pdf_page": 3},
            {"source_id": PPTX_SOURCE_ID, "pdf_page": 5},
        ]
        if output_format["name"] == "quiz_brief":
            types = ("recall", "explanation", "application", "connection", "explanation", "application")
            questions = [
                {
                    "question_id": f"q{index}",
                    "question_type": question_type,
                    "question": f"Grounded {question_type} question {index}?",
                    "provenance": both_sources,
                }
                for index, question_type in enumerate(types, start=1)
            ]
            return {
                "questions": questions,
                "answers": [
                    {"question_id": q["question_id"], "answer": f"Answer to {q['question_id']}.", "provenance": both_sources}
                    for q in questions
                ],
            }
        return {
            field: [{"text": f"Grounded content for {field}.", "provenance": both_sources}]
            for field in output_format["schema"]["properties"]
        }


class NoCallProvider:
    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "cached-only-v1"}

    def generate_structured_output(self, *_a, **_kw):
        raise AssertionError("This action must not call the provider a second time")


class QuizReviseActionTests(unittest.TestCase):
    def _app(self, *, provider, cache_dir: Path) -> TestClient:
        app = create_app(
            state=_state_fixture(),
            ledger=new_ledger(),
            reasoning_provider=provider,
            cache_dir=cache_dir,
        )
        return TestClient(app)

    def test_get_quiz_and_revise_routes_are_not_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(provider=NoCallProvider(), cache_dir=Path(tmp))
            self.assertEqual(client.get("/modules/SYN101/weeks/1/quiz").status_code, 405)
            self.assertEqual(client.get("/modules/SYN101/weeks/1/revise").status_code, 405)

    def test_get_week_page_never_generates_a_quiz_or_revision_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(provider=NoCallProvider(), cache_dir=Path(tmp))
            response = client.get("/modules/SYN101/weeks/1")
        self.assertEqual(response.status_code, 200)

    def test_quiz_post_delegates_and_renders_with_both_citation_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeWorkflowProvider()
            client = self._app(provider=provider, cache_dir=Path(tmp))
            with patch("university_jarvis.hub_service.build_week_context", return_value=_week_context("QUIZ")):
                response = client.post("/modules/SYN101/weeks/1/quiz")

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertEqual(len(provider.requests), 1)
        self.assertIn("Questions", body)
        self.assertIn("Answers", body)
        self.assertIn("Grounded recall question", body)
        self.assertIn("PDF p. 3", body)
        self.assertIn("Slide 5", body)
        self.assertIn("Generated just now", body)

    def test_quiz_second_post_is_cached_and_never_calls_provider_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            provider = FakeWorkflowProvider()
            client = self._app(provider=provider, cache_dir=cache_dir)
            with patch("university_jarvis.hub_service.build_week_context", return_value=_week_context("QUIZ")):
                client.post("/modules/SYN101/weeks/1/quiz")
                second = client.post("/modules/SYN101/weeks/1/quiz")

        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(provider.requests), 1)
        self.assertIn("Reused a previously generated result", second.text)

    def test_revise_post_delegates_and_renders_section_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeWorkflowProvider()
            client = self._app(provider=provider, cache_dir=Path(tmp))
            with patch("university_jarvis.hub_service.build_week_context", return_value=_week_context("REVISE")):
                response = client.post("/modules/SYN101/weeks/1/revise")

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertEqual(len(provider.requests), 1)
        self.assertIn("Essential knowledge", body)
        self.assertIn("Key concepts", body)
        self.assertIn("Grounded content for essential_knowledge", body)
        self.assertIn("PDF p. 3", body)
        self.assertIn("Slide 5", body)

    def test_quiz_and_revise_on_unknown_module_or_week_fail_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(provider=NoCallProvider(), cache_dir=Path(tmp))
            for path in (
                "/modules/ZZFAKE/weeks/1/quiz",
                "/modules/ZZFAKE/weeks/1/revise",
                "/modules/SYN101/weeks/99/quiz",
            ):
                self.assertEqual(client.post(path).status_code, 404, path)

    def test_quiz_never_writes_to_the_workspace_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            cache_dir = Path(tmp) / "cache"
            app = create_app(
                state=_state_fixture(), ledger=new_ledger(), workspace_root=workspace_root,
                reasoning_provider=FakeWorkflowProvider(), cache_dir=cache_dir,
            )
            client = TestClient(app)
            with patch("university_jarvis.hub_service.build_week_context", return_value=_week_context("QUIZ")):
                client.post("/modules/SYN101/weeks/1/quiz")
            self.assertFalse(workspace_root.exists())

    def test_backend_state_error_is_rendered_honestly_not_as_a_crash(self) -> None:
        from university_jarvis.state import StateError

        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(provider=NoCallProvider(), cache_dir=Path(tmp))
            with patch(
                "university_jarvis.hub_service.build_week_context",
                side_effect=StateError("No Week 1 state for SYN101"),
            ):
                response = client.post("/modules/SYN101/weeks/1/quiz")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Action failed", response.text)
        self.assertIn("No Week 1 state for SYN101", response.text)


class AssignmentCoachActionTests(unittest.TestCase):
    def _app(self, *, provider, cache_dir: Path) -> TestClient:
        app = create_app(
            state=_state_fixture(), ledger=new_ledger(), reasoning_provider=provider, cache_dir=cache_dir,
        )
        return TestClient(app)

    def test_get_assignment_route_is_not_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(provider=NoCallProvider(), cache_dir=Path(tmp))
            self.assertEqual(client.get("/modules/SYN101/assignment").status_code, 405)

    def test_assignment_post_is_module_scoped_and_renders_section_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeWorkflowProvider()
            client = self._app(provider=provider, cache_dir=Path(tmp))
            with patch(
                "university_jarvis.hub_service.build_assignment_context",
                return_value=_assignment_context(),
            ):
                response = client.post("/modules/SYN101/assignment")

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertEqual(len(provider.requests), 1)
        self.assertIn("What the assignment is asking", body)
        self.assertIn("Marking criteria", body)
        self.assertIn("PDF p. 3", body)
        self.assertIn("Slide 5", body)
        self.assertNotIn("Action failed", body)

    def test_assignment_page_still_shows_module_weeks_and_assessments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeWorkflowProvider()
            client = self._app(provider=provider, cache_dir=Path(tmp))
            with patch(
                "university_jarvis.hub_service.build_assignment_context",
                return_value=_assignment_context(),
            ):
                response = client.post("/modules/SYN101/assignment")
        self.assertIn("Week 1", response.text)

    def test_assignment_on_unknown_module_fails_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(provider=NoCallProvider(), cache_dir=Path(tmp))
            self.assertEqual(client.post("/modules/ZZFAKE/assignment").status_code, 404)

    def test_assignment_never_writes_to_the_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            app = create_app(
                state=_state_fixture(), ledger=new_ledger(), workspace_root=workspace_root,
                reasoning_provider=FakeWorkflowProvider(), cache_dir=Path(tmp) / "cache",
            )
            client = TestClient(app)
            with patch(
                "university_jarvis.hub_service.build_assignment_context",
                return_value=_assignment_context(),
            ):
                client.post("/modules/SYN101/assignment")
            self.assertFalse(workspace_root.exists())


class ExistingHubFunctionalityStillIntactTests(unittest.TestCase):
    """A light regression check that Slice 4 did not disturb Slice 1-3 pages."""

    def test_home_modules_assessments_still_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(state=_state_fixture(), ledger=new_ledger(), workspace_root=Path(tmp) / "workspace")
            client = TestClient(app)
            for path in ("/", "/modules", "/assessments", "/check"):
                self.assertEqual(client.get(path).status_code, 200, path)


if __name__ == "__main__":
    unittest.main()
