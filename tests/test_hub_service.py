"""Hub Slice 1: the structured service boundary over the existing backend."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis import hub_service
from university_jarvis.academic_picture import (
    DERIVED_WORKSPACE,
    MACHINE_OBSERVED,
    STUDENT_ENTERED,
    UNLINKED,
)
from university_jarvis.blackboard import (
    BlackboardClient,
    BlackboardSession,
    HttpResponse,
    sources_destination,
)
from university_jarvis.intake_ledger import new_ledger
from university_jarvis.reasoning import TokenUsage, generate_prepare_brief
from university_jarvis.workspace import capture_after_lecture, materialize_week_workspace


SOURCE_ID = "syn101-w01-lecture-01-pdf"
BASE = "https://blackboard.example.test/learn/api/public/v1"


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
                    {
                        "week": 1,
                        "date": None,
                        "topic": "Intro",
                        "progress": "unknown",
                        "source_ids": [],
                    }
                ],
                "assessments": [
                    {
                        "id": "a1",
                        "title": "Essay",
                        "category": "coursework",
                        "deadline": None,
                        "deadline_status": "TBC",
                        "weight_percent": 50,
                    }
                ],
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
        "module": {
            "code": "SYN101",
            "title": "Introduction to Example Studies",
            "semester": 1,
            "academic_year": "2025/26",
        },
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
        "week_overview",
        "before_class",
        "core_concepts",
        "examples_cases",
        "lecture_attention",
        "after_class_questions",
        "assessment_connections",
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
        raise AssertionError("hub_service.materialize_workspace must never call the provider on a cache hit")


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


class ReadOnlyBoundaryTests(unittest.TestCase):
    def test_get_academic_picture_delegates_and_preserves_provenance(self) -> None:
        state = _state_fixture()
        ledger = new_ledger()
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            picture = hub_service.get_academic_picture(
                state=state, ledger=ledger, workspace_root=workspace_root
            )

        self.assertEqual([m["module_code"] for m in picture["modules"]], ["SYN101"])
        module = picture["modules"][0]
        self.assertTrue(module["in_academic_state"])
        self.assertFalse(module["in_intake_ledger"])
        self.assertEqual(module["assessments"][0]["deadline_status"], "TBC")
        self.assertEqual(module["assessments"][0]["provenance"], STUDENT_ENTERED)
        week = module["weeks"][0]
        self.assertFalse(week["study_state"]["record_found"])  # no academic-record.json exists
        self.assertEqual(week["study_state"]["provenance"], DERIVED_WORKSPACE)
        self.assertEqual(week["materials"], [])
        # Every value must already be JSON-plain -- no Path/dataclass survives.
        json.dumps(picture)

    def test_get_academic_picture_never_creates_the_workspace_directory(self) -> None:
        state = _state_fixture()
        ledger = new_ledger()
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "does-not-exist-yet"
            hub_service.get_academic_picture(
                state=state, ledger=ledger, workspace_root=workspace_root
            )
            self.assertFalse(workspace_root.exists())

    def test_get_attention_reports_known_assessment_with_tbc_intact(self) -> None:
        state = _state_fixture()
        ledger = new_ledger()
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            attention = hub_service.get_attention(
                state=state, ledger=ledger, workspace_root=workspace_root
            )

        self.assertEqual(attention["study_state_unknown"], [])
        self.assertEqual(attention["open_unresolved_items"], [])
        self.assertEqual(len(attention["known_assessments"]), 1)
        known = attention["known_assessments"][0]
        self.assertEqual(known["kind"], "KNOWN_ASSESSMENT")
        self.assertIn("TBC", known["description"])
        self.assertEqual(known["evidence"]["deadline_status"], "TBC")
        json.dumps(attention)

    def test_get_attention_surfaces_study_state_unknown_from_materials_without_writing(self) -> None:
        state = _state_fixture()
        ledger = {
            "schema_version": 1,
            "modules": {
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
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            attention = hub_service.get_attention(
                state=state, ledger=ledger, workspace_root=workspace_root
            )
            self.assertFalse(workspace_root.exists())

        self.assertEqual(len(attention["study_state_unknown"]), 1)
        gap = attention["study_state_unknown"][0]
        self.assertEqual(gap["kind"], "STUDY_STATE_UNKNOWN")
        self.assertEqual(gap["module_code"], "SYN101")
        self.assertEqual(gap["evidence"]["observed_material"], ["Lecture slides"])


class LocalWriteBoundaryTests(unittest.TestCase):
    def _seed_cache_and_materialize(self, root: Path) -> tuple[Path, Path]:
        cache_dir = root / "cache"
        workspace_root = root / "workspace"
        generate_prepare_brief(prepare_context(), SeedProvider(), cache_dir)
        with patch(
            "university_jarvis.workspace.build_prepare_context",
            return_value=prepare_context(),
        ):
            materialize_week_workspace(
                {}, "SYN101", 1, provider=NoCallProvider(), cache_dir=cache_dir, workspace_root=workspace_root
            )
        return cache_dir, workspace_root

    def test_capture_after_lecture_note_is_local_write_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _cache_dir, workspace_root = self._seed_cache_and_materialize(root)

            result = hub_service.capture_after_lecture_note(
                "SYN101",
                1,
                questions=["What is the exam format?"],
                workspace_root=workspace_root,
                captured_at="2025-01-03T09:00:00+00:00",
            )

        self.assertEqual(result["capture_id"], "capture-0001")
        self.assertEqual(result["captured_at"], "2025-01-03T09:00:00+00:00")
        self.assertIsInstance(result["record_path"], str)
        self.assertIsInstance(result["study_pack_path"], str)
        self.assertIsInstance(result["notebooklm_path"], str)
        json.dumps(result)

    def test_capture_after_lecture_note_requires_prior_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspace"
            with self.assertRaises(Exception):
                hub_service.capture_after_lecture_note(
                    "SYN101", 1, questions=["Anything?"], workspace_root=workspace_root
                )


class ExternalActionBoundaryTests(unittest.TestCase):
    def test_materialize_workspace_uses_cache_and_never_calls_provider_on_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            generate_prepare_brief(prepare_context(), SeedProvider(), cache_dir)

            with patch(
                "university_jarvis.workspace.build_prepare_context",
                return_value=prepare_context(),
            ):
                result = hub_service.materialize_workspace(
                    "SYN101",
                    1,
                    state={},
                    provider=NoCallProvider(),
                    cache_dir=cache_dir,
                    workspace_root=workspace_root,
                )

        self.assertEqual(result["cache_status"], "cached")
        self.assertIsInstance(result["record_path"], str)
        json.dumps(result)

    def test_teach_topic_delegates_to_teach_week_and_never_reruns_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            generate_prepare_brief(prepare_context(), SeedProvider(), cache_dir)
            with patch(
                "university_jarvis.workspace.build_prepare_context",
                return_value=prepare_context(),
            ):
                materialize_week_workspace(
                    {}, "SYN101", 1, provider=NoCallProvider(), cache_dir=cache_dir, workspace_root=workspace_root
                )
            capture_after_lecture(
                "SYN101",
                1,
                uncertainties=["I don't understand accrual accounting"],
                workspace_root=workspace_root,
                captured_at="2025-01-03T09:00:00+00:00",
            )

            teach_week_context = {**prepare_context(), "workflow": "TEACH"}
            provider = TeachProvider()
            with patch(
                "university_jarvis.workspace.build_week_context",
                return_value=teach_week_context,
            ):
                result = hub_service.teach_topic(
                    "SYN101",
                    1,
                    topic="accrual accounting",
                    state={},
                    provider=provider,
                    cache_dir=cache_dir,
                    workspace_root=workspace_root,
                    taught_at="2025-01-03T10:00:00+00:00",
                )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(result["taught_at"], "2025-01-03T10:00:00+00:00")
        self.assertEqual(result["topic"], "accrual accounting")
        self.assertIsInstance(result["record_path"], str)
        self.assertIn("brief", result)
        json.dumps(result)


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


class _FakeTransport:
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


class UniversityCheckBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        previous = os.environ.get("JARVIS_LEDGER_FILE")
        os.environ["JARVIS_LEDGER_FILE"] = str(Path(tmpdir.name) / "intake-ledger.json")

        def _restore() -> None:
            if previous is None:
                os.environ.pop("JARVIS_LEDGER_FILE", None)
            else:
                os.environ["JARVIS_LEDGER_FILE"] = previous

        self.addCleanup(_restore)
        root = sources_destination("ZZUNIC", 1, "x").parent.parent
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))

    def test_run_university_check_delegates_and_never_touches_drive_by_default(self) -> None:
        transport = _FakeTransport()
        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
        client = BlackboardClient(session, http_get=transport)

        result = hub_service.run_university_check(client, ledger=new_ledger())

        self.assertEqual([m["module_code"] for m in result["modules"]], ["ZZUNIC"])
        week = result["modules"][0]["weeks"][0]
        self.assertEqual(week["week"], 1)
        self.assertIn("success", week)  # derived property survives serialization
        self.assertEqual(result["scope_issues"], [])
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
