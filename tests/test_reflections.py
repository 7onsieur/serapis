"""After-lecture reflections, corrections, study exports and their Hub surface (all offline, fictional data)."""

from __future__ import annotations

import copy
import io
import json
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

import test_hub_slice4 as S4
from university_jarvis import hub_service, reflections
from university_jarvis.hub_web import create_app
from university_jarvis.intake_ledger import new_ledger
from university_jarvis.reasoning import REVISE_WORKFLOW, build_reasoning_context
from university_jarvis.state import StateError
from university_jarvis.student_setup import save_assessment
from university_jarvis.workspace import (
    _docx_bytes,
    _notebooklm_markdown,
    _teach_target,
    capture_after_lecture,
    correct_after_lecture_entry,
    record_learning_attempt,
)

OPENING = "2026-10-26T09:00:00+00:00"
LATER = "2026-10-27T10:30:00+00:00"
FIXED = "2026-10-28T08:00:00+00:00"


def _state(tmp: Path) -> dict:
    """Two modules, three module-weeks, one assessment whose deadline the student has not entered."""
    from university_jarvis.state import load_state
    from university_jarvis.student_setup import add_module, initialize_personal_state

    path = tmp / "academic-state.json"
    with patch.dict("os.environ", {"SERAPIS_HOME": str(tmp)}):
        initialize_personal_state()
        add_module("SYN101", "Introduction to Example Studies", path=path)
        add_module("SYN202", "Second Fictional Module", path=path)
        save_assessment("SYN101", title="Essay one", path=path)
        state = load_state(path)
    for module in state["modules"]:
        module["weeks"] = [
            {"week": number, "date": None, "topic": f"Topic {number}", "progress": "unknown", "source_ids": []}
            for number in ((1, 2) if module["code"] == "SYN101" else (1,))
        ]
    return state


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "workspace"
        self.state = _state(self.tmp)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def record_path(self, module="SYN101", week=1) -> Path:
        return self.root / module / f"week-{week:02d}" / "academic-record.json"

    def record(self, module="SYN101", week=1) -> dict:
        return json.loads(self.record_path(module, week).read_text(encoding="utf-8"))

    def reflect(self, module="SYN101", week=1, **fields):
        return capture_after_lecture(module, week, state=self.state, workspace_root=self.root,
                                     captured_at=fields.pop("captured_at", OPENING), **fields)

    def client(self) -> TestClient:
        return TestClient(create_app(state=self.state, ledger=new_ledger(), workspace_root=self.root,
                                     reasoning_provider=S4.NoCallProvider()))


class CreationAndPersistence(Base):
    def test_reflection_works_without_any_ai_provider_or_prior_workspace(self) -> None:
        result = self.reflect(questions=["What is framing?"], notes=["Covered framing."])
        record = self.record()
        self.assertEqual(result.capture_id, "capture-0001")
        self.assertEqual(record["workflows"]["prepare_me"]["status"], "not_generated")
        self.assertEqual(record["module"]["code"], "SYN101")
        self.assertEqual(record["week"]["number"], 1)

    def test_student_authorship_and_timestamp_are_preserved(self) -> None:
        self.reflect(understood=["Framing shapes answers."])
        capture = self.record()["workflows"]["after_lecture"]["captures"][0]
        self.assertEqual(capture["captured_at"], OPENING)
        self.assertEqual(capture["provenance"]["classification"], "student_reported")
        self.assertEqual(capture["provenance"]["verification_status"], "unverified_against_official_sources")

    def test_revisiting_adds_entries_and_never_rewrites_history(self) -> None:
        self.reflect(questions=["Q one?"])
        first = copy.deepcopy(self.record()["workflows"]["after_lecture"]["captures"][0])
        self.reflect(questions=["Q two?"], captured_at=LATER)
        captures = self.record()["workflows"]["after_lecture"]["captures"]
        self.assertEqual([c["capture_id"] for c in captures], ["capture-0001", "capture-0002"])
        self.assertEqual(captures[0], first)

    def test_double_submit_is_not_saved_twice(self) -> None:
        self.reflect(questions=["Same?"])
        with self.assertRaisesRegex(StateError, "identical"):
            self.reflect(questions=["Same?"])
        self.assertEqual(len(self.record()["workflows"]["after_lecture"]["captures"]), 1)

    def test_empty_reflection_creates_no_record(self) -> None:
        with self.assertRaises(StateError):
            self.reflect(notes=["   "])
        self.assertFalse(self.record_path().exists())

    def test_oversized_entries_are_refused(self) -> None:
        with self.assertRaisesRegex(StateError, "longer than"):
            self.reflect(notes=["x" * (reflections.MAX_ENTRY_CHARS + 1)])
        with self.assertRaisesRegex(StateError, "Too many"):
            self.reflect(questions=[f"q{i}" for i in range(reflections.MAX_ENTRIES_PER_FIELD + 1)])

    def test_module_and_week_isolation(self) -> None:
        self.reflect("SYN101", 1, questions=["Only week one?"])
        self.reflect("SYN101", 2, questions=["Only week two?"])
        self.reflect("SYN202", 1, questions=["Other module?"])
        for module, week, expected in (("SYN101", 1, "Only week one?"), ("SYN101", 2, "Only week two?"),
                                       ("SYN202", 1, "Other module?")):
            texts = reflections.effective_values(self.record(module, week), "questions")
            self.assertEqual(texts, [expected])
            md = _notebooklm_markdown(self.record(module, week))
            for other in ("Only week one?", "Only week two?", "Other module?"):
                self.assertEqual(other in md, other == expected)

    def test_unknown_week_is_refused_and_writes_nothing(self) -> None:
        with self.assertRaises(StateError):
            self.reflect("SYN101", 9, notes=["x"])
        self.assertFalse((self.root / "SYN101" / "week-09").exists())


