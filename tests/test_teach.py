from __future__ import annotations

import copy
import io
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
    TEACH_PROMPT_VERSION,
    TEACH_SCHEMA_VERSION,
    TokenUsage,
    _cache_key,
    generate_prepare_brief,
)
from university_jarvis.workspace import (
    capture_after_lecture,
    materialize_week_workspace,
    teach_week,
)


SOURCE_ID = "syn101-w01-lecture-01-pdf"


def week_context(workflow: str) -> dict:
    return {
        "workflow": workflow,
        "objective_context": {
            "version": 1,
            "primary_objective": "Learn genuinely.",
            "stretch_objective": "Stretch only with evidence.",
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
                "locator": "must-not-reach-provider.pdf",
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
                "character_count": 180,
                "excerpts": [
                    {
                        "pdf_page": 4,
                        "text": "Question framing is how a question is formed: wording, scope and assumptions in a question. Evidence checking examines information: activities and communications can express that identity. Sample Product shows why existing source context matter when an offering changes.",
                        "truncated": False,
                    }
                ],
            }
        ],
    }


def prepare_brief() -> dict:
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
        field: [
            {
                "text": f"Prepared source-grounded material for {field}.",
                "provenance": [{"source_id": SOURCE_ID, "pdf_page": 4}],
            }
        ]
        for field in fields
    }


def teach_brief(source_id: str = SOURCE_ID) -> dict:
    reference = [{"source_id": source_id, "pdf_page": 4}]
    return {
        "direct_explanation": {
            "text": "Ask what is being asked; then check whether available information supports an answer.",
            "provenance": reference,
        },
        "teaching_sequence": [
            {
                "move_type": "build_understanding",
                "title": "Begin with the question",
                "explanation": "The lecture places wording, scope and assumptions in a question on the question-framing side of the distinction.",
                "why_it_follows": None,
                "provenance": reference,
            },
            {
                "move_type": "contrast",
                "title": "Now separate action from identity",
                "explanation": "Evidence checking examines sources and claims; framing a question identifies what information is relevant.",
                "why_it_follows": "A question helps determine which evidence may be relevant, so the two interact without being identical.",
                "provenance": reference,
            },
            {
                "move_type": "worked_example",
                "title": "Reason through Sample Product",
                "explanation": "Changing the wording does not make evidence irrelevant: the source context still matters.",
                "why_it_follows": "The example shows that a claim must be assessed in context and cannot be judged from its wording alone.",
                "provenance": reference,
            },
        ],
        "mental_model": {
            "text": "Question framing identifies what is being asked; evidence checking examines information that may support an answer.",
            "provenance": reference,
        },
        "check_questions": [
            {
                "text": "What source would help answer this question?",
                "provenance": reference,
            },
            {
                "text": "Explain the distinction in your own words.",
                "provenance": reference,
            },
        ],
        "unknowns": ["The supplied excerpt does not establish every possible distinction."],
    }


def legacy_teach_brief() -> dict:
    reference = [{"source_id": SOURCE_ID, "pdf_page": 4}]
    return {
        field: [{"text": f"Legacy {field}.", "provenance": reference}]
        for field in (
            "explanation",
            "connections",
            "source_examples",
            "takeaways",
            "check_questions",
        )
    } | {"unknowns": []}


class PrepareProvider:
    last_usage = TokenUsage(100, 50, 150)

    def cache_identity(self):
        return {"provider": "fake", "model": "prepare-v1"}

    def generate_structured_output(self, context, instructions, output_format):
        return prepare_brief()


