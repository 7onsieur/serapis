"""A stored reference answer may grade a student only when the pages it cites support it.

Synthetic text, scripted offline provider, no network (``tests/conftest.py`` fails any real socket).
The fixture is borrowed from ``test_tutoring``; only the supplied passages and the stored reference change.
Lexical support is a screen, not proof of truth -- the last tests pin what it can and cannot catch.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import test_tutoring as base  # noqa: E402

from university_jarvis import tutor_policy as tp  # noqa: E402
from university_jarvis import hub_service, tutoring  # noqa: E402

PAGE1 = ("Standard error describes how much sample means vary. It is calculated as the sample standard deviation "
         "divided by the square root of the sample size. A larger sample gives a smaller standard error.")
PAGE2 = ("Standard deviation describes how far observations fall from the sample mean. It is calculated from squared "
         "deviations around the mean. A larger spread gives a larger standard deviation.")
GOOD = ("Standard error is the sample standard deviation divided by the square root of the sample size, so a larger "
        "sample gives a smaller standard error.")


class ReferenceSafetyTests(unittest.TestCase):
    setUp = base.TutoringTests.setUp
    create = base.TutoringTests.create
    answer = base.TutoringTests.answer
    learning = base.TutoringTests.learning
    session_file = base.TutoringTests.session_file

    def _context(self, _state, module_code, week_number, workflow, **_kw):
        excerpts = [{"pdf_page": n, "text": t} for n, t in getattr(self, "pages", {1: PAGE1, 2: PAGE2}).items()]
        return {"module": {"code": module_code}, "week": {"number": week_number},
                "sources": [{"id": "s1", "extraction": {"fingerprint": self.fingerprint}}],
                "source_contexts": [{"source_id": "s1", "retrieval": {"status": "matched"}, "excerpts": excerpts}]}

    def set_reference(self, answer, page=1):
        record = json.loads(self.record_path.read_text())
        quiz = record["learning"]["quiz_history"]["attempts"][0]
        quiz["answers"][0]["answer"] = answer
        quiz["questions"][0]["provenance"][0]["pdf_page"] = page
        self.record_path.write_text(json.dumps(record))

    def set_reference_of(self, qid, answer, page=1):
        record = json.loads(self.record_path.read_text())
        quiz = record["learning"]["quiz_history"]["attempts"][0]
        next(a for a in quiz["answers"] if a["question_id"] == qid)["answer"] = answer
        next(q for q in quiz["questions"] if q["question_id"] == qid)["provenance"][0]["pdf_page"] = page
        self.record_path.write_text(json.dumps(record))

    def feedback_calls(self):
        return [c for c in self.provider.calls if c["action"] == "FEEDBACK"]

    def assert_not_graded(self, result, *, text="my answer"):
        self.assertEqual(self.feedback_calls(), [])  # the reference never reached the model
        self.assertEqual(result["tutor"]["kind"], "FEEDBACK")
        attempt = self.learning()["evidence"][0]
        self.assertEqual(attempt["student_response"], text)  # the student's answer is kept
        self.assertEqual((attempt["evaluation"]["outcome"], attempt["evaluation"]["basis"]),
                         ("UNCLEAR", "REFERENCE_NOT_SUPPORTED"))
        self.assertNotIn("correct", result["tutor"]["text"].lower().replace("can't check", ""))

    # --- referenced answer is backed -------------------------------------------------
    def test_a_supported_reference_still_grades(self):
        self.set_reference(GOOD)
        self.provider.diagnosis = "correct"
        result = self.answer(self.create("TEST_ME"))
        self.assertEqual(len(self.feedback_calls()), 1)
        self.assertEqual(self.learning()["evidence"][0]["evaluation"]["basis"], "TUTOR_TURN_MODEL_JUDGEMENT")
        self.assertEqual(result["tutor"]["kind"], "FEEDBACK")

    # --- the four failure families -----------------------------------------------------
    def test_an_unsupported_reference_is_not_used_to_grade(self):
        self.set_reference("The standard error is the largest mistake a pollster can make in a survey of voters.")
        self.assert_not_graded(self.answer(self.create("TEST_ME")))

    def test_a_contradicted_reference_that_flips_a_direction_word_is_not_used(self):
        self.set_reference(GOOD.replace("divided", "multiplied"))
        self.assert_not_graded(self.answer(self.create("TEST_ME")))

    def test_a_reference_asserting_an_absolute_the_page_never_states_is_not_used(self):
        self.set_reference(GOOD + " Doubling the sample always halves it exactly.")
        self.assert_not_graded(self.answer(self.create("TEST_ME")))

    def test_a_reference_cited_to_a_page_that_was_not_supplied_is_not_used(self):
        self.set_reference(GOOD, page=7)
        self.assert_not_graded(self.answer(self.create("TEST_ME")))

    def test_a_reference_cited_without_a_page_number_is_not_used(self):
        self.set_reference(GOOD, page=None)
        self.assert_not_graded(self.answer(self.create("TEST_ME")))

    def test_a_reference_cited_to_the_decoy_page_is_not_used(self):
        self.set_reference(GOOD, page=2)  # page 2 is about standard deviation; page 1 backs the answer better
        self.assert_not_graded(self.answer(self.create("TEST_ME")))

    def test_a_reference_without_a_source_fingerprint_is_unsupported(self):
        task = {"expected_answer": GOOD,
                "source_references": [{"source_id": "s1", "pdf_page": 1, "fingerprint": None}]}
        self.assertIn("fingerprint", tutoring._reference_problem(task, self._context(None, "BIO101", 1, "x")))
        task["source_references"][0]["fingerprint"] = self.fingerprint
        self.assertIsNone(tutoring._reference_problem(task, self._context(None, "BIO101", 1, "x")))
        self.assertIsNone(tutoring._reference_problem({"expected_answer": None, "source_references": []}, {}))

    # --- retries, duplicates, recovery ---------------------------------------------------
    def test_duplicate_submission_is_stored_once_and_never_flips_to_a_judgement(self):
        self.set_reference("The standard error is the largest mistake a pollster can make in a survey of voters.")
        session = self.create("TEST_ME")
        first = self.answer(session, "a1")
        again = self.answer(session, "a1")
        self.assertEqual(first["tutor"], again["tutor"])
        self.assertEqual(len(self.learning()["evidence"]), 1)
        self.assert_not_graded(again)

    def test_a_second_answer_after_a_rejected_reference_is_also_not_graded(self):
        self.set_reference("Standard error means the survey has too few voters and a biased pollster.")
        session = self.create("TEST_ME")
        self.answer(session, "a1", text="first try")
        self.answer(session, "a2", text="second try")
        self.assertEqual(self.feedback_calls(), [])
        self.assertEqual([a["evaluation"]["basis"] for a in self.learning()["evidence"]],
                         ["REFERENCE_NOT_SUPPORTED"] * 2)

    def test_the_decision_is_made_again_from_the_stored_session_after_a_restart(self):
        self.set_reference(GOOD, page=2)
        session = self.create("TEST_ME")
        # a fresh load of the stored session (as after a server restart) reaches the same verdict
        reloaded = tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual(reloaded["task"]["has_reference_answer"], True)
        self.assert_not_graded(self.answer(reloaded))

    # --- policy unit tests and pinned limitations ------------------------------------------
    def test_policy_accepts_a_faithful_paraphrase_and_names_each_rejection(self):
        self.assertIsNone(tp.reference_unsupported(GOOD, [PAGE1], [PAGE2]))
        self.assertIn("no checkable", tp.reference_unsupported("", [PAGE1]))
        self.assertIn("not supported", tp.reference_unsupported("Pollsters survey many voters.", [PAGE1]))
        self.assertIsNotNone(tp.reference_unsupported(GOOD, [PAGE2], [PAGE1]))  # decoy cited, true page uncited

    def test_known_limitation_a_relation_swap_using_the_passages_own_words_is_not_detected(self):
        swapped = ("Standard error is the square root of the sample size divided by the sample standard deviation, "
                   "so a larger sample gives a smaller standard error.")
        # Documented gap: lexical screening cannot tell a swapped numerator and denominator. Needs semantic checking.
        self.assertIsNone(tp.reference_unsupported(swapped, [PAGE1], [PAGE2]))


BAD = "Standard error is the largest mistake a pollster can make in a survey of voters."


class StudentFacingActionTests(ReferenceSafetyTests):
    """REVEAL, HINT, EXPLAIN, follow-up generation and re-evaluation all go through the same gate."""
    hint = base.TutoringTests.hint
    reveal = base.TutoringTests.reveal

    def never_sent(self, text=BAD):
        self.assertFalse([c for c in self.provider.calls if text in json.dumps(c)], "reference reached a model prompt")

    def test_reveal_of_an_unverified_reference_shows_nothing_and_records_no_help(self):
        self.set_reference(BAD)
        session = self.create("TEST_ME")
        shown = self.reveal(session)
        self.assertEqual(shown["tutor"]["kind"], "NOTE")
        self.assertIn("can't verify the reference answer", shown["tutor"]["text"])
        self.assertNotIn(BAD, json.dumps(shown))
        self.assertFalse(self.learning().get("task_exposures"))  # no help was given, so none is recorded
        self.assertFalse(tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)["revealed"])
        self.assertEqual(self.reveal(session)["tutor"], shown["tutor"])  # duplicate request: stored result
        self.assertEqual(self.reveal(session, "rv2")["tutor"]["kind"], "NOTE")  # a retry is refused the same way
        answered = self.answer(session, "a1")  # the student can still answer; it is not classified as revealed
        self.assertEqual(answered["assistance_status"], "UNAIDED")
        attempt = self.learning()["evidence"][0]
        self.assertEqual((attempt["student_response"], attempt["evaluation"]["basis"]), ("my answer", "REFERENCE_NOT_SUPPORTED"))
        self.never_sent()

    def test_reveal_of_a_verified_reference_still_works(self):
        self.set_reference(GOOD)
        shown = self.reveal(self.create("TEST_ME"))
        self.assertEqual((shown["tutor"]["kind"], shown["tutor"]["text"]), ("REVEAL", GOOD))

    def test_reveal_is_refused_when_the_source_no_longer_matches(self):
        self.set_reference(GOOD)
        session = self.create("TEST_ME")
        self.fingerprint = {"algorithm": "sha256", "value": "changed"}
        self.assertEqual(self.reveal(session)["tutor"]["kind"], "NOTE")

    def test_second_level_hint_does_not_send_an_unverified_reference_to_the_model(self):
        self.set_reference(BAD)
        session = self.create("TEST_ME")
        self.assertEqual(self.hint(session, "h1")["tutor"]["kind"], "HINT")  # level 1 only names the pages
        refused = self.hint(session, "h2")
        self.assertEqual(refused["tutor"]["kind"], "NOTE")
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)["hint_level"], 1)
        self.assertEqual([e["kind"] for e in self.learning()["task_exposures"]], ["HINT"])  # only level 1 was shown

    def test_second_level_hint_with_a_verified_reference_still_calls_the_model(self):
        self.set_reference(GOOD)
        session = self.create("TEST_ME")
        self.hint(session, "h1")
        self.assertEqual(self.hint(session, "h2")["tutor"]["kind"], "HINT")
        self.assertEqual([c["action"] for c in self.provider.calls], ["HINT"])

    def test_teach_me_will_not_explain_from_an_unverified_reference(self):
        self.set_reference(BAD)
        self.set_reference_of("r2", BAD)
        with self.assertRaises(tutoring.TutorSessionError) as raised:
            self.create("TEACH_ME")
        self.assertIn("none of the available tasks has a reference answer it can verify", str(raised.exception))
        self.assertIn("TEST_ME", str(raised.exception))  # the recovery option is named
        self.assertEqual(self.provider.calls, [])
        self.assertFalse(self.learning().get("task_exposures"))
        self.assertEqual(tutoring.list_sessions("BIO101", 1, workspace_root=self.root), [])

    def test_teach_me_with_a_verified_reference_still_explains(self):
        self.set_reference(GOOD)
        self.assertEqual(self.create("TEACH_ME")["turns"][0]["kind"], "EXPLANATION")

    def test_follow_up_generation_withholds_an_unverified_parent_reference(self):
        self.set_reference(BAD)
        session = self.create("TEST_ME")
        tutoring.skip_question({}, "BIO101", 1, session["session_id"], client_turn_id="s1",
                               provider=self.provider, workspace_root=self.root)
        try:
            tutoring.next_question({}, "BIO101", 1, session["session_id"], client_turn_id="n1",
                                   provider=self.provider, workspace_root=self.root)
        except Exception:  # noqa: BLE001 - the scripted reply is not a valid question; only the prompt matters
            pass
        asked = [c for c in self.provider.calls if c["action"] == "NEXT_QUESTION"]
        self.assertEqual(len(asked), 1)
        self.assertIsNone(asked[0]["parent_expected_answer_or_rubric"])
        self.never_sent()

    def test_follow_up_generation_still_sends_a_verified_parent_reference(self):
        self.set_reference(GOOD)
        session = self.create("TEST_ME")
        tutoring.skip_question({}, "BIO101", 1, session["session_id"], client_turn_id="s1",
                               provider=self.provider, workspace_root=self.root)
        try:
            tutoring.next_question({}, "BIO101", 1, session["session_id"], client_turn_id="n1",
                                   provider=self.provider, workspace_root=self.root)
        except Exception:  # noqa: BLE001
            pass
        asked = [c for c in self.provider.calls if c["action"] == "NEXT_QUESTION"]
        self.assertEqual(asked[0]["parent_expected_answer_or_rubric"], GOOD)

    def test_a_session_stored_before_the_validator_is_gated_when_it_is_resumed(self):
        self.set_reference(GOOD)
        session = self.create("TEST_ME")  # created while the reference looked fine
        path = self.session_file(session)
        stored = json.loads(path.read_text())
        stored["task"]["expected_answer"] = BAD  # an older session holding an unverified reference
        for question in stored["questions"]:
            question["task"]["expected_answer"] = BAD
        path.write_text(json.dumps(stored))
        resumed = tutoring.resume_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertNotIn(BAD, json.dumps(resumed))  # the view never carries the reference
        self.assertEqual(self.reveal(resumed)["tutor"]["kind"], "NOTE")
        self.hint(resumed, "h1")
        self.assertEqual(self.hint(resumed, "h2")["tutor"]["kind"], "NOTE")
        self.assert_not_graded(self.answer(resumed))
        self.never_sent()

    def test_re_evaluating_a_saved_attempt_does_not_send_an_unverified_reference_to_the_model(self):
        self.set_reference(BAD)
        hub_service.answer_quiz_question("BIO101", 1, "quiz-1", "r1", "my answer", workspace_root=self.root)
        attempt_id = self.learning()["evidence"][0]["attempt_id"]
        saved = hub_service.evaluate_learning_attempt("BIO101", 1, attempt_id, state={}, provider=self.provider,
                                                      workspace_root=self.root)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(saved["evaluation"]["basis"], "REFERENCE_NOT_SUPPORTED")
        self.assertEqual(self.learning()["evidence"][0]["student_response"], "my answer")

    def test_re_evaluating_against_a_verified_reference_still_calls_the_model(self):
        self.set_reference(GOOD)
        hub_service.answer_quiz_question("BIO101", 1, "quiz-1", "r1", "my answer", workspace_root=self.root)
        attempt_id = self.learning()["evidence"][0]["attempt_id"]
        try:
            hub_service.evaluate_learning_attempt("BIO101", 1, attempt_id, state={}, provider=self.provider,
                                                  workspace_root=self.root)
        except Exception:  # noqa: BLE001 - the scripted reply is not an evaluation; only the call matters
            pass
        self.assertEqual(self.provider.calls[0]["expected_answer_or_rubric"], GOOD)

    def test_derived_numeric_references_are_not_graded_known_limitation(self):
        # Deliberately not weakened: a number derived from the page is not in the page, so it cannot be
        # verified lexically. Pinned for the later quantitative-verification work.
        self.set_reference("2")
        self.assert_not_graded(self.answer(self.create("TEST_ME")))


class RecoveryTests(ReferenceSafetyTests):
    """Phase 3 recovery: no repeated unverified task, bounded retries, source-only hints, independent NEXT."""

    hint = base.TutoringTests.hint
    reveal = base.TutoringTests.reveal
    never_sent = StudentFacingActionTests.never_sent

    def _context(self, state, module_code, week_number, workflow, **kw):
        self.queries = getattr(self, "queries", []) + [kw.get("query")]
        return super()._context(state, module_code, week_number, workflow, **kw)

    def snapshot(self):
        learning = self.learning()
        return {k: learning[k] for k in learning if k not in ("unverified_tasks",)}

    def test_teach_me_moves_to_another_verified_task_and_never_offers_the_bad_one_again(self):
        self.set_reference(BAD)
        self.set_reference_of("r2", GOOD)
        before = self.snapshot()
        session = self.create("TEACH_ME")
        self.assertEqual(session["task"]["origin"], "QUIZ:quiz-1:r2")
        self.assertEqual([c["action"] for c in self.provider.calls], ["EXPLAIN"])
        self.assertNotIn(BAD, json.dumps(self.provider.calls))
        self.assertEqual([e["task_key"] for e in self.learning()["task_exposures"]], ["QUIZ:quiz-1:r2"])
        self.assertEqual([(e["origin"], e["capability"]) for e in self.learning()["unverified_tasks"]],
                         [("QUIZ:quiz-1:r1", "RECALL")])
        self.assertEqual({k: v for k, v in self.snapshot().items() if k != "task_exposures"},
                         {k: v for k, v in before.items() if k != "task_exposures"})  # evidence untouched

    def test_a_rejected_task_is_not_recommended_to_a_later_session_either(self):
        self.set_reference(BAD)
        self.set_reference_of("r2", GOOD)
        first = self.create("TEACH_ME")
        tutoring.end_session("BIO101", 1, first["session_id"], workspace_root=self.root)
        record = json.loads(self.record_path.read_text())
        record["learning"]["task_exposures"] = []  # even with r2 free again, r1 stays out
        self.record_path.write_text(json.dumps(record))
        self.assertEqual(self.create("TEACH_ME", request="req-2")["task"]["origin"], "QUIZ:quiz-1:r2")

    def test_when_every_task_is_unverified_the_end_is_terminal_and_generation_is_bounded(self):
        self.set_reference(BAD)
        self.set_reference_of("r2", BAD)
        self.provider.override = {"task": "What is the standard error?", "expected_answer_or_rubric": BAD,
                                  "source_references": [{"source_id": "s1", "pdf_page": 1}]}
        before = self.snapshot()
        for n in range(6):
            with self.assertRaises(tutoring.TutorSessionError) as raised:
                self.create("TEACH_ME", request=f"req-{n}")
            self.assertIn("TEST_ME", str(raised.exception))  # always a clear terminal message with a way out
        # the quiz tasks were never sent to a model; at most MAX_UNVERIFIED_GENERATED new tasks were ever generated
        self.assertEqual(len(self.provider.calls), hub_service.MAX_UNVERIFIED_GENERATED)
        self.assertNotIn("EXPLAIN", [c.get("action") for c in self.provider.calls])
        after = self.snapshot()
        after.pop("generated_tasks"); before.pop("generated_tasks", None)
        self.assertEqual(after, before)  # evidence, answers and exposures untouched
        origins = [e["origin"] for e in self.learning()["unverified_tasks"]]
        self.assertEqual(len(origins), len(set(origins)))  # one marker per task, not per click
        self.assertEqual(tutoring.list_sessions("BIO101", 1, workspace_root=self.root), [])

    def test_a_marker_stops_applying_when_the_cited_source_changes(self):
        task = {"origin": "QUIZ:quiz-1:r1", "task": "t", "source_references": [{"source_id": "s1", "fingerprint": "A"}]}
        changed = {**task, "source_references": [{"source_id": "s1", "fingerprint": "B"}]}
        entries = [{"origin": "QUIZ:quiz-1:r1", "task_text_hash": "x",
                    "fingerprints": [list(f) for f in hub_service._ref_fingerprints(task)]}]
        self.assertTrue(hub_service._is_rejected(entries, task))
        self.assertFalse(hub_service._is_rejected(entries, changed))

    def test_teach_me_still_works_after_a_test_me_session_on_a_rejected_task(self):
        self.set_reference(BAD)
        self.assertEqual(self.create("TEST_ME")["task"]["origin"], "QUIZ:quiz-1:r1")  # TEST_ME is unchanged

    # --- HINT ---------------------------------------------------------------------------
    def question_text(self, text):
        record = json.loads(self.record_path.read_text())
        record["learning"]["quiz_history"]["attempts"][0]["questions"][0]["question"] = text
        self.record_path.write_text(json.dumps(record))

    def test_second_hint_for_an_unverified_reference_is_a_deterministic_source_only_hint(self):
        self.set_reference(BAD)
        self.question_text("What does standard error describe about sample means?")
        session = self.create("TEST_ME")
        self.hint(session, "h1")
        hint = self.hint(session, "h2")
        self.assertEqual((hint["tutor"]["kind"], hint["tutor"]["hint_level"]), ("HINT", 2))
        self.assertIn("'standard'", hint["tutor"]["text"])
        self.assertNotIn("pollster", hint["tutor"]["text"])
        self.assertEqual(self.provider.calls, [])  # no model call, no verifier, reference never sent
        self.never_sent()
        self.assertEqual([e["hint_level"] for e in self.learning()["task_exposures"]], [1, 2])
        self.assertNotIn(BAD, json.dumps(tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)))

    def test_source_only_hint_uses_only_the_question_words_the_cited_page_also_uses(self):
        self.assertIsNone(tp.source_only_hint("Why?", [PAGE1]))
        self.assertIsNone(tp.source_only_hint("What is photosynthesis in plants?", [PAGE1]))
        hint = tp.source_only_hint("What does standard error describe about sample means?", [PAGE1])
        self.assertNotIn("divided", hint)  # nothing from the page beyond the question's own words

    # --- NEXT ---------------------------------------------------------------------------
    def next_from(self, session):
        tutoring.skip_question({}, "BIO101", 1, session["session_id"], client_turn_id="s1",
                               provider=self.provider, workspace_root=self.root)
        try:
            tutoring.next_question({}, "BIO101", 1, session["session_id"], client_turn_id="n1",
                                   provider=self.provider, workspace_root=self.root)
        except Exception:  # noqa: BLE001 - the scripted reply is not a valid question; only the inputs matter
            pass

    def test_next_from_an_unverified_root_keeps_its_reference_out_of_retrieval_and_the_prompt(self):
        self.set_reference(BAD)
        session = self.create("TEST_ME")
        self.queries = []
        self.next_from(session)
        self.assertTrue(self.queries)
        self.assertEqual([q for q in self.queries[-1:] if BAD in q], [])  # generation context: no reference
        asked = [c for c in self.provider.calls if c["action"] == "NEXT_QUESTION"]
        self.assertEqual(len(asked), 1)
        self.assertIsNone(asked[0]["parent_expected_answer_or_rubric"])
        self.never_sent()

    def test_next_from_a_verified_root_still_retrieves_with_its_reference(self):
        self.set_reference(GOOD)
        session = self.create("TEST_ME")
        self.queries = []
        self.next_from(session)
        self.assertIn(GOOD, self.queries[-1])

    def test_a_generated_question_whose_own_reference_is_unsupported_is_rejected(self):
        self.set_reference(GOOD)
        session = self.create("TEST_ME")
        self.provider.override = {"question": "How does a larger sample change the standard error of a mean?",
                                  "expected_answer": "A larger sample makes the standard error smaller.",
                                  "citations": [{"source_id": "s1", "pdf_page": 2}]}  # page 2 is the decoy
        self.next_from(session)
        reloaded = tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual(len(reloaded["questions"]), 1)  # nothing opened


if __name__ == "__main__":
    unittest.main()