class Corrections(Base):
    def setUp(self) -> None:
        super().setUp()
        self.reflect(uncertainties=["Why does framing matter"], questions=["What is bias?"],
                     understood=["I know sampling"])

    def correct(self, entry_id, **kwargs):
        return correct_after_lecture_entry("SYN101", 1, entry_id, workspace_root=self.root,
                                           corrected_at=FIXED, **kwargs)

    def test_correction_keeps_original_and_shows_current_wording(self) -> None:
        before = copy.deepcopy(self.record()["workflows"]["after_lecture"]["captures"])
        self.correct("capture-0001:understood:0", action="correct", new_text="I know random sampling",
                     reason="too vague")
        record = self.record()
        self.assertEqual(record["workflows"]["after_lecture"]["captures"], before)
        entry = next(e for e in reflections.effective_entries(record) if e["field"] == "understood")
        self.assertEqual((entry["status"], entry["text"], entry["original_text"]),
                         ("corrected", "I know random sampling", "I know sampling"))
        correction = record["workflows"]["after_lecture"]["corrections"][0]
        self.assertEqual((correction["corrected_at"], correction["reason"], correction["previous_text"]),
                         (FIXED, "too vague", "I know sampling"))
        self.assertEqual(correction["provenance"]["classification"], "student_reported")

    def test_correcting_an_open_question_supersedes_the_old_item_without_deleting_it(self) -> None:
        self.correct("capture-0001:questions:0", action="correct", new_text="What is sampling bias?")
        items = self.record()["learning"]["unresolved_items"]["items"]
        old = next(i for i in items if i["text"] == "What is bias?")
        new = next(i for i in items if i["text"] == "What is sampling bias?")
        self.assertEqual((old["status"], new["status"]), ("superseded", "open"))
        self.assertEqual(old["superseded_by"], "correction-0001")
        self.assertEqual(new["provenance"]["correction_id"], "correction-0001")
        self.assertEqual(new["provenance"]["classification"], "student_reported")

    def test_second_correction_chains_from_the_latest_wording(self) -> None:
        self.correct("capture-0001:questions:0", action="correct", new_text="Second wording")
        self.correct("capture-0001:questions:0", action="correct", new_text="Third wording")
        open_texts = [i["text"] for i in self.record()["learning"]["unresolved_items"]["items"]
                      if i["status"] == "open" and i["kind"] == "question"]
        self.assertEqual(open_texts, ["Third wording"])
        self.assertEqual(len(self.record()["workflows"]["after_lecture"]["corrections"]), 2)

    def test_withdraw_resolve_and_reopen(self) -> None:
        self.correct("capture-0001:understood:0", action="withdraw", reason="wrong")
        self.assertEqual(reflections.effective_values(self.record(), "understood"), [])
        self.correct("capture-0001:questions:0", action="resolve")
        self.assertEqual(reflections.open_reflection_items(self.record()),
                         [{"kind": "uncertainty", "text": "Why does framing matter",
                           "entry_id": "capture-0001:uncertainties:0"}])
        self.assertEqual(reflections.resolved_values(self.record()), [{"kind": "question", "text": "What is bias?"}])
        self.correct("capture-0001:questions:0", action="reopen")
        self.assertEqual(len(reflections.open_reflection_items(self.record())), 2)
        self.assertEqual(self.record()["learning"]["unresolved_items"]["status"], "open")

    def test_invalid_corrections_are_refused_and_change_nothing(self) -> None:
        snapshot = self.record_path().read_bytes()
        bad = [
            dict(entry_id="capture-0001:questions:7", action="correct", new_text="x"),
            dict(entry_id="capture-0009:questions:0", action="withdraw"),
            dict(entry_id="not an id", action="withdraw"),
            dict(entry_id="capture-0001:questions:0", action="delete"),
            dict(entry_id="capture-0001:questions:0", action="correct", new_text="  "),
            dict(entry_id="capture-0001:questions:0", action="correct", new_text="What is bias?"),
            dict(entry_id="capture-0001:understood:0", action="resolve"),
            dict(entry_id="capture-0001:questions:0", action="reopen"),
        ]
        for kwargs in bad:
            with self.subTest(kwargs), self.assertRaises(StateError):
                self.correct(**kwargs)
        self.assertEqual(self.record_path().read_bytes(), snapshot)

    def test_a_withdrawn_entry_cannot_be_withdrawn_again_but_can_be_rewritten(self) -> None:
        self.correct("capture-0001:understood:0", action="withdraw")
        with self.assertRaises(StateError):
            self.correct("capture-0001:understood:0", action="withdraw")
        self.correct("capture-0001:understood:0", action="correct", new_text="Rewritten")
        self.assertEqual(reflections.effective_values(self.record(), "understood"), ["Rewritten"])

    def test_corrections_are_isolated_to_their_week(self) -> None:
        self.reflect("SYN101", 2, questions=["Week two question"])
        with self.assertRaises(StateError):
            correct_after_lecture_entry("SYN101", 2, "capture-0001:uncertainties:0", action="withdraw",
                                        workspace_root=self.root)  # that entry only exists in week 1
        self.assertEqual(reflections.effective_values(self.record("SYN101", 2), "questions"), ["Week two question"])

    def test_exports_show_corrected_wording_and_omit_withdrawn_text(self) -> None:
        self.correct("capture-0001:understood:0", action="correct", new_text="I know random sampling")
        self.correct("capture-0001:questions:0", action="withdraw")
        md = _notebooklm_markdown(self.record())
        self.assertIn("I know random sampling", md)
        self.assertIn("corrected by student", md)
        self.assertNotIn("I know sampling\n", md)
        self.assertNotIn("What is bias?", md)


