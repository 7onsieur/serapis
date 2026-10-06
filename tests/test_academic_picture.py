from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.academic_picture import (
    DERIVED_WORKSPACE,
    MACHINE_OBSERVED,
    STUDENT_ENTERED,
    UNLINKED,
    build_academic_picture,
    render_picture_text,
)
from university_jarvis.cli import main


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
        "progress": {"overall_status": "LEGACY-SENTINEL-VALUE", "last_updated": None},
        "modules": [
            {
                "code": "SYN101",
                "title": "State-only module",
                "semester": 1,
                "academic_year": "2025/26",
                "teaching": {},
                "assessments": [],
                "progress": {
                    "status": "LEGACY-SENTINEL-VALUE",
                    "completed_week_numbers": [1],
                    "last_consolidated_week": 1,
                },
                "weeks": [
                    {
                        "week": 1,
                        "date": None,
                        "topic": "State-only topic",
                        "progress": "LEGACY-SENTINEL-VALUE",
                        "source_ids": [],
                        "items": [
                            {
                                "category": "DO",
                                "text": "Read something.",
                                "source_ids": [],
                                "status": "LEGACY-SENTINEL-VALUE",
                            }
                        ],
                    }
                ],
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
                "progress": {
                    "status": "LEGACY-SENTINEL-VALUE",
                    "completed_week_numbers": [],
                    "last_consolidated_week": None,
                },
                "weeks": [
                    {
                        "week": 1,
                        "date": None,
                        "topic": "Both-source topic",
                        "progress": "LEGACY-SENTINEL-VALUE",
                        "source_ids": [],
                        "items": [],
                    }
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
                            "_content_1": {
                                "content_handler": "resource/x-bb-document",
                                "content_id": "_content_1",
                                "title": "Week 1 lesson",
                                "created": "2025-01-01T00:00:00Z",
                                "modified": "2025-01-01T00:00:00Z",
                                "last_seen_at": "2025-01-02T22:13:50+00:00",
                                "source_path": [],
                                "attachments": {
                                    "Lecture1.pdf": {
                                        "content_sha256": "deadbeef",
                                        "file_name": "Lecture1.pdf",
                                        "first_seen_at": "2025-01-02T22:13:23+00:00",
                                        "last_changed_at": "2025-01-02T22:13:23+00:00",
                                        "last_seen_at": "2025-01-02T22:13:50+00:00",
                                    }
                                },
                            }
                        }
                    },
                    "2": {"documents": {}},
                }
            },
            "SYN103": {
                "weeks": {
                    "1": {"documents": {}},
                }
            },
        },
    }


def _academic_record_fixture() -> dict:
    return {
        "workspace_schema_version": 3,
        "record_type": "academic_week",
        "module": {"code": "SYN102", "title": "Both-sources module"},
        "week": {"number": 1, "date": None, "topic": None, "declared_progress": "unknown"},
        "sources": [],
        "workflows": {
            "prepare_me": {"status": "completed"},
            "after_lecture": {"status": "recorded", "captures": []},
            "teach": {"status": "not_recorded", "interactions": []},
            "quiz": {"status": "not_recorded"},
            "revise": {"status": "not_recorded"},
        },
        "learning": {
            "unresolved_items": {
                "status": "open",
                "items": [{"kind": "question", "text": "Still unclear on X."}],
            }
        },
    }


class AcademicPictureBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace_root = Path(self.tmp.name) / "workspace"
        record_dir = self.workspace_root / "SYN102" / "week-01"
        record_dir.mkdir(parents=True)
        (record_dir / "academic-record.json").write_text(
            json.dumps(_academic_record_fixture()), encoding="utf-8"
        )

        self.state = _state_fixture()
        self.ledger = _ledger_fixture()
        self.picture = build_academic_picture(
            state=self.state, ledger=self.ledger, workspace_root=self.workspace_root
        )

    def _module(self, code: str):
        for module in self.picture.modules:
            if module.module_code == code:
                return module
        raise AssertionError(f"module {code} not in picture")

    def _week(self, module_code: str, week: int):
        module = self._module(module_code)
        for w in module.weeks:
            if w.week == week:
                return w
        raise AssertionError(f"week {week} not in module {module_code}")

    def test_module_only_in_academic_state(self) -> None:
        module = self._module("SYN101")
        self.assertTrue(module.in_academic_state)
        self.assertFalse(module.in_intake_ledger)

    def test_module_only_in_intake_ledger(self) -> None:
        module = self._module("SYN103")
        self.assertFalse(module.in_academic_state)
        self.assertTrue(module.in_intake_ledger)

    def test_week_present_in_both(self) -> None:
        week = self._week("SYN102", 1)
        self.assertTrue(week.in_academic_state)
        self.assertTrue(week.in_intake_ledger)

    def test_week_only_in_ledger_not_in_state(self) -> None:
        week = self._week("SYN102", 2)
        self.assertFalse(week.in_academic_state)
        self.assertTrue(week.in_intake_ledger)

    def test_machine_material_remains_unlinked(self) -> None:
        week = self._week("SYN102", 1)
        self.assertEqual(len(week.materials), 1)
        material = week.materials[0]
        self.assertEqual(material.provenance, MACHINE_OBSERVED)
        self.assertEqual(material.linkage_status, UNLINKED)
        self.assertEqual(material.filename, "Lecture1.pdf")

    def test_assessment_deadline_status_tbc_preserved_exactly(self) -> None:
        module = self._module("SYN102")
        self.assertEqual(len(module.assessments), 1)
        assessment = module.assessments[0]
        self.assertEqual(assessment.deadline, "2025-02-01")
        self.assertEqual(assessment.deadline_status, "TBC")
        self.assertEqual(assessment.provenance, STUDENT_ENTERED)

    def test_existing_workflow_statuses_surfaced_exactly(self) -> None:
        week = self._week("SYN102", 1)
        study_state = week.study_state
        self.assertTrue(study_state.record_found)
        self.assertEqual(study_state.provenance, DERIVED_WORKSPACE)
        self.assertEqual(
            study_state.workflow_statuses,
            {
                "prepare_me": "completed",
                "after_lecture": "recorded",
                "teach": "not_recorded",
                "quiz": "not_recorded",
                "revise": "not_recorded",
            },
        )

    def test_unresolved_items_surfaced(self) -> None:
        week = self._week("SYN102", 1)
        study_state = week.study_state
        self.assertEqual(study_state.unresolved_items_status, "open")
        self.assertEqual(len(study_state.unresolved_items), 1)
        self.assertEqual(study_state.unresolved_items[0]["text"], "Still unclear on X.")

    def test_missing_academic_record_is_not_treated_as_not_studied(self) -> None:
        week = self._week("SYN101", 1)
        study_state = week.study_state
        self.assertFalse(study_state.record_found)
        self.assertEqual(study_state.workflow_statuses, {})
        rendered = render_picture_text(self.picture)
        self.assertIn("no academic-record.json found", rendered)
        self.assertNotIn("not studied\"", rendered.replace("(unknown whether studied, not \"not studied\").", ""))

    def test_legacy_progress_fields_excluded_from_picture(self) -> None:
        rendered = render_picture_text(self.picture)
        self.assertNotIn("LEGACY-SENTINEL-VALUE", rendered)
        for module in self.picture.modules:
            self.assertFalse(hasattr(module, "progress"))
            for week in module.weeks:
                self.assertFalse(hasattr(week, "progress"))

    def test_render_is_deterministic(self) -> None:
        first = render_picture_text(self.picture)
        second = render_picture_text(
            build_academic_picture(
                state=copy.deepcopy(self.state),
                ledger=copy.deepcopy(self.ledger),
                workspace_root=self.workspace_root,
            )
        )
        self.assertEqual(first, second)

    def test_no_input_files_mutated(self) -> None:
        state_path = Path(self.tmp.name) / "academic-state.json"
        ledger_path = Path(self.tmp.name) / "intake-ledger.json"
        state_path.write_text(json.dumps(self.state, sort_keys=True), encoding="utf-8")
        ledger_path.write_text(json.dumps(self.ledger, sort_keys=True), encoding="utf-8")
        before_state = state_path.read_bytes()
        before_ledger = ledger_path.read_bytes()
        record_path = self.workspace_root / "SYN102" / "week-01" / "academic-record.json"
        before_record = record_path.read_bytes()

        build_academic_picture(
            state=json.loads(before_state),
            ledger=json.loads(before_ledger),
            workspace_root=self.workspace_root,
        )

        self.assertEqual(state_path.read_bytes(), before_state)
        self.assertEqual(ledger_path.read_bytes(), before_ledger)
        self.assertEqual(record_path.read_bytes(), before_record)


class AcademicPictureCliTests(unittest.TestCase):
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
            json.dumps(_academic_record_fixture()), encoding="utf-8"
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

    def test_cli_picture_output_is_deterministic_and_does_not_mutate_inputs(self) -> None:
        before_state = self.state_path.read_bytes()
        before_ledger = self.ledger_path.read_bytes()

        buf1 = io.StringIO()
        with redirect_stdout(buf1):
            exit_code = main(["picture"], workspace_root=self.workspace_root)
        self.assertEqual(exit_code, 0)

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            main(["picture"], workspace_root=self.workspace_root)

        self.assertEqual(buf1.getvalue(), buf2.getvalue())
        self.assertIn("SYN102", buf1.getvalue())
        self.assertIn("TBC", buf1.getvalue())
        self.assertIn("UNLINKED", buf1.getvalue())
        self.assertEqual(self.state_path.read_bytes(), before_state)
        self.assertEqual(self.ledger_path.read_bytes(), before_ledger)


if __name__ == "__main__":
    unittest.main()