class TeachProvider:
    def __init__(self, source_id: str = SOURCE_ID) -> None:
        self.calls = []
        self.source_id = source_id
        self.last_usage = TokenUsage(200, 100, 300)

    def cache_identity(self):
        return {"provider": "fake", "model": "teach-v1"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls.append(
            {"context": copy.deepcopy(context), "instructions": instructions, "format": output_format}
        )
        return teach_brief(self.source_id)


class TeachTests(unittest.TestCase):
    def _workspace(self, root: Path) -> tuple[Path, Path]:
        cache_dir = root / "cache"
        workspace_root = root / "workspace"
        context = week_context("PREPARE_ME")
        generate_prepare_brief(context, PrepareProvider(), cache_dir)
        with patch("university_jarvis.workspace.build_prepare_context", return_value=context):
            materialize_week_workspace(
                {},
                "SYN101",
                1,
                provider=PrepareProvider(),
                cache_dir=cache_dir,
                workspace_root=workspace_root,
            )
        capture_after_lecture(
            "SYN101",
            1,
            uncertainties=["I don't understand the difference between question framing and evidence checking"],
            questions=["How should I apply the question framing and evidence checking distinction?"],
            workspace_root=workspace_root,
            captured_at="2025-01-01T10:00:00+00:00",
        )
        return cache_dir, workspace_root

    def test_explicit_topic_is_grounded_adaptive_cached_and_state_neutral(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_dir, workspace_root = self._workspace(root)
            record_path = workspace_root / "SYN101" / "week-01" / "academic-record.json"
            before = json.loads(record_path.read_text(encoding="utf-8"))
            provider = TeachProvider()
            with patch(
                "university_jarvis.workspace.build_week_context",
                return_value=week_context("TEACH"),
            ):
                first = teach_week(
                    {}, "SYN101", 1,
                    topic="question framing vs evidence checking",
                    provider=provider,
                    cache_dir=cache_dir,
                    workspace_root=workspace_root,
                    taught_at="2025-01-01T12:00:00+00:00",
                )
                second = teach_week(
                    {}, "SYN101", 1,
                    topic="question framing vs evidence checking",
                    provider=provider,
                    cache_dir=cache_dir,
                    workspace_root=workspace_root,
                    taught_at="2025-01-01T12:05:00+00:00",
                )

            self.assertEqual(first.cache_status, "generated")
            self.assertEqual(second.cache_status, "cached")
            self.assertEqual(len(provider.calls), 1)
            supplied = provider.calls[0]["context"]
            self.assertEqual(supplied["teach_request"]["topic"], "question framing vs evidence checking")
            self.assertIn("prepare_me", supplied)
            self.assertNotIn("locator", supplied["sources"][0])
            self.assertEqual(supplied["student_context"][0]["kind"], "uncertainty")
            self.assertEqual(
                supplied["student_context"][0]["provenance"]["classification"],
                "student_reported",
            )
            instructions = provider.calls[0]["instructions"]
            self.assertIn("patient, adaptive tutor", instructions)
            self.assertIn("simple answer to the requested topic or captured confusion", instructions)
            self.assertIn("why the example demonstrates that concept", instructions)
            self.assertIn("never present it as\nan official-source claim", instructions)

            moves = first.brief.teaching_sequence
            self.assertEqual(
                [move.move_type for move in moves],
                ["build_understanding", "contrast", "worked_example"],
            )
            self.assertIn("interact without being identical", moves[1].why_it_follows)
            self.assertIn("assessed in context", moves[2].why_it_follows)
            self.assertEqual(len(first.brief.check_questions), 2)
            self.assertTrue(first.brief.unknowns)

            after = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(after["workflows"]["prepare_me"], before["workflows"]["prepare_me"])
            self.assertEqual(after["workflows"]["after_lecture"], before["workflows"]["after_lecture"])
            self.assertEqual(after["learning"], before["learning"])
            self.assertEqual(after["learning"]["mastery"], {"status": "unknown", "concepts": []})
            self.assertEqual(after["learning"]["quiz_history"]["attempts"], [])
            self.assertEqual(after["learning"]["flashcards"]["items"], [])
            self.assertTrue(all(item["status"] == "open" for item in after["learning"]["unresolved_items"]["items"]))
            interactions = after["workflows"]["teach"]["interactions"]
            self.assertEqual(len(interactions), 2)
            self.assertFalse(interactions[0]["provenance"]["canonical_source_evidence"])
            generated = interactions[0]["generated_learning"]
            self.assertEqual(
                generated["direct_explanation"]["provenance"][0]["source_id"],
                SOURCE_ID,
            )
            self.assertEqual(
                interactions[0]["generation"]["prompt_version"],
                TEACH_PROMPT_VERSION,
            )
            self.assertEqual(
                interactions[0]["generation"]["schema_version"],
                TEACH_SCHEMA_VERSION,
            )
            old_key = _cache_key(
                supplied, provider, "teach-grounding-v2", 1
            )
            new_key = _cache_key(
                supplied, provider, TEACH_PROMPT_VERSION, TEACH_SCHEMA_VERSION
            )
            self.assertNotEqual(old_key, new_key)
            self.assertEqual(interactions[0]["generation"]["cache_key"], new_key)

            self.assertTrue(is_zipfile(second.study_pack_path))
            with ZipFile(second.study_pack_path) as document:
                self.assertIsNone(document.testzip())
                xml = ET.fromstring(document.read("word/document.xml"))
            text = " ".join(node.text or "" for node in xml.iter() if node.tag.endswith("}t"))
            self.assertIn("5. Taught topics", text)
            self.assertIn("not a substitute for the university source material", text)
            self.assertNotIn("teach-0001", text)
            self.assertNotIn("teach-0002", text)
            self.assertEqual(text.count("Question framing identifies what is being asked"), 1)
            self.assertIn("Why it follows", text)
            self.assertIn("Mental model", text)
            notebooklm = second.notebooklm_path.read_text(encoding="utf-8")
            self.assertEqual(notebooklm.count("## Question framing vs evidence checking"), 1)
            self.assertIn("Generated learning derived from the cited sources", notebooklm)
            self.assertIn("NotebookLM output is not itself university evidence", notebooklm)

    def test_omitted_topic_selects_an_open_captured_item_and_cli_renders_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_dir, workspace_root = self._workspace(root)
            provider = TeachProvider()
            output = io.StringIO()
            state = {
                "modules": [{"code": "SYN101", "title": "Introduction to Example Studies"}]
            }
            with patch("university_jarvis.cli.load_state", return_value=state):
                with patch(
                    "university_jarvis.workspace.build_week_context",
                    return_value=week_context("TEACH"),
                ):
                    with redirect_stdout(output):
                        exit_code = main(
                            ["teach", "SYN101", "--week", "1"],
                            reasoning_provider=provider,
                            cache_dir=cache_dir,
                            workspace_root=workspace_root,
                        )
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(
                provider.calls[0]["context"]["teach_request"]["selection"],
                "automatic_open_unresolved_item",
            )
            rendered = output.getvalue()
            self.assertIn("How should I apply the question framing and evidence checking distinction?", rendered)
            self.assertIn("Student-reported context (not an official-source claim)", rendered)
            self.assertIn("Start here", rendered)
            self.assertIn("Why this follows", rendered)
            self.assertIn("Mental model", rendered)
            self.assertIn("Unscored retrieval checks", rendered)

    def test_out_of_scope_source_citation_is_rejected_without_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_dir, workspace_root = self._workspace(root)
            record_path = workspace_root / "SYN101" / "week-01" / "academic-record.json"
            before = record_path.read_bytes()
            provider = TeachProvider("unconfigured-general-knowledge")
            with patch(
                "university_jarvis.workspace.build_week_context",
                return_value=week_context("TEACH"),
            ):
                with self.assertRaisesRegex(ReasoningError, "not supplied to this workflow"):
                    teach_week(
                        {}, "SYN101", 1,
                        topic="question framing vs evidence checking",
                        provider=provider,
                        cache_dir=cache_dir,
                        workspace_root=workspace_root,
                    )
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(record_path.read_bytes(), before)
            self.assertFalse(any(cache_dir.glob("*.tmp")))

    def test_v11_docx_rebuild_preserves_a_v1_teach_interaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, workspace_root = self._workspace(root)
            record_path = workspace_root / "SYN101" / "week-01" / "academic-record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["workflows"]["teach"] = {
                "status": "recorded",
                "interactions": [
                    {
                        "teach_id": "teach-0001",
                        "taught_at": "2025-01-01T11:00:00+00:00",
                        "topic": "legacy topic",
                        "student_context": [],
                        "generated_learning": legacy_teach_brief(),
                    }
                ],
            }
            record_path.write_text(json.dumps(record), encoding="utf-8")

            result = capture_after_lecture(
                "SYN101",
                1,
                questions=["A later question"],
                workspace_root=workspace_root,
                captured_at="2025-01-01T11:30:00+00:00",
            )

            self.assertTrue(is_zipfile(result.study_pack_path))
            with ZipFile(result.study_pack_path) as document:
                xml = ET.fromstring(document.read("word/document.xml"))
            text = " ".join(node.text or "" for node in xml.iter() if node.tag.endswith("}t"))
            self.assertIn("Legacy explanation.", text)


if __name__ == "__main__":
    unittest.main()