class AssessmentBoundaries(Base):
    def test_assessment_comments_never_change_academic_facts_or_attention(self) -> None:
        before = copy.deepcopy(self.state)
        self.reflect(assessment_comments=["Lecturer said the essay is due Friday 5 December and worth 60%"])
        self.assertEqual(self.state, before)  # in-memory state untouched
        picture = hub_service.get_academic_picture(state=self.state, ledger=new_ledger(), workspace_root=self.root)
        assessment = picture["modules"][0]["assessments"][0]
        self.assertIsNone(assessment["deadline"])
        attention = json.dumps(hub_service.get_attention(state=self.state, ledger=new_ledger(), workspace_root=self.root))
        self.assertNotIn("5 December", attention)

    def test_exports_label_assessment_remarks_as_unconfirmed(self) -> None:
        self.reflect(assessment_comments=["Maybe an open-book exam"])
        record = self.record()
        for text in (_notebooklm_markdown(record), _docx_text(record)):
            self.assertIn("Maybe an open-book exam", text)
            self.assertIn("not a confirmed deadline", text)
        self.assertNotIn("Maybe an open-book exam", json.dumps(hub_service.build_student_journey(
            self.state, hub_service.get_academic_picture(state=self.state, ledger=new_ledger(),
                                                         workspace_root=self.root), workspace_root=self.root)["steps"]))

    def test_revise_context_marks_assessment_remarks_unconfirmed(self) -> None:
        self.reflect(assessment_comments=["Might be 40 percent"], questions=["How do I cite?"])
        context = reflections.reflection_context(self.record())
        self.assertEqual(context["classification"], "student_reported")
        self.assertEqual(context["assessment_remarks_unconfirmed"], ["Might be 40 percent"])
        self.assertIn("never present them as official-source claims", context["note"])


