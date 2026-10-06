"""Post-V1 visual redesign -- presentation-only guarantees.

Proves the redesign changed appearance, not truth: real counts only (no
invented metrics), no completion/urgency language, provenance/UNKNOWN/TBC
still present, existing action routes/forms unchanged, and basic
accessibility (skip link, focus-visible, reduced-motion) landed.

Synthetic fixtures only. No external call is possible: every route here is
either a plain GET or explicitly exercises a mocked/faked client, and the
global tests/conftest.py socket guard would fail loudly otherwise.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

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
            "university": "Test University", "programme": "BA Testing",
            "year_of_study": 2, "level": 5, "academic_year": "2025/26",
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
                    {"id": "a1", "title": "Essay", "category": "coursework",
                     "deadline": None, "deadline_status": "TBC", "weight_percent": 50},
                ],
            },
            {
                "code": "SYN102",
                "title": None,
                "semester": 1,
                "academic_year": "2025/26",
                "weeks": [{"week": 1, "date": None, "topic": None, "progress": "unknown", "source_ids": []}],
                "assessments": [],
            },
        ],
        "sources": [],
    }


_FORBIDDEN_ANYWHERE = (
    "productivity", "streak", "your score", "% complete", "percent complete",
    "overdue", "due soon", "recommended for you", "priority",
)


class RedesignHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = {
            "schema_version": 1,
            "modules": {
                "SYN101": {"weeks": {"1": {"documents": {
                    "doc-1": {"title": "Lecture slides", "last_seen_at": "2025-01-01T00:00:00+00:00", "attachments": {}}
                }}}}
            },
        }
        self.app = create_app(state=_state_fixture(), ledger=self.ledger)
        self.client = TestClient(self.app)

    def test_no_fabricated_metrics_or_urgency_language_anywhere(self) -> None:
        for path in ("/", "/modules", "/modules/SYN101", "/modules/SYN101/weeks/1", "/assessments", "/check"):
            body = self.client.get(path).text.lower()
            for word in _FORBIDDEN_ANYWHERE:
                self.assertNotIn(word, body, f"{word!r} found on {path}")

    def test_home_stat_tiles_reflect_real_counts_only(self) -> None:
        body = self.client.get("/").text
        # 2 real modules (headline stat), 3 real weeks (2 + 1, stat tile),
        # exactly as in the fixture.
        self.assertIn(">2<", body)  # module count in the hero headline stat
        self.assertIn('<div class="n">3</div>', body)  # weeks known

    def test_home_module_quicklinks_link_to_real_modules(self) -> None:
        body = self.client.get("/").text
        self.assertIn('href="/modules/SYN101"', body)
        self.assertIn('href="/modules/SYN102"', body)

    def test_modules_page_card_grid_preserves_unknown_title(self) -> None:
        body = self.client.get("/modules").text
        self.assertIn("SYN102", body)
        self.assertIn("Title unknown", body)  # SYN102's title is genuinely unknown

    def test_provenance_tags_survive_the_redesign(self) -> None:
        body = self.client.get("/modules/SYN101/weeks/1").text
        self.assertIn("Lecture slides", body)
        self.assertIn("No source match", body)
        self.assertIn("Course", body)
        self.assertIn("Blackboard", body)

    def test_week_unknown_study_state_is_never_rendered_as_not_studied(self) -> None:
        body = self.client.get("/modules/SYN101/weeks/2").text
        self.assertIn("No study record exists", body)
        self.assertNotIn("not studied", body.lower())

    def test_all_five_week_actions_still_present_as_forms(self) -> None:
        body = self.client.get("/modules/SYN101/weeks/1").text
        for action in ("/build", "/teach", "/quiz", "/revise", "/after-lecture"):
            self.assertIn(f'action="/modules/SYN101/weeks/1{action}"', body)

    def test_assignment_coach_form_still_present(self) -> None:
        body = self.client.get("/modules/SYN101").text
        self.assertIn('action="/modules/SYN101/assignment"', body)


class RedesignAccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(state=_state_fixture(), ledger=new_ledger())
        self.client = TestClient(self.app)

    def test_skip_link_present(self) -> None:
        body = self.client.get("/").text
        self.assertIn("skip-link", body)
        self.assertIn('href="#main"', body)
        self.assertIn('id="main"', body)

    def test_focus_visible_rule_present(self) -> None:
        body = self.client.get("/").text
        self.assertIn(":focus-visible", body)

    def test_reduced_motion_media_query_present(self) -> None:
        body = self.client.get("/").text
        self.assertIn("prefers-reduced-motion", body)

    def test_viewport_and_dark_color_scheme_present(self) -> None:
        body = self.client.get("/").text
        self.assertIn('name="viewport"', body)
        self.assertIn("color-scheme: dark", body)

    def test_no_get_route_makes_any_external_or_write_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch

            workspace_root = Path(tmp) / "workspace"
            app = create_app(state=_state_fixture(), ledger=new_ledger(), workspace_root=workspace_root)
            client = TestClient(app)

            def _boom(*_a, **_kw):
                raise AssertionError("GET must remain side-effect free")

            with patch("university_jarvis.hub_service.check_university", side_effect=_boom), \
                 patch("university_jarvis.workspace.materialize_week_workspace", side_effect=_boom), \
                 patch("university_jarvis.workspace.teach_week", side_effect=_boom), \
                 patch("socket.socket.connect", side_effect=_boom):
                for path in ("/", "/modules", "/modules/SYN101", "/modules/SYN101/weeks/1", "/assessments", "/check"):
                    self.assertEqual(client.get(path).status_code, 200, path)
            self.assertFalse(workspace_root.exists())


if __name__ == "__main__":
    unittest.main()
