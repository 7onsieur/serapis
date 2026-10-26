"""Evidence-aware REVISE and TEACH: what the digest says, what the model is told, what the student sees."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_teach as T  # noqa: E402

from university_jarvis import hub_service, learning_digest as D, reasoning as R  # noqa: E402
from university_jarvis.reasoning import TokenUsage  # noqa: E402
from university_jarvis.workspace import (  # noqa: E402
    record_learning_attempt, save_learning_evaluation, teach_week)

REF = [{"source_id": T.SOURCE_ID, "pdf_page": 4}]
SECRET_WORDS = "my private wrong answer text"


def revise_brief():
    fields = [f for f, _ in R.REVISE_WORKFLOW.sections]
    return {f: [{"text": f"{f} content.", "provenance": REF}] for f in fields}


class Recorder:
    def __init__(self, brief=None):
        self.contexts, self.instructions, self.brief = [], [], brief or revise_brief()
        self.last_usage = TokenUsage(100, 50, 150)

    def cache_identity(self):
        return {"provider": "fake", "model": "rec"}

    def generate_structured_output(self, context, instructions, output_format):
        self.contexts.append(copy.deepcopy(context))
        self.instructions.append(instructions)
        return copy.deepcopy(self.brief)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache, self.workspace = T.TeachTests()._workspace(self.root)
        self.n = 0

    def attempt(self, task, outcome=None, *, assistance="UNAIDED", capability="EXPLANATION", key=None, **evaluation):
        self.n += 1
        row = record_learning_attempt(
            "SYN101", 1, capability=capability, task=task, origin=key or f"QUIZ:quiz-1:q{self.n}",
            response=f"{SECRET_WORDS} {self.n}", assistance_status=assistance, source_references=REF,
            root=self.workspace, attempted_at=f"2026-10-{self.n:02d}T10:00:00+00:00", task_key=key)
        if outcome:
            save_learning_evaluation("SYN101", 1, row["attempt_id"],
                                     {"outcome": outcome, "reason": f"Reason {self.n}", "basis": "MODEL_JUDGEMENT",
                                      **evaluation}, root=self.workspace)
        return row

    def record(self):
        return json.loads((self.workspace / "SYN101" / "week-01" / "academic-record.json").read_text())

    def digest(self):
        return D.build_learning_digest(self.record())

    def revise(self, provider):
        with patch("university_jarvis.hub_service.build_week_context", return_value=T.week_context("REVISE")):
            return hub_service.generate_revision_brief("SYN101", 1, state={}, provider=provider,
                                                       cache_dir=self.cache, workspace_root=self.workspace)


class DigestTests(Base):
    def test_no_evidence_means_no_digest_and_an_honest_general_message(self):
        digest = self.digest()
        self.assertEqual(digest["status"], "NONE")
        self.assertIsNone(D.model_view(digest))
        text = D.render_digest(digest)
        self.assertIn("not tailored to you", text)
        self.assertIn("general to the week", text)

    def test_priorities_follow_observed_outcomes_not_recency_alone(self):
        self.attempt("Define stakeholder", "SUPPORTED")
        self.attempt("Explain primary versus secondary", "NOT_SUPPORTED")
        self.attempt("Apply the map", "PARTLY_SUPPORTED", capability="APPLICATION")
        self.attempt("What is an organisation", None)  # not yet evaluated
        digest = self.digest()
        standings = [i["standing"] for i in digest["items"]]
        self.assertEqual(standings, [D.NEEDS_WORK, D.PARTLY, D.UNCERTAIN, D.DEMONSTRATED])
        self.assertEqual(digest["items"][0]["task"], "Explain primary versus secondary")
        self.assertEqual(digest["priority_order"], [i["id"] for i in digest["items"]])
        self.assertIn("RECALL", digest["untested_capabilities"])

    def test_a_single_unaided_success_is_never_described_as_mastery(self):
        self.attempt("Define stakeholder", "SUPPORTED")
        text = D.render_digest(self.digest())
        self.assertIn("one question, answered once", text)
        self.assertNotRegex(text.lower(), r"mastered|\bstrong\b|weak (?:at|in|on)|you are weak|excellent")
        self.assertIn("not as proof you know it", text)
        self.assertIn("Fewer than three answers", text)
        self.assertIn("not a grade", text)

    def test_success_after_help_or_after_the_answer_was_shown_is_labelled_as_such(self):
        self.attempt("Prompted task", "SUPPORTED", assistance="PROMPTED")
        self.attempt("Revealed task", "SUPPORTED", assistance="REVEALED")
        digest = self.digest()
        self.assertEqual({i["standing"] for i in digest["items"]}, {D.AFTER_HELP})
        self.assertIn("Retest it unaided", D.render_digest(digest))

    def test_contradictory_unaided_answers_are_flagged_not_averaged(self):
        self.attempt("Same question", "SUPPORTED", key="TASK-1")
        self.attempt("Same question", "NOT_SUPPORTED", key="TASK-1")
        digest = self.digest()
        self.assertEqual(len(digest["items"]), 1)
        self.assertEqual(digest["items"][0]["standing"], D.MIXED)
        self.assertEqual(digest["items"][0]["attempts"], 2)
        self.assertIn("disagree", D.render_digest(digest))

    def test_wrong_then_right_after_help_is_progress_not_a_contradiction(self):
        self.attempt("Same question", "NOT_SUPPORTED", key="TASK-1")
        self.attempt("Same question", "SUPPORTED", assistance="PROMPTED", key="TASK-1")
        self.assertEqual(self.digest()["items"][0]["standing"], D.AFTER_HELP)

    def test_a_disputed_judgement_counts_as_uncertain_not_as_a_weakness(self):
        self.attempt("Disputed task", "NOT_SUPPORTED", key="TASK-D")
        path = self.workspace / "SYN101" / "week-01" / "academic-record.json"
        record = json.loads(path.read_text())
        record["learning"]["evidence"][0]["evaluation"]["dispute"] = {"session_id": "s", "turn_id": "t"}
        path.write_text(json.dumps(record))
        item = self.digest()["items"][0]
        self.assertEqual((item["standing"], item["disputed"]), (D.UNCERTAIN, True))

    def test_the_model_never_receives_the_students_own_words(self):
        self.attempt("Explain primary versus secondary", "NOT_SUPPORTED")
        blob = json.dumps(D.model_view(self.digest()))
        self.assertNotIn(SECRET_WORDS, blob)
        self.assertNotIn("student_response", blob)

    def test_relevance_filter_keeps_only_questions_about_the_topic(self):
        self.attempt("Explain primary versus secondary stakeholders", "NOT_SUPPORTED")
        self.attempt("Describe the marketing mix", "NOT_SUPPORTED")
        picked = D.relevant_to_topic(self.digest(), "secondary stakeholders")
        self.assertEqual([i["task"] for i in picked["items"]], ["Explain primary versus secondary stakeholders"])
        self.assertEqual(D.relevant_to_topic(self.digest(), "something unrelated entirely")["status"], "NONE")

    def test_the_digest_is_bounded(self):
        for index in range(20):
            self.attempt(f"Distinct question number {index} about topic{index}", "NOT_SUPPORTED", key=f"K{index}")
        digest = self.digest()
        self.assertEqual(len(digest["items"]), D.MAX_ITEMS)
        self.assertTrue(any("highest-priority" in limit for limit in digest["limits"]))


class ReviseTests(Base):
    def test_with_no_recorded_answers_revise_is_general_and_says_so(self):
        provider = Recorder()
        result = self.revise(provider)
        self.assertNotIn("learning_evidence", provider.contexts[0])
        self.assertEqual(result["evidence_status"], "NONE")
        self.assertIn("not tailored to you", result["evidence_rendered"])
        self.assertTrue(result["rendered"])

    def test_recorded_answers_reach_the_model_prioritised_and_the_student_sees_observed_versus_suggested(self):
        self.attempt("Define stakeholder", "SUPPORTED")
        self.attempt("Explain primary versus secondary", "NOT_SUPPORTED")
        provider = Recorder()
        result = self.revise(provider)
        evidence = provider.contexts[0]["learning_evidence"]
        self.assertEqual(evidence["items"][0]["standing"], D.NEEDS_WORK)
        self.assertEqual(evidence["priority_order"][0], evidence["items"][0]["id"])
        self.assertIn("evidence gap, not a weakness", evidence["note"])
        self.assertIn("learning_evidence", provider.instructions[0])
        self.assertIn('"Observed:"', provider.instructions[0])
        shown = result["evidence_rendered"]
        self.assertIn("What your recorded answers show (observed)", shown)
        self.assertIn("What to do next (suggested", shown)
        self.assertLess(shown.index("Explain primary versus secondary"), shown.index("Define stakeholder"))
        self.assertIn("Re-read the cited material", shown)
        self.assertNotIn("src-", shown)
        self.assertIn("see ", shown)  # a readable place to look

    def test_new_evidence_changes_the_context_so_a_stale_brief_is_not_served(self):
        provider = Recorder()
        self.attempt("Define stakeholder", "SUPPORTED")
        first = self.revise(provider)
        again = self.revise(provider)
        self.assertEqual((first["cache_status"], again["cache_status"]), ("generated", "cached"))
        self.assertEqual(len(provider.contexts), 1)
        self.attempt("Explain primary versus secondary", "NOT_SUPPORTED")
        third = self.revise(provider)
        self.assertEqual(third["cache_status"], "generated")
        self.assertEqual(len(provider.contexts), 2)
        self.assertEqual(provider.contexts[1]["learning_evidence"]["items"][0]["standing"], D.NEEDS_WORK)

    def test_revise_never_writes_the_record(self):
        self.attempt("Define stakeholder", "NOT_SUPPORTED")
        path = self.workspace / "SYN101" / "week-01" / "academic-record.json"
        before = path.read_bytes()
        self.revise(Recorder())
        self.assertEqual(path.read_bytes(), before)

    def test_without_a_workspace_revise_still_works_generally(self):
        provider = Recorder()
        with patch("university_jarvis.hub_service.build_week_context", return_value=T.week_context("REVISE")):
            result = hub_service.generate_revision_brief("SYN101", 1, state={}, provider=provider,
                                                         cache_dir=self.cache, workspace_root=self.root / "nowhere")
        self.assertEqual(result["evidence_status"], "NONE")

    def test_the_instructions_forbid_mastery_claims_and_invented_student_traits(self):
        text = R.REVISE_WORKFLOW.instructions
        self.assertIn("Never say or imply the student has mastered", text)
        self.assertIn("evidence gap", text)
        self.assertIn("thin", text)


class TeachEvidenceTests(Base):
    def teach(self, topic):
        provider = T.TeachProvider()
        with patch("university_jarvis.workspace.build_week_context", return_value=T.week_context("TEACH")):
            result = teach_week({}, "SYN101", 1, topic=topic, provider=provider, cache_dir=self.cache,
                                workspace_root=self.workspace)
        return provider, result

    def test_with_no_evidence_the_lesson_is_general_and_not_presented_as_personalised(self):
        provider, result = self.teach("question framing vs evidence checking")
        self.assertNotIn("learning_evidence", provider.calls[0]["context"])
        self.assertEqual(result.evidence_used, [])
        self.assertIsNone(D.render_teach_evidence(result.evidence_used))
        self.assertIn("do not suggest the lesson was personalised", provider.calls[0]["instructions"])

    def test_relevant_prior_answers_shape_the_lesson_and_are_disclosed(self):
        self.attempt("Explain question framing versus evidence checking", "NOT_SUPPORTED")
        self.attempt("Describe the marketing mix", "NOT_SUPPORTED")
        provider, result = self.teach("question framing vs evidence checking")
        evidence = provider.calls[0]["context"]["learning_evidence"]
        self.assertEqual([i["task"] for i in evidence["items"]], ["Explain question framing versus evidence checking"])
        self.assertNotIn("marketing", json.dumps(evidence))
        shown = D.render_teach_evidence(result.evidence_used)
        self.assertIn("took these recorded answers of yours into account", shown)
        self.assertIn("not a measure of what you know", shown)
        stored = self.record()["workflows"]["teach"]["interactions"][-1]
        self.assertEqual(stored["evidence_used"][0]["standing"], D.NEEDS_WORK)

    def test_unrelated_evidence_does_not_personalise(self):
        self.attempt("Describe the marketing mix", "NOT_SUPPORTED")
        provider, result = self.teach("question framing vs evidence checking")
        self.assertNotIn("learning_evidence", provider.calls[0]["context"])
        self.assertEqual(result.evidence_used, [])

    def test_teach_instructions_forbid_inventing_student_characteristics(self):
        text = R.TEACH_INSTRUCTIONS
        self.assertIn("no learning style", text)
        self.assertIn("confidence, motivation, ability or mastery", text)
        self.assertIn("Observations are about specific answers, not about the person", text)

    def test_teach_through_the_hub_returns_the_disclosure(self):
        self.attempt("Explain question framing versus evidence checking", "PARTLY_SUPPORTED")
        provider = T.TeachProvider()
        with patch("university_jarvis.workspace.build_week_context", return_value=T.week_context("TEACH")):
            out = hub_service.teach_topic("SYN101", 1, topic="question framing vs evidence checking", state={},
                                          provider=provider, cache_dir=self.cache, workspace_root=self.workspace)
        self.assertIn("recorded answers", out["evidence_rendered"])
        self.assertIn("partly supported", out["evidence_rendered"])
