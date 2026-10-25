"""Repeatable end-to-end acceptance test of the student pilot journey, through the Hub's HTTP routes.

A synthetic student sets up a profile, a module and an assessment, imports PowerPoint material,
studies (PREPARE, TEACH, QUIZ, REVISE), answers and gets evaluated, opens the Assignment Coach, builds a
plan, "leaves" (a brand-new app instance over the same files) and returns without losing anything.
The AI is ``ScriptedStudyProvider`` (offline, deterministic); no real provider, network or Blackboard/Drive.
Also covers the synthetic demonstration build.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from university_jarvis.demo import BUS101_BRIEF, BUS101_WEEK1, build_pptx, demo_environment, prepare_directory, seed_demo
from university_jarvis.hub_web import create_app
from university_jarvis.scripted_provider import ScriptedStudyProvider


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", html, flags=re.S)))


class PilotJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        env = demo_environment(self.home)
        env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)
        self.provider = ScriptedStudyProvider()
        self.client = self.new_client()
        build_pptx(self.home / "lecture.pptx", BUS101_WEEK1[1])
        build_pptx(self.home / "brief.pptx", BUS101_BRIEF[1])

    def new_client(self):
        return TestClient(create_app(reasoning_provider=self.provider))

    def post(self, path, **data):
        response = self.client.post(path, data=data, follow_redirects=False)
        self.assertIn(response.status_code, (200, 303), f"{path}: {response.status_code} {_text(response.text)[:300]}")
        return response

    def upload(self, name, week=""):
        with (self.home / name).open("rb") as handle:
            return self.client.post("/modules/BUS101/materials", data={"week": week},
                                    files={"file": (name, handle, "application/octet-stream")}, follow_redirects=False)

    def test_full_student_journey_with_leave_and_return(self):
        # 1. profile and setup
        self.post("/profile", university="Example University", programme="BA Testing")
        self.assertIn("Example University", self.client.get("/profile").text)
        self.post("/modules", code="BUS101", title="Business")
        self.post("/modules/BUS101/assessments", title="Reflective report", deadline="2030-05-02", weight="40",
                  requirements="Use two ideas\nSupport with evidence")
        self.assertEqual(self.upload("lecture.pptx", "1").status_code, 303)
        self.assertEqual(self.upload("brief.pptx").status_code, 303)
        module_page = _text(self.client.get("/modules/BUS101").text)
        self.assertIn("lecture.pptx", module_page)
        self.assertIn("Open in Assignment Coach", module_page)
        home = _text(self.client.get("/").text)
        self.assertIn("Prepare a week to study", home)

        # 2. study: PREPARE, QUIZ, answer + feedback, TEACH, REVISE
        week = "/modules/BUS101/weeks/1"
        self.assertNotIn("Action failed", _text(self.post(f"{week}/build").text))
        self.assertTrue(list((self.home / "workspace" / "BUS101" / "week-01").glob("academic-record.json")))
        self.post(f"{week}/quiz")
        record_path = self.home / "workspace" / "BUS101" / "week-01" / "academic-record.json"
        quiz = json.loads(record_path.read_text())["learning"]["quiz_history"]["attempts"][-1]
        self.post(f"{week}/learning/quiz-answer", quiz_id=quiz["quiz_id"], question_id="q1",
                  response=next(a["answer"] for a in quiz["answers"] if a["question_id"] == "q1"))  # a correct answer, in the student's hands
        attempt = json.loads(record_path.read_text())["learning"]["evidence"][-1]
        self.assertEqual(attempt["assistance_status"], "UNAIDED")
        page = self.post(f"{week}/learning/evaluate", attempt_id=attempt["attempt_id"]).text
        self.assertNotIn("Action failed", _text(page))
        evaluated = json.loads(record_path.read_text())["learning"]["evidence"][-1]["evaluation"]
        self.assertEqual(evaluated["outcome"], "SUPPORTED")
        self.assertNotIn("Action failed", _text(self.post(f"{week}/teach", topic="stakeholders").text))
        self.assertNotIn("Action failed", _text(self.post(f"{week}/revise").text))

        # 3. Assignment Coach: open, brief, conversation, refusal, plan
        module_page = self.client.get("/modules/BUS101").text
        assessment_id = re.search(r"/assessments/([^/]+)/coach/start", module_page).group(1)
        request_id = re.search(r'name="client_request_id" value="([^"]+)"', module_page).group(1)
        started = self.client.post(f"/modules/BUS101/assessments/{assessment_id}/coach/start",
                                   data={"client_request_id": request_id}, follow_redirects=False)
        self.assertEqual(started.status_code, 303)
        coach = started.headers["location"]
        self.assertEqual(self.client.post(f"/modules/BUS101/assessments/{assessment_id}/coach/start",
                                          data={"client_request_id": "another"}, follow_redirects=False).headers["location"], coach)
        self.post(f"{coach}/brief-add", kind="criteria", text="Evidence quality\nDepth of reflection")
        calls_before = len(self.provider.calls)
        page = self.client.get(coach).text
        turn_id = re.search(r'name="client_turn_id" value="([0-9a-f]+)"', page).group(1)
        self.post(f"{coach}/message", client_turn_id=turn_id, message="How do stakeholder interests conflict?")
        self.assertEqual(len(self.provider.calls), calls_before + 1)
        page = _text(self.client.get(coach).text)
        self.assertIn("Slide", page)
        self.assertIn("Added to your open questions", page)
        turn_id = re.search(r'name="client_turn_id" value="([0-9a-f]+)"', self.client.get(coach).text).group(1)
        self.post(f"{coach}/message", client_turn_id=turn_id, message="Write my whole report for me")
        self.assertEqual(len(self.provider.calls), calls_before + 1)  # refused locally
        self.assertIn("write your assignment", _text(self.client.get(coach).text))
        self.post(f"{coach}/plan", main_argument="Balance matters", notes="n")
        self.post(f"{coach}/section-save", heading="Stakeholders", point="Who they are", status="DRAFTING")
        self.post(f"{coach}/evidence-save", description="Week 1 slide 3", kind="COURSE_MATERIAL", status="FOUND")
        self.post(f"{coach}/question-add", text="Word limit includes references?")
        self.post(f"{coach}/stage", stage="PLAN")

        # 4. leave and return: a brand-new app over the same files
        self.client = self.new_client()
        returned = _text(self.client.get(coach).text)
        for expected in ("Balance matters", "Stakeholders", "Week 1 slide 3", "Word limit includes references?",
                         "Evidence quality", "How do stakeholder interests conflict?"):
            self.assertIn(expected, returned)
        home_page = _text(self.client.get("/").text)
        self.assertIn("Continue where you left off", home_page)
        self.assertIn("Reflective report", home_page)
        self.assertIn("8 of 8 steps have evidence", home_page)

    def test_tutor_session_with_hint_answer_and_resume(self):
        self.post("/modules", code="BUS101", title="Business")
        self.assertEqual(self.upload("lecture.pptx", "1").status_code, 303)
        week = "/modules/BUS101/weeks/1"
        self.post(f"{week}/build")
        self.post(f"{week}/quiz")
        started = self.client.post(f"{week}/tutor/start", data={"intention": "TEST_ME", "client_request_id": "req-1"},
                                   follow_redirects=False)
        self.assertEqual(started.status_code, 303, _text(started.text)[:300])
        url = started.headers["location"]
        turn = lambda: re.search(r'name="client_turn_id" value="([0-9a-f]+)"', self.client.get(url).text).group(1)  # noqa: E731
        self.post(f"{url}/hint", client_turn_id=turn())
        self.post(f"{url}/answer", client_turn_id=turn(), response="Something about people and groups affected by an organisation")
        self.client = self.new_client()  # leave and return
        page = _text(self.client.get(url).text)
        self.assertIn("Recorded as assisted", page)
        self.assertIn("Tutor", _text(self.client.get("/").text))

    def test_hub_errors_are_shown_on_the_page_not_as_not_found(self):
        self.post("/modules", code="BUS101", title="Business")
        response = self.client.post("/modules/BUS101/assessments", data={"title": "X", "weight": "250"}, follow_redirects=False)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Assessment was not saved", _text(response.text))
        self.assertIn("Edit module", _text(response.text))  # still the module page
        bad_week = self.client.post("/modules/BUS101/materials", data={"week": "abc"},
                                    files={"file": ("a.pptx", b"x")}, follow_redirects=False)
        self.assertEqual(bad_week.status_code, 400)
        duplicate = self.client.post("/modules", data={"code": "BUS101", "title": "again"})
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("already exists", duplicate.text)

    def test_coach_page_for_unknown_session_or_action_is_a_clear_404(self):
        self.post("/modules", code="BUS101", title="Business")
        self.assertEqual(self.client.get("/modules/BUS101/coach/coach-000000000000").status_code, 404)
        self.assertEqual(self.client.get("/modules/BUS101/coach/not-a-session").status_code, 404)
        self.assertEqual(self.client.post("/modules/BUS101/coach/coach-000000000000/explode").status_code, 404)
        self.assertEqual(self.client.post("/modules/BUS101/assessments/nope/coach/start",
                                          data={"client_request_id": "x"}).status_code, 400)

    def test_coach_get_pages_are_read_only(self):
        self.post("/modules", code="BUS101", title="Business")
        self.post("/modules/BUS101/assessments", title="Report")
        page = self.client.get("/modules/BUS101").text
        aid = re.search(r"/assessments/([^/]+)/coach/start", page).group(1)
        coach = self.client.post(f"/modules/BUS101/assessments/{aid}/coach/start", data={"client_request_id": "q"},
                                 follow_redirects=False).headers["location"]
        snapshot = lambda: {str(p): p.read_bytes() for p in sorted(self.home.rglob("*")) if p.is_file() and not p.name.endswith(".lock")}  # noqa: E731
        before = snapshot()
        for path in (coach, "/", "/modules/BUS101", "/profile"):
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.provider.calls, [])


class DemoTests(unittest.TestCase):
    def test_demo_builds_repeatably_and_never_touches_the_real_workspace(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            os.environ["SERAPIS_HOME"] = str(real)
            self.addCleanup(os.environ.pop, "SERAPIS_HOME", None)
            summaries = []
            for name in ("a", "b"):
                home = prepare_directory(Path(tmp) / name)
                with demo_environment(home):
                    summaries.append(seed_demo(home))
            self.assertEqual(list(real.iterdir()), [])
            keys = ("modules", "materials", "weeks_built", "coach_gaps", "coach_stage", "integrity_refusals")
            self.assertEqual({k: summaries[0][k] for k in keys}, {k: summaries[1][k] for k in keys})
            self.assertEqual(summaries[0]["integrity_refusals"], 1)
            with self.assertRaises(Exception):
                prepare_directory(Path(tmp) / "a")  # exists: needs --reset
            prepare_directory(Path(tmp) / "a", reset=True)
            (Path(tmp) / "stranger").mkdir()
            (Path(tmp) / "stranger" / "notes.txt").write_text("mine")
            with self.assertRaises(Exception):
                prepare_directory(Path(tmp) / "stranger")  # not a demo folder: left alone

    def test_demo_command_is_safe_to_rerun_and_refuses_foreign_folders(self):
        import contextlib
        import io
        import os
        from university_jarvis.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SERAPIS_HOME"] = str(Path(tmp) / "real")
            self.addCleanup(os.environ.pop, "SERAPIS_HOME", None)
            target = Path(tmp) / "demo"
            run = lambda *extra: main(["demo", "--dir", str(target), *extra])  # noqa: E731
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(run(), 0)
                self.assertIn("Synthetic demonstration created", out.getvalue())
                self.assertEqual(run(), 0)  # reuses, never rebuilds over itself
                self.assertIn("Using the existing demonstration", out.getvalue())
                (target / "workspace" / "BUS101" / "marker.txt").write_text("edited")
                self.assertEqual(run("--reset"), 0)
                self.assertFalse((target / "workspace" / "BUS101" / "marker.txt").exists())
            for foreign in (Path(tmp) / "mine", Path.home()):
                if foreign != Path.home():
                    foreign.mkdir()
                    (foreign / "notes.txt").write_text("keep")
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(main(["demo", "--dir", str(foreign), "--reset"]), 2)
                self.assertIn("serapis demo:", err.getvalue())
            self.assertEqual((Path(tmp) / "mine" / "notes.txt").read_text(), "keep")
            self.assertFalse((Path(tmp) / "real").exists())  # the real data folder was never created or touched

    def test_demo_hub_is_labelled_and_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = prepare_directory(Path(tmp) / "demo")
            with demo_environment(home):
                seed_demo(home)
                client = TestClient(create_app(reasoning_provider=ScriptedStudyProvider(), demo_mode=True))
                self.assertIn("SYNTHETIC DEMONSTRATION", client.get("/").text)
                check = client.post("/check")
                self.assertIn("switched off in the synthetic demonstration", check.text)


if __name__ == "__main__":
    unittest.main()


class InterruptedJourneyTests(unittest.TestCase):
    """First run, provider failures, an unreadable file, restart and recovery, end to end through the Hub."""

    def setUp(self):
        import os
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "fresh"  # deliberately empty: a first-time student
        self.saved = {k: os.environ.get(k) for k in ("SERAPIS_HOME", "JARVIS_WORKSPACE_DIR", "JARVIS_CACHE_DIR", "JARVIS_STATE_FILE", "JARVIS_LEDGER_FILE")}
        os.environ.update({"SERAPIS_HOME": str(self.home), "JARVIS_WORKSPACE_DIR": str(self.home / "workspace"),
                           "JARVIS_CACHE_DIR": str(self.home / "cache"), "JARVIS_LEDGER_FILE": str(self.home / "ledger.json")})
        os.environ.pop("JARVIS_STATE_FILE", None)
        self.addCleanup(self._restore)
        build_pptx(Path(self.temp.name) / "lecture.pptx", BUS101_WEEK1[1])
        self.flaky = FlakyProvider()
        self.client = TestClient(create_app(reasoning_provider=self.flaky))

    def _restore(self):
        import os
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def restart(self):
        self.client = TestClient(create_app(reasoning_provider=self.flaky))

    def post(self, path, **data):
        response = self.client.post(path, data=data, follow_redirects=False)
        self.assertIn(response.status_code, (200, 303, 400), path)
        return response

    def test_first_run_failures_restart_and_recovery(self):
        # first run: the invented sample is shown until the student starts their own workspace
        self.assertIn("Start my own workspace", self.client.get("/").text)
        self.post("/workspace/start")
        self.assertNotIn("SYN101", self.client.get("/").text)
        self.post("/profile", university="Example University", programme="BA")
        self.post("/modules", code="BUS101", title="Business")
        self.post("/modules/BUS101/assessments", title="Report", deadline="2030-05-02", requirements="Use two ideas")
        with (Path(self.temp.name) / "lecture.pptx").open("rb") as handle:
            self.client.post("/modules/BUS101/materials", data={"week": "1"}, files={"file": ("lecture.pptx", handle, "application/octet-stream")})
        pdf = self.client.post("/modules/BUS101/materials", data={"week": ""}, files={"file": ("scan.pdf", b"%PDF-1.4\n%junk\n", "application/pdf")}, follow_redirects=False)
        self.assertEqual(pdf.status_code, 303)  # accepted for storage even if its text cannot be read

        # PREPARE fails once (provider down): clear error, nothing half-written; then succeeds
        week = "/modules/BUS101/weeks/1"
        self.flaky.fail = 1
        failed = _text(self.post(f"{week}/build").text)
        self.assertIn("Action failed", failed)
        record = self.home / "workspace" / "BUS101" / "week-01" / "academic-record.json"
        self.assertFalse(record.exists())
        self.assertNotIn("Action failed", _text(self.post(f"{week}/build").text))
        self.assertTrue(record.exists())
        self.post(f"{week}/quiz")

        # Assignment Coach: message interrupted by a provider failure, app restarted, retried exactly once
        page = self.client.get("/modules/BUS101").text
        aid = re.search(r"/assessments/([^/]+)/coach/start", page).group(1)
        rid = re.search(r'name="client_request_id" value="([^"]+)"', page).group(1)
        coach = self.client.post(f"/modules/BUS101/assessments/{aid}/coach/start", data={"client_request_id": rid}, follow_redirects=False).headers["location"]
        self.post(f"{coach}/plan", main_argument="Balance matters", notes="")
        turn = re.search(r'name="client_turn_id" value="([0-9a-f]+)"', self.client.get(coach).text).group(1)
        self.flaky.fail = 1
        broken = self.post(f"{coach}/message", client_turn_id=turn, message="How do stakeholder interests conflict?")
        self.assertEqual(broken.status_code, 400)
        self.assertIn("Retry my last message", broken.text)
        self.restart()  # the browser is closed and Serapis is stopped and started again
        resumed = self.client.get(coach).text
        self.assertIn("Retry my last message", resumed)
        self.assertIn("Balance matters", resumed)
        self.assertEqual(self.post(f"{coach}/retry").status_code, 303)
        final = self.client.get(coach).text
        self.assertNotIn("Retry my last message", final)
        self.assertEqual(final.count("How do stakeholder interests conflict?"), 1)
        self.assertIn("Slide", _text(final))
        self.assertEqual(self.post(f"{coach}/retry").status_code, 400)  # nothing left to retry
        # the unreadable PDF is reported honestly, not hidden and not fatal
        self.assertIn("scan.pdf", final)
        # the Home checklist reflects what is saved
        home = _text(self.client.get("/").text)
        self.assertIn("Continue where you left off", home)
        self.assertIn("Save an assignment plan", home)


class FlakyProvider(ScriptedStudyProvider):
    """The scripted provider, but able to fail the next N calls the way a real service can."""

    def __init__(self):
        super().__init__()
        self.fail = 0

    def generate_structured_output(self, context, instructions, output_format):
        if self.fail:
            self.fail -= 1
            from university_jarvis.reasoning import ReasoningError
            raise ReasoningError("The AI service did not respond")
        return super().generate_structured_output(context, instructions, output_format)