class LearningIntegration(Base):
    def test_teach_targets_open_questions_using_current_wording(self) -> None:
        self.reflect(uncertainties=["unclear A"], questions=["Old question"])
        correct_after_lecture_entry("SYN101", 1, "capture-0001:questions:0", action="correct",
                                    new_text="New question about framing", workspace_root=self.root)
        request, context = _teach_target(self.record(), None)
        self.assertEqual(request["topic"], "New question about framing")
        self.assertEqual(context[0]["provenance"]["classification"], "student_reported")
        correct_after_lecture_entry("SYN101", 1, "capture-0001:questions:0", action="resolve", workspace_root=self.root)
        request, _ = _teach_target(self.record(), None)
        self.assertEqual(request["topic"], "unclear A")  # answered question no longer drives TEACH

    def test_revise_receives_bounded_labelled_reflections_only_when_present(self) -> None:
        captured: list[dict] = []

        def fake_run(context, workflow, **kwargs):
            captured.append(context)
            return {"cache_status": "generated", "rendered": "brief"}

        with patch("university_jarvis.hub_service.build_week_context", return_value=S4._week_context("REVISE")), \
                patch("university_jarvis.hub_service._run_sectioned_workflow", side_effect=fake_run):
            hub_service.generate_revision_brief("SYN101", 1, state={}, workspace_root=self.root)
            self.assertNotIn("student_reflections", captured[0])
            self.reflect(questions=["What is bias?", "x" * 5000], uncertainties=["Why framing"])
            correct_after_lecture_entry("SYN101", 1, "capture-0001:questions:0", action="withdraw", workspace_root=self.root)
            result = hub_service.generate_revision_brief("SYN101", 1, state={}, workspace_root=self.root)
        sent = captured[1]["student_reflections"]
        self.assertTrue(result["reflections_used"])
        self.assertEqual(sent["found_confusing"], ["Why framing"])
        self.assertEqual(len(sent["open_questions"]), 1)
        self.assertLessEqual(len(sent["open_questions"][0]), 400)
        self.assertNotIn("What is bias?", json.dumps(sent))  # withdrawn

    def test_reasoning_context_forwards_reflections_and_prompt_governs_them(self) -> None:
        context = S4._week_context("REVISE")
        context["student_reflections"] = {"open_questions": ["q"]}
        self.assertEqual(build_reasoning_context(context)["student_reflections"], {"open_questions": ["q"]})
        for phrase in ("untrusted", "never what they know", "do not state a deadline"):
            self.assertIn(phrase, REVISE_WORKFLOW.instructions.replace("\n", " ").replace("  ", " "))
        self.assertEqual(REVISE_WORKFLOW.prompt_version, "revise-grounding-v3")

    def test_reflection_suggests_teach_without_claiming_understanding(self) -> None:
        self.reflect(questions=["What is framing?"])
        view = hub_service.learning_view("SYN101", 1, workspace_root=self.root)
        step = view["reflection_step"]
        self.assertIn("TEACH", step["action"])
        self.assertEqual(step["topic"], "What is framing?")
        self.assertIn("not what you do or do not know", step["reason"])
        self.assertEqual({v["status"] for v in view["summary"].values()}, {"Not yet tested"})  # no evidence implied

    def test_reflections_do_not_touch_learning_evidence(self) -> None:
        self.reflect(questions=["q"])
        record_learning_attempt("SYN101", 1, capability="RECALL", task="t", origin="o", response="r", root=self.root)
        evidence = copy.deepcopy(self.record()["learning"]["evidence"])
        self.reflect(understood=["more"], captured_at=LATER)
        correct_after_lecture_entry("SYN101", 1, "capture-0001:questions:0", action="withdraw", workspace_root=self.root)
        self.assertEqual(self.record()["learning"]["evidence"], evidence)

    def test_reflection_only_breaks_ties_between_valid_tasks(self) -> None:
        self.reflect(questions=["How does sampling bias arise?"])
        tasks = [{"task": "Define a census."}, {"task": "Explain sampling bias."}]
        ordered = hub_service._prefer_reflection_topics(tasks, self.record())
        self.assertEqual([t["task"] for t in ordered], ["Explain sampling bias.", "Define a census."])
        self.assertEqual(hub_service._prefer_reflection_topics(tasks, {}), tasks)

    def test_closed_items_are_not_surfaced_as_attention(self) -> None:
        self.reflect(questions=["Needs attention?"])
        correct_after_lecture_entry("SYN101", 1, "capture-0001:questions:0", action="resolve", workspace_root=self.root)
        attention = hub_service.get_attention(state=self.state, ledger=new_ledger(), workspace_root=self.root)
        self.assertEqual(attention["open_unresolved_items"], [])

    def test_week_journey_orders_the_student_path(self) -> None:
        journey = hub_service.week_journey("SYN101", 1, workspace_root=self.root)
        self.assertEqual([s["id"] for s in journey["steps"]],
                         ["prepare", "attend", "reflect", "teach", "quiz", "revise", "export"])
        self.assertEqual(journey["next"]["id"], "prepare")
        self.reflect(questions=["What is framing?"])
        journey = hub_service.week_journey("SYN101", 1, workspace_root=self.root)
        done = {s["id"] for s in journey["steps"] if s["done"]}
        self.assertEqual(done, {"reflect"})  # attending/revising are never inferred
        self.assertIn("What is framing?", next(s for s in journey["steps"] if s["id"] == "teach")["detail"])


