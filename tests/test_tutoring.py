from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis import hub_service, tutoring, workspace
from university_jarvis.reasoning import ReasoningError
from university_jarvis.state import StateError
from university_jarvis.workspace import record_learning_attempt, record_task_exposure

FP = {"algorithm": "sha256", "value": "abc"}
ANSWER_TEXT = "Cells are the basic structural and functional unit of all living organisms"


class FakeProvider:
    """Scripted offline provider: records every call, never touches a network."""

    def __init__(self, diagnosis="partial", fail_times=0, delay=0.0):
        self.calls, self.diagnosis, self.fail_times, self.delay = [], diagnosis, fail_times, delay
        self.override = None

    def cache_identity(self):
        return {"provider": "fake", "model": "tutor-test"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls.append(context)
        if self.delay:
            time.sleep(self.delay)
        if self.fail_times:
            self.fail_times -= 1
            raise ReasoningError("OpenAI reasoning request failed before a response was received")
        if self.override is not None:
            return self.override
        action = context["action"]
        return {"message": f"{action} reply", "citations": [{"source_id": "s1", "pdf_page": 1}],
                "diagnosis": self.diagnosis if action == "FEEDBACK" else "none"}


class TutoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.record_path = self.root / "BIO101" / "week-01" / "academic-record.json"
        self.record_path.parent.mkdir(parents=True)
        ref = {"source_id": "s1", "pdf_page": 1, "fingerprint": FP}

        def question(qid, kind):
            return {"question_id": qid, "question_type": kind, "question": f"{kind} task {qid}?", "provenance": [dict(ref)]}

        record = {
            "workspace_schema_version": 4, "module": {"code": "BIO101", "title": "Biology"},
            "week": {"number": 1, "topic": "Cells"},
            "sources": [{"source_id": "s1", "title": "Lecture", "type": "pdf",
                         "extraction": {"character_count": 12, "method": "pdf", "fingerprint": FP}}],
            "workflows": {"prepare_me": {"result": {}}, "teach": {"interactions": []}, "after_lecture": {"captures": []}},
            "learning": {"evidence": [], "quiz_history": {"status": "recorded", "attempts": [{
                "quiz_id": "quiz-1",
                "questions": [question("r1", "recall"), question("r2", "recall"), question("e1", "explanation")],
                "answers": [{"question_id": "r1", "answer": ANSWER_TEXT}, {"question_id": "r2", "answer": "Second"},
                            {"question_id": "e1", "answer": "Explain"}]}]}},
        }
        self.record_path.write_text(json.dumps(record))
        self.fingerprint = FP
        self.matched = True
        patches = [patch("university_jarvis.hub_service.build_week_context", side_effect=self._context),
                   patch("university_jarvis.tutoring.build_week_context", side_effect=self._context)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.provider = FakeProvider()

    def _context(self, _state, module_code, week_number, workflow, **_kw):
        retrieval = {"status": "matched" if self.matched else "no_match"}
        return {"module": {"code": module_code}, "week": {"number": week_number},
                "sources": [{"id": "s1", "extraction": {"fingerprint": self.fingerprint}}],
                "source_contexts": [{"source_id": "s1", "retrieval": retrieval,
                                     "excerpts": [{"pdf_page": 1, "text": "Grounded passage"}]}]}

    # helpers
    def create(self, intention="TEST_ME", request="req-1", provider=None):
        return tutoring.create_session({}, "BIO101", 1, intention=intention, client_request_id=request,
                                       provider=provider or self.provider, workspace_root=self.root)

    def answer(self, session, turn="a1", text="my answer", provider=None):
        return tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id=turn, text=text,
                                        provider=provider or self.provider, workspace_root=self.root)

    def hint(self, session, turn):
        return tutoring.request_hint({}, "BIO101", 1, session["session_id"], client_turn_id=turn,
                                     provider=self.provider, workspace_root=self.root)

    def reveal(self, session, turn="rv"):
        return tutoring.reveal_answer({}, "BIO101", 1, session["session_id"], client_turn_id=turn,
                                      provider=self.provider, workspace_root=self.root)

    def learning(self):
        return json.loads(self.record_path.read_text())["learning"]

    def session_file(self, session):
        return self.record_path.parent / "tutor-sessions" / f"{session['session_id']}.json"

    # --- sessions and intentions -------------------------------------------------
    def test_test_me_asks_without_explaining_and_first_answer_is_unaided(self):
        session = self.create("TEST_ME")
        self.assertEqual([t["kind"] for t in session["turns"]], ["QUESTION"])
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(session["available_actions"], ["ANSWER", "HINT", "REVEAL", "SKIP", "END"])
        result = self.answer(session)
        self.assertEqual(result["assistance_status"], "UNAIDED")
        attempt = self.learning()["evidence"][0]
        self.assertEqual((attempt["session_id"], attempt["hint_level"]), (session["session_id"], 0))
        self.assertEqual(attempt["origin"], "QUIZ:quiz-1:r1")
        self.assertEqual(attempt["evaluation"]["outcome"], "PARTLY_SUPPORTED")
        self.assertEqual(attempt["evaluation"]["basis"], "TUTOR_TURN_MODEL_JUDGEMENT")
        self.assertEqual(result["tutor"]["kind"], "FEEDBACK")

    def test_teach_me_explains_first_so_the_first_answer_is_assisted(self):
        session = self.create("TEACH_ME")
        self.assertEqual([t["kind"] for t in session["turns"]], ["EXPLANATION", "QUESTION"])
        self.assertEqual(self.provider.calls[0]["action"], "EXPLAIN")
        self.assertEqual(self.learning()["task_exposures"][0]["kind"], "EXPLANATION")
        result = self.answer(session)
        self.assertEqual(result["assistance_status"], "PROMPTED")
        self.assertIn("Earlier explanation on this task", self.learning()["evidence"][0]["prompt_help"])

    def test_teach_me_refuses_to_explain_from_unmatched_sources_and_stores_nothing(self):
        self.matched = False
        with self.assertRaises(StateError):
            self.create("TEACH_ME")
        self.assertEqual(self.provider.calls, [])
        self.assertFalse((self.record_path.parent / "tutor-sessions").exists())

    def test_invalid_intention_and_ids(self):
        with self.assertRaises(StateError):
            self.create("CHAT")
        with self.assertRaises(StateError):
            tutoring.load_session("BIO101", 1, "../../etc/passwd", workspace_root=self.root)

    def test_reference_answer_never_appears_in_student_views(self):
        session = self.create()
        result = self.answer(session)
        for view in (session, result["session"], tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)):
            self.assertNotIn(ANSWER_TEXT, json.dumps(view))
            self.assertNotIn("expected_answer", view["task"])
            self.assertTrue(view["task"]["has_reference_answer"])

    # --- idempotency and concurrency --------------------------------------------
    def test_create_is_idempotent_for_the_same_request_id(self):
        first, second = self.create(request="same"), self.create(request="same")
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(len(list((self.record_path.parent / "tutor-sessions").glob("tutor-*.json"))), 1)
        with self.assertRaises(StateError):
            self.create("TEACH_ME", request="same")

    def test_concurrent_creates_with_one_request_id_make_one_session(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.create(request="race"))) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len({r["session_id"] for r in results}), 1)
        self.assertEqual(len(tutoring.list_sessions("BIO101", 1, workspace_root=self.root)), 1)

    def test_resubmitting_a_completed_turn_returns_it_without_a_second_attempt_or_call(self):
        session = self.create()
        first = self.answer(session, "dup")
        calls = len(self.provider.calls)
        second = self.answer(session, "dup")
        self.assertEqual(first["attempt_id"], second["attempt_id"])
        self.assertEqual(len(self.provider.calls), calls)
        self.assertEqual(len(self.learning()["evidence"]), 1)
        with self.assertRaises(StateError):
            self.answer(session, "dup", text="a different answer")

    def test_concurrent_double_submit_records_one_attempt(self):
        session = self.create()
        slow = FakeProvider(delay=0.3)
        outcomes = []

        def submit():
            try:
                outcomes.append(("ok", self.answer(session, "race", provider=slow)))
            except StateError as exc:
                outcomes.append(("busy", str(exc)))

        threads = [threading.Thread(target=submit) for _ in range(3)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(1 for kind, _ in outcomes if kind == "ok"), 1)
        self.assertEqual(len(self.learning()["evidence"]), 1)
        self.assertEqual(len(slow.calls), 1)

    def test_evidence_layer_is_idempotent_and_rejects_conflicting_replays(self):
        kwargs = dict(capability="RECALL", task="t", origin="QUIZ:quiz-1:r1", root=self.root,
                      session_id="tutor-aaaaaaaaaaaa", turn_id="t0002")
        first = record_learning_attempt("BIO101", 1, response="one", **kwargs)
        again = record_learning_attempt("BIO101", 1, response="one", **kwargs)
        self.assertEqual(first["attempt_id"], again["attempt_id"])
        self.assertEqual(len(self.learning()["evidence"]), 1)
        with self.assertRaises(StateError):
            record_learning_attempt("BIO101", 1, response="two", **kwargs)
        with self.assertRaises(StateError):
            record_learning_attempt("BIO101", 1, capability="RECALL", task="t", origin="o", response="x",
                                    root=self.root, session_id="tutor-aaaaaaaaaaaa")

    # --- failure and crash recovery ---------------------------------------------
    def test_failed_ai_call_keeps_the_raw_response_and_recovers_without_duplicates(self):
        session = self.create()
        flaky = FakeProvider(fail_times=1)
        with self.assertRaises(ReasoningError):
            self.answer(session, "retry-me", text="my careful answer", provider=flaky)
        evidence = self.learning()["evidence"]
        self.assertEqual([a["student_response"] for a in evidence], ["my careful answer"])
        self.assertIsNone(evidence[0]["evaluation"])
        self.assertEqual(evidence[0]["assistance_status"], "UNAIDED")
        resumed = tutoring.resume_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual(resumed["recovery"], {"client_turn_id": "retry-me", "action": "ANSWER", "state": "RETRY"})
        self.assertEqual(resumed["available_actions"], ["END"])
        with self.assertRaises(StateError):  # a different turn must not overtake the unfinished one
            self.answer(session, "other", text="something else", provider=flaky)
        result = self.answer(session, "retry-me", text="my careful answer", provider=flaky)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(len(self.learning()["evidence"]), 1)
        self.assertEqual(self.learning()["evidence"][0]["evaluation"]["outcome"], "PARTLY_SUPPORTED")
        self.assertIsNone(tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)["recovery"])

    def test_invalid_model_output_fails_the_turn_without_an_evaluation(self):
        cases = {
            "cites an unknown source": {"message": "m", "diagnosis": "correct", "citations": [{"source_id": "zz", "pdf_page": 1}]},
            "cites an unsupplied page": {"message": "m", "diagnosis": "correct", "citations": [{"source_id": "s1", "pdf_page": 9}]},
            "no citations": {"message": "m", "diagnosis": "correct", "citations": []},
            "bad diagnosis": {"message": "m", "diagnosis": "brilliant", "citations": [{"source_id": "s1", "pdf_page": 1}]},
            "extra field": {"message": "m", "diagnosis": "correct", "citations": [{"source_id": "s1", "pdf_page": 1}], "x": 1},
        }
        for name, bad in cases.items():
            with self.subTest(name):
                self.setUp()
                session = self.create(request=name)
                provider = FakeProvider()
                provider.override = bad
                with self.assertRaises(ReasoningError):
                    self.answer(session, "t", provider=provider)
                attempt = self.learning()["evidence"][0]
                self.assertIsNone(attempt["evaluation"])
                self.assertEqual(attempt["student_response"], "my answer")

    def test_interrupted_pending_turn_is_recoverable_only_after_the_lease_expires(self):
        session = self.create()
        flaky = FakeProvider(fail_times=1)
        with self.assertRaises(ReasoningError):
            self.answer(session, "crash", provider=flaky)
        path = self.session_file(session)
        data = json.loads(path.read_text())
        turn = next(t for t in data["turns"] if t["role"] == "student")
        turn.update(status="PENDING", started_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        path.write_text(json.dumps(data))  # simulate a process that died mid-call
        with self.assertRaisesRegex(StateError, "still being processed"):
            self.answer(session, "crash")
        self.assertEqual(tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)["recovery"]["state"], "IN_PROGRESS")
        turn["started_at"] = (datetime.now(timezone.utc) - timedelta(seconds=tutoring.STALE_PENDING_SECONDS + 5)).isoformat()
        path.write_text(json.dumps(data))
        self.assertEqual(self.answer(session, "crash")["status"], "COMPLETE")
        self.assertEqual(len(self.learning()["evidence"]), 1)

    def test_load_and_resume_never_write(self):
        session = self.create()
        path = self.session_file(session)
        before = path.read_bytes()
        tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        tutoring.resume_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        tutoring.list_sessions("BIO101", 1, workspace_root=self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_corrupt_session_file_is_reported_not_trusted(self):
        session = self.create()
        self.session_file(session).write_text("{not json")
        with self.assertRaises(StateError):
            tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual(tutoring.list_sessions("BIO101", 1, workspace_root=self.root)[0]["status"], "UNREADABLE")

    # --- hints, reveal and unaided protection -----------------------------------
    def test_hint_levels_zero_to_two_and_assisted_classification(self):
        session = self.create()
        first = self.hint(session, "h1")
        self.assertEqual(first["tutor"]["hint_level"], 1)
        self.assertIn("Lecture", first["tutor"]["text"])
        self.assertEqual(self.provider.calls, [])  # level 1 needs no model call
        second = self.hint(session, "h2")
        self.assertEqual(second["tutor"]["kind"], "HINT")
        self.assertEqual(self.provider.calls[0]["action"], "HINT")
        with self.assertRaisesRegex(StateError, "No further hints"):
            self.hint(session, "h3")
        result = self.answer(session)
        self.assertEqual(result["assistance_status"], "PROMPTED")
        self.assertEqual(self.learning()["evidence"][0]["hint_level"], 2)

    def test_one_hint_is_enough_to_stop_the_task_being_unaided(self):
        session = self.create()
        self.hint(session, "h1")
        self.assertNotEqual(self.answer(session)["assistance_status"], "UNAIDED")

    def test_hint_that_leaks_the_reference_answer_is_rejected_and_not_shown(self):
        session = self.create()
        self.hint(session, "h1")
        leaky = FakeProvider()
        leaky.override = {"message": f"Basically: {ANSWER_TEXT}.", "diagnosis": "none",
                          "citations": [{"source_id": "s1", "pdf_page": 1}]}
        with self.assertRaisesRegex(ReasoningError, "reveal the reference answer"):
            tutoring.request_hint({}, "BIO101", 1, session["session_id"], client_turn_id="h2",
                                  provider=leaky, workspace_root=self.root)
        self.assertEqual(len(leaky.calls), 1)
        shown = tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertNotIn("Basically", json.dumps(shown))
        self.assertEqual(shown["hint_level"], 1)
        self.assertEqual(shown["recovery"]["state"], "RETRY")

    def test_revealed_answer_can_never_become_fresh_unaided_evidence(self):
        session = self.create()
        revealed = self.reveal(session)
        self.assertEqual(revealed["tutor"]["text"], ANSWER_TEXT)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.session_available(session), ["ANSWER", "NEXT", "END"])
        result = self.answer(session, "after-reveal", text=ANSWER_TEXT)
        self.assertEqual(result["assistance_status"], "REVEALED")
        # even a caller that claims UNAIDED is floored by the recorded exposure
        forced = record_learning_attempt("BIO101", 1, capability="RECALL", task="recall task r1?", origin="QUIZ:quiz-1:r1",
                                         response="again", assistance_status="UNAIDED", root=self.root,
                                         session_id="tutor-bbbbbbbbbbbb", turn_id="t0002", task_key="QUIZ:quiz-1:r1")
        self.assertEqual(forced["assistance_status"], "REVEALED")

    def session_available(self, session):
        return tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)["available_actions"]

    def test_reveal_protection_holds_across_sessions_and_task_is_not_reoffered(self):
        first = self.create(request="one")
        self.reveal(first)
        tutoring.end_session("BIO101", 1, first["session_id"], workspace_root=self.root)  # revealed, never answered
        second = self.create(request="two")
        self.assertNotEqual(second["task"]["task_key"], first["task"]["task_key"])
        self.assertEqual(self.answer(second)["assistance_status"], "UNAIDED")  # a different, unseen task

    def test_feedback_counts_as_exposure_so_a_second_answer_is_not_unaided(self):
        session = self.create()
        self.assertEqual(self.answer(session, "a1")["assistance_status"], "UNAIDED")
        self.assertEqual(self.answer(session, "a2", text="second try")["assistance_status"], "PROMPTED")
        self.assertEqual([a["assistance_status"] for a in self.learning()["evidence"]], ["UNAIDED", "PROMPTED"])

    def test_assisted_evidence_is_never_summarised_as_demonstrated_unaided(self):
        session = self.create()
        self.hint(session, "h1")
        self.provider.diagnosis = "correct"
        self.answer(session)
        view = hub_service.learning_view("BIO101", 1, workspace_root=self.root)
        self.assertEqual(view["summary"]["RECALL"]["status"], "Demonstrated after help")
        self.assertEqual(view["recommendation"]["mode"], "UNAIDED_RETEST")

    def test_revealed_attempt_is_labelled_and_triggers_an_unaided_retest(self):
        session = self.create()
        self.reveal(session)
        self.provider.diagnosis = "correct"
        self.answer(session)
        view = hub_service.learning_view("BIO101", 1, workspace_root=self.root)
        self.assertEqual(view["summary"]["RECALL"]["status"], "Attempted after the answer was shown")
        self.assertEqual(view["recommendation"]["mode"], "UNAIDED_RETEST")

    def test_exposure_recording_is_idempotent(self):
        kwargs = dict(task_key="QUIZ:quiz-1:r1", kind="HINT", session_id="tutor-aaaaaaaaaaaa", turn_id="t0002", root=self.root)
        record_task_exposure("BIO101", 1, **kwargs)
        record_task_exposure("BIO101", 1, **kwargs)
        self.assertEqual(len(self.learning()["task_exposures"]), 1)
        with self.assertRaises(StateError):
            record_task_exposure("BIO101", 1, **{**kwargs, "kind": "PEEK"})

    # --- sources, grounding and limits ------------------------------------------
    def test_changed_source_blocks_judgement_but_keeps_the_answer(self):
        session = self.create()
        self.fingerprint = {"algorithm": "sha256", "value": "changed"}
        result = self.answer(session, "stale")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.provider.calls, [])
        attempt = self.learning()["evidence"][0]
        self.assertEqual(attempt["student_response"], "my answer")
        self.assertIsNone(attempt["evaluation"])
        with self.assertRaisesRegex(StateError, "sources for this task changed"):
            self.answer(session, "again")

    def test_unmatched_retrieval_gives_unclear_without_calling_the_model(self):
        session = self.create()
        self.matched = False
        result = self.answer(session)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(result["diagnosis"], "unclear")
        self.assertEqual(self.learning()["evidence"][0]["evaluation"]["basis"], "NO_EVIDENCE_RETRIEVED")

    def test_model_context_is_bounded_and_excludes_the_response_from_retrieval(self):
        session = self.create()
        for n in range(4):
            self.answer(session, f"a{n}", text=f"answer {n}")
        last = self.provider.calls[-1]
        self.assertLessEqual(len(last["recent_turns"]), tutoring.RECENT_TURNS)
        self.assertEqual(last["student_response"], "answer 3")
        self.assertNotIn("transcript", last)

    def test_answer_length_and_call_limits(self):
        session = self.create()
        with self.assertRaises(StateError):
            self.answer(session, "big", text="x" * (tutoring.MAX_RESPONSE_CHARS + 1))
        with self.assertRaises(StateError):
            self.answer(session, "blank", text="   ")
        self.assertEqual(self.learning()["evidence"], [])
        with patch.object(tutoring, "MAX_MODEL_CALLS", 1):
            self.answer(session, "one")
            with self.assertRaisesRegex(StateError, "AI-call limit"):
                self.answer(session, "two", text="more")

    def test_usage_is_accumulated_per_session(self):
        class Usage:
            def to_dict(self):
                return {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}

        self.provider.last_usage = Usage()
        session = self.create()
        self.answer(session, "u1")
        self.assertEqual(self.session_data(session)["usage"]["total_tokens"], 5)

    def session_data(self, session):
        return json.loads(self.session_file(session).read_text())

    # --- ending and resuming ----------------------------------------------------
    def test_end_is_idempotent_and_blocks_new_turns_but_replays_finished_ones(self):
        session = self.create()
        done = self.answer(session, "a1")
        ended = tutoring.end_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        again = tutoring.end_session("BIO101", 1, session["session_id"], reason="LATER", workspace_root=self.root)
        self.assertEqual((ended["status"], again["end_reason"]), ("ENDED", "STUDENT_ENDED"))
        self.assertEqual(ended["available_actions"], [])
        with self.assertRaisesRegex(StateError, "has ended"):
            self.answer(session, "new", text="late")
        with self.assertRaisesRegex(StateError, "has ended"):
            tutoring.resume_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual(self.answer(session, "a1")["attempt_id"], done["attempt_id"])

    def test_resume_after_restart_continues_the_same_conversation(self):
        session = self.create("TEACH_ME")
        self.hint(session, "h1")
        resumed = tutoring.resume_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual(resumed["hint_level"], 1)
        self.assertEqual([t["kind"] for t in resumed["turns"] if t["role"] == "tutor"], ["EXPLANATION", "QUESTION", "HINT"])
        self.assertIn(resumed["session_id"], [s["session_id"] for s in tutoring.list_sessions("BIO101", 1, workspace_root=self.root)])
        self.assertEqual(self.answer(resumed, "after")["status"], "COMPLETE")

    # --- review round: what counts as "the same task" ----------------------------
    def _second_quiz_repeating_r1(self):
        record = json.loads(self.record_path.read_text())
        first = record["learning"]["quiz_history"]["attempts"][0]
        repeat = json.loads(json.dumps(first["questions"][0]))
        repeat["question"] = "RECALL task r1 ?!"  # same wording once case and punctuation are ignored
        record["learning"]["quiz_history"]["attempts"].append(
            {"quiz_id": "quiz-2", "questions": [repeat], "answers": [{"question_id": "r1", "answer": "Again"}]})
        self.record_path.write_text(json.dumps(record))

    def test_identical_wording_under_a_new_id_is_still_the_revealed_task(self):
        self._second_quiz_repeating_r1()
        first = self.create(request="one")
        self.assertEqual(first["task"]["task_key"], "QUIZ:quiz-1:r1")
        self.reveal(first)
        tutoring.end_session("BIO101", 1, first["session_id"], workspace_root=self.root)
        later = self.create(request="two")
        self.assertEqual(later["task"]["task_key"], "QUIZ:quiz-1:r2")  # quiz-2:r1 is spent, r2 is genuinely new
        forced = record_learning_attempt("BIO101", 1, capability="RECALL", task="recall TASK r1", origin="QUIZ:quiz-2:r1",
                                         response="x", assistance_status="UNAIDED", root=self.root)
        self.assertEqual(forced["assistance_status"], "REVEALED")

    def test_a_different_task_on_the_same_concept_can_still_be_unaided_after_help(self):
        taught = self.create("TEACH_ME", request="teach")
        self.hint(taught, "h1")
        self.reveal(taught)
        self.assertEqual(self.answer(taught, "a1", text=ANSWER_TEXT)["assistance_status"], "REVEALED")
        tutoring.end_session("BIO101", 1, taught["session_id"], workspace_root=self.root)
        fresh = self.create("TEST_ME", request="test")
        self.assertEqual(fresh["task"]["task_key"], "QUIZ:quiz-1:r2")
        self.assertEqual([t["kind"] for t in fresh["turns"]], ["QUESTION"])
        self.provider.diagnosis = "correct"
        result = self.answer(fresh, "b1", text="in my own words")
        self.assertEqual(result["assistance_status"], "UNAIDED")
        self.assertEqual(self.learning()["evidence"][-1]["prompt_help"], [])
        # the earlier revealed attempt is unchanged and the new one is independent evidence
        self.assertEqual([a["assistance_status"] for a in self.learning()["evidence"]], ["REVEALED", "UNAIDED"])
        self.assertEqual(hub_service.learning_view("BIO101", 1, workspace_root=self.root)["summary"]["RECALL"]["status"],
                         "Demonstrated unaided")

    def test_returning_to_an_answered_task_in_a_later_session_is_never_unaided(self):
        first = self.create(request="one")
        self.assertEqual(self.answer(first, "a1")["assistance_status"], "UNAIDED")
        tutoring.end_session("BIO101", 1, first["session_id"], workspace_root=self.root)
        self.assertNotEqual(self.create(request="two")["task"]["task_key"], first["task"]["task_key"])
        again = record_learning_attempt("BIO101", 1, capability="RECALL", task=first["task"]["task"], origin=first["task"]["task_key"],
                                        response="again", assistance_status="UNAIDED", root=self.root)
        self.assertEqual(again["assistance_status"], "PROMPTED")  # feedback was shown after the first answer
        self.assertIn("Earlier feedback on this task", again["prompt_help"])

    def test_the_floor_protects_non_tutor_callers_too(self):
        session = self.create()
        self.reveal(session)
        row = record_learning_attempt("BIO101", 1, capability="RECALL", task="anything", origin=session["task"]["task_key"],
                                      response="x", root=self.root)  # no task_key, no session: a legacy-style call
        self.assertEqual(row["assistance_status"], "REVEALED")

    # --- review round: exposure only for help that was actually produced ----------
    def test_failed_or_rejected_hint_records_no_exposure(self):
        session = self.create()
        self.hint(session, "h1")
        for bad in (FakeProvider(fail_times=1), self._leaky()):
            with self.assertRaises(ReasoningError):
                tutoring.request_hint({}, "BIO101", 1, session["session_id"], client_turn_id="h2",
                                      provider=bad, workspace_root=self.root)
            self.assertEqual([e["hint_level"] for e in self.learning()["task_exposures"]], [1])
            self.assertEqual(tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)["hint_level"], 1)
        self.assertEqual(self.hint(session, "h2")["tutor"]["hint_level"], 2)
        self.assertEqual([e["hint_level"] for e in self.learning()["task_exposures"]], [1, 2])

    def _leaky(self):
        provider = FakeProvider()
        provider.override = {"message": ANSWER_TEXT, "diagnosis": "none", "citations": [{"source_id": "s1", "pdf_page": 1}]}
        return provider

    def test_unavailable_hint_is_neither_shown_nor_counted(self):
        session = self.create()
        self.hint(session, "h1")
        self.matched = False
        result = self.hint(session, "h2")
        self.assertEqual(result["tutor"]["citations"], [])
        self.assertEqual([e["hint_level"] for e in self.learning()["task_exposures"]], [1])
        self.assertEqual(result["session"]["hint_level"], 1)

    def test_failed_explanation_leaves_the_task_unaided_and_stores_nothing(self):
        with self.assertRaises(ReasoningError):
            self.create("TEACH_ME", provider=FakeProvider(fail_times=1))
        self.assertNotIn("task_exposures", self.learning())
        self.assertFalse((self.record_path.parent / "tutor-sessions").exists())
        session = self.create("TEST_ME", request="after")
        self.assertEqual(session["task"]["task_key"], "QUIZ:quiz-1:r1")
        self.assertEqual(self.answer(session)["assistance_status"], "UNAIDED")

    def test_crash_between_exposure_and_display_is_conservative_and_documented(self):
        real_write = tutoring._write
        with patch.object(tutoring, "_write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.create("TEACH_ME", request="crash")
        self.assertEqual(self.learning()["task_exposures"][0]["kind"], "EXPLANATION")  # over-counted, never under-counted
        self.assertEqual(tutoring.list_sessions("BIO101", 1, workspace_root=self.root), [])
        self.assertIn("never over-credited", tutoring.__doc__)
        tutoring._write = real_write
        retry = self.create("TEACH_ME", request="crash")  # the spent task is skipped; the student loses nothing
        self.assertEqual(retry["task"]["task_key"], "QUIZ:quiz-1:r2")

    def test_failure_after_hint_exposure_is_retried_to_one_exposure(self):
        session = self.create()
        with patch.object(tutoring, "_finish", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.hint(session, "h1")
        shown = tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual((shown["hint_level"], shown["recovery"]["state"]), (0, "RETRY"))
        self.assertEqual(len(self.learning()["task_exposures"]), 1)  # conservative: counted though not yet shown
        self.assertEqual(self.hint(session, "h1")["tutor"]["hint_level"], 1)
        self.assertEqual(len(self.learning()["task_exposures"]), 1)

    def test_concurrent_duplicate_hint_requests_produce_one_hint(self):
        session = self.create()
        outcomes = []

        def go():
            try:
                outcomes.append(self.hint(session, "same")["tutor"]["hint_level"])
            except StateError:
                outcomes.append("busy")

        threads = [threading.Thread(target=go) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertIn(1, outcomes)
        data = tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual(sum(1 for t in data["turns"] if t.get("kind") == "HINT"), 1)
        self.assertEqual(len(self.learning()["task_exposures"]), 1)

    # --- review round: ending a session never loses a raw answer -----------------
    def test_ending_after_a_crash_before_the_evidence_write_still_saves_the_answer(self):
        session = self.create()
        with patch.object(tutoring, "record_learning_attempt", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.answer(session, "lost?", text="my only copy")
        self.assertEqual(self.learning()["evidence"], [])
        ended = tutoring.end_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        saved = self.learning()["evidence"]
        self.assertEqual([a["student_response"] for a in saved], ["my only copy"])
        self.assertIsNone(saved[0]["evaluation"])
        self.assertEqual(saved[0]["assistance_status"], "UNAIDED")
        self.assertEqual([t["status"] for t in ended["turns"] if t["role"] == "student"], ["ABANDONED"])
        self.assertEqual(self.answer(session, "lost?", text="my only copy")["status"], "ABANDONED")
        self.assertEqual(len(self.learning()["evidence"]), 1)

    def test_ending_leaves_a_live_in_flight_turn_alone(self):
        session = self.create()
        with self.assertRaises(ReasoningError):
            self.answer(session, "live", provider=FakeProvider(fail_times=1))
        path = self.session_file(session)
        data = json.loads(path.read_text())
        turn = next(t for t in data["turns"] if t["role"] == "student")
        turn.update(status="PENDING", started_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        data["status"] = "ACTIVE"
        path.write_text(json.dumps(data))
        before = len(self.learning()["evidence"])
        ended = tutoring.end_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertEqual([t["status"] for t in ended["turns"] if t["role"] == "student"], ["PENDING"])
        self.assertEqual(len(self.learning()["evidence"]), before)

    def test_delete_removes_only_the_transcript(self):
        session = self.create()
        self.reveal(session)
        before = self.learning()
        tutoring.delete_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertFalse(self.session_file(session).exists())
        self.assertEqual(self.learning(), before)
        with self.assertRaises(StateError):
            tutoring.load_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        with self.assertRaises(StateError):
            tutoring.delete_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        follow_up = self.create(request="after")
        self.assertNotEqual(follow_up["task"]["task_key"], session["task"]["task_key"])

    def test_delete_refuses_while_a_request_is_in_flight(self):
        session = self.create()
        with self.assertRaises(ReasoningError):
            self.answer(session, "live", provider=FakeProvider(fail_times=1))
        path = self.session_file(session)
        data = json.loads(path.read_text())
        turn = next(t for t in data["turns"] if t["role"] == "student")
        turn.update(status="PENDING", started_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(StateError, "still being processed"):
            tutoring.delete_session("BIO101", 1, session["session_id"], workspace_root=self.root)
        self.assertTrue(path.exists())


class TutoringStorageTests(unittest.TestCase):
    """Where sessions live, and that Git never sees them. Synthetic paths only."""

    REPO = Path(__file__).resolve().parents[1]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)

    @staticmethod
    def _git(cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)

    def _require_git(self):
        if shutil.which("git") is None:
            self.skipTest("git not available")

    def test_default_and_configured_workspace_roots(self):
        home, repo = self.tmp / "home", self.tmp / "repo"
        repo.mkdir()
        with patch.object(workspace, "PROJECT_ROOT", repo), patch.dict(os.environ, {"SERAPIS_HOME": str(home)}):
            os.environ.pop("JARVIS_WORKSPACE_DIR", None)
            self.assertEqual(workspace.default_workspace_root(), home / "workspace")  # outside any checkout
            (repo / "workspace").mkdir()
            self.assertEqual(workspace.default_workspace_root(), repo / "workspace")  # legacy, ignored by .gitignore
            os.environ["JARVIS_WORKSPACE_DIR"] = str(self.tmp / "custom")
            self.assertEqual(workspace.default_workspace_root(), self.tmp / "custom")
            self.assertEqual(tutoring._sessions_dir("bio101", 1, None), self.tmp / "custom" / "BIO101" / "week-01" / "tutor-sessions")
        self.assertEqual(tutoring._session_path("BIO101", 2, "tutor-0123456789ab", self.tmp),
                         self.tmp / "BIO101" / "week-02" / "tutor-sessions" / "tutor-0123456789ab.json")

    def test_repository_gitignore_covers_every_workspace_location(self):
        self._require_git()
        for path in (
            "workspace/BIO101/week-01/tutor-sessions/tutor-0123456789ab.json",
            "anywhere/custom/BIO101/week-01/tutor-sessions/tutor-0123456789ab.json",
            "anywhere/custom/BIO101/week-01/tutor-sessions/index.lock",
            "anywhere/custom/BIO101/week-01/academic-record.json",
            "anywhere/custom/BIO101/week-01/academic-record.json.lock",
        ):
            with self.subTest(path=path):
                self.assertEqual(self._git(self.REPO, "check-ignore", "-q", path).returncode, 0, path)
        tracked = self._git(self.REPO, "ls-files").stdout.splitlines()
        self.assertFalse([f for f in tracked if "tutor-sessions" in f or f.endswith("academic-record.json")])

    def test_sessions_stay_out_of_a_repository_even_without_any_gitignore_rule(self):
        self._require_git()
        repo = self.tmp / "checkout"
        repo.mkdir()
        self.assertEqual(self._git(repo, "init", "-q").returncode, 0)
        root = repo / "study"  # a configured workspace inside a checkout that has no .gitignore at all
        record = root / "BIO101" / "week-01" / "academic-record.json"
        record.parent.mkdir(parents=True)
        ref = {"source_id": "s1", "pdf_page": 1, "fingerprint": FP}
        record.write_text(json.dumps({
            "sources": [{"source_id": "s1", "title": "L", "extraction": {"character_count": 12, "fingerprint": FP}}],
            "learning": {"evidence": [], "quiz_history": {"attempts": [{"quiz_id": "q", "questions": [
                {"question_id": "r1", "question_type": "recall", "question": "Q?", "provenance": [ref]}],
                "answers": [{"question_id": "r1", "answer": "REFERENCE ANSWER TEXT"}]}]}}}))

        def context(*_a, **_k):
            return {"sources": [{"id": "s1", "extraction": {"fingerprint": FP}}], "source_contexts": [
                {"source_id": "s1", "retrieval": {"status": "matched"}, "excerpts": [{"pdf_page": 1, "text": "x"}]}]}

        with patch("university_jarvis.hub_service.build_week_context", side_effect=context):
            session = tutoring.create_session({}, "BIO101", 1, intention="TEST_ME", client_request_id="r",
                                              provider=FakeProvider(), workspace_root=root)
        directory = root / "BIO101" / "week-01" / "tutor-sessions"
        self.assertTrue((directory / f"{session['session_id']}.json").is_file())
        self.assertIn("REFERENCE ANSWER TEXT", (directory / f"{session['session_id']}.json").read_text())
        self.assertEqual((directory / ".gitignore").read_text(), "*\n")
        status = self._git(repo, "status", "--porcelain", "--untracked-files=all").stdout
        self.assertNotIn("tutor-sessions", status)
        self._git(repo, "add", "-A")
        self.assertNotIn("tutor-sessions", self._git(repo, "ls-files").stdout)
        if os.name == "posix":
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual((directory / f"{session['session_id']}.json").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
