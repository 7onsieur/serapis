from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis import hub_service
from university_jarvis.hub_service import select_next_study_task
from university_jarvis.workspace import record_learning_attempt, save_learning_evaluation


class LearningEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.record_path = self.root / "BIO101" / "week-01" / "academic-record.json"
        self.record_path.parent.mkdir(parents=True)
        self.record = {
            "workspace_schema_version": 3,
            "module": {"code": "BIO101", "title": "Biology"}, "week": {"number": 1, "topic": "Cells"},
            "sources": [{"source_id": "s1", "title": "Lecture", "type": "pdf",
                         "extraction": {"character_count": 12, "fingerprint": {"algorithm": "sha256", "value": "abc"}}}],
            "workflows": {"prepare_me": {"result": {}}, "teach": {"interactions": [{"teach_id": "teach-1"}]},
                          "after_lecture": {"captures": [{"capture_id": "capture-1"}]}},
            "learning": {"notes": {"items": [{"text": "note"}]}, "evidence": []},
        }
        self.record_path.write_text(json.dumps(self.record))
        (self.record_path.parent / "BIO101-Week-01-Study-Pack.docx").write_bytes(b"")
        (self.record_path.parent / "BIO101-Week-01-NotebookLM.md").write_text("")

    def test_raw_response_is_persisted_before_evaluation_and_preserved(self):
        row = record_learning_attempt("BIO101", 1, capability="EXPLANATION", task="Explain cells",
            origin="TEACH", response="Verbatim answer", source_references=[{"source_id":"s1","pdf_page":2}],
            root=self.root, attempted_at="2026-10-07T10:00:00+00:00")
        on_disk = json.loads(self.record_path.read_text())
        saved = on_disk["learning"]["evidence"][0]
        self.assertEqual(saved["student_response"], "Verbatim answer")
        self.assertIsNone(saved["evaluation"])
        self.assertEqual(saved["source_references"][0]["fingerprint"]["value"], "abc")
        self.assertNotEqual(saved["student_response"], saved.get("expected_answer"))
        save_learning_evaluation("BIO101", 1, row["attempt_id"], {"outcome":"SUPPORTED","basis":"MODEL_JUDGEMENT"}, root=self.root)
        saved = json.loads(self.record_path.read_text())["learning"]["evidence"][0]
        self.assertEqual(saved["student_response"], "Verbatim answer")

    def test_prompted_evidence_and_unattempted_are_not_misrepresented(self):
        row = record_learning_attempt("BIO101", 1, capability="RECALL", task="Define cell",
            origin="QUIZ", response="answer", assistance_status="PROMPTED", prompt_help=["Hint"], root=self.root)
        self.assertEqual(row["assistance_status"], "PROMPTED")
        self.assertEqual(row["prompt_help"], ["Hint"])
        source = {"source_id":"s1", "extraction":{"character_count":12}}
        self.assertEqual(select_next_study_task([row], [source])["action"], "Retest recall unaided")
        self.assertIn("not yet been tested", select_next_study_task([], [source])["reason"])
        self.assertIn("No reliable recommendation", select_next_study_task([], [])["action"])

    def _save_quiz_tasks(self):
        self.record["learning"]["quiz_history"] = {"status":"recorded", "attempts":[{
            "quiz_id":"quiz-1", "questions":[
                {"question_id":"r1", "question_type":"recall", "question":"Recall task?", "provenance":[{"source_id":"s1", "pdf_page":1, "fingerprint":{"algorithm":"sha256", "value":"abc"}}]},
                {"question_id":"e1", "question_type":"explanation", "question":"Explain task?", "provenance":[{"source_id":"s1", "pdf_page":1, "fingerprint":{"algorithm":"sha256", "value":"abc"}}]},
                {"question_id":"a1", "question_type":"application", "question":"Apply task?", "provenance":[{"source_id":"s1", "pdf_page":1, "fingerprint":{"algorithm":"sha256", "value":"abc"}}]},
            ], "answers":[{"question_id":key, "answer":f"Expected {key}"} for key in ("r1", "e1", "a1")]
        }]}
        self.record_path.write_text(json.dumps(self.record))

    @staticmethod
    def _context(_state, module_code, week_number, workflow):
        return {"module":{"code":module_code}, "week":{"number":week_number},
            "sources":[{"id":"s1", "extraction":{"fingerprint":{"algorithm":"sha256", "value":"abc"}}}],
            "source_contexts":[{"source_id":"s1", "excerpts":[{"pdf_page":1,"text":"Grounded passage"}]}]}

    def test_continue_uses_recommended_capability_and_never_calls_ai_for_saved_task(self):
        class NoCall:
            def generate_structured_output(self, *args): raise AssertionError("saved matching task should be reused")
        cases = [
            ([], "RECALL", "QUIZ:quiz-1:r1"),
            ([{"capability":"RECALL", "assistance_status":"UNAIDED", "evaluation":{"outcome":"SUPPORTED"}}], "EXPLANATION", "QUIZ:quiz-1:e1"),
            ([{"capability":"RECALL", "assistance_status":"UNAIDED", "evaluation":{"outcome":"SUPPORTED"}}, {"capability":"EXPLANATION", "assistance_status":"UNAIDED", "evaluation":{"outcome":"SUPPORTED"}}], "APPLICATION", "QUIZ:quiz-1:a1"),
        ]
        for evidence, capability, origin in cases:
            with self.subTest(capability=capability):
                self._save_quiz_tasks()
                self.record["learning"]["evidence"] = evidence
                self.record_path.write_text(json.dumps(self.record))
                with patch("university_jarvis.hub_service.build_week_context", side_effect=self._context):
                    selected = hub_service.continue_learning_task("BIO101", 1, state={}, provider=NoCall(), workspace_root=self.root)
                self.assertEqual(selected["recommendation"]["capability"], capability)
                self.assertEqual(selected["task"]["capability"], capability)
                self.assertEqual(selected["task"]["origin"], origin)

    def test_prompted_retest_and_unclear_retry_keep_capability_and_require_new_unseen_task(self):
        class NoCall:
            def generate_structured_output(self, *args): raise AssertionError("unseen task should be reused")
        for evaluation in (None, {"outcome":"NOT_SUPPORTED"}, {"outcome":"UNCLEAR"}):
            self._save_quiz_tasks()
            self.record["learning"]["evidence"] = [{"capability":"EXPLANATION", "assistance_status":"PROMPTED",
                "prompt_help":["Hint"], "origin":"QUIZ:old:e0", "evaluation":evaluation}]
            self.record_path.write_text(json.dumps(self.record))
            with patch("university_jarvis.hub_service.build_week_context", side_effect=self._context):
                selected = hub_service.continue_learning_task("BIO101", 1, state={}, provider=NoCall(), workspace_root=self.root)
            self.assertEqual(selected["recommendation"]["capability"], "EXPLANATION")
            self.assertEqual(selected["task"]["capability"], "EXPLANATION")
            self.assertEqual(selected["task"]["assistance_status"], "UNAIDED")
            self.assertNotEqual(selected["task"]["origin"], "QUIZ:old:e0")

    def test_used_task_is_not_reused_and_generation_is_explicit_and_capability_bounded(self):
        class TaskProvider:
            def __init__(self): self.contexts = []
            def cache_identity(self): return {"provider":"fake", "model":"task-v1"}
            def generate_structured_output(self, context, instructions, output_format):
                self.contexts.append(context)
                return {"task":"Apply this concept?", "expected_answer_or_rubric":"Expected application", "source_references":[{"source_id":"s1", "pdf_page":1}]}
        self._save_quiz_tasks()
        self.record["learning"]["evidence"] = [{"capability":"APPLICATION", "assistance_status":"UNAIDED", "origin":"QUIZ:quiz-1:a1", "evaluation":{"outcome":"UNCLEAR"}}]
        self.record_path.write_text(json.dumps(self.record))
        provider = TaskProvider()
        with patch("university_jarvis.hub_service.build_week_context", side_effect=self._context):
            result = hub_service.continue_learning_task("BIO101", 1, state={}, provider=provider, workspace_root=self.root)
        self.assertTrue(result["generated"])
        self.assertEqual(result["task"]["capability"], "APPLICATION")
        self.assertEqual(provider.contexts[0]["capability"], "APPLICATION")
        self.assertEqual(len(provider.contexts), 1)
        self.assertIn("Expected application", json.loads(self.record_path.read_text())["learning"]["generated_tasks"][0]["expected_answer"])


if __name__ == "__main__":
    unittest.main()