def _docx_text(record: dict) -> str:
    with ZipFile(io.BytesIO(_docx_bytes(record))) as archive:
        xml = ET.fromstring(archive.read("word/document.xml"))
    return "\n".join("".join(t.text or "" for t in p.iter() if t.tag.endswith("}t")) for p in xml.iter()
                     if p.tag.endswith("}p"))


class ExportContent(Base):
    def full_record(self) -> dict:
        self.reflect(covered=["Sampling and framing"], understood=["Random sampling"],
                     uncertainties=["Why framing matters"], questions=["What is bias?"],
                     examples_cases=["The census case"], lecturer_emphasis=["Define terms carefully"],
                     assessment_comments=["Essay rubric mentioned"], notes=["My private thoughts"])
        path = self.record_path()
        record = json.loads(path.read_text())
        record["learning"]["quiz_history"] = {"status": "recorded", "attempts": [{
            "quiz_id": "quiz-0001", "created_at": OPENING,
            "questions": [{"question_id": "q1", "question_type": "recall", "question": "State the sampling rule?",
                           "provenance": []}],
            "answers": [{"question_id": "q1", "answer": "SECRET-REFERENCE-ANSWER", "provenance": []}]}]}
        record["learning"]["evidence"] = [{
            "attempt_id": "a1", "capability": "RECALL", "task": "State the sampling rule?", "origin": "QUIZ:quiz-0001:q1",
            "student_response": "MY-PRIVATE-ANSWER-TEXT", "expected_answer": "SECRET-REFERENCE-ANSWER",
            "assistance_status": "UNAIDED", "task_key": "k1",
            "evaluation": {"outcome": "NOT_SUPPORTED", "reason": "REASON-LEAKING-THE-REFERENCE", "basis": "x"}}]
        record["workflows"]["prepare_me"]["generation"] = {"provider": {"model": "SECRET-MODEL"}, "cache_key": "CK"}
        return record

    def test_docx_is_a_valid_word_package_with_every_section(self) -> None:
        record = self.full_record()
        data = _docx_bytes(record)
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual({"[Content_Types].xml", "word/document.xml", "word/styles.xml", "word/numbering.xml"} - set(archive.namelist()), set())
            for name in archive.namelist():
                if name.endswith((".xml", ".rels")):
                    ET.fromstring(archive.read(name))
        text = _docx_text(record)
        for heading in ("Week 1 Study Pack", "1. Orientation", "3. My reflections", "4. Questions to resolve",
                        "5. Taught topics", "6. Practice questions and recorded answers", "7. Revision priorities",
                        "8. Assessment connections", "9. Sources and provenance"):
            self.assertIn(heading, text)
        for expected in ("Sampling and framing", "Why framing matters", "What is bias?", "The census case",
                         "Define terms carefully", "My private thoughts", "State the sampling rule?",
                         "Student-reported", "AI-generated study aid", "University source"):
            self.assertIn(expected, text)

    def test_exports_never_include_reference_answers_private_answers_or_internal_metadata(self) -> None:
        record = self.full_record()
        blobs = [_docx_text(record), _notebooklm_markdown(record)]
        for blob in blobs:
            for forbidden in ("SECRET-REFERENCE-ANSWER", "MY-PRIVATE-ANSWER-TEXT", "REASON-LEAKING-THE-REFERENCE",
                              "SECRET-MODEL", "cache_key", "prompt_version", "system prompt", str(self.root),
                              "api_key", "OPENAI"):
                self.assertNotIn(forbidden, blob)
        self.assertIn("Reference answers are", blobs[0])

    def test_evidence_is_summarised_as_standing_not_grade(self) -> None:
        md = _notebooklm_markdown(self.full_record())
        self.assertIn("not supported by the course material", md)
        self.assertIn("provisional", md)
        self.assertNotIn("mastery score", md.lower())

    def test_empty_and_incomplete_records_still_export(self) -> None:
        self.reflect(notes=["Only a note"])
        bare = self.record()
        bare["sources"] = []
        for blob in (_docx_text(bare), _notebooklm_markdown(bare)):
            self.assertIn("Only a note", blob)
            self.assertIn("No source-based preparation", blob)
            self.assertIn("No quiz or check questions", blob)
            self.assertIn("No course sources are attached", blob)
        skeleton = {"module": {"code": "X1", "title": "T"}, "week": {"number": 3}, "workflows": {}, "learning": {}, "sources": []}
        self.assertIn("No reflections have been recorded yet.", _notebooklm_markdown(skeleton))
        self.assertIn("No reflections have been recorded yet.", _docx_text(skeleton))

    def test_regeneration_tracks_the_evolving_record_and_is_deterministic(self) -> None:
        self.reflect(understood=["First?"])
        first = _notebooklm_markdown(self.record())
        self.assertEqual(first, _notebooklm_markdown(self.record()))
        self.assertEqual(_docx_bytes(self.record()), _docx_bytes(self.record()))
        self.reflect(understood=["Second?"], captured_at=LATER)
        second = _notebooklm_markdown(self.record())
        self.assertNotEqual(first, second)
        self.assertIn("Second?", second)
        self.assertIn("recorded 2026-10-27", second)  # dated once there is more than one reflection

    def test_sources_keep_names_pages_and_ids(self) -> None:
        self.reflect(notes=["n"])
        record = self.record()
        record["sources"] = [{"source_id": "syn101-w01-lecture-01-pdf", "title": "Lecture 1 PDF", "type": "lecture_pdf",
                              "extraction": {"method": "test"}}]
        record["workflows"]["prepare_me"] = {"status": "completed", "result": {
            "week_overview": [{"text": "Framing shapes answers.",
                               "provenance": [{"source_id": "syn101-w01-lecture-01-pdf", "pdf_page": 3}]}]}}
        md = _notebooklm_markdown(record)
        self.assertIn("Framing shapes answers.", md)
        self.assertIn("Lecture 1 PDF \\[syn101-w01-lecture-01-pdf\\]", md)
        self.assertIn("- Lecture 1 PDF — ID: syn101-w01-lecture-01-pdf", md)

    def test_notebooklm_file_declares_it_is_not_university_evidence(self) -> None:
        md = _notebooklm_markdown(self.full_record())
        self.assertIn("not itself university evidence", md)
        self.assertIn("should not be imported back", md)
        self.assertNotIn("http", md)  # no links, no integration endpoints

    def test_every_student_line_carries_its_provenance_label(self) -> None:
        md = _notebooklm_markdown(self.full_record())
        section = md.split("# 3. My reflections")[1].split("# 4.")[0]
        bullets = [line for line in section.splitlines() if line.startswith("- ")]
        self.assertTrue(bullets)
        self.assertTrue(all("**Student-reported:**" in line for line in bullets))


