from __future__ import annotations

import io
import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile, is_zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.cli import main
from university_jarvis.reasoning import (
    ReasoningError,
    TokenUsage,
    generate_prepare_brief,
)
from university_jarvis.workspace import capture_after_lecture, materialize_week_workspace, record_learning_attempt, save_learning_evaluation


SOURCE_ID = "syn101-w01-lecture-01-pdf"


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
        "week": {
            "number": 1,
            "date": None,
            "topic": None,
            "progress": "unknown",
        },
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
                    "page_count": 42,
                    "nonempty_page_count": 42,
                    "character_count": 8_149,
                    "fingerprint": {
                        "algorithm": "sha256",
                        "value": "a" * 64,
                    },
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
                "excerpts": [
                    {
                        "pdf_page": 3,
                        "text": "Bounded source text.",
                        "truncated": True,
                    }
                ],
            }
        ],
    }


def cached_brief() -> dict:
    sections = (
        "week_overview",
        "before_class",
        "core_concepts",
        "examples_cases",
        "lecture_attention",
        "after_class_questions",
        "assessment_connections",
    )
    return {
        section: [
            {
                "text": f"Grounded study content for {section}.",
                "provenance": [{"source_id": SOURCE_ID, "pdf_page": 3}],
            }
        ]
        for section in sections
    }


class SeedProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.last_usage = TokenUsage(1_000, 500, 1_500)

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "cached-only-v1"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls += 1
        return cached_brief()


class NoCallProvider:
    def __init__(self) -> None:
        self.calls = 0

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "cached-only-v1"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls += 1
        raise AssertionError("workspace generation must never call the provider")


