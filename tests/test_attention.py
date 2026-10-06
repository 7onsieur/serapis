from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.academic_picture import build_academic_picture
from university_jarvis.attention import (
    KNOWN_ASSESSMENT,
    OPEN_UNRESOLVED_ITEM,
    STUDY_STATE_UNKNOWN,
    build_attention_picture,
    render_attention_text,
)
from university_jarvis.cli import main

from tests.test_academic_picture import _minimal_mission


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
        "progress": {"overall_status": "unknown", "last_updated": None},
        "modules": [
            {
                "code": "SYN101",
                "title": "State-only assessment module",
                "semester": 1,
                "academic_year": "2025/26",
                "teaching": {},
                "assessments": [
                    {
                        "id": "syn101-essay",
                        "title": "Essay",
                        "category": "ASSESSMENT",
                        "deadline": "2025-02-01",
                        "deadline_status": None,
                        "weight_percent": 50,
                    }
                ],
                "progress": {"status": "unknown", "completed_week_numbers": [], "last_consolidated_week": None},
                "weeks": [],
            },
            {
                "code": "SYN102",
                "title": "Both-sources module",
                "semester": 1,
                "academic_year": "2025/26",
                "teaching": {},
                "assessments": [
                    {
                        "id": "syn102-formative",
                        "title": "Formative plan",
                        "category": "ASSESSMENT",
                        "deadline": "2025-02-01",
                        "deadline_status": "TBC",
                        "weight_percent": None,
                    }
                ],
                "progress": {"status": "unknown", "completed_week_numbers": [], "last_consolidated_week": None},
                "weeks": [
                    {
                        "week": 1,
                        "date": None,
                        "topic": "Recorded week",
                        "progress": "unknown",
                        "source_ids": [],
                        "items": [],
                    },
                    {
                        "week": 2,
                        "date": None,
                        "topic": "Unrecorded week",
                        "progress": "unknown",
                        "source_ids": [],
                        "items": [],
                    },
                ],
            },
        ],
        "sources": [],
    }


def _ledger_fixture() -> dict:
    return {
        "schema_version": 1,
        "modules": {
            "SYN102": {
                "weeks": {
                    "1": {
                        "documents": {
                            "_c1": {
                                "content_id": "_c1",
                                "title": "Week 1 lesson",
                                "attachments": {
                                    "Week1.pdf": {
                                        "content_sha256": "aaa",
                                        "file_name": "Week1.pdf",
                                        "first_seen_at": "2025-01-02T00:00:00Z",
                                        "last_changed_at": "2025-01-02T00:00:00Z",
                                        "last_seen_at": "2025-01-02T00:00:00Z",
                                    }
                                },
                            }
                        }
                    },
                    "2": {
                        "documents": {
                            "_c2": {
                                "content_id": "_c2",
                                "title": "Week 2 lesson",
                                "attachments": {
                                    "Week2.pptx": {
                                        "content_sha256": "bbb",
                                        "file_name": "Week2.pptx",
                                        "first_seen_at": "2025-01-02T00:00:00Z",
                                        "last_changed_at": "2025-01-02T00:00:00Z",
                                        "last_seen_at": "2025-01-02T00:00:00Z",
                                    }
                                },
                            }
                        }
                    },
                }
            },
            "SYN103": {
                "weeks": {
                    "1": {
                        "documents": {
                            "_c3": {
                                "content_id": "_c3",
                                "title": "Week 1 lesson",
                                "attachments": {
                                    "SYN103-Lecture1.pdf": {
                                        "content_sha256": "ccc",
                                        "file_name": "SYN103-Lecture1.pdf",
                                        "first_seen_at": "2025-01-02T00:00:00Z",
                                        "last_changed_at": "2025-01-02T00:00:00Z",
                                        "last_seen_at": "2025-01-02T00:00:00Z",
                                    }
                                },
                            }
                        }
                    }
                }
            },
            "SYN104": {"weeks": {"1": {"documents": {}}}},
        },
    }


def _record_fixture(open_item: bool) -> dict:
    return {
        "workspace_schema_version": 3,
        "record_type": "academic_week",
        "module": {"code": "SYN102", "title": "Both-sources module"},
        "week": {"number": 1, "date": None, "topic": None, "declared_progress": "unknown"},
        "sources": [],
        "workflows": {
            "prepare_me": {"status": "completed"},
            "after_lecture": {"status": "not_recorded", "captures": []},
            "teach": {"status": "not_recorded", "interactions": []},
            "quiz": {"status": "not_recorded"},
            "revise": {"status": "not_recorded"},
        },
        "learning": {
            "unresolved_items": (
                {"status": "open", "items": [{"kind": "question", "text": "Still unclear."}]}
                if open_item
                else {"status": "none_recorded", "items": []}
            )
        },
    }


class AttentionBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace_root = Path(self.tmp.name) / "workspace"
        record_dir = self.workspace_root / "SYN102" / "week-01"
        record_dir.mkdir(parents=True)
        (record_dir / "academic-record.json").write_text(
            json.dumps(_record_fixture(open_item=True)), encoding="utf-8"
        )

        self.state = _state_fixture()
        self.ledger = _ledger_fixture()
        self.picture = build_academic_picture(
            state=self.state, ledger=self.ledger, workspace_root=self.workspace_root
        )
        self.attention = build_attention_picture(self.picture)

    def test_observed_material_without_record_yields_study_state_unknown(self) -> None:
        weeks = {(i.module_code, i.week) for i in self.attention.study_state_unknown}
        self.assertIn(("SYN102", 2), weeks)
        self.assertIn(("SYN103", 1), weeks)

    def test_missing_record_never_claims_not_studied(self) -> None:
        rendered = render_attention_text(self.attention)
        for phrase in ("not studied", "unfinished", "overdue", "needs studying"):
            self.assertNotIn(phrase, rendered.lower())

    def test_week_with_record_not_flagged_despite_not_recorded_workflows(self) -> None:
        weeks = {(i.module_code, i.week) for i in self.attention.study_state_unknown}
        self.assertNotIn(("SYN102", 1), weeks)

    def test_open_unresolved_item_surfaced(self) -> None:
        self.assertEqual(len(self.attention.open_unresolved_items), 1)
        item = self.attention.open_unresolved_items[0]
        self.assertEqual(item.module_code, "SYN102")
        self.assertEqual(item.week, 1)
        self.assertEqual(item.kind, OPEN_UNRESOLVED_ITEM)
        self.assertIn("Still unclear.", item.description)

    def test_non_open_unresolved_item_not_surfaced(self) -> None:
        other_dir = self.workspace_root / "SYN104" / "week-01"
        other_dir.mkdir(parents=True)
        (other_dir / "academic-record.json").write_text(
            json.dumps(_record_fixture(open_item=False)), encoding="utf-8"
        )
        state = self.state
        picture = build_academic_picture(
            state=state, ledger=self.ledger, workspace_root=self.workspace_root
        )
        attention = build_attention_picture(picture)
        modules_with_open_items = {i.module_code for i in attention.open_unresolved_items}
        self.assertNotIn("SYN104", modules_with_open_items)

    def test_multiple_modules_weeks_aggregate(self) -> None:
        modules_seen = {i.module_code for i in self.attention.study_state_unknown}
        self.assertEqual(modules_seen, {"SYN102", "SYN103"})

    def test_assessment_tbc_preserved(self) -> None:
        syn102 = [i for i in self.attention.known_assessments if i.module_code == "SYN102"]
        self.assertEqual(len(syn102), 1)
        self.assertEqual(syn102[0].kind, KNOWN_ASSESSMENT)
        self.assertIn("[TBC]", syn102[0].description)
        self.assertEqual(syn102[0].evidence["deadline_status"], "TBC")

    def test_assessment_recorded_deadline_no_urgency_language(self) -> None:
        syn101 = [i for i in self.attention.known_assessments if i.module_code == "SYN101"]
        self.assertEqual(len(syn101), 1)
        description = syn101[0].description.lower()
        for phrase in ("due soon", "overdue", "urgent", "priority"):
            self.assertNotIn(phrase, description)
        self.assertIn("2025-02-01", syn101[0].description)

    def test_ledger_only_module_works(self) -> None:
        weeks = {(i.module_code, i.week) for i in self.attention.study_state_unknown}
        self.assertIn(("SYN103", 1), weeks)

    def test_state_only_assessment_works(self) -> None:
        syn101 = [i for i in self.attention.known_assessments if i.module_code == "SYN101"]
        self.assertEqual(len(syn101), 1)

    def test_deterministic_ordering(self) -> None:
        first = render_attention_text(self.attention)
        second_picture = build_academic_picture(
            state=self.state, ledger=self.ledger, workspace_root=self.workspace_root
        )
        second = render_attention_text(build_attention_picture(second_picture))
        self.assertEqual(first, second)

    def test_no_input_mutation(self) -> None:
        record_path = self.workspace_root / "SYN102" / "week-01" / "academic-record.json"
        before = record_path.read_bytes()
        build_attention_picture(self.picture)
        self.assertEqual(record_path.read_bytes(), before)

    def test_no_external_imports(self) -> None:
        import university_jarvis.attention as attention_module

        source = Path(attention_module.__file__).read_text(encoding="utf-8")
        for forbidden in ("blackboard", "drive", "reasoning", "requests", "urllib", "socket"):
            self.assertNotIn(forbidden, source.lower())


class AttentionCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state_path = root / "academic-state.json"
        self.ledger_path = root / "intake-ledger.json"
        self.workspace_root = root / "workspace"
        record_dir = self.workspace_root / "SYN102" / "week-01"
        record_dir.mkdir(parents=True)
        (record_dir / "academic-record.json").write_text(
            json.dumps(_record_fixture(open_item=True)), encoding="utf-8"
        )
        self.state_path.write_text(json.dumps(_state_fixture()), encoding="utf-8")
        self.ledger_path.write_text(json.dumps(_ledger_fixture()), encoding="utf-8")

        self._env_patch = {
            "JARVIS_STATE_FILE": str(self.state_path),
            "JARVIS_LEDGER_FILE": str(self.ledger_path),
        }
        self._old_env = {key: os.environ.get(key) for key in self._env_patch}
        os.environ.update(self._env_patch)
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_cli_attention_deterministic_and_no_mutation(self) -> None:
        before_state = self.state_path.read_bytes()
        before_ledger = self.ledger_path.read_bytes()

        buf1 = io.StringIO()
        with redirect_stdout(buf1):
            exit_code = main(["attention"], workspace_root=self.workspace_root)
        self.assertEqual(exit_code, 0)

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            main(["attention"], workspace_root=self.workspace_root)

        self.assertEqual(buf1.getvalue(), buf2.getvalue())
        self.assertIn("Study state unknown", buf1.getvalue())
        self.assertIn("Open unresolved items", buf1.getvalue())
        self.assertIn("Known assessments", buf1.getvalue())
        self.assertEqual(self.state_path.read_bytes(), before_state)
        self.assertEqual(self.ledger_path.read_bytes(), before_ledger)

    def test_existing_picture_command_unchanged(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main(["picture"], workspace_root=self.workspace_root)
        self.assertEqual(exit_code, 0)
        self.assertIn("academic picture (read-only)", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
