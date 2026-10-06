"""Hub Slice 2: the local, read-only web shell -- route/render tests.

Every test here uses synthetic state/ledger/workspace fixtures only, never
the real (gitignored) data/workspace files. A dedicated ``_forbid_external``
context manager patches every real entry point to a Blackboard, Drive, or
model call so that if any route ever reached one, the test would fail loudly
instead of silently succeeding against a fake.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from university_jarvis.hub_web import create_app
from university_jarvis.intake_ledger import new_ledger


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
                "weeks": [
                    {"week": 1, "date": None, "topic": "Intro", "progress": "unknown", "source_ids": []},
                    {"week": 2, "date": None, "topic": None, "progress": "unknown", "source_ids": []},
                ],
                "assessments": [
                    {
                        "id": "a1",
                        "title": "Essay",
                        "category": "coursework",
                        "deadline": None,
                        "deadline_status": "TBC",
                        "weight_percent": 50,
                    },
                    {
                        "id": "a2",
                        "title": "Exam",
                        "category": "exam",
                        "deadline": "2027-05-01",
                        "deadline_status": None,
                        "weight_percent": 50,
                    },
                ],
            }
        ],
        "sources": [],
    }


def _ledger_fixture() -> dict:
    ledger = new_ledger()
    ledger["modules"] = {
        "SYN101": {
            "weeks": {
                "1": {
                    "documents": {
                        "doc-1": {
                            "title": "Lecture slides",
                            "last_seen_at": "2025-01-01T00:00:00+00:00",
                            "attachments": {},
                        }
                    }
                }
            }
        },
        # Ledger-only module: never appears in academic-state.json.
        "SYN109": {"weeks": {"1": {"documents": {}}}},
    }
    return ledger


def _forbid_external() -> ExitStack:
    """Patch every real Blackboard/Drive/model entry point to raise if reached."""

    def _boom(*_args, **_kwargs):
        raise AssertionError("Hub read routes must never trigger an external call")

    stack = ExitStack()
    stack.enter_context(patch("university_jarvis.university.check_university", side_effect=_boom))
    stack.enter_context(
        patch("university_jarvis.workspace.materialize_week_workspace", side_effect=_boom)
    )
    stack.enter_context(patch("university_jarvis.workspace.teach_week", side_effect=_boom))
    stack.enter_context(
        patch("university_jarvis.workspace.capture_after_lecture", side_effect=_boom)
    )
    stack.enter_context(
        patch(
            "university_jarvis.reasoning.OpenAIReasoningProvider.generate_structured_output",
            side_effect=_boom,
        )
    )
    stack.enter_context(
        patch("university_jarvis.blackboard_browser.open_browser_client", side_effect=_boom)
    )
    stack.enter_context(
        patch("university_jarvis.blackboard_browser.run_interactive_authentication", side_effect=_boom)
    )
    stack.enter_context(
        patch("university_jarvis.credentials.get_blackboard_session_cookie", side_effect=_boom)
    )
    stack.enter_context(patch("university_jarvis.credentials.get_openai_api_key", side_effect=_boom))
    stack.enter_context(
        patch("university_jarvis.credentials.get_google_drive_token_json", side_effect=_boom)
    )
    stack.enter_context(patch("socket.socket.connect", side_effect=_boom))
    return stack


class HubWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace_root = Path(self._tmp.name) / "workspace"
        self.state = _state_fixture()
        self.ledger = _ledger_fixture()
        self.forbid = _forbid_external()
        self.addCleanup(self.forbid.close)
        self.app = create_app(
            state=self.state, ledger=self.ledger, workspace_root=self.workspace_root
        )
        self.client = TestClient(self.app)

    def test_home_renders_attention_with_tbc_and_no_urgency_language(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("Attention", body)
        self.assertIn("Study state unknown", body)
        self.assertIn("Open unresolved items", body)
        self.assertIn("Known assessments", body)
        self.assertIn("TBC", body)
        self.assertIn("Lecture slides", body)  # STUDY_STATE_UNKNOWN evidence
        for forbidden in ("overdue", "due soon", "urgent", "recommend", "priority"):
            self.assertNotIn(forbidden, body.lower())

    def test_home_never_creates_the_workspace_directory(self) -> None:
        self.client.get("/")
        self.assertFalse(self.workspace_root.exists())

    def test_modules_lists_state_and_ledger_only_modules_without_crashing(self) -> None:
        response = self.client.get("/modules")
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("SYN101", body)
        self.assertIn("SYN109", body)  # ledger-only module renders safely

    def test_module_detail_shows_weeks_and_unknown_topic(self) -> None:
        response = self.client.get("/modules/SYN101")
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("Week 1", body)
        self.assertIn("Week 2", body)
        self.assertIn("UNKNOWN", body)  # week 2 has no topic

    def test_module_detail_lowercase_code_resolves(self) -> None:
        response = self.client.get("/modules/syn101")
        self.assertEqual(response.status_code, 200)
        self.assertIn("SYN101", response.text)

    def test_ledger_only_module_detail_renders_without_academic_state(self) -> None:
        response = self.client.get("/modules/SYN109")
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("SYN109", body)
        self.assertIn("No assessments are recorded", body)

    def test_unknown_module_is_404(self) -> None:
        response = self.client.get("/modules/ZZFAKE")
        self.assertEqual(response.status_code, 404)

    def test_week_detail_shows_material_and_unknown_study_state_not_not_studied(self) -> None:
        response = self.client.get("/modules/SYN101/weeks/1")
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("Lecture slides", body)
        self.assertIn("No source match", body)
        self.assertIn("No study record exists", body)
        self.assertNotIn("not studied", body.lower())

    def test_week_detail_with_neither_source_is_404(self) -> None:
        response = self.client.get("/modules/SYN101/weeks/99")
        self.assertEqual(response.status_code, 404)

    def test_assessments_page_preserves_tbc_and_known_deadline(self) -> None:
        response = self.client.get("/assessments")
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("Essay", body)
        self.assertIn("TBC", body)
        self.assertIn("Exam", body)
        self.assertIn("2027-05-01", body)

    def test_navigation_links_present_on_every_page(self) -> None:
        for path in ("/", "/modules", "/assessments"):
            body = self.client.get(path).text
            self.assertIn('href="/"', body)
            self.assertIn('href="/modules"', body)
            self.assertIn('href="/assessments"', body)

    def test_home_is_deterministic_across_repeated_requests(self) -> None:
        first = self.client.get("/").text
        second = self.client.get("/").text
        self.assertEqual(first, second)

    def test_no_academic_record_ever_written_by_any_get_route(self) -> None:
        for path in ("/", "/modules", "/modules/SYN101", "/modules/SYN101/weeks/1", "/assessments"):
            self.client.get(path)
        self.assertFalse(self.workspace_root.exists())


class HubWebRealisticGapTests(unittest.TestCase):
    """A module known only to academic-state.json, with a week that already
    has an academic-record.json, must render its real workflow state."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace_root = Path(self._tmp.name) / "workspace"
        record_dir = self.workspace_root / "SYN101" / "week-01"
        record_dir.mkdir(parents=True)
        record = {
            "workspace_schema_version": 3,
            "record_type": "academic_week",
            "module": {"code": "SYN101", "title": "State-only module", "semester": 1, "academic_year": "2025/26"},
            "week": {"number": 1, "date": None, "topic": "Intro", "declared_progress": "unknown"},
            "sources": [],
            "workflows": {
                "prepare_me": {"status": "completed", "result": {}},
                "after_lecture": {"status": "not_recorded", "captures": []},
                "teach": {"status": "not_recorded", "interactions": []},
                "quiz": {"status": "not_recorded"},
                "revise": {"status": "not_recorded"},
            },
            "learning": {"unresolved_items": {"status": "none_recorded", "items": []}},
        }
        (record_dir / "academic-record.json").write_text(json.dumps(record), encoding="utf-8")
        self.forbid = _forbid_external()
        self.addCleanup(self.forbid.close)
        self.app = create_app(
            state=_state_fixture(), ledger=new_ledger(), workspace_root=self.workspace_root
        )
        self.client = TestClient(self.app)

    def test_week_with_existing_record_shows_prepare_me_completed(self) -> None:
        response = self.client.get("/modules/SYN101/weeks/1")
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("prepare_me", body)
        self.assertIn("completed", body)
        self.assertNotIn("No study record exists", body)


if __name__ == "__main__":
    unittest.main()
