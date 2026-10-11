"""Hub Phase 3B: the Tutor panel and session pages over ``tutoring``.

Synthetic data, fake providers, in-process TestClient only (no browser, no network:
``tests/conftest.py`` fails any real socket). GET pages are proven read-only by
comparing every file in the workspace before and after.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from university_jarvis import tutoring
from university_jarvis.hub_web import create_app
from university_jarvis.intake_ledger import new_ledger
from university_jarvis.reasoning import ReasoningError
from university_jarvis.workspace import record_learning_attempt

FP = {"algorithm": "sha256", "value": "abc"}
SECRET = "RUBRIC-SECRET: cells are the basic unit of living organisms"
WEEK = "/modules/SYN101/weeks/1"


def _state() -> dict:
    return {
        "schema_version": 1,
        "mission": {"statement": "Learn.", "primary_objective": {"statement": "Learn."},
                    "stretch_objective": {"statement": "More."},
                    "operating_principles": [{"id": "p1", "statement": "Learn genuinely."}],
                    "constraints": [{"id": "c1", "statement": "No misconduct."}]},
        "student": {"university": "Test University", "programme": "BA Testing", "year_of_study": 2,
                    "level": 5, "academic_year": "2025/26"},
        "modules": [{"code": "SYN101", "title": "Example Studies", "semester": 1, "academic_year": "2025/26",
                     "weeks": [{"week": 1, "date": None, "topic": None, "progress": "unknown", "source_ids": []}],
                     "assessments": []}],
        "sources": [],
    }


class FakeProvider:
    def __init__(self, diagnosis="partial"):
        self.calls, self.diagnosis, self.fail_next = [], diagnosis, 0

    def cache_identity(self):
        return {"provider": "fake", "model": "m"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls.append(context)
        if self.fail_next:
            self.fail_next -= 1
            raise ReasoningError("OpenAI reasoning request failed before a response was received")
        action = context["action"]
        return {"message": f"{action} reply", "citations": [{"source_id": "s1", "pdf_page": 1}],
                "diagnosis": self.diagnosis if action == "FEEDBACK" else "none"}


class HubTutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.record_path = self.root / "SYN101" / "week-01" / "academic-record.json"
        self.record_path.parent.mkdir(parents=True)
        ref = {"source_id": "s1", "pdf_page": 1, "fingerprint": FP}

        def question(qid, text):
            return {"question_id": qid, "question_type": "recall", "question": text, "provenance": [dict(ref)]}

        self.record_path.write_text(json.dumps({
            "workspace_schema_version": 4, "module": {"code": "SYN101", "title": "Example Studies"},
            "week": {"number": 1, "topic": "Cells"},
            "sources": [{"source_id": "s1", "title": "Lecture 1", "type": "pdf",
                         "extraction": {"character_count": 12, "method": "pdf", "fingerprint": FP}}],
            "workflows": {"prepare_me": {"result": {}, "status": "recorded"}, "teach": {"interactions": []},
                          "after_lecture": {"captures": []}},
            "learning": {"evidence": [], "quiz_history": {"status": "recorded", "attempts": [{
                "quiz_id": "quiz-1",
                "questions": [question("r1", "What is the basic unit of life?"),
                              question("r2", "Name one organelle and its job.")],
                "answers": [{"question_id": "r1", "answer": SECRET}, {"question_id": "r2", "answer": "Nucleus stores DNA"}]}]}}}))
        self.matched = True
        for target in ("university_jarvis.hub_service.build_week_context", "university_jarvis.tutoring.build_week_context"):
            patcher = patch(target, side_effect=self._context)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.provider = FakeProvider()
        self.client = self.make_client(self.provider)

    def make_client(self, provider):
        app = create_app(state=_state(), ledger=new_ledger(), workspace_root=self.root, reasoning_provider=provider)
        return TestClient(app)

    def _context(self, _state, module_code, week_number, workflow, **_kw):
        return {"module": {"code": module_code}, "week": {"number": week_number},
                "sources": [{"id": "s1", "extraction": {"fingerprint": FP}}],
                "source_contexts": [{"source_id": "s1", "retrieval": {"status": "matched" if self.matched else "no_match"},
                                     "excerpts": [{"pdf_page": 1, "text": SECRET + ". Nucleus stores DNA. Grounded passage."}]}]}

    # helpers
    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file()}

    def learning(self):
        return json.loads(self.record_path.read_text())["learning"]

    def start(self, intention="TEST_ME", request_id="req-1", client=None):
        response = (client or self.client).post(f"{WEEK}/tutor/start", data={"intention": intention, "client_request_id": request_id},
                                                follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text[:300])
        return response.headers["location"]

    def post(self, url, action, **data):
        return self.client.post(f"{url}/{action}", data=data, follow_redirects=False)

    def turn_id(self, page_html):
        return re.search(r'name="client_turn_id" value="([0-9a-f]+)"', page_html).group(1)

    def page(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.text

    # --- panel, start and read-only pages ------------------------------------------
    def test_week_page_shows_panel_with_honest_notices_and_is_read_only(self):
        before = self.snapshot()
        html = self.client.get(WEEK).text
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.provider.calls, [])
        for text in ("Start a session", "Teach me", "Test me", "provisional", "recorded as assisted",
                     "sends the relevant excerpts"):
            self.assertIn(text.lower(), html.lower())
        self.assertNotIn(SECRET, html)

    def test_start_test_me_redirects_to_a_read_only_session_page_without_the_reference_answer(self):
        url = self.start("TEST_ME")
        self.assertRegex(url, rf"^{WEEK}/tutor/tutor-[0-9a-f]{{12}}$")
        before = self.snapshot()
        html = self.page(url)
        self.page(url)
        self.assertEqual(self.snapshot(), before)  # GET never writes
        self.assertEqual(self.provider.calls, [])  # nor calls the provider
        self.assertIn("What is the basic unit of life?", html)
        self.assertNotIn(SECRET, html)
        self.assertNotIn("RUBRIC", html)
        self.assertIn("Hints used: 0 of 2", html)

    def test_start_teach_me_shows_the_explanation_first(self):
        html = self.page(self.start("TEACH_ME"))
        self.assertLess(html.index("Tutor &mdash; explanation"), html.index("EXPLAIN reply"))
        self.assertLess(html.index("EXPLAIN reply"), html.index("Tutor &mdash; question"))
        self.assertEqual(self.provider.calls[0]["action"], "EXPLAIN")

    def test_start_is_idempotent_for_a_resubmitted_form(self):
        first, second = self.start(request_id="same"), self.start(request_id="same")
        self.assertEqual(first, second)
        self.assertEqual(len(list((self.record_path.parent / "tutor-sessions").glob("tutor-*.json"))), 1)

    # --- answer, duplicate submission, retry ----------------------------------------
    def test_answer_is_recorded_unaided_with_provisional_feedback(self):
        url = self.start()
        turn = self.turn_id(self.page(url))
        response = self.post(url, "answer", client_turn_id=turn, response="Cells <b>I think</b>")
        self.assertEqual((response.status_code, response.headers["location"]), (303, url))
        html = self.page(url)
        self.assertIn("Recorded as unaided", html)
        self.assertIn("FEEDBACK reply", html)
        self.assertIn("provisional", html.lower())
        self.assertIn("Cells &lt;b&gt;I think&lt;/b&gt;", html)  # student text is escaped
        self.assertEqual([a["assistance_status"] for a in self.learning()["evidence"]], ["UNAIDED"])

    def test_double_post_of_the_same_turn_makes_one_attempt_and_one_model_call(self):
        url = self.start()
        turn = self.turn_id(self.page(url))
        for _ in range(3):
            self.assertEqual(self.post(url, "answer", client_turn_id=turn, response="mine").status_code, 303)
        self.assertEqual(len(self.learning()["evidence"]), 1)
        self.assertEqual(len(self.provider.calls), 1)
        stale_tab = self.post(url, "answer", client_turn_id=turn, response="different text")
        self.assertEqual(stale_tab.status_code, 200)
        self.assertIn("already used for a different request", stale_tab.text)
        self.assertEqual(len(self.learning()["evidence"]), 1)

    def test_new_actions_get_new_turn_ids(self):
        url = self.start()
        first = self.turn_id(self.page(url))
        self.post(url, "answer", client_turn_id=first, response="one")
        second = self.turn_id(self.page(url))
        self.assertNotEqual(first, second)

    def test_failed_ai_call_shows_retry_that_reuses_the_same_turn_id(self):
        url = self.start()
        turn = self.turn_id(self.page(url))
        self.provider.fail_next = 1
        failed = self.post(url, "answer", client_turn_id=turn, response="my saved answer")
        self.assertEqual(failed.status_code, 200)
        self.assertIn("did not finish", failed.text)
        self.assertEqual([a["student_response"] for a in self.learning()["evidence"]], ["my saved answer"])
        html = self.page(url)  # a reload (or a new visit) still offers the retry
        self.assertIn("Retry", html)
        self.assertIn(f'name="client_turn_id" value="{turn}"', html)
        self.assertIn('name="response" value="my saved answer"', html)
        self.assertNotIn('<textarea name="response"', html)  # no new answer until the old one is resolved
        retried = self.post(url, "answer", client_turn_id=turn, response="my saved answer")
        self.assertEqual(retried.status_code, 303)
        self.assertEqual(len(self.learning()["evidence"]), 1)
        self.assertIn("FEEDBACK reply", self.page(url))
        self.assertNotIn("Retry", self.page(url))

    def test_interrupted_session_can_be_resumed_by_a_fresh_server(self):
        url = self.start()
        turn = self.turn_id(self.page(url))
        self.provider.fail_next = 1
        self.post(url, "answer", client_turn_id=turn, response="half done")
        restarted = self.make_client(FakeProvider())
        html = restarted.get(url).text
        self.assertIn("Retry", html)
        self.assertEqual(restarted.post(f"{url}/answer", data={"client_turn_id": turn, "response": "half done"},
                                        follow_redirects=False).status_code, 303)
        self.assertEqual(len(self.learning()["evidence"]), 1)
        self.assertIn(f"{WEEK}/tutor/", self.client.get(WEEK).text)  # listed for resuming

    # --- hints, "I don't know", reveal ----------------------------------------------
    def test_hints_dont_know_and_assisted_recording(self):
        url = self.start()
        self.assertEqual(self.post(url, "hint", client_turn_id=self.turn_id(self.page(url))).status_code, 303)
        self.assertEqual(self.post(url, "dont-know", client_turn_id=self.turn_id(self.page(url))).status_code, 303)
        html = self.page(url)
        self.assertIn("Hints used: 2 of 2", html)
        self.assertNotIn("Give me a hint", html)
        out = self.post(url, "dont-know", client_turn_id=self.turn_id(html))
        self.assertEqual(out.status_code, 200)
        self.assertIn("No further hints", out.text)
        self.assertIn("Show the answer", out.text)
        self.assertNotIn(SECRET, out.text)  # I don't know never reveals
        self.post(url, "answer", client_turn_id=self.turn_id(self.page(url)), response="after hints")
        self.assertIn("Recorded as assisted", self.page(url))
        self.assertEqual(self.learning()["evidence"][0]["assistance_status"], "PROMPTED")
        self.assertEqual(self.learning()["evidence"][0]["hint_level"], 2)

    def test_reveal_needs_explicit_confirmation_and_is_the_only_way_to_see_the_answer(self):
        url = self.start()
        pages = [self.page(url)]
        self.post(url, "hint", client_turn_id=self.turn_id(pages[-1]))
        pages.append(self.page(url))
        refused = self.post(url, "reveal", client_turn_id=self.turn_id(pages[-1]))
        self.assertIn("Tick the box", refused.text)
        self.assertNotIn(SECRET, refused.text)
        self.assertFalse([e for e in self.learning().get("task_exposures", []) if e["kind"] == "REVEAL"])
        self.assertTrue(all(SECRET not in p for p in pages))
        shown = self.post(url, "reveal", client_turn_id=self.turn_id(pages[-1]), confirm="yes")
        self.assertEqual(shown.status_code, 303)
        html = self.page(url)
        self.assertIn(SECRET, html)
        self.assertIn("you asked to see it", html)
        self.assertNotIn("Show the answer</button>", html)
        self.post(url, "answer", client_turn_id=self.turn_id(html), response="copying it")
        self.assertIn("Recorded after the answer was shown", self.page(url))
        self.assertEqual(self.learning()["evidence"][0]["assistance_status"], "REVEALED")

    def test_assistance_labels_say_why_and_the_help_note_matches_the_session(self):
        # TEST_ME: the first answer is unaided and carries no reason; the help note is the plain warning
        url = self.start("TEST_ME")
        html = self.page(url)
        self.assertIn("A hint means your next answer is recorded as assisted.", html)
        self.post(url, "answer", client_turn_id=self.turn_id(html), response="first")
        html = self.page(url)
        self.assertIn("Recorded as unaided</strong>.", html)  # no reason clause when unaided
        # after feedback the next answer is assisted, and the page says so instead of warning about hints
        self.assertIn("already recorded as assisted", html)
        self.post(url, "answer", client_turn_id=self.turn_id(html), response="second")
        self.assertIn("help or feedback was already shown for this question", self.page(url))
        # a hint is named as the reason
        self.post(url, "hint", client_turn_id=self.turn_id(self.page(url)))
        self.post(url, "answer", client_turn_id=self.turn_id(self.page(url)), response="third")
        self.assertIn("hint 1 used", self.page(url))
        # TEACH_ME names the explanation; a revealed answer is labelled as such
        teach = self.start("TEACH_ME", request_id="teach")
        self.post(teach, "answer", client_turn_id=self.turn_id(self.page(teach)), response="mine")
        self.assertIn("Recorded as assisted</strong> (the tutor explained first)", self.page(teach))
        self.post(teach, "reveal", client_turn_id=self.turn_id(self.page(teach)), confirm="yes")
        self.post(teach, "answer", client_turn_id=self.turn_id(self.page(teach)), response="copy")
        self.assertIn("Recorded after the answer was shown</strong> (the answer had been shown)", self.page(teach))

    def test_provider_context_is_not_a_page_leak(self):
        url = self.start()
        self.post(url, "hint", client_turn_id=self.turn_id(self.page(url)))
        self.post(url, "hint", client_turn_id=self.turn_id(self.page(url)))
        self.post(url, "answer", client_turn_id=self.turn_id(self.page(url)), response="x")
        self.assertTrue(self.provider.calls)  # the model saw the rubric (needed to judge) ...
        self.assertNotIn(SECRET, self.page(url))  # ... the student never does before a reveal
        self.assertNotIn(SECRET, self.client.get(WEEK).text)

    # --- end, resume, delete --------------------------------------------------------
    def test_end_session_then_actions_are_refused_and_page_is_a_read_only_summary(self):
        url = self.start()
        self.assertEqual(self.post(url, "end").status_code, 303)
        html = self.page(url)
        self.assertIn("This session has ended", html)
        self.assertNotIn("Send answer", html)
        late = self.post(url, "answer", client_turn_id="late-1", response="too late")
        self.assertIn("has ended", late.text)
        self.assertEqual(self.learning()["evidence"], [])
        self.assertIn("ended", self.client.get(WEEK).text)

    def test_delete_requires_confirmation_and_keeps_evidence_and_exposures(self):
        url = self.start()
        self.post(url, "hint", client_turn_id=self.turn_id(self.page(url)))
        self.post(url, "reveal", client_turn_id=self.turn_id(self.page(url)), confirm="yes")
        self.post(url, "answer", client_turn_id=self.turn_id(self.page(url)), response="my answer")
        evidence_before = self.learning()["evidence"]
        exposures_before = self.learning()["task_exposures"]
        refused = self.post(url, "delete")
        self.assertEqual(refused.status_code, 200)
        self.assertIn("Tick the box", refused.text)
        self.assertEqual(self.client.get(url).status_code, 200)
        done = self.post(url, "delete", confirm="yes")
        self.assertEqual((done.status_code, done.headers["location"]), (303, WEEK))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(list((self.record_path.parent / "tutor-sessions").glob("tutor-*.json")), [])
        self.assertEqual(self.learning()["evidence"], evidence_before)
        self.assertEqual(self.learning()["task_exposures"], exposures_before)
        # the revealed question is not offered again as fresh, and cannot yield unaided evidence
        new_url = self.start("TEST_ME", request_id="after-delete")
        self.assertIn("Name one organelle", self.page(new_url))
        self.assertNotIn("What is the basic unit of life?", self.page(new_url))
        forced = record_learning_attempt("SYN101", 1, capability="RECALL", task="What is the basic unit of life?",
                                         origin="QUIZ:quiz-1:r1", response="again", assistance_status="UNAIDED", root=self.root)
        self.assertEqual(forced["assistance_status"], "REVEALED")

    def test_deleting_an_active_session_with_an_unfinished_answer_saves_the_answer(self):
        url = self.start()
        turn = self.turn_id(self.page(url))
        self.provider.fail_next = 1
        self.post(url, "answer", client_turn_id=turn, response="don't lose me")
        self.post(url, "delete", confirm="yes")
        self.assertEqual([a["student_response"] for a in self.learning()["evidence"]], ["don't lose me"])

    # --- errors: configuration, sources, expired sessions ----------------------------
    def test_missing_ai_configuration_is_explained_and_nothing_is_stored(self):
        client = self.make_client(None)  # no injected provider: the real one, with no key
        with patch("university_jarvis.reasoning.get_openai_api_key", return_value=None):
            response = client.post(f"{WEEK}/tutor/start", data={"intention": "TEACH_ME", "client_request_id": "nokey"},
                                   follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no OpenAI API credential is configured", response.text)
        self.assertFalse((self.record_path.parent / "tutor-sessions").exists())

    def test_unsupported_sources_are_refused_clearly(self):
        self.matched = False
        response = self.client.post(f"{WEEK}/tutor/start", data={"intention": "TEACH_ME", "client_request_id": "nm"},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn("will not explain", response.text)
        self.assertEqual(self.provider.calls, [])

    def test_unknown_expired_or_malicious_session_ids_get_a_clear_404(self):
        for sid in ("tutor-000000000000", "nope", "..%2F..%2Fetc"):
            with self.subTest(sid=sid):
                response = self.client.get(f"{WEEK}/tutor/{sid}")
                self.assertEqual(response.status_code, 404)
                self.assertIn("not found", response.text.lower())
        self.assertEqual(self.post(f"{WEEK}/tutor/tutor-000000000000", "answer", client_turn_id="x", response="y").status_code, 200)
        self.assertEqual(self.client.post(f"{WEEK}/tutor/tutor-000000000000/explode").status_code, 404)

    def test_invalid_intention_is_rejected(self):
        response = self.client.post(f"{WEEK}/tutor/start", data={"intention": "CHAT", "client_request_id": "x"}, follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn("TEACH_ME or TEST_ME", response.text)

    # --- Hub security ----------------------------------------------------------------
    def test_post_routes_keep_the_hub_csrf_and_host_guards(self):
        url = self.start()
        before = self.snapshot()
        for path, data in ((f"{WEEK}/tutor/start", {"intention": "TEST_ME", "client_request_id": "evil"}),
                           (f"{url}/answer", {"client_turn_id": "e1", "response": "x"}),
                           (f"{url}/hint", {"client_turn_id": "e2"}),
                           (f"{url}/reveal", {"client_turn_id": "e3", "confirm": "yes"}),
                           (f"{url}/end", {}), (f"{url}/delete", {"confirm": "yes"})):
            for headers in ({"origin": "http://evil.example"}, {"sec-fetch-site": "cross-site"}, {"host": "evil.example"}):
                with self.subTest(path=path, headers=headers):
                    response = self.client.post(path, data=data, headers=headers, follow_redirects=False)
                    self.assertIn(response.status_code, (400, 403))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.client.get(url, headers={"host": "evil.example"}).status_code, 403)

    def test_action_urls_do_not_accept_get(self):
        url = self.start()
        for path in (f"{WEEK}/tutor/start", f"{url}/answer", f"{url}/delete", f"{url}/reveal"):
            self.assertEqual(self.client.get(path).status_code in (404, 405), True, path)
        self.assertEqual(self.provider.calls, [])


if __name__ == "__main__":
    unittest.main()


class HubTutorDiagnosisTests(unittest.TestCase):
    """Phase 3C slice 1 through the web layer; borrows the fixture and helpers, not the tests."""

    setUp = HubTutorTests.setUp
    make_client = HubTutorTests.make_client
    _context = HubTutorTests._context
    learning = HubTutorTests.learning
    start = HubTutorTests.start
    post = HubTutorTests.post
    turn_id = HubTutorTests.turn_id
    page = HubTutorTests.page

    WRONG = "I believe viruses are the basic unit of life"
    MIS = {"label": "Thinks viruses are the unit of life", "quote": "viruses are the basic unit",
           "confidence": "medium", "citations": [{"source_id": "s1", "pdf_page": 1}]}

    def scripted(self, **fields):
        base = {"message": "Look at the cited passage again.", "diagnosis": "misconception",
                "citations": [{"source_id": "s1", "pdf_page": 1}], "misconception": self.MIS}
        outputs = {**base, **fields}
        original = self.provider.generate_structured_output

        def generate(context, instructions, output_format):
            if context["action"] == "FEEDBACK":
                self.provider.calls.append(context)
                return outputs
            return original(context, instructions, output_format)
        self.provider.generate_structured_output = generate

    def answer(self, url, **data):
        turn = self.turn_id(self.page(url))
        return self.post(url, "answer", client_turn_id=turn, response=self.WRONG, **data)

    def test_answer_form_offers_the_optional_confidence_selector(self):
        html = self.page(self.start())
        for label in ("Sure", "Unsure", "Guessing", "Prefer not to say", "does not change how your answer is judged"):
            self.assertIn(label, html)

    def test_confidence_is_saved_shown_and_not_required(self):
        self.scripted(diagnosis="partial", misconception=None)
        url = self.start()
        self.assertEqual(self.answer(url, confidence="GUESSING").status_code, 303)
        self.assertEqual(self.learning()["evidence"][0]["self_reported_confidence"], "GUESSING")
        self.assertIn("You said: guessing", self.page(url))
        bad = self.answer(self.start(request_id="r2"), confidence="certain")
        self.assertEqual(bad.status_code, 200)
        self.assertIn("Sure, Unsure or Guessing", bad.text)

    def test_a_suspected_misunderstanding_is_shown_with_quote_and_can_be_disputed(self):
        self.scripted()
        url = self.start()
        self.answer(url)
        html = self.page(url)
        self.assertIn("Possible misunderstanding (provisional, medium confidence)", html)
        self.assertIn("viruses are the basic unit", html)
        self.assertIn("That's not what I meant", html)
        self.assertIn("Suggested next step", html)
        calls = len(self.provider.calls)
        target = re.search(r'name="target" value="(t\d+)"', html).group(1)
        out = self.post(url, "dispute", client_turn_id=f"dispute-{target}", target=target)
        self.assertEqual((out.status_code, out.headers["location"]), (303, url))
        after = self.page(url)
        self.assertIn("disputed by you", after)
        self.assertNotIn("That's not what I meant", after)
        self.assertEqual(len(self.provider.calls), calls)
        attempt = self.learning()["evidence"][0]
        self.assertEqual((attempt["student_response"], attempt["evaluation"]["outcome"]), (self.WRONG, "NOT_SUPPORTED"))
        self.assertEqual(attempt["evaluation"]["dispute"]["status"], "DISPUTED_BY_STUDENT")  # marked, not erased
        again = self.post(url, "dispute", client_turn_id=f"dispute-{target}", target=target)  # double click
        self.assertEqual(again.status_code, 303)
        self.assertEqual(len(self.learning()["evidence"]), 1)

    def test_disputing_nothing_shows_an_error_not_a_crash(self):
        self.scripted(diagnosis="partial", misconception=None)
        url = self.start()
        self.answer(url)
        out = self.post(url, "dispute", client_turn_id="d-x", target="t0002")
        self.assertEqual(out.status_code, 200)
        self.assertIn("no suspected misunderstanding", out.text)

    def test_a_feedback_that_leaks_the_reference_answer_is_never_displayed(self):
        self.scripted(diagnosis="partial", misconception=None, message=f"Actually: {SECRET}")
        url = self.start()
        self.answer(url)
        html = self.page(url)
        self.assertNotIn(SECRET, html)
        self.assertIn("did not finish", html)
        self.assertIn(self.WRONG, html)  # the answer itself is safe

    def test_a_fallback_reply_gave_no_help_so_the_page_does_not_say_answers_are_assisted(self):
        self.scripted(diagnosis="partial", misconception=None, message=f"Actually: {SECRET}")
        url = self.start()
        turn = self.turn_id(self.page(url))
        for _ in range(tutoring.MAX_REJECTED_REPLIES + 1):
            self.post(url, "answer", client_turn_id=turn, response=self.WRONG)
        html = self.page(url)
        self.assertNotIn(SECRET, html)
        self.assertIn("passed my safety checks", html)
        self.assertIn("ask for a hint, or tell me the part you do understand", html)
        self.assertIn("A hint means your next answer is recorded as assisted", html)
        self.assertNotIn("already recorded as assisted", html)

    def test_a_dispute_turn_is_labelled_not_left_blank(self):
        self.scripted()
        url = self.start()
        self.answer(url)
        target = re.search(r'name="target" value="(t\d+)"', self.page(url)).group(1)
        self.post(url, "dispute", client_turn_id="d1", target=target)
        self.assertIn("said a suspected misunderstanding is not what they meant", self.page(url))