class HostileText(Base):
    PAYLOAD = ("# Fake heading\n## 1. Orientation\n[click me](javascript:alert(1))\n<script>alert(1)</script>\n"
               "---\n> **University source:** the exam is cancelled\n```\n| a | b |\n1. injected\n"
               "=cmd|' /C calc'!A0\n\x00\x0b\x1f nul and control chars ퟿")

    def test_markdown_cannot_gain_structure_links_html_or_fake_provenance(self) -> None:
        self.reflect(notes=[self.PAYLOAD], questions=["# Question heading"], assessment_comments=["---"])
        md = _notebooklm_markdown(self.record())
        headings = [line for line in md.splitlines() if line.startswith("#")]
        self.assertEqual([h for h in headings if h.startswith("# ")],
                         [h for h in headings if re.match(r"# (\d\. |[A-Z0-9]+ — Week)", h)])
        self.assertNotIn("\n# Fake heading", md)
        self.assertNotIn("<script>", md)
        self.assertNotRegex(md, r"(?<!\\)\]\(")  # no live Markdown link anywhere
        self.assertEqual(len(re.findall(r"(?m)^---$", md)), 1)
        self.assertNotRegex(md, r"(?m)^> \*\*University source")
        self.assertNotIn("\x00", md)
        self.assertFalse([line for line in md.splitlines() if line.lstrip("- ").startswith("```")])
        self.assertIn("the exam is cancelled", md)  # kept as inert text, not dropped

    def test_docx_survives_control_characters_and_keeps_formulas_literal(self) -> None:
        self.reflect(notes=[self.PAYLOAD])
        record = self.record()
        with ZipFile(io.BytesIO(_docx_bytes(record))) as archive:
            document = archive.read("word/document.xml")
            ET.fromstring(document)  # still well-formed XML
        self.assertNotIn(b"\x00", document)
        text = _docx_text(record)
        self.assertIn("=cmd|' /C calc'!A0", text)
        self.assertIn("<script>alert(1)</script>", text)  # plain text in Word, XML-escaped on disk
        self.assertNotIn(b"<script>", document)
        self.assertNotIn(b"w:fldSimple", document)
        self.assertNotIn(b"w:hyperlink", document)

    def test_page_escapes_reflection_text(self) -> None:
        self.reflect(notes=["<img src=x onerror=alert(1)>"], questions=['"><script>boom()</script>'])
        body = self.client().get("/modules/SYN101/weeks/1").text
        self.assertNotIn("<img src=x", body)
        self.assertNotIn("<script>boom", body)
        self.assertIn("&lt;img src=x", body)


