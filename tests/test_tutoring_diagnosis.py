"""Phase 3C slice 1: structured diagnosis, misconception safety, dispute, self-confidence, leak guard.

Synthetic material and a scripted offline provider only. The fixture (record, sources, patched
retrieval) is borrowed from ``test_tutoring`` so both suites exercise the same engine.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import test_tutoring as base  # noqa: E402
from unittest.mock import patch  # noqa: E402

from university_jarvis import hub_service, tutoring  # noqa: E402
from university_jarvis.workspace import effective_outcome  # noqa: E402
from university_jarvis.reasoning import ReasoningError  # noqa: E402
from university_jarvis.state import StateError  # noqa: E402

ANSWER_TEXT = base.ANSWER_TEXT
WRONG = "I believe viruses are the basic unit of life because they replicate"
CITE = [{"source_id": "s1", "pdf_page": 1}]


def mis(**over):
    return {**{"label": "Thinks viruses are the unit of life", "quote": "viruses are the basic unit",
               "confidence": "high", "citations": CITE}, **over}


def reply(diagnosis="partial", message="Feedback text.", misconception="absent", citations=None):
    out = {"message": message, "diagnosis": diagnosis, "citations": citations or CITE}
    if misconception != "absent":
        out["misconception"] = misconception
    return out


class DiagnosisTests(unittest.TestCase):
    setUp = base.TutoringTests.setUp
    _context = base.TutoringTests._context
    create = base.TutoringTests.create
    answer = base.TutoringTests.answer
    hint = base.TutoringTests.hint
    reveal = base.TutoringTests.reveal
    learning = base.TutoringTests.learning
    session_file = base.TutoringTests.session_file

    def ask(self, scripted, text=WRONG, turn="a1", intention="TEST_ME", session=None, confidence=None):
        session = session or self.create(intention)
        self.provider.override = scripted
        result = tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id=turn, text=text,
                                          provider=self.provider, workspace_root=self.root, confidence=confidence)
        return session, result

    def evaluation(self, index=-1):
        return self.learning()["evidence"][index]["evaluation"]

    def dispute(self, session, target, turn="d1"):
        return tutoring.dispute_diagnosis({}, "BIO101", 1, session["session_id"], client_turn_id=turn,
                                          target_turn_id=target, provider=self.provider, workspace_root=self.root)

    # --- the five readings -------------------------------------------------------------
    def test_each_diagnosis_maps_to_a_provisional_outcome(self):
        expected = {"correct": "SUPPORTED", "partial": "PARTLY_SUPPORTED", "off_target": "NOT_SUPPORTED",
                    "unclear": "UNCLEAR", "misconception": "NOT_SUPPORTED"}
        for diagnosis, outcome in expected.items():
            with self.subTest(diagnosis=diagnosis):
                self.setUp()
                scripted = reply(diagnosis, misconception=mis() if diagnosis == "misconception" else None)
                _, result = self.ask(scripted)
                self.assertEqual((result["status"], result["diagnosis"]), ("COMPLETE", diagnosis))
                self.assertEqual(self.evaluation()["outcome"], outcome)
                self.assertEqual(self.evaluation()["basis"], "TUTOR_TURN_MODEL_JUDGEMENT")

    def test_a_valid_misconception_is_stored_as_suspected_with_quote_and_confidence(self):
        session, result = self.ask(reply("misconception", misconception=mis()))
        turn = next(t for t in result["session"]["turns"] if t["turn_id"] == result["turn_id"])
        self.assertEqual(turn["misconception"]["status"], "SUSPECTED")
        self.assertEqual(turn["misconception"]["quote"], "viruses are the basic unit")
        self.assertEqual(turn["misconception"]["confidence"], "high")
        self.assertTrue(turn["can_dispute"])
        self.assertEqual(self.evaluation()["misconception"]["confidence"], "high")
        self.assertEqual(turn["next_action"], "REVIEW_SOURCE")

    def test_legacy_three_key_replies_still_work(self):
        _, result = self.ask(reply("partial"))
        self.assertEqual(result["diagnosis"], "partial")

    # --- unsupported diagnoses fall back safely ------------------------------------------
    def test_unsupported_misconceptions_fall_back_to_unclear_and_the_turn_still_completes(self):
        bad = {
            "no structured misconception": reply("misconception"),
            "null misconception": reply("misconception", misconception=None),
            "quote not said by the student": reply("misconception", misconception=mis(quote="cells are the smallest unit")),
            "low confidence": reply("misconception", misconception=mis(confidence="low")),
            "no citations": reply("misconception", misconception=mis(citations=[])),
            "unsupplied source": reply("misconception", misconception=mis(citations=[{"source_id": "nope", "pdf_page": 1}])),
            "unsupplied page": reply("misconception", misconception=mis(citations=[{"source_id": "s1", "pdf_page": 99}])),
        }
        for name, scripted in bad.items():
            with self.subTest(name):
                self.setUp()
                session, result = self.ask(scripted)
                self.assertEqual((result["status"], result["diagnosis"]), ("COMPLETE", "unclear"))
                evaluation = self.evaluation()
                self.assertEqual(evaluation["outcome"], "UNCLEAR")  # never NOT_SUPPORTED on an unproven accusation
                self.assertEqual(evaluation["model_diagnosis"], "misconception")
                self.assertNotIn("misconception", evaluation)
                turn = next(t for t in result["session"]["turns"] if t["turn_id"] == result["turn_id"])
                self.assertFalse(turn["can_dispute"])
                self.assertEqual(len(self.learning()["evidence"]), 1)

    def test_a_misconception_attached_to_another_diagnosis_is_ignored(self):
        _, result = self.ask(reply("partial", misconception=mis()))
        turn = next(t for t in result["session"]["turns"] if t["turn_id"] == result["turn_id"])
        self.assertNotIn("misconception", turn)
        self.assertEqual(self.evaluation()["outcome"], "PARTLY_SUPPORTED")

    def test_a_misconception_label_that_states_the_answer_is_dropped(self):
        scripted = reply("misconception", misconception=mis(label="Wrong: the answer is " + ANSWER_TEXT))
        _, result = self.ask(scripted)
        self.assertEqual(result["diagnosis"], "unclear")

    # --- hedged / uncertain answers --------------------------------------------------------
    def test_a_pure_dont_know_is_saved_without_a_model_call_or_a_negative_judgement(self):
        session = self.create()
        before = len(self.provider.calls)
        _, result = self.ask(reply("misconception", misconception=mis()), text="idk", session=session)
        self.assertEqual(len(self.provider.calls), before)  # no model call
        self.assertEqual(result["diagnosis"], "unclear")
        self.assertEqual(self.evaluation()["outcome"], "UNCLEAR")
        self.assertEqual(self.evaluation()["basis"], "STUDENT_UNCERTAIN")
        self.assertEqual(self.learning()["evidence"][0]["student_response"], "idk")
        self.assertNotIn("task_exposures", self.learning())  # nothing was taught, so nothing is assisted
        self.assertEqual(result["session"]["model_calls"], 0)
        self.assertEqual(result["tutor"]["next_action"], "OFFER_HINT")
        again = tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a2",
                                         text=WRONG, provider=self.provider, workspace_root=self.root)
        self.assertEqual(again["assistance_status"], "UNAIDED")  # a hedge did not spend the unaided attempt

    def test_a_hedged_real_answer_is_judged_normally(self):
        before = len(self.provider.calls)
        _, result = self.ask(reply("correct"), text="I think cells are the basic unit of life")
        self.assertEqual(len(self.provider.calls), before + 1)
        self.assertEqual(result["diagnosis"], "correct")
        turn = next(t for t in result["session"]["turns"] if t["turn_id"] == result["turn_id"])
        self.assertEqual(turn["next_action"], "CHECK_REASONING")

    # --- dispute ----------------------------------------------------------------------------
    def test_disputing_marks_the_diagnosis_disputed_without_erasing_answer_or_evaluation(self):
        session, result = self.ask(reply("misconception", misconception=mis()))
        stored_before = json.loads(json.dumps(self.learning()["evidence"][0]))
        calls, exposures = len(self.provider.calls), len(self.learning()["task_exposures"])
        out = self.dispute(session, result["turn_id"])
        attempt = self.learning()["evidence"][0]
        self.assertEqual(out["status"], "COMPLETE")
        self.assertEqual(len(self.provider.calls), calls)  # no model call
        self.assertEqual(len(self.learning()["evidence"]), 1)  # no new attempt
        self.assertEqual(len(self.learning()["task_exposures"]), exposures)
        # Everything that was there is still there, unchanged, apart from the added note.
        dispute = attempt["evaluation"].pop("dispute")
        self.assertEqual(attempt, stored_before)
        self.assertEqual(attempt["evaluation"]["outcome"], "NOT_SUPPORTED")  # historical judgement kept
        self.assertEqual(dispute["status"], "DISPUTED_BY_STUDENT")
        self.assertEqual(dispute["disputed_outcome"], "NOT_SUPPORTED")
        self.assertEqual(effective_outcome({**attempt["evaluation"], "dispute": dispute}), "UNCLEAR")
        self.assertEqual(effective_outcome(attempt["evaluation"]), "NOT_SUPPORTED")  # without the note
        turn = next(t for t in out["session"]["turns"] if t["turn_id"] == result["turn_id"])
        self.assertEqual(turn["misconception"]["status"], "DISPUTED")
        self.assertEqual(turn["misconception"]["quote"], "viruses are the basic unit")  # not erased from the transcript
        self.assertEqual(turn["diagnosis"], "misconception")
        self.assertFalse(turn["can_dispute"])
        self.assertEqual(out["session"]["last_diagnosis"], "unclear")

    def test_a_disputed_reading_is_not_acted_on_as_confirmed_by_other_features(self):
        session, result = self.ask(reply("misconception", misconception=mis()))
        record = lambda: json.loads(self.record_path.read_text())  # noqa: E731
        before = hub_service.select_next_study_task(record()["learning"]["evidence"], record()["sources"])
        self.assertIn("not supported", before["reason"])
        self.dispute(session, result["turn_id"])
        after = hub_service.select_next_study_task(record()["learning"]["evidence"], record()["sources"])
        self.assertIn("unclear", after["reason"])
        self.assertEqual(after["capability"], before["capability"])  # still worth another attempt, not "confirmed wrong"

    def test_dispute_is_idempotent_and_cannot_be_repeated_under_a_new_turn_id(self):
        session, result = self.ask(reply("misconception", misconception=mis()))
        first = self.dispute(session, result["turn_id"])
        self.assertEqual(self.dispute(session, result["turn_id"])["turn_id"], first["turn_id"])
        self.assertEqual(len([t for t in tutoring.load_session("BIO101", 1, session["session_id"],
                                                                 workspace_root=self.root)["turns"]
                              if t.get("action") == "DISPUTE"]), 1)
        with self.assertRaisesRegex(StateError, "already disputed"):
            self.dispute(session, result["turn_id"], turn="d2")
        with self.assertRaisesRegex(StateError, "different request"):
            self.dispute(session, "t0099")

    def test_nothing_to_dispute_is_refused(self):
        session, result = self.ask(reply("partial"))
        with self.assertRaisesRegex(StateError, "no suspected misunderstanding"):
            self.dispute(session, result["turn_id"])
        with self.assertRaises(StateError):
            self.dispute(session, "t0042", turn="d9")

    def test_disputing_never_weakens_assistance_records(self):
        session = self.create("TEACH_ME")  # explanation first: the answer is assisted
        _, result = self.ask(reply("misconception", misconception=mis()), session=session)
        self.assertEqual(result["assistance_status"], "PROMPTED")
        self.dispute(session, result["turn_id"])
        self.assertEqual(self.learning()["evidence"][0]["assistance_status"], "PROMPTED")
        nxt = tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a2", text="Cells, I think.",
                                       provider=self.provider, workspace_root=self.root)
        self.assertEqual(nxt["assistance_status"], "PROMPTED")  # the task stays spent after a dispute

    def test_the_view_hides_the_dispute_button_while_a_turn_is_unfinished(self):
        session, result = self.ask(reply("misconception", misconception=mis()))
        view = tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertTrue(next(t for t in view["turns"] if t["turn_id"] == result["turn_id"])["can_dispute"])
        tutoring.end_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        ended = tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertFalse(next(t for t in ended["turns"] if t["turn_id"] == result["turn_id"])["can_dispute"])

    # --- optional self-reported confidence ------------------------------------------------------
    def test_confidence_is_optional_normalised_and_kept_on_the_attempt(self):
        _, none = self.ask(reply("partial"), confidence=None)
        self.assertNotIn("self_reported_confidence", self.learning()["evidence"][0])
        self.setUp()
        for given, kept in (("Sure", "SURE"), ("unsure", "UNSURE"), (" GUESSING ", "GUESSING")):
            with self.subTest(given=given):
                self.setUp()
                self.ask(reply("partial"), confidence=given)
                self.assertEqual(self.learning()["evidence"][0]["self_reported_confidence"], kept)
        self.setUp()
        self.ask(reply("partial"), confidence="")  # a blank form field means "prefer not to say"
        self.assertNotIn("self_reported_confidence", self.learning()["evidence"][0])

    def test_an_invalid_confidence_is_refused_before_anything_is_saved(self):
        session = self.create()
        with self.assertRaisesRegex(StateError, "Sure, Unsure or Guessing"):
            self.ask(reply("partial"), confidence="certain", session=session)
        self.assertEqual(self.learning()["evidence"], [])

    def test_confidence_never_reaches_the_model_or_changes_the_evaluation(self):
        outcomes = []
        for confidence in (None, "SURE", "UNSURE", "GUESSING"):
            self.setUp()
            self.ask(reply("misconception", misconception=mis()), confidence=confidence)
            outcomes.append((self.evaluation()["outcome"], self.evaluation()["reason"]))
            payload = json.dumps(self.provider.calls)
            for word in ("SURE", "GUESSING", "UNSURE", "self_"):
                self.assertNotIn(word, payload)
        self.assertEqual(len(set(outcomes)), 1)

    def test_replaying_a_turn_with_a_different_confidence_is_refused(self):
        session, _ = self.ask(reply("partial"), confidence="SURE")
        with self.assertRaisesRegex(StateError, "different request"):
            self.ask(reply("partial"), confidence="GUESSING", session=session)

    def test_a_lucky_guess_is_not_consolidated(self):
        _, result = self.ask(reply("correct"), text=ANSWER_TEXT, confidence="GUESSING")
        turn = next(t for t in result["session"]["turns"] if t["turn_id"] == result["turn_id"])
        self.assertEqual(self.evaluation()["outcome"], "SUPPORTED")  # confidence did not override the judgement
        self.assertEqual(turn["next_action"], "CHECK_REASONING")

    # --- answer-leak guard -------------------------------------------------------------------
    def test_feedback_that_reveals_the_reference_answer_is_refused_retried_once_and_never_displayed(self):
        for leak in (f"Not quite. The answer is: {ANSWER_TEXT}.",
                     "Close, but note the basic structural and functional unit of all living things is what matters."):
            with self.subTest(leak=leak[:30]):
                self.setUp()
                session = self.create()
                self.provider.override = reply("partial", message=leak)
                done = tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a1", text=WRONG,
                                                provider=self.provider, workspace_root=self.root)
                # Two paid calls (original + one bounded retry), both refused: the student still gets a useful reply.
                self.assertEqual(len(self.provider.calls), 2)
                self.assertEqual(done["session"]["model_calls"], 2)
                self.assertEqual((done["status"], done["diagnosis"]), ("COMPLETE", "unclear"))
                self.assertTrue(done["tutor"]["text"].startswith(tutoring.FALLBACK_FEEDBACK))
                self.assertNotIn(ANSWER_TEXT, json.dumps(done))
                self.assertNotIn("structural and functional unit", json.dumps(done))
                evidence = self.learning()["evidence"]
                self.assertEqual(evidence[0]["student_response"], WRONG)  # answer kept, once
                self.assertEqual(evidence[0]["evaluation"]["basis"], "TUTOR_REPLY_REJECTED")
                self.assertEqual(len(evidence), 1)
                self.assertNotIn("task_exposures", self.learning())  # leaked text was never shown or counted
                self.assertGreater(done["session"]["usage"].get("total_tokens", 1), 0)

    def test_a_leak_followed_by_a_clean_retry_completes_with_the_clean_reply_and_tells_the_model_why(self):
        session = self.create()
        seen = []
        original = self.provider.generate_structured_output

        def script(context, instructions, output_format):
            seen.append(context.get("previous_reply_refused_because"))
            self.provider.override = (reply("partial", message=f"The answer is: {ANSWER_TEXT}.") if len(seen) == 1
                                      else reply("partial", message="You have part of it; re-read page 1 and try again."))
            return original(context, instructions, output_format)
        with patch.object(self.provider, "generate_structured_output", side_effect=script):
            done = tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a1", text=WRONG,
                                            provider=self.provider, workspace_root=self.root)
        self.assertEqual(done["diagnosis"], "partial")
        self.assertEqual(done["tutor"]["text"], "You have part of it; re-read page 1 and try again.")
        self.assertIsNone(seen[0])
        self.assertIn("private reference answer", seen[1])
        self.assertNotIn(ANSWER_TEXT, seen[1])  # the note never repeats the refused reply
        self.assertEqual(done["session"]["model_calls"], 2)
        self.assertEqual(len(self.learning()["evidence"]), 1)

    def submit(self, session, turn="a1", text=WRONG):
        return tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id=turn, text=text,
                                        provider=self.provider, workspace_root=self.root)

    def test_rejected_feedback_ends_in_a_safe_fallback_after_one_retry_and_replays_stably(self):
        session = self.create()
        self.provider.override = reply("partial", message=f"The answer is: {ANSWER_TEXT}.")
        done = self.submit(session)
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual(done["status"], "COMPLETE")
        self.assertEqual(done["diagnosis"], "unclear")
        self.assertTrue(done["tutor"]["text"].startswith(tutoring.FALLBACK_FEEDBACK))
        self.assertEqual(done["tutor"]["citations"], [])
        self.assertNotIn(ANSWER_TEXT, json.dumps(done))
        self.assertIsNone(done["session"]["recovery"])
        self.assertIn("ANSWER", done["session"]["available_actions"])  # the student is free to continue
        evidence = self.learning()["evidence"]
        self.assertEqual(len(evidence), 1)  # still one attempt, answer intact
        self.assertEqual(evidence[0]["student_response"], WRONG)
        self.assertEqual((evidence[0]["evaluation"]["outcome"], evidence[0]["evaluation"]["basis"]),
                         ("UNCLEAR", "TUTOR_REPLY_REJECTED"))
        self.assertEqual(evidence[0]["assistance_status"], "UNAIDED")
        self.assertNotIn("task_exposures", self.learning())  # nothing was shown, so nothing is assisted
        turn = next(t for t in done["session"]["turns"] if t["turn_id"] == done["turn_id"])
        self.assertEqual(turn["next_action"], "OFFER_HINT")  # advice matches the situation
        calls = len(self.provider.calls)
        self.assertEqual(self.submit(session)["turn_id"], done["turn_id"])  # replay is stable and free
        self.assertEqual(len(self.provider.calls), calls)
        self.provider.override = reply("partial")  # a healthy model later: a new answer is judged normally
        later = self.submit(session, turn="a2", text="Another try")
        self.assertEqual((later["assistance_status"], later["diagnosis"]), ("UNAIDED", "partial"))

    def test_transport_failures_do_not_trigger_the_fallback(self):
        session = self.create()
        self.provider.fail_times = tutoring.MAX_REJECTED_REPLIES + 1
        for _ in range(tutoring.MAX_REJECTED_REPLIES + 1):
            with self.assertRaises(ReasoningError):
                self.submit(session)
        done = self.submit(session)  # a real model call finally succeeds
        self.assertEqual(done["tutor"]["text"], "FEEDBACK reply")

    def test_retries_and_rejections_count_against_the_session_call_limit(self):
        session = self.create()
        self.provider.override = reply("partial", message=f"The answer is: {ANSWER_TEXT}.")
        with patch.object(tutoring, "MAX_MODEL_CALLS", 1):
            done = self.submit(session)  # the limit refuses the retry; the student still gets the safe reply
            self.assertEqual(len(self.provider.calls), 1)
            self.assertTrue(done["tutor"]["text"].startswith(tutoring.FALLBACK_FEEDBACK))
            with self.assertRaisesRegex(StateError, "AI-call limit"):
                self.submit(session, turn="a2")
        self.assertEqual(self.learning()["evidence"][0]["student_response"], WRONG)

    def test_each_kind_of_invalid_reply_is_retried_once_then_ends_in_the_fallback(self):
        bad = [reply("partial", message=""), reply("partial", citations=[{"source_id": "nope", "pdf_page": 1}]),
               {"message": "x"}, reply("none")]
        for scripted in bad:
            with self.subTest(scripted=str(scripted)[:40]):
                self.setUp()
                session = self.create()
                self.provider.override = scripted
                done = self.submit(session)
                self.assertEqual(len(self.provider.calls), 2)
                self.assertTrue(done["tutor"]["text"].startswith(tutoring.FALLBACK_FEEDBACK))

    def test_a_hint_that_keeps_leaking_ends_in_a_plain_fallback_with_no_help_recorded(self):
        session = self.create()
        self.hint(session, "h1")
        self.provider.override = reply("none", message=f"It is: {ANSWER_TEXT}")
        done = self.hint(session, "h2")
        self.assertEqual(done["status"], "COMPLETE")
        self.assertNotIn(ANSWER_TEXT, json.dumps(done))
        self.assertEqual(done["session"]["hint_level"], 1)  # no level-2 help was given or counted

    def test_feedback_may_echo_the_students_own_words_but_not_the_answer_they_did_not_give(self):
        _, result = self.ask(reply("partial", message=f'You wrote "{WRONG}". Look again at the source.'))
        self.assertEqual(result["status"], "COMPLETE")

    def test_after_a_reveal_feedback_may_discuss_the_shown_answer(self):
        session = self.create()
        self.reveal(session)
        _, result = self.ask(reply("partial", message=f"The answer shown was: {ANSWER_TEXT}."), session=session)
        self.assertEqual(result["status"], "COMPLETE")

    # --- duplicates, interruption, compatibility ------------------------------------------------
    def test_duplicate_submission_returns_the_stored_result_with_one_call_and_one_attempt(self):
        session, first = self.ask(reply("misconception", misconception=mis()))
        calls = len(self.provider.calls)
        second = tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a1", text=WRONG,
                                          provider=self.provider, workspace_root=self.root)
        self.assertEqual(len(self.provider.calls), calls)
        self.assertEqual(second["diagnosis"], "misconception")
        self.assertEqual(len(self.learning()["evidence"]), 1)

    def test_an_interrupted_call_recovers_with_the_structured_diagnosis_intact(self):
        session = self.create()
        self.provider.fail_times = 1
        self.provider.override = reply("misconception", misconception=mis())
        with self.assertRaises(ReasoningError):
            tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a1", text=WRONG,
                                     provider=self.provider, workspace_root=self.root)
        self.assertIsNone(self.learning()["evidence"][0]["evaluation"])
        done = tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a1", text=WRONG,
                                        provider=self.provider, workspace_root=self.root)
        self.assertEqual(done["diagnosis"], "misconception")
        self.assertEqual(len(self.learning()["evidence"]), 1)
        self.assertEqual(self.learning()["evidence"][0]["evaluation"]["outcome"], "NOT_SUPPORTED")

    def test_an_interrupted_answer_keeps_the_self_reported_confidence(self):
        session = self.create()
        self.provider.fail_times = 1
        with self.assertRaises(ReasoningError):
            tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a1", text=WRONG,
                                     provider=self.provider, workspace_root=self.root, confidence="UNSURE")
        self.assertEqual(self.learning()["evidence"][0]["self_reported_confidence"], "UNSURE")

    def test_a_session_file_from_before_this_slice_still_loads_and_continues(self):
        session = self.create()
        self.ask(reply("partial"), session=session)
        path = self.session_file(session)
        data = json.loads(path.read_text())
        data["prompt_version"] = "tutor-turn-v1"
        for turn in data["turns"]:
            for key in ("self_confidence", "next_action", "misconception", "model_diagnosis", "target_turn_id"):
                turn.pop(key, None)
        path.write_text(json.dumps(data))
        view = tutoring.resume_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertTrue(all(t["can_dispute"] is False for t in view["turns"]))
        self.provider.override = reply("misconception", misconception=mis())
        out = tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id="a2", text=WRONG,
                                       provider=self.provider, workspace_root=self.root)
        self.assertEqual(out["diagnosis"], "misconception")
        self.assertEqual(out["assistance_status"], "PROMPTED")  # earlier feedback still floors the task

    def test_teach_me_and_test_me_share_the_same_diagnosis_path(self):
        for intention, expected in (("TEACH_ME", "PROMPTED"), ("TEST_ME", "UNAIDED")):
            with self.subTest(intention=intention):
                self.setUp()
                _, result = self.ask(reply("misconception", misconception=mis()), intention=intention)
                self.assertEqual((result["diagnosis"], result["assistance_status"]), ("misconception", expected))
                self.assertEqual(self.evaluation()["misconception"]["label"], "Thinks viruses are the unit of life")

    def test_evidence_records_keep_every_pre_existing_field(self):
        self.ask(reply("partial"))
        attempt = self.learning()["evidence"][0]
        for key in ("attempt_id", "attempted_at", "capability", "task", "origin", "student_response",
                    "assistance_status", "prompt_help", "source_references", "expected_answer", "evaluation",
                    "session_id", "turn_id", "hint_level", "task_key"):
            self.assertIn(key, attempt)


if __name__ == "__main__":
    unittest.main()