class AcademicWorkspaceTests(unittest.TestCase):
    def _seed_cache(self, cache_dir: Path) -> None:
        provider = SeedProvider()
        result = generate_prepare_brief(prepare_context(), provider, cache_dir)
        self.assertEqual(result.cache_status, "generated")
        self.assertEqual(provider.calls, 1)

    def test_cached_prepare_creates_deterministic_record_and_valid_docx(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            self._seed_cache(cache_dir)
            provider = NoCallProvider()

            with patch(
                "university_jarvis.workspace.build_prepare_context",
                return_value=prepare_context(),
            ):
                first = materialize_week_workspace(
                    {},
                    "SYN101",
                    1,
                    provider=provider,
                    cache_dir=cache_dir,
                    workspace_root=workspace_root,
                )
                first_record_bytes = first.record_path.read_bytes()
                first_docx_bytes = first.study_pack_path.read_bytes()
                first_notebooklm_bytes = first.notebooklm_path.read_bytes()
                second = materialize_week_workspace(
                    {},
                    "SYN101",
                    1,
                    provider=provider,
                    cache_dir=cache_dir,
                    workspace_root=workspace_root,
                )

            self.assertEqual(provider.calls, 0)
            self.assertEqual(first.cache_status, "cached")
            self.assertEqual(first.record_path, second.record_path)
            self.assertEqual(first.study_pack_path, second.study_pack_path)
            self.assertEqual(first.notebooklm_path, second.notebooklm_path)
            self.assertEqual(first_record_bytes, second.record_path.read_bytes())
            self.assertEqual(first_docx_bytes, second.study_pack_path.read_bytes())
            self.assertEqual(first_notebooklm_bytes, second.notebooklm_path.read_bytes())

            record = json.loads(first.record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["module"]["code"], "SYN101")
            self.assertEqual(record["week"]["number"], 1)
            self.assertEqual(record["week"]["declared_progress"], "unknown")
            self.assertEqual(record["learning"]["mastery"]["status"], "unknown")
            self.assertEqual(record["learning"]["mastery"]["concepts"], [])
            self.assertEqual(record["learning"]["flashcards"]["status"], "not_generated")
            self.assertEqual(record["learning"]["flashcards"]["items"], [])
            self.assertNotIn("locator", record["sources"][0])
            self.assertEqual(
                record["sources"][0]["extraction"]["fingerprint"]["value"],
                "a" * 64,
            )
            item = record["workflows"]["prepare_me"]["result"]["core_concepts"][0]
            self.assertEqual(item["provenance"][0]["source_id"], SOURCE_ID)
            self.assertEqual(item["provenance"][0]["pdf_page"], 3)
            self.assertEqual(
                record["workflows"]["prepare_me"]["generation"]["usage"],
                {"input_tokens": 1_000, "output_tokens": 500, "total_tokens": 1_500},
            )
            self.assertTrue(is_zipfile(first.study_pack_path))
            self.assertGreater(first.study_pack_path.stat().st_size, 1_000)
            with ZipFile(first.study_pack_path) as document:
                self.assertIsNone(document.testzip())
                self.assertIn("word/document.xml", document.namelist())
                xml = ET.fromstring(document.read("word/document.xml"))
            text = " ".join(node.text or "" for node in xml.iter() if node.tag.endswith("}t"))
            self.assertIn("Week 1 Study Pack", text)
            self.assertIn("Core concepts", text)
            self.assertIn("Grounded study content for core_concepts.", text)
            self.assertIn(SOURCE_ID, text)
            self.assertIn("PDF p. 3", text)
            notebooklm = first.notebooklm_path.read_text(encoding="utf-8")
            self.assertIn("# 2. Core concepts and examples", notebooklm)
            self.assertIn("Claims from university materials include source names", notebooklm)
            self.assertNotIn("academic-record.json", notebooklm)
            self.assertIn(SOURCE_ID, notebooklm)
            self.assertNotIn("# Flashcards", notebooklm)
            self.assertNotIn("# Mastery", notebooklm)

    def test_rebuild_preserves_captures_teach_and_evaluated_learning_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_dir, workspace_root = root / "cache", root / "workspace"
            self._seed_cache(cache_dir)
            with patch("university_jarvis.workspace.build_prepare_context", return_value=prepare_context()):
                materialize_week_workspace({}, "SYN101", 1, provider=NoCallProvider(), cache_dir=cache_dir, workspace_root=workspace_root)
            capture_after_lecture("SYN101", 1, notes=["existing student note"], workspace_root=workspace_root)
            record_path = workspace_root / "SYN101" / "week-01" / "academic-record.json"
            record = json.loads(record_path.read_text())
            record["workflows"]["teach"] = {"status":"recorded", "interactions":[{"teach_id":"teach-1"}]}
            record_path.write_text(json.dumps(record))
            attempt = record_learning_attempt("SYN101", 1, capability="RECALL", task="Define", origin="QUIZ", response="Raw response", root=workspace_root)
            save_learning_evaluation("SYN101", 1, attempt["attempt_id"], {"outcome":"SUPPORTED", "reason":"specific", "basis":"MODEL_JUDGEMENT"}, root=workspace_root)
            with patch("university_jarvis.workspace.build_prepare_context", return_value=prepare_context()):
                materialize_week_workspace({}, "SYN101", 1, provider=NoCallProvider(), cache_dir=cache_dir, workspace_root=workspace_root)
            final = json.loads(record_path.read_text())
            self.assertEqual(final["workflows"]["after_lecture"]["captures"][0]["entries"]["lecture_notes"], ["existing student note"])
            self.assertEqual(final["workflows"]["teach"]["interactions"][0]["teach_id"], "teach-1")
            self.assertEqual(final["learning"]["evidence"][0]["student_response"], "Raw response")
            self.assertEqual(final["learning"]["evidence"][0]["evaluation"]["outcome"], "SUPPORTED")


    def test_missing_cache_fails_without_provider_or_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = NoCallProvider()
            workspace_root = root / "workspace"
            with patch(
                "university_jarvis.workspace.build_prepare_context",
                return_value=prepare_context(),
            ):
                with self.assertRaisesRegex(
                    ReasoningError, "No matching cached PREPARE_ME result"
                ):
                    materialize_week_workspace(
                        {},
                        "SYN101",
                        1,
                        provider=provider,
                        cache_dir=root / "empty-cache",
                        workspace_root=workspace_root,
                    )

            self.assertEqual(provider.calls, 0)
            self.assertFalse(workspace_root.exists())

    def test_workspace_cli_is_a_control_surface_for_cached_materialisation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            self._seed_cache(cache_dir)
            provider = NoCallProvider()
            output = io.StringIO()

            with patch("university_jarvis.cli.load_state", return_value={}):
                with patch(
                    "university_jarvis.workspace.build_prepare_context",
                    return_value=prepare_context(),
                ):
                    with redirect_stdout(output):
                        result = main(
                            ["workspace", "SYN101", "--week", "1"],
                            reasoning_provider=provider,
                            cache_dir=cache_dir,
                            workspace_root=workspace_root,
                        )

            self.assertEqual(result, 0)
            self.assertEqual(provider.calls, 0)
            self.assertIn("cached PREPARE_ME result", output.getvalue())
            self.assertIn("academic-record.json", output.getvalue())
            self.assertIn("NotebookLM upload source", output.getvalue())
            self.assertTrue(
                (workspace_root / "SYN101" / "week-01" / "academic-record.json").is_file()
            )

    def test_after_lecture_appends_student_history_and_updates_docx_without_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            self._seed_cache(cache_dir)
            provider = NoCallProvider()
            with patch(
                "university_jarvis.workspace.build_prepare_context",
                return_value=prepare_context(),
            ):
                workspace = materialize_week_workspace(
                    {}, "SYN101", 1, provider=provider, cache_dir=cache_dir,
                    workspace_root=workspace_root,
                )

            original = json.loads(workspace.record_path.read_text(encoding="utf-8"))
            original_prepare = copy.deepcopy(original["workflows"]["prepare_me"])
            original_sources = copy.deepcopy(original["sources"])
            notes_file = root / "lecture-notes.txt"
            notes_file.write_text(
                "The lecturer compared two cases.\n"
                "I still don't really understand the difference between question framing and evidence checking.\n"
                "Question: How should the distinction be applied?",
                encoding="utf-8",
            )
            first = capture_after_lecture(
                "SYN101",
                1,
                notes=["My general lecture recollection."],
                notes_file=notes_file,
                lecturer_emphasis=["The lecturer emphasised consistency."],
                examples_cases=["A case discussed in class."],
                understood=["I understood the role of associations."],
                assessment_comments=["A reported comment about the assessment."],
                workspace_root=workspace_root,
                captured_at="2025-01-01T10:15:00+00:00",
            )
            second = capture_after_lecture(
                "SYN101",
                1,
                questions=["What should I revisit next?"],
                workspace_root=workspace_root,
                captured_at="2025-01-01T11:00:00+00:00",
            )

            self.assertEqual(provider.calls, 0)
            self.assertEqual(first.capture_id, "capture-0001")
            self.assertEqual(second.capture_id, "capture-0002")
            record = json.loads(workspace.record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["workflows"]["prepare_me"], original_prepare)
            self.assertEqual(record["sources"], original_sources)
            captures = record["workflows"]["after_lecture"]["captures"]
            self.assertEqual(len(captures), 2)
            self.assertEqual(captures[0]["entries"]["lecture_notes"][0], "My general lecture recollection.")
            self.assertEqual(
                captures[0]["provenance"]["classification"], "student_reported"
            )
            self.assertEqual(
                captures[0]["provenance"]["verification_status"],
                "unverified_against_official_sources",
            )
            self.assertEqual(
                record["knowledge_classification"]["source_grounded"]["location"],
                "workflows.prepare_me.result",
            )
            self.assertEqual(record["learning"]["mastery"], {"status": "unknown", "concepts": []})
            unresolved = record["learning"]["unresolved_items"]
            self.assertEqual(unresolved["status"], "open")
            self.assertEqual(
                [(item["kind"], item["text"]) for item in unresolved["items"]],
                [
                    ("uncertainty", "the difference between question framing and evidence checking."),
                    ("question", "How should the distinction be applied?"),
                    ("question", "What should I revisit next?"),
                ],
            )
            self.assertEqual(
                captures[0]["input_sources"][1]["file_name"], "lecture-notes.txt"
            )
            self.assertNotIn(str(root), json.dumps(record))

            with ZipFile(second.study_pack_path) as document:
                xml = ET.fromstring(document.read("word/document.xml"))
            text = " ".join(node.text or "" for node in xml.iter() if node.tag.endswith("}t"))
            self.assertIn("3. My lecture notes", text)
            self.assertIn("Student-reported material", text)
            self.assertIn("My general lecture recollection.", text)
            self.assertIn("What should I revisit next?", text)
            self.assertIn("Grounded study content for core_concepts.", text)
            self.assertIn("not verified against official sources", text)
            notebooklm = second.notebooklm_path.read_text(encoding="utf-8")
            self.assertIn("# 4. Questions to resolve", notebooklm)
            self.assertEqual(notebooklm.count("How should the distinction be applied?"), 1)
            self.assertIn("My general lecture recollection.", notebooklm)
            self.assertIn("A reported comment about the assessment.", notebooklm)

    def test_after_lecture_cli_and_rematerialisation_make_zero_calls_and_preserve_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_dir = root / "cache"
            workspace_root = root / "workspace"
            self._seed_cache(cache_dir)
            provider = NoCallProvider()
            with patch(
                "university_jarvis.workspace.build_prepare_context",
                return_value=prepare_context(),
            ):
                materialize_week_workspace(
                    {}, "SYN101", 1, provider=provider, cache_dir=cache_dir,
                    workspace_root=workspace_root,
                )
                with patch("university_jarvis.cli.load_state", return_value={}):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        exit_code = main(
                            [
                                "after-lecture", "SYN101", "--week", "1",
                                "--uncertainty", "I cannot yet connect the two ideas.",
                            ],
                            reasoning_provider=provider,
                            cache_dir=cache_dir,
                            workspace_root=workspace_root,
                        )
                before = json.loads(
                    (workspace_root / "SYN101" / "week-01" / "academic-record.json").read_text()
                )
                before_docx = (
                    workspace_root / "SYN101" / "week-01" / "SYN101-Week-01-Study-Pack.docx"
                ).read_bytes()
                before_notebooklm = (
                    workspace_root / "SYN101" / "week-01" / "SYN101-Week-01-NotebookLM.md"
                ).read_bytes()
                rematerialized = materialize_week_workspace(
                    {}, "SYN101", 1, provider=provider, cache_dir=cache_dir,
                    workspace_root=workspace_root,
                )
            after = json.loads(rematerialized.record_path.read_text())

            self.assertEqual(exit_code, 0)
            self.assertEqual(provider.calls, 0)
            self.assertIn("capture-0001", output.getvalue())
            self.assertEqual(
                after["workflows"]["after_lecture"],
                before["workflows"]["after_lecture"],
            )
            self.assertEqual(
                after["workflows"]["prepare_me"],
                before["workflows"]["prepare_me"],
            )
            self.assertEqual(after["learning"], before["learning"])
            self.assertEqual(rematerialized.study_pack_path.read_bytes(), before_docx)
            self.assertEqual(rematerialized.notebooklm_path.read_bytes(), before_notebooklm)


if __name__ == "__main__":
    unittest.main()