class HubSurface(Base):
    def test_week_page_shows_journey_form_and_labelled_fields(self) -> None:
        client = self.client()
        body = client.get("/modules/SYN101/weeks/1").text
        self.assertIn("Prepare &rarr; Attend &rarr; Reflect &rarr; TEACH &rarr; Quiz &rarr; REVISE &rarr; Export", body)
        self.assertIn("Reflect after the lecture", body)
        self.assertIn("student-reported", body)
        self.assertIn("Save a reflection or prepare this week first", body)  # exports not offered yet
        for field_id in re.findall(r'<textarea id="([^"]+)"', body):
            self.assertIn(f'<label for="{field_id}">', body)  # keyboard/screen-reader labelling
        self.assertNotRegex(body, r'tabindex="[1-9]')
        self.assertIn('name="viewport"', body)
        self.assertEqual(re.search(r"<title>(.*?)</title>", body, re.S).group(1).strip(),
                         "SYN101 Week 1 — Serapis by Limitless Hub")

    def test_post_reflection_then_page_lists_it_with_correction_controls(self) -> None:
        client = self.client()
        response = client.post("/modules/SYN101/weeks/1/after-lecture", data={
            "covered": "Framing", "understood": "A\nB", "uncertainty": "Why?", "question": "What is bias?",
            "examples": "Census", "emphasis": "Terms", "assessment": "Essay mentioned", "notes": "Mine"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Action failed", response.text)
        record = self.record()
        entries = record["workflows"]["after_lecture"]["captures"][0]["entries"]
        self.assertEqual((entries["understood"], entries["covered"], entries["assessment_comments"]),
                         (["A", "B"], ["Framing"], ["Essay mentioned"]))
        body = client.get("/modules/SYN101/weeks/1").text
        self.assertIn("Student-reported", body)
        self.assertIn("Correct or update this entry", body)
        self.assertIn("/reflections/correct", body)
        self.assertIn("export/study-pack", body)
        self.assertIn("export/notebooklm", body)
        self.assertIn("From your reflections", body)

    def test_correction_route_round_trip(self) -> None:
        client = self.client()
        client.post("/modules/SYN101/weeks/1/after-lecture", data={"question": "What is bias?"})
        response = client.post("/modules/SYN101/weeks/1/reflections/correct", data={
            "entry_id": "capture-0001:questions:0", "action": "correct", "new_text": "What is sampling bias?",
            "reason": "typo"})
        self.assertNotIn("Action failed", response.text)
        self.assertIn("What is sampling bias?", response.text)
        self.assertIn("corrected", response.text)
        bad = client.post("/modules/SYN101/weeks/1/reflections/correct",
                          data={"entry_id": "capture-0004:questions:0", "action": "withdraw"})
        self.assertIn("Action failed", bad.text)
        self.assertEqual(client.post("/modules/NOPE/weeks/1/reflections/correct", data={}).status_code, 404)

    def test_downloads_are_attachments_built_from_the_current_record(self) -> None:
        client = self.client()
        self.assertEqual(client.get("/modules/SYN101/weeks/1/export/study-pack").status_code, 404)  # nothing yet
        client.post("/modules/SYN101/weeks/1/after-lecture", data={"question": "First question?"})
        before = sorted(p.name for p in self.record_path().parent.iterdir())
        mtimes = {p: p.stat().st_mtime_ns for p in self.record_path().parent.iterdir()}

        docx = client.get("/modules/SYN101/weeks/1/export/study-pack")
        self.assertEqual(docx.status_code, 200)
        self.assertEqual(docx.headers["content-type"],
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(docx.headers["content-disposition"], 'attachment; filename="SYN101-Week-01-Study-Pack.docx"')
        self.assertEqual(docx.headers["x-content-type-options"], "nosniff")
        self.assertEqual(docx.headers["cache-control"], "no-store")
        with ZipFile(io.BytesIO(docx.content)) as archive:
            self.assertIn("First question?", archive.read("word/document.xml").decode())

        md = client.get("/modules/SYN101/weeks/1/export/notebooklm")
        self.assertEqual(md.headers["content-type"], "text/markdown; charset=utf-8")
        self.assertEqual(md.headers["content-disposition"], 'attachment; filename="SYN101-Week-01-NotebookLM.md"')
        self.assertIn("First question?", md.text)

        # GET never writes: same files, same modification times.
        self.assertEqual(sorted(p.name for p in self.record_path().parent.iterdir()), before)
        self.assertEqual({p: p.stat().st_mtime_ns for p in self.record_path().parent.iterdir()}, mtimes)

        # A newer reflection appears in the next download without any explicit rebuild.
        client.post("/modules/SYN101/weeks/1/after-lecture", data={"question": "Second question?"})
        self.assertIn("Second question?", client.get("/modules/SYN101/weeks/1/export/notebooklm").text)

    def test_download_rejects_unknown_kinds_modules_weeks_and_foreign_hosts(self) -> None:
        client = self.client()
        client.post("/modules/SYN101/weeks/1/after-lecture", data={"notes": "x"})
        for path in ("/modules/SYN101/weeks/1/export/pdf", "/modules/SYN101/weeks/1/export/..%2Frecord",
                     "/modules/NOPE/weeks/1/export/study-pack", "/modules/SYN101/weeks/7/export/study-pack",
                     "/modules/SYN101/weeks/2/export/study-pack"):
            self.assertEqual(client.get(path).status_code, 404, path)
        hostile = TestClient(client.app, base_url="http://evil.example")
        self.assertNotEqual(hostile.get("/modules/SYN101/weeks/1/export/study-pack").status_code, 200)

    def test_exports_are_not_importable_as_materials(self) -> None:
        from university_jarvis import hub_web
        self.assertEqual(hub_web._UPLOAD_SUFFIXES, (".pdf", ".pptx"))  # .md/.docx exports can never be added as sources
        client = self.client()
        client.post("/modules/SYN101/weeks/1/after-lecture", data={"notes": "x"})
        md = client.get("/modules/SYN101/weeks/1/export/notebooklm").content
        response = client.post("/modules/SYN101/materials", data={"week": "1"},
                               files={"file": ("notebooklm.md", md, "text/markdown")})
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(any(s.get("locator", "").endswith(".md") for s in self.state.get("sources", [])))

    def test_reflecting_makes_no_provider_call(self) -> None:
        provider = S4.NoCallProvider()
        client = TestClient(create_app(state=self.state, ledger=new_ledger(), workspace_root=self.root,
                                       reasoning_provider=provider))
        client.post("/modules/SYN101/weeks/1/after-lecture", data={"question": "q"})
        client.post("/modules/SYN101/weeks/1/reflections/correct",
                    data={"entry_id": "capture-0001:questions:0", "action": "resolve"})
        client.get("/modules/SYN101/weeks/1/export/study-pack")
        client.get("/modules/SYN101/weeks/1/export/notebooklm")


class PreparingAfterReflecting(Base):
    def test_prepare_after_reflecting_keeps_reflections_and_fills_preparation(self) -> None:
        from university_jarvis.workspace import materialize_week_workspace
        import test_hub_actions as A
        from university_jarvis.reasoning import generate_prepare_brief

        self.reflect(questions=["Keep me?"])
        cache = self.tmp / "cache"
        generate_prepare_brief(A.prepare_context(), A.SeedProvider(), cache)
        with patch("university_jarvis.workspace.build_prepare_context", return_value=A.prepare_context()):
            materialize_week_workspace(self.state, "SYN101", 1, provider=A.SeedProvider(), cache_dir=cache,
                                       workspace_root=self.root)
        record = self.record()
        self.assertEqual(record["workflows"]["prepare_me"]["status"], "completed")
        self.assertTrue(record["workflows"]["prepare_me"]["result"])
        self.assertEqual(reflections.effective_values(record, "questions"), ["Keep me?"])


if __name__ == "__main__":
    unittest.main()


class EnvironmentAliases(unittest.TestCase):
    def test_serapis_names_win_and_legacy_jarvis_names_still_work(self) -> None:
        from university_jarvis.state import env_setting
        with patch.dict("os.environ", {"JARVIS_CACHE_DIR": "/old"}, clear=False):
            self.assertEqual(env_setting("CACHE_DIR"), "/old")
            with patch.dict("os.environ", {"SERAPIS_CACHE_DIR": "/new"}):
                self.assertEqual(env_setting("CACHE_DIR"), "/new")
