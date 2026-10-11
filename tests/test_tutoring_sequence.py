"""Phase 3C slice 2: bounded adaptive question sequences.

Synthetic material and scripted offline providers only (no network: ``tests/conftest.py`` fails any
real socket). The record/session fixture is borrowed from ``test_tutoring``; retrieval is patched to
return a small synthetic passage so generated questions can be checked against real page text.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import test_hub_tutor as hub  # noqa: E402
import test_tutoring as base  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from university_jarvis import tutor_policy as tp  # noqa: E402
from university_jarvis import tutoring  # noqa: E402
from university_jarvis.reasoning import ReasoningError  # noqa: E402
from university_jarvis.state import StateError  # noqa: E402

CITE = [{"source_id": "s1", "pdf_page": 1}]
PASSAGE = ("Cells are the basic structural and functional unit of all living organisms. The cell membrane is a "
           "selectively permeable barrier that controls what enters and leaves the cell. Mitochondria release "
           "usable energy from nutrients in the cell through respiration. Second.")
FOLLOW = {"question": "Which part of a living organism controls what enters and leaves a cell?",
          "expected_answer": "The cell membrane is a selectively permeable barrier that controls what enters and leaves the cell.",
          "citations": CITE}
DIFFERENT = {"question": "A microbe in a pond is a single living organism; which cell structure releases usable energy "
                         "for it from nutrients?",
             "expected_answer": "Mitochondria release usable energy from nutrients in the cell through respiration.",
             "citations": CITE}
DECOY = "The weather over the harbour was sunny with a light wind and a few gulls."
FORBIDDEN = re.compile(r"master|retain|retention|independent|learned|understands", re.I)


class Script:
    """Scripted provider: feedback diagnoses and generated questions are consumed in order."""

    def __init__(self, feedback=(), questions=()):
        self.feedback, self.questions, self.calls = list(feedback), list(questions), []
        self.fail_next = 0

    def cache_identity(self):
        return {"provider": "fake", "model": "sequence-test"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls.append(context)
        if self.fail_next:
            self.fail_next -= 1
            raise ReasoningError("OpenAI reasoning request failed before a response was received")
        action = context["action"]
        if action == "NEXT_QUESTION":
            item = self.questions.pop(0)
            return item(context) if callable(item) else deepcopy(item)
        diagnosis = self.feedback.pop(0) if self.feedback and action == "FEEDBACK" else "partial"
        out = {"message": f"{action} reply", "citations": CITE, "diagnosis": diagnosis if action == "FEEDBACK" else "none"}
        if diagnosis == "misconception" and action == "FEEDBACK":
            quote = " ".join(re.findall(r"[A-Za-z]+", context["student_response"])[:2])
            out["misconception"] = {"label": "Mixes up cells and viruses", "quote": quote, "confidence": "high",
                                    "citations": CITE}
        return out

    def asked(self):
        return [c for c in self.calls if c["action"] == "NEXT_QUESTION"]


class SequenceBase(unittest.TestCase):
    setUp = base.TutoringTests.setUp
    create = base.TutoringTests.create
    answer = base.TutoringTests.answer
    learning = base.TutoringTests.learning
    session_file = base.TutoringTests.session_file

    def _context(self, _state, module_code, week_number, workflow, **_kw):
        return {"module": {"code": module_code}, "week": {"number": week_number},
                "sources": [{"id": "s1", "extraction": {"fingerprint": self.fingerprint}}],
                "source_contexts": [{"source_id": "s1", "retrieval": {"status": "matched" if self.matched else "no_match"},
                                     "excerpts": [{"pdf_page": 1, "text": getattr(self, "passage", PASSAGE)},
                                                  {"pdf_page": 2, "text": DECOY}]}]}

    def script(self, feedback=(), questions=()):
        self.provider = Script(feedback, questions)
        return self.provider

    def nxt(self, session, turn="n1"):
        return tutoring.next_question({}, "BIO101", 1, session["session_id"], client_turn_id=turn,
                                      provider=self.provider, workspace_root=self.root)

    def skip(self, session, turn="s1"):
        return tutoring.skip_question({}, "BIO101", 1, session["session_id"], client_turn_id=turn,
                                      provider=self.provider, workspace_root=self.root)

    def hint(self, session, turn):
        return tutoring.request_hint({}, "BIO101", 1, session["session_id"], client_turn_id=turn,
                                     provider=self.provider, workspace_root=self.root)

    def reveal(self, session, turn="rv"):
        return tutoring.reveal_answer({}, "BIO101", 1, session["session_id"], client_turn_id=turn,
                                      provider=self.provider, workspace_root=self.root)

    def view(self, session):
        return tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)

    def plan(self, session):
        return self.view(session)["sequence"]["plan"]

    def evidence_labels(self):
        return [tp.classify_evidence(a) for a in self.learning()["evidence"]]


class SequenceFlowTests(SequenceBase):
    def test_partial_answer_leads_to_a_targeted_follow_up_then_a_different_question(self):
        self.script(["partial", "correct", "correct"], [FOLLOW, DIFFERENT])
        session = self.create("TEST_ME")
        self.assertEqual(session["sequence"]["plan"]["reason"], "AWAITING_ANSWER")
        self.assertNotIn("NEXT", session["available_actions"])
        self.answer(session, "a1", "Cells are units")
        view = self.view(session)
        self.assertEqual(view["sequence"]["plan"]["step"], "FOLLOW_UP")
        self.assertEqual(view["sequence"]["plan"]["reason"], "PARTIAL_ANSWER")
        self.assertIn("NEXT", view["available_actions"])

        opened = self.nxt(session)
        self.assertEqual(opened["tutor"]["kind"], "QUESTION")
        follow = opened["session"]
        self.assertEqual((follow["sequence"]["position"], follow["sequence"]["current"]["role"]), (2, "FOLLOW_UP"))
        self.assertEqual(follow["task"]["task"], FOLLOW["question"])
        self.assertIn("missing", follow["sequence"]["current"]["why"])
        self.assertEqual(follow["hint_level"], 0)
        self.assertNotIn("NEXT", follow["available_actions"])
        generation = self.provider.asked()[0]
        self.assertEqual((generation["step"], generation["reason"], generation["intention"]), ("FOLLOW_UP", "PARTIAL_ANSWER", "TEST_ME"))
        self.assertEqual(generation["parent_question"], session["task"]["task"])

        self.answer(session, "a2", "The cell membrane controls what enters and leaves")
        self.assertEqual(self.plan(session)["reason"], "FOLLOW_UP_CORRECT")
        different = self.nxt(session, "n2")["session"]
        self.assertEqual(different["sequence"]["current"]["role"], "TRANSFER")
        self.assertEqual(different["sequence"]["asked"], 3)
        self.answer(session, "a3", "Mitochondria")
        end = self.plan(session)
        self.assertEqual((end["step"], end["reason"]), ("END", "SEQUENCE_COMPLETE"))
        with self.assertRaises(tutoring.TutorSessionError):
            self.nxt(session, "n3")
        self.assertEqual(len(self.provider.asked()), 2)

    def test_correct_unhedged_answer_goes_straight_to_a_different_question(self):
        self.script(["correct"], [DIFFERENT])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are the basic unit of living organisms")
        self.assertEqual((self.plan(session)["step"], self.plan(session)["reason"]), ("TRANSFER", "CORRECT_ANSWER"))
        self.assertEqual(self.nxt(session)["session"]["sequence"]["current"]["role"], "TRANSFER")

    def test_correct_but_guessed_is_checked_with_a_follow_up_not_consolidated(self):
        self.script(["correct"], [FOLLOW])
        session = self.create("TEST_ME")
        tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a1", text="Cells are the basic unit",
                                 provider=self.provider, workspace_root=self.root, confidence="GUESSING")
        self.assertEqual((self.plan(session)["step"], self.plan(session)["reason"]), ("FOLLOW_UP", "REASONING_CHECK"))

    def test_mistaken_answer_follow_up_carries_only_the_validated_misconception(self):
        self.script(["misconception"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Viruses are the unit of life")
        self.assertEqual(self.plan(session)["reason"], "MISCONCEPTION")
        self.nxt(session)
        self.assertEqual(self.provider.asked()[0]["misconception_label"], "Mixes up cells and viruses")

    def test_follow_up_that_is_not_secure_ends_the_sequence_instead_of_piling_on(self):
        self.script(["partial", "partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        self.answer(session, "a2", "The membrane maybe")
        end = self.plan(session)
        self.assertEqual((end["step"], end["reason"]), ("END", "REVIEW_SOURCES"))
        self.assertNotIn("NEXT", self.view(session)["available_actions"])

    def test_uncertain_student_gets_no_new_question_until_something_can_be_judged(self):
        self.script(["unclear"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "I don't know")
        self.assertEqual((self.plan(session)["step"], self.plan(session)["reason"]), ("NONE", "NEEDS_CLARITY"))
        self.assertEqual(self.provider.calls, [])  # a pure "I don't know" costs no model call
        with self.assertRaises(tutoring.TutorSessionError):
            self.nxt(session)
        self.assertIn("SKIP", self.view(session)["available_actions"])

    def test_two_unjudgeable_answers_in_a_row_stop_the_sequence(self):
        self.script(["unclear", "unclear"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "I don't know")
        self.answer(session, "a2", "idk")
        self.assertEqual((self.plan(session)["step"], self.plan(session)["reason"]), ("END", "NO_PROGRESS"))

    def test_repeated_same_misconception_stops_the_sequence(self):
        self.script(["misconception", "misconception"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Viruses are the unit of life")
        self.nxt(session)
        self.answer(session, "a2", "Viruses are living cells")
        self.assertEqual(self.plan(session)["reason"], "REPEATED_MISCONCEPTION")

    def test_teach_me_and_test_me_share_one_engine(self):
        self.script(["partial", "correct"], [FOLLOW])
        session = self.create("TEACH_ME")
        first = self.answer(session, "a1", "Cells are units")
        self.assertEqual(first["assistance_status"], "PROMPTED")
        self.nxt(session)
        self.assertEqual(self.provider.asked()[0]["intention"], "TEACH_ME")
        second = self.answer(session, "a2", "The cell membrane")
        self.assertEqual(second["assistance_status"], "UNAIDED")  # a new question is a new, unaided task
        first_attempt, second_attempt = self.learning()["evidence"]
        self.assertEqual(second_attempt["lineage"]["prior_help"], ["EXPLANATION", "FEEDBACK"])
        self.assertEqual(self.evidence_labels(), ["ASSISTED", "NEW_QUESTION_AFTER_HELP"])


class LineageAndAssistanceTests(SequenceBase):
    def test_lineage_separates_first_contact_assisted_new_question_and_revealed_answers(self):
        self.script(["partial", "partial", "correct"], [FOLLOW, DIFFERENT])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        self.hint(session, "h1")
        self.answer(session, "a2", "The membrane maybe")  # follow-up answered after a hint
        self.assertEqual(self.plan(session)["step"], "END")
        self.assertEqual(self.evidence_labels(), ["UNAIDED_FIRST_CONTACT", "ASSISTED"])

        self.script(["partial", "correct"], [FOLLOW])
        other = self.create("TEST_ME", request="req-2")
        self.reveal(other)
        self.answer(other, "b1", base.ANSWER_TEXT)
        self.assertEqual(self.evidence_labels()[-1], "REVEALED")

    def test_new_question_after_help_is_not_called_transfer_retention_or_mastery(self):
        self.script(["partial", "correct"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        self.answer(session, "a2", "The membrane")
        attempts = self.learning()["evidence"]
        self.assertEqual(attempts[1]["lineage"], {"role": "FOLLOW_UP", "question_id": "q2", "parent_question_id": "q1",
                                                  "root_question_id": "q1", "prior_help": ["FEEDBACK"],
                                                  "earlier_help_elsewhere": False})
        label = tp.classify_evidence(attempts[1])
        self.assertEqual(label, "NEW_QUESTION_AFTER_HELP")
        for forbidden in ("TRANSFER", "RETENTION", "INDEPENDENT", "MASTER"):
            self.assertNotIn(forbidden, label)
        # No lineage (older attempts) never upgrades to a lineage label.
        self.assertEqual(tp.classify_evidence({"assistance_status": "UNAIDED"}), "UNAIDED_UNLINKED")
        self.assertEqual(tp.classify_evidence({"assistance_status": "UNAIDED", "lineage": {"role": "FOLLOW_UP", "prior_help": []}}),
                         "UNAIDED_UNLINKED")

    def test_each_question_has_its_own_hints_exposures_and_task_key(self):
        self.script(["partial", "partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.hint(session, "h1")
        self.answer(session, "a1", "Cells are units")
        self.assertEqual(self.learning()["evidence"][0]["assistance_status"], "PROMPTED")
        self.nxt(session)
        opened = self.view(session)
        self.assertEqual((opened["hint_level"], opened["revealed"]), (0, False))
        keys = {e["task_key"] for e in self.learning()["task_exposures"]}
        self.assertEqual(keys, {"QUIZ:quiz-1:r1"})
        self.answer(session, "a2", "The membrane")
        second = self.learning()["evidence"][1]
        self.assertEqual((second["assistance_status"], second["task_key"], second["hint_level"]),
                         ("UNAIDED", f"TUTOR:{session['session_id']}:q2", 0))
        self.hint(session, "h2")  # hinting q2 floors q2 only
        self.assertEqual([q["hint_level"] for q in self.session_json(session)["questions"]], [1, 1])
        self.assertEqual({e["task_key"] for e in self.learning()["task_exposures"]},
                         {"QUIZ:quiz-1:r1", f"TUTOR:{session['session_id']}:q2"})
        self.assertEqual(self.view(session)["sequence"]["items"][0]["hints"], 1)

    def session_json(self, session):
        return json.loads(self.session_file(session).read_text())

    def test_revealing_a_follow_up_floors_only_that_question(self):
        self.script(["partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        self.reveal(session, "rv2")
        self.answer(session, "a2", "The membrane")
        first, second = self.learning()["evidence"]
        self.assertEqual((first["assistance_status"], second["assistance_status"]), ("UNAIDED", "REVEALED"))
        questions = self.session_json(session)["questions"]
        self.assertEqual([q["revealed"] for q in questions], [False, True])

    def test_revealed_opening_question_offers_a_fresh_question_marked_after_help(self):
        self.script(["correct"], [FOLLOW])
        session = self.create("TEST_ME")
        self.reveal(session)
        self.assertEqual((self.plan(session)["step"], self.plan(session)["reason"]), ("FOLLOW_UP", "ANSWER_WAS_SHOWN"))
        self.nxt(session)
        self.answer(session, "a2", "The cell membrane controls what enters")
        attempt = self.learning()["evidence"][0]
        self.assertEqual(attempt["lineage"]["prior_help"], ["REVEAL"])
        self.assertEqual(tp.classify_evidence(attempt), "NEW_QUESTION_AFTER_HELP")

    def test_dispute_still_works_on_a_later_question(self):
        self.script(["partial", "misconception"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        result = self.answer(session, "a2", "Viruses are the membrane")
        target = result["tutor"]["in_reply_to"]
        done = tutoring.dispute_diagnosis({}, "BIO101", 1, session["session_id"], client_turn_id="d1",
                                          target_turn_id=target, provider=self.provider, workspace_root=self.root)
        self.assertEqual(done["status"], "COMPLETE")
        self.assertEqual(self.learning()["evidence"][1]["evaluation"]["dispute"]["status"], "DISPUTED_BY_STUDENT")


class GeneratedQuestionRejectionTests(SequenceBase):
    def start_partial(self, questions):
        self.script(["partial"], questions)
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        return session

    fresh_needed = False

    def assert_rejected(self, bad, reason):
        if self.fresh_needed:
            self.setUp()  # a clean workspace per case: the opening task is picked from unused ones
        self.fresh_needed = True
        session = self.start_partial([bad])
        evidence_before = deepcopy(self.learning())
        with self.assertRaises(ReasoningError) as caught:
            self.nxt(session)
        self.assertIn(reason, str(caught.exception))
        view = self.view(session)
        self.assertEqual(view["sequence"]["asked"], 1)  # nothing was shown or opened
        self.assertEqual(self.learning(), evidence_before)  # nothing recorded for a question that never existed
        return session

    def test_invalid_citation_is_rejected(self):
        self.assert_rejected({**FOLLOW, "citations": [{"source_id": "s1", "pdf_page": 99}]}, "not a supplied source passage")
        self.assert_rejected({**FOLLOW, "citations": [{"source_id": "zzz", "pdf_page": 1}]}, "not a supplied source passage")
        self.assert_rejected({**FOLLOW, "citations": []}, "page-level source citation")
        self.assert_rejected({**FOLLOW, "citations": [{"source_id": "s1", "pdf_page": None}]}, "page-level source citation")

    def test_answer_not_supported_by_the_cited_passage_is_rejected(self):
        self.assert_rejected({**FOLLOW, "expected_answer": "Ribosomes assemble proteins inside the nucleolus quickly."},
                             "not supported by the cited passages")

    def test_question_unrelated_to_the_original_concept_is_rejected(self):
        self.assert_rejected({"question": "What does the selectively permeable barrier control?",
                              "expected_answer": "A selectively permeable barrier controls what enters and leaves.",
                              "citations": CITE}, "not tied to the original concept")

    def test_question_that_gives_away_its_own_answer_is_rejected(self):
        leak = {**FOLLOW, "question": "In a living organism the cell membrane is a selectively permeable barrier that "
                                      "controls what enters and leaves the cell, so what is it called?"}
        self.assert_rejected(leak, "gives away its own answer")

    def test_question_that_leaks_the_opening_reference_answer_is_rejected(self):
        leak = {**FOLLOW, "question": "Cells are the basic structural and functional unit of all living organisms, so "
                                      "what barrier does a living cell have?"}
        self.assert_rejected(leak, "reveal an earlier reference answer")

    def test_rewording_of_the_opening_question_is_rejected(self):
        reworded = {**FOLLOW, "question": "recall task r1?"}
        self.assert_rejected(reworded, "rewording")

    def test_rewording_of_text_already_shown_is_rejected(self):
        self.script(["partial", "partial"], [FOLLOW, FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        self.answer(session, "a2", "Not sure the membrane")
        self.assertEqual(self.plan(session)["step"], "END")

    def test_same_answer_as_an_earlier_question_is_rejected(self):
        self.assert_rejected({**FOLLOW, "expected_answer": base.ANSWER_TEXT.lower() + " overall"},
                             "same answer")

    def test_different_question_must_be_genuinely_different(self):
        self.script(["partial", "correct"], [FOLLOW, {**DIFFERENT, "question": FOLLOW["question"] + " Name it."}])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        self.answer(session, "a2", "The cell membrane")
        self.assertEqual(self.plan(session)["step"], "TRANSFER")
        with self.assertRaises(ReasoningError) as caught:
            self.nxt(session, "n2")
        self.assertIn("rewording", str(caught.exception))

    def test_malformed_reply_is_rejected(self):
        self.assert_rejected({"message": "Here is a question", "diagnosis": "none", "citations": CITE}, "required structure")

    def test_repeated_rejections_degrade_to_a_fixed_fallback_and_stop_the_sequence(self):
        session = self.start_partial([{**FOLLOW, "citations": []}, {**FOLLOW, "citations": []}])
        for _ in range(2):
            with self.assertRaises(ReasoningError):
                self.nxt(session)
        calls = len(self.provider.calls)
        done = self.nxt(session)  # third attempt with the same id: no model call, fixed note, nothing invented
        self.assertEqual(len(self.provider.calls), calls)
        self.assertEqual(done["tutor"]["text"], tutoring.FALLBACK_QUESTION)
        view = done["session"]
        self.assertEqual(view["sequence"]["asked"], 1)
        self.assertEqual((view["sequence"]["plan"]["step"], view["sequence"]["plan"]["reason"]), ("END", "GENERATION_FAILED"))
        self.assertNotIn("NEXT", view["available_actions"])
        self.assertIn("ANSWER", view["available_actions"])  # the student can still work on the current question
        with self.assertRaises(tutoring.TutorSessionError):
            self.nxt(session, "another")

    def test_sources_changed_degrades_without_a_model_call(self):
        session = self.start_partial([FOLLOW])
        self.fingerprint = {"algorithm": "sha256", "value": "changed"}
        calls = len(self.provider.calls)
        done = self.nxt(session)
        self.assertEqual(len(self.provider.calls), calls)
        self.assertIn("changed", done["tutor"]["text"])
        self.assertEqual(done["session"]["sequence"]["plan"]["reason"], "GENERATION_FAILED")


class AuditTests(SequenceBase):
    def test_first_contact_is_only_claimed_when_nothing_else_in_the_week_was_helped(self):
        self.script(["partial", "partial"], [])
        first = self.create("TEST_ME")
        self.answer(first, "a1", "Cells are units")
        self.assertEqual(self.learning()["evidence"][0]["lineage"]["earlier_help_elsewhere"], False)
        self.assertEqual(self.evidence_labels(), ["UNAIDED_FIRST_CONTACT"])
        second = self.create("TEST_ME", request="req-2")  # a different task, same week, after earlier help
        self.answer(second, "b1", "Second")
        self.assertEqual(self.learning()["evidence"][1]["lineage"]["earlier_help_elsewhere"], True)
        self.assertEqual(self.evidence_labels(), ["UNAIDED_FIRST_CONTACT", "UNAIDED_UNLINKED"])
        self.assertEqual(self.view(second)["summary"]["questions"][0]["evidence"], "UNAIDED_UNLINKED")
        # A missing or unknown flag (older attempts) is never read as first contact.
        for flag in ({}, {"earlier_help_elsewhere": None}):
            self.assertEqual(tp.classify_evidence({"assistance_status": "UNAIDED", "lineage": {"role": "INITIAL", **flag}}),
                             "UNAIDED_UNLINKED")

    def test_help_exposures_from_other_sessions_are_never_rewritten(self):
        self.script(["partial", "partial"], [])
        first = self.create("TEST_ME")
        self.answer(first, "a1", "Cells are units")
        before = deepcopy(self.learning()["task_exposures"])
        second = self.create("TEST_ME", request="req-2")
        self.answer(second, "b1", "Second")
        self.assertEqual(self.learning()["task_exposures"][:len(before)], before)

    def test_decoy_citation_cannot_borrow_support_from_another_page(self):
        decoy = {**FOLLOW, "citations": [{"source_id": "s1", "pdf_page": 1}, {"source_id": "s1", "pdf_page": 2}]}
        session = GeneratedQuestionRejectionTests.start_partial(self, [decoy])
        with self.assertRaises(ReasoningError) as caught:
            self.nxt(session)
        self.assertIn("a cited passage does not support", str(caught.exception))

    def test_citing_only_an_irrelevant_page_is_rejected(self):
        session = GeneratedQuestionRejectionTests.start_partial(self, [{**FOLLOW, "citations": [{"source_id": "s1", "pdf_page": 2}]}])
        with self.assertRaises(ReasoningError) as caught:
            self.nxt(session)
        self.assertIn("not supported", str(caught.exception))

    def test_expected_answer_that_only_restates_the_question_is_rejected(self):
        restated = {**FOLLOW, "expected_answer": "cell organism living control leave enter part"}
        session = GeneratedQuestionRejectionTests.start_partial(self, [restated])
        with self.assertRaises(ReasoningError) as caught:
            self.nxt(session)
        self.assertIn("adds nothing beyond the question", str(caught.exception))

    def test_question_repeating_an_earlier_quiz_question_is_rejected(self):
        repeat = {**FOLLOW, "question": "recall task r2?"}
        session = GeneratedQuestionRejectionTests.start_partial(self, [repeat])
        with self.assertRaises(ReasoningError) as caught:
            self.nxt(session)
        self.assertIn("rewording", str(caught.exception))

    def test_reference_that_stops_being_supported_is_never_used_to_judge_an_answer(self):
        self.script(["partial", "correct"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        self.passage = "Nothing here about the topic; only harbour weather."
        calls = len(self.provider.calls)
        result = self.answer(session, "a2", "The cell membrane")
        self.assertEqual(len(self.provider.calls), calls)  # no judgement was asked for
        self.assertEqual(result["diagnosis"], "unclear")
        evaluation = self.learning()["evidence"][1]["evaluation"]
        self.assertEqual((evaluation["outcome"], evaluation["basis"]), ("UNCLEAR", "REFERENCE_NOT_SUPPORTED"))
        self.assertEqual(self.learning()["evidence"][1]["student_response"], "The cell membrane")

    def test_ending_while_a_question_is_being_built_does_not_open_it_afterwards(self):
        def end_midway(_context):
            tutoring.end_session("BIO101", 1, session["session_id"], workspace_root=self.root)
            return deepcopy(FOLLOW)

        self.script(["partial"], [end_midway])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        with self.assertRaises(tutoring.TutorSessionError):
            self.nxt(session)
        view = self.view(session)
        self.assertEqual((view["status"], view["sequence"]["asked"]), ("ENDED", 1))
        with self.assertRaises(tutoring.TutorSessionError):
            self.nxt(session)

    def test_failed_retries_cannot_exceed_the_model_call_cap(self):
        self.script(["partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        data = json.loads(self.session_file(session).read_text())
        data["model_calls"] = tutoring.MAX_MODEL_CALLS - 2
        self.session_file(session).write_text(json.dumps(data))
        self.provider.fail_next = 50
        before = len(self.provider.calls)
        raised = []
        for _ in range(5):
            try:
                self.nxt(session)
            except (ReasoningError, tutoring.TutorSessionError) as exc:
                raised.append(f"{type(exc).__name__}: {exc}")
        self.assertEqual(len(self.provider.calls) - before, 1)  # one call spent; a retry may not use the last one
        self.assertEqual(self.view(session)["model_calls"], tutoring.MAX_MODEL_CALLS - 1)
        self.assertEqual(len(raised), 5)
        self.assertIn("AI-call limit", raised[-1])

    def test_skip_hint_reveal_and_dispute_spend_no_extra_questions_or_calls(self):
        self.script(["misconception"], [FOLLOW])
        session = self.create("TEST_ME")
        result = self.answer(session, "a1", "Viruses are the unit of life")
        calls = self.view(session)["model_calls"]
        tutoring.dispute_diagnosis({}, "BIO101", 1, session["session_id"], client_turn_id="d1",
                                   target_turn_id=result["tutor"]["in_reply_to"], provider=self.provider,
                                   workspace_root=self.root)
        self.hint(session, "h1")
        self.reveal(session)
        view = self.view(session)
        self.assertEqual((view["model_calls"], view["sequence"]["asked"]), (calls, 1))
        self.assertEqual(len(self.learning()["evidence"]), 1)


class SkipTests(SequenceBase):
    def test_skip_records_nothing_and_needs_no_model_call(self):
        self.script([], [FOLLOW])
        session = self.create("TEST_ME")
        done = self.skip(session)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.learning()["evidence"], [])
        self.assertNotIn("task_exposures", self.learning())
        view = done["session"]
        self.assertNotIn("ANSWER", view["available_actions"])
        self.assertEqual(self.plan(session)["reason"], "FRESH_ANGLE_AFTER_SKIP")
        with self.assertRaises(tutoring.TutorSessionError):
            self.answer(session, "a1", "late answer")
        self.assertEqual(self.nxt(session)["session"]["sequence"]["current"]["role"], "FOLLOW_UP")

    def test_two_skips_stop_the_sequence(self):
        self.script([], [FOLLOW])
        session = self.create("TEST_ME")
        self.skip(session)
        self.nxt(session)
        self.skip(session, "s2")
        self.assertEqual((self.plan(session)["step"], self.plan(session)["reason"]), ("END", "REPEATED_SKIPS"))

    def test_an_answered_question_cannot_be_skipped_but_can_be_left_with_next_or_end(self):
        self.script(["correct"], [])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are the basic unit of living organisms")
        self.assertNotIn("SKIP", self.view(session)["available_actions"])
        with self.assertRaises(tutoring.TutorSessionError):
            self.skip(session)


class StopRuleAndBudgetTests(SequenceBase):
    def test_question_count_is_bounded(self):
        self.assertEqual(tp.MAX_QUESTIONS, 3)
        step = tp.plan_next(role="FOLLOW_UP", asked=3, settled=True, diagnosis="correct", calls_left=10)
        self.assertEqual(step, {"step": "END", "reason": "QUESTION_LIMIT"})

    def test_call_budget_blocks_a_new_question_but_not_ending(self):
        self.script(["partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        data = json.loads(self.session_file(session).read_text())
        data["model_calls"] = tutoring.MAX_MODEL_CALLS - 1
        self.session_file(session).write_text(json.dumps(data))
        self.assertEqual((self.plan(session)["step"], self.plan(session)["reason"]), ("END", "CALL_BUDGET"))
        with self.assertRaises(tutoring.TutorSessionError):
            self.nxt(session)
        self.assertIn("END", self.view(session)["available_actions"])

    def test_hard_cap_still_applies_to_question_generation(self):
        self.script(["partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        data = json.loads(self.session_file(session).read_text())
        data["model_calls"] = tutoring.MAX_MODEL_CALLS
        self.session_file(session).write_text(json.dumps(data))
        with self.assertRaises(tutoring.TutorSessionError):
            self.nxt(session)
        self.assertEqual(len(self.provider.asked()), 0)

    def test_each_new_question_spends_exactly_one_call(self):
        self.script(["partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        before = self.view(session)["model_calls"]
        self.assertEqual(self.nxt(session)["session"]["model_calls"], before + 1)

    def test_policy_table_is_deterministic(self):
        cases = [
            (dict(role="INITIAL", asked=1, settled=False), "NONE", "AWAITING_ANSWER"),
            (dict(role="INITIAL", asked=1, settled=True, diagnosis="off_target"), "FOLLOW_UP", "OFF_TARGET"),
            (dict(role="INITIAL", asked=1, settled=True, diagnosis="correct", hedged=True), "FOLLOW_UP", "REASONING_CHECK"),
            (dict(role="INITIAL", asked=1, settled=True, diagnosis="unclear"), "NONE", "NEEDS_CLARITY"),
            (dict(role="INITIAL", asked=1, settled=True, diagnosis="correct", skips_total=2), "END", "REPEATED_SKIPS"),
            (dict(role="FOLLOW_UP", asked=3, settled=True, diagnosis="correct"), "END", "QUESTION_LIMIT"),
            (dict(role="TRANSFER", asked=3, settled=True, diagnosis="correct"), "END", "SEQUENCE_COMPLETE"),
            (dict(role="TRANSFER", asked=2, settled=True, diagnosis="partial"), "END", "SEQUENCE_COMPLETE"),
            (dict(role="FOLLOW_UP", asked=2, settled=True, diagnosis="correct"), "TRANSFER", "FOLLOW_UP_CORRECT"),
            (dict(role="FOLLOW_UP", asked=2, settled=True, diagnosis="correct", self_confidence="GUESSING"), "END", "REVIEW_SOURCES"),
            (dict(role="FOLLOW_UP", asked=2, settled=True, revealed=True), "END", "REVIEW_SOURCES"),
            (dict(role="INITIAL", asked=1, settled=True, diagnosis="partial", generation_failures=1), "END", "GENERATION_FAILED"),
        ]
        for facts, step, reason in cases:
            with self.subTest(facts=facts):
                self.assertEqual(tp.plan_next(**{"calls_left": 10, **facts}), {"step": step, "reason": reason})
        self.assertTrue(set(tp.STEP_REASONS) >= {r for _, _, r in cases})


class RecoveryTests(SequenceBase):
    def test_failed_generation_is_retried_with_the_same_turn_id_without_duplicating_a_question(self):
        self.script(["partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.provider.fail_next = 1
        with self.assertRaises(ReasoningError):
            self.nxt(session)
        mid = self.view(session)
        self.assertEqual((mid["recovery"]["action"], mid["recovery"]["state"], mid["sequence"]["asked"]), ("NEXT", "RETRY", 1))
        with self.assertRaises(tutoring.TutorSessionError):  # nothing new until the unfinished turn is repeated
            self.skip(session, "other")
        done = self.nxt(session)
        self.assertEqual(done["status"], "COMPLETE")
        self.assertEqual(done["session"]["sequence"]["asked"], 2)

    def test_process_death_during_generation_leaves_a_pending_turn_that_recovers_after_the_lease(self):
        def die(_context):
            raise KeyboardInterrupt  # not an Exception: nothing marks the turn FAILED, like a killed process

        self.script(["partial"], [die, FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        with self.assertRaises(KeyboardInterrupt):
            self.nxt(session)
        self.assertEqual(self.view(session)["recovery"]["state"], "IN_PROGRESS")
        with self.assertRaises(tutoring.TutorSessionError):
            self.nxt(session)  # still inside the lease: refuse rather than double-spend
        path = self.session_file(session)
        data = json.loads(path.read_text())
        next(t for t in data["turns"] if t.get("action") == "NEXT")["started_at"] = "2020-01-01T00:00:00+00:00"
        path.write_text(json.dumps(data))
        self.assertEqual(self.view(session)["recovery"]["state"], "RETRY")
        done = self.nxt(session)
        self.assertEqual((done["status"], done["session"]["sequence"]["asked"]), ("COMPLETE", 2))
        self.assertEqual(self.nxt(session)["session"]["sequence"]["asked"], 2)  # and stays idempotent

    def test_duplicate_next_submission_returns_the_stored_result(self):
        self.script(["partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        first = self.nxt(session)
        calls = len(self.provider.calls)
        again = self.nxt(session)
        self.assertEqual(len(self.provider.calls), calls)
        self.assertEqual(again["tutor"]["text"], first["tutor"]["text"])
        self.assertEqual(again["session"]["sequence"]["asked"], 2)
        with self.assertRaises(tutoring.TutorSessionError):  # a second click with a new id has nothing to advance to
            self.nxt(session, "n-second-click")
        self.assertEqual(self.view(session)["sequence"]["asked"], 2)

    def test_duplicate_answer_to_a_generated_question_makes_one_attempt(self):
        self.script(["partial", "correct"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        self.answer(session, "a2", "The membrane")
        self.answer(session, "a2", "The membrane")
        self.assertEqual(len(self.learning()["evidence"]), 2)
        with self.assertRaises(tutoring.TutorSessionError):
            self.answer(session, "a2", "something else")

    def test_ending_with_an_unfinished_next_keeps_everything_and_stays_idempotent(self):
        self.script(["partial"], [FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        self.provider.fail_next = 1
        with self.assertRaises(ReasoningError):
            self.nxt(session)
        ended = tutoring.end_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        again = tutoring.end_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual((ended["status"], again["status"]), ("ENDED", "ENDED"))
        self.assertEqual(len(self.learning()["evidence"]), 1)
        self.assertEqual(ended["summary"]["asked"], 1)

    def test_a_question_rejected_in_flight_does_not_leave_a_half_open_question(self):
        self.script(["partial"], [{**FOLLOW, "citations": []}, FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        with self.assertRaises(ReasoningError):
            self.nxt(session)
        raw = json.loads(self.session_file(session).read_text())
        self.assertEqual([q["question_id"] for q in raw["questions"]], ["q1"])
        self.assertEqual(raw["current_question_id"], "q1")
        self.assertEqual(self.nxt(session)["session"]["sequence"]["asked"], 2)


class LegacySessionTests(SequenceBase):
    def downgrade(self, session):
        path = self.session_file(session)
        data = json.loads(path.read_text())
        for key in ("questions", "current_question_id", "sequence_state"):
            data.pop(key)
        data["schema_version"] = 1
        for turn in data["turns"]:
            for key in ("question_id", "question_role", "role_in_sequence", "hedged", "non_answer"):
                turn.pop(key, None)
        path.write_text(json.dumps(data, indent=2))
        return path

    def test_reading_a_version_1_session_migrates_in_memory_and_never_writes(self):
        self.script(["partial"], [])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        path = self.downgrade(session)
        before = path.read_bytes()
        view = tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        resumed = tutoring.resume_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        rows = tutoring.list_sessions("BIO101", 1, workspace_root=self.root)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((view["schema_version"], view["migrated_from"]), (2, 1))
        self.assertEqual([q["role"] for q in view["questions"]], ["INITIAL"])
        self.assertEqual(view["sequence"]["position"], 1)
        self.assertEqual(rows[0]["status"], "ACTIVE")
        self.assertEqual(resumed["sequence"]["plan"]["reason"], "PARTIAL_ANSWER")  # a migrated session can continue into the sequence
        self.assertNotIn(base.ANSWER_TEXT, json.dumps(view))

    def test_a_version_1_session_continues_and_is_upgraded_by_the_first_real_action(self):
        self.script(["partial", "partial"], [FOLLOW])
        session = self.create("TEST_ME")
        path = self.downgrade(session)
        self.hint(session, "h1")  # a real mutation
        self.assertEqual(json.loads(path.read_text())["schema_version"], 2)
        result = self.answer(session, "a1", "Cells are units")
        attempt = self.learning()["evidence"][0]
        self.assertEqual(attempt["lineage"]["role"], "INITIAL")
        self.assertEqual(result["assistance_status"], "PROMPTED")
        self.nxt(session)
        self.assertEqual(self.view(session)["sequence"]["current"]["role"], "FOLLOW_UP")

    def test_a_version_1_teach_me_session_keeps_its_explanation_in_lineage(self):
        self.script([], [])
        session = self.create("TEACH_ME")
        self.downgrade(session)
        view = self.view(session)
        self.assertEqual(view["questions"][0]["lineage"]["prior_help"], ["EXPLANATION"])
        self.assertTrue(view["sequence"]["current"]["assisted"])

    def test_unknown_future_schema_version_is_still_refused(self):
        session = self.create("TEST_ME")
        path = self.session_file(session)
        data = json.loads(path.read_text())
        data["schema_version"] = 99
        path.write_text(json.dumps(data))
        with self.assertRaises(StateError):
            self.view(session)


class NoOverclaimTests(SequenceBase):
    def test_views_never_leak_private_answers_or_make_mastery_or_retention_claims(self):
        self.script(["partial", "correct", "correct"], [FOLLOW, DIFFERENT])
        session = self.create("TEACH_ME")
        self.answer(session, "a1", "Cells are units")
        self.nxt(session)
        self.answer(session, "a2", "The membrane")
        self.nxt(session, "n2")
        self.answer(session, "a3", "Mitochondria")
        ended = tutoring.end_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        text = json.dumps({"summary": ended["summary"], "sequence": ended["sequence"]})
        self.assertIsNone(FORBIDDEN.search(text), FORBIDDEN.search(text))
        for secret in (base.ANSWER_TEXT, FOLLOW["expected_answer"], DIFFERENT["expected_answer"]):
            self.assertNotIn(secret, json.dumps(ended))
        summary = ended["summary"]
        self.assertEqual((summary["asked"], summary["answered"], summary["skipped"], summary["revealed"]), (3, 3, 0, 0))
        self.assertEqual([i["evidence"] for i in summary["questions"]],
                         ["ASSISTED", "NEW_QUESTION_AFTER_HELP", "NEW_QUESTION_AFTER_HELP"])
        self.assertIn("does not show lasting understanding", summary["caveat"])

    def test_reveal_is_counted_in_the_summary_and_the_answer_stays_hidden_before_it(self):
        self.script([], [])
        session = self.create("TEST_ME")
        self.assertNotIn(base.ANSWER_TEXT, json.dumps(self.view(session)))
        revealed = self.reveal(session)
        self.assertEqual(revealed["session"]["summary"]["revealed"], 1)


class HubSequenceTests(unittest.TestCase):
    """Hub pages for the sequence, using the Hub fixture's helpers (not its tests)."""

    make_client = hub.HubTutorTests.make_client
    snapshot = hub.HubTutorTests.snapshot
    learning = hub.HubTutorTests.learning
    start = hub.HubTutorTests.start
    post = hub.HubTutorTests.post
    turn_id = hub.HubTutorTests.turn_id
    page = hub.HubTutorTests.page

    def setUp(self):
        hub.HubTutorTests.setUp(self)
        self.provider = Script(["partial", "correct", "correct"], [FOLLOW, DIFFERENT])
        self.client = self.make_client(self.provider)

    def _context(self, _state, module_code, week_number, workflow, **_kw):
        return {"module": {"code": module_code}, "week": {"number": week_number},
                "sources": [{"id": "s1", "extraction": {"fingerprint": hub.FP}}],
                "source_contexts": [{"source_id": "s1", "retrieval": {"status": "matched"},
                                     "excerpts": [{"pdf_page": 1, "text": PASSAGE}]}]}

    def test_hub_walks_the_whole_sequence_and_shows_why_progress_and_a_factual_summary(self):
        url = self.start("TEST_ME")
        html = self.page(url)
        self.assertIn("Question 1 of up to 3", html)
        self.assertNotIn("Ask for the next question", html)
        self.post(url, "answer", client_turn_id=self.turn_id(html), response="Cells are units")
        html = self.page(url)
        self.assertIn("Ask for the next question", html)
        self.assertIn("targets the part that was missing", html)
        self.assertEqual(self.post(url, "next", client_turn_id=self.turn_id(html)).status_code, 303)
        html = self.page(url)
        self.assertIn("Question 2 of up to 3", html)
        self.assertIn(FOLLOW["question"], html)
        self.assertIn("Why this question:", html)
        self.assertIn("follow-up question", html)
        self.assertIn("Progress through this session", html)
        self.assertNotIn(FOLLOW["expected_answer"], html)
        self.assertIn("Recorded as unaided", self.after_answer(url, "The membrane"))
        html = self.page(url)
        self.post(url, "next", client_turn_id=self.turn_id(html))
        html = self.page(url)
        self.assertIn("Question 3 of up to 3", html)
        self.assertIn("different question", html)
        self.assertNotIn("Ask for the next question", html)
        self.assertIn("Skip this question", html)
        self.post(url, "end")
        html = self.page(url)
        self.assertIn("Session summary", html)
        self.assertIn("This session has ended", html)
        self.assertIn("does not show lasting understanding", html)
        self.assertIsNone(FORBIDDEN.search(re.sub(r"<style>.*?</style>", "", html, flags=re.S)),
                          FORBIDDEN.search(html))
        self.assertIn("a new question, answered after help on an earlier one", html)

    def after_answer(self, url, text):
        self.post(url, "answer", client_turn_id=self.turn_id(self.page(url)), response=text)
        return self.page(url)

    def test_hub_skip_and_rejected_question_are_safe(self):
        self.provider = Script(["partial"], [{**FOLLOW, "citations": []}] * 3)
        self.client = self.make_client(self.provider)
        url = self.start("TEST_ME", request_id="req-skip")
        html = self.page(url)
        self.assertIn("Skip this question", html)
        self.post(url, "skip", client_turn_id=self.turn_id(html))
        html = self.page(url)
        self.assertIn("skipped this question", html)
        self.assertEqual(self.learning()["evidence"], [])
        turn = self.turn_id(html)
        for _ in range(2):
            error = self.post(url, "next", client_turn_id=turn)
            self.assertEqual(error.status_code, 200)  # re-rendered with an error, nothing shown
            self.assertIn("Generated question rejected", error.text)
        self.post(url, "next", client_turn_id=turn)
        html = self.page(url)
        self.assertIn("so I&#39;m not going to invent one", html)
        self.assertNotIn("Ask for the next question", html)

    def test_hub_get_pages_stay_read_only_for_sequence_sessions(self):
        url = self.start("TEST_ME", request_id="req-ro")
        self.post(url, "answer", client_turn_id=self.turn_id(self.page(url)), response="Cells are units")
        before, calls = self.snapshot(), len(self.provider.calls)
        self.page(url)
        self.page(url)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.provider.calls), calls)

if __name__ == "__main__":
    unittest.main()
