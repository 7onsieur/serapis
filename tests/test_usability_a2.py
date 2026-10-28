"""A2 usability: TBC deadlines, form recovery, material categories and brief links.

Server-side and TestClient coverage only; real-browser checks live in tests/browser.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from university_jarvis.hub_web import create_app
from university_jarvis.state import StateError, load_state, save_state
from university_jarvis.student_setup import (
    add_module, import_material, initialize_personal_state, reassign_material,
    remove_assessment, remove_material, replace_material, save_assessment, set_material_details,
)


class A2Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.env = patch.dict(os.environ, {"SERAPIS_HOME": str(self.home)}, clear=False)
        self.env.start()
        initialize_personal_state()
        add_module("BIO101", "Biology")
        add_module("CHEM101", "Chemistry")
        self.file = Path(self.tmp.name) / "brief.pptx"
        self.file.write_bytes(b"synthetic brief")

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def assessments(self, code: str = "BIO101") -> list[dict]:
        return next(m for m in load_state()["modules"] if m["code"] == code)["assessments"]

    def source(self, sid: str) -> dict:
        return next(s for s in load_state()["sources"] if s["id"] == sid)


class DeadlineStateTests(A2Base):
    def test_blank_tbc_and_date_states(self) -> None:
        save_assessment("BIO101", title="Blank")
        save_assessment("BIO101", title="Pending", deadline="TBA")
        save_assessment("BIO101", title="Pending2", deadline=" to be confirmed ")
        save_assessment("BIO101", title="Flag", deadline_tbc=True)
        save_assessment("BIO101", title="Dated", deadline="2027-03-01")
        blank, tba, tbc_words, flag, dated = self.assessments()
        self.assertEqual((blank["deadline"], blank["deadline_status"]), (None, None))
        for record in (tba, tbc_words, flag):
            self.assertEqual((record["deadline"], record["deadline_status"]), (None, "TBC"))
            self.assertEqual(record["fact_provenance"]["deadline"]["status"], "UNKNOWN")
        self.assertEqual((dated["deadline"], dated["deadline_status"]), ("2027-03-01", "unverified"))
        self.assertEqual(dated["fact_provenance"]["deadline"]["status"], "NEEDS_VERIFICATION")

    def test_switching_between_date_and_tbc(self) -> None:
        save_assessment("BIO101", title="Essay", deadline="2027-03-01")
        aid = self.assessments()[0]["id"]
        save_assessment("BIO101", assessment_id=aid, title="Essay", deadline_tbc=True)
        self.assertEqual((self.assessments()[0]["deadline"], self.assessments()[0]["deadline_status"]), (None, "TBC"))
        save_assessment("BIO101", assessment_id=aid, title="Essay", deadline="2027-04-02")
        self.assertEqual((self.assessments()[0]["deadline"], self.assessments()[0]["deadline_status"]), ("2027-04-02", "unverified"))

    def test_contradictory_and_invalid_values_rejected_without_change(self) -> None:
        save_assessment("BIO101", title="Essay", deadline="2027-03-01", weight_percent="20", requirements="a\nb")
        before = (self.home / "academic-state.json").read_bytes()
        aid = self.assessments()[0]["id"]
        for kwargs in ({"deadline": "2027-04-01", "deadline_tbc": True}, {"deadline": "soon"}, {"deadline": "2027-13-01"}, {"weight_percent": "150"}):
            with self.assertRaises(StateError):
                save_assessment("BIO101", assessment_id=aid, title="Changed", **kwargs)
        self.assertEqual((self.home / "academic-state.json").read_bytes(), before)

    def test_tbc_never_becomes_confirmed_and_old_records_load(self) -> None:
        state = load_state()
        legacy = {"id": "assessment-old", "category": "ASSESSMENT", "title": "Old", "deadline": "2027-01-01", "deadline_status": "unverified", "weight_percent": None, "requirements": None}
        state["modules"][0]["assessments"].append(legacy)
        save_state(state, self.home / "academic-state.json")
        self.assertEqual(self.assessments()[0]["id"], "assessment-old")
        save_assessment("BIO101", title="TBC one", deadline="TBC")
        self.assertNotEqual(self.assessments()[1]["fact_provenance"]["deadline"]["status"], "CONFIRMED")


class ProvenancePreservationTests(A2Base):
    def confirmed_assessment(self) -> str:
        """An assessment whose every fact is CONFIRMED by evidence from a (synthetic) source."""
        save_assessment("BIO101", title="Essay", deadline="2027-03-01", weight_percent="40", requirements="Use sources\nCite")
        sid = import_material("BIO101", self.file)["source"]["id"]
        state = load_state()
        state["sources"][0]["source_class"] = "UNIVERSITY_MATERIAL"  # a legacy/verified source: the only kind that may confirm
        record = state["modules"][0]["assessments"][0]
        for field in ("title", "deadline", "deadline_status", "weight_percent", "requirements"):
            record["fact_provenance"][field] = {"status": "CONFIRMED", "evidence": [{"source_id": sid, "location": "p1"}]}
        save_state(state, self.home / "academic-state.json")
        return record["id"]

    def prov(self, field: str) -> dict:
        return self.assessments()[0]["fact_provenance"][field]

    def edit(self, aid: str, **overrides) -> None:
        values = {"title": "Essay", "deadline": "2027-03-01", "weight_percent": "40", "requirements": "Use sources\nCite"}
        values.update(overrides)
        save_assessment("BIO101", assessment_id=aid, **values)

    def test_noop_save_keeps_all_confirmation_and_evidence(self) -> None:
        aid = self.confirmed_assessment()
        before = copy.deepcopy(self.assessments()[0])
        self.edit(aid)
        self.assertEqual(self.assessments()[0], before)

    def test_only_changed_fields_are_downgraded(self) -> None:
        aid = self.confirmed_assessment()
        self.edit(aid, weight_percent="50")
        self.assertEqual(self.prov("weight_percent"), {"status": "NEEDS_VERIFICATION", "evidence": []})
        for field in ("title", "deadline", "deadline_status", "requirements"):
            self.assertEqual(self.prov(field)["status"], "CONFIRMED", field)
            self.assertTrue(self.prov(field)["evidence"], field)

    def test_each_field_change_drops_only_its_own_confirmation(self) -> None:
        for field, change in (("title", {"title": "Essay 2"}), ("requirements", {"requirements": "Different"}),
                              ("deadline", {"deadline": "2027-04-04"}), ("weight_percent", {"weight_percent": "41"})):
            with self.subTest(field=field):
                self.tearDown(); self.setUp()
                aid = self.confirmed_assessment()
                self.edit(aid, **change)
                self.assertEqual(self.prov(field)["status"], "NEEDS_VERIFICATION")
                self.assertEqual(self.prov(field)["evidence"], [])

    def test_equivalent_input_forms_count_as_unchanged(self) -> None:
        aid = self.confirmed_assessment()
        self.edit(aid, title="  Essay  ", weight_percent="40.0", requirements="Use sources\n\n  Cite  \n")
        self.assertEqual({f: self.prov(f)["status"] for f in ("title", "weight_percent", "requirements")}, {"title": "CONFIRMED", "weight_percent": "CONFIRMED", "requirements": "CONFIRMED"})

    def test_tbc_transitions(self) -> None:
        aid = self.confirmed_assessment()
        save_assessment("BIO101", assessment_id=aid, title="Essay", weight_percent="40", requirements="Use sources\nCite", deadline_tbc=True)
        record = self.assessments()[0]
        self.assertEqual((record["deadline"], record["deadline_status"]), (None, "TBC"))
        self.assertEqual(record["fact_provenance"]["deadline"], {"status": "UNKNOWN", "evidence": []})
        self.assertEqual(record["fact_provenance"]["deadline_status"], {"status": "NEEDS_VERIFICATION", "evidence": []})
        self.assertEqual(record["fact_provenance"]["title"]["status"], "CONFIRMED")
        save_assessment("BIO101", assessment_id=aid, title="Essay", weight_percent="40", requirements="Use sources\nCite", deadline_tbc=True)  # TBC -> TBC no-op
        self.assertEqual(self.assessments()[0], record)
        self.edit(aid, deadline="")  # TBC -> blank
        self.assertEqual((self.assessments()[0]["deadline"], self.assessments()[0]["deadline_status"]), (None, None))
        self.assertEqual(self.prov("deadline_status"), {"status": "UNKNOWN", "evidence": []})

    def test_same_date_keeps_existing_status_and_never_upgrades(self) -> None:
        aid = self.confirmed_assessment()
        state = load_state()
        state["modules"][0]["assessments"][0]["deadline_status"] = "confirmed"
        save_state(state, self.home / "academic-state.json")
        self.edit(aid)
        self.assertEqual(self.assessments()[0]["deadline_status"], "confirmed")
        aid2 = save_assessment("BIO101", title="Other", deadline="2027-05-05") and self.assessments()[1]["id"]
        save_assessment("BIO101", assessment_id=aid2, title="Other", deadline="2027-05-06")
        self.assertEqual(self.assessments()[1]["fact_provenance"]["deadline"]["status"], "NEEDS_VERIFICATION")

    def test_legacy_record_without_provenance_gets_it(self) -> None:
        state = load_state()
        state["modules"][0]["assessments"].append({"id": "assessment-old", "category": "ASSESSMENT", "title": "Old", "deadline": None, "deadline_status": None, "weight_percent": None, "requirements": None})
        save_state(state, self.home / "academic-state.json")
        save_assessment("BIO101", assessment_id="assessment-old", title="Old", weight_percent="10")
        record = self.assessments()[0]
        self.assertEqual(record["fact_provenance"]["weight_percent"]["status"], "NEEDS_VERIFICATION")
        self.assertEqual(record["fact_provenance"]["title"]["status"], "NEEDS_VERIFICATION")


class SourceAuthorityTests(A2Base):
    def confirm_with(self, source_id: str) -> dict:
        save_assessment("BIO101", title="Essay", deadline="2027-03-01")
        state = load_state()
        state["modules"][0]["assessments"][0]["fact_provenance"]["deadline"] = {"status": "CONFIRMED", "evidence": [{"source_id": source_id}]}
        return state

    def test_new_uploads_are_student_entered_and_cannot_confirm(self) -> None:
        source = import_material("BIO101", self.file, material_kind="assessment_brief")["source"]
        self.assertEqual(source["source_class"], "STUDENT_ENTERED")
        with self.assertRaisesRegex(StateError, "requires university or explicitly reconciled LMS evidence"):
            from university_jarvis.state import _validate_state, normalize_academic_truth
            _validate_state(normalize_academic_truth(self.confirm_with(source["id"])))

    def test_legacy_university_material_still_confirms_and_is_not_reclassified(self) -> None:
        sid = import_material("BIO101", self.file)["source"]["id"]
        state = self.confirm_with(sid)
        state["sources"][0]["source_class"] = "UNIVERSITY_MATERIAL"  # historical record
        save_state(state, self.home / "academic-state.json")
        self.assertEqual(self.source(sid)["source_class"], "UNIVERSITY_MATERIAL")
        # Ordinary operations leave the legacy class alone.
        set_material_details(sid, material_kind="assessment_brief")
        replacement = Path(self.tmp.name) / "v2.pptx"
        replacement.write_bytes(b"v2")
        replace_material(sid, replacement)
        reassign_material(sid, "BIO101", 2)
        import_material("BIO101", replacement, material_kind="reading")
        self.assertEqual(self.source(sid)["source_class"], "UNIVERSITY_MATERIAL")

    def test_no_operation_changes_a_new_uploads_authority(self) -> None:
        save_assessment("BIO101", title="Essay")
        aid = self.assessments()[0]["id"]
        sid = import_material("BIO101", self.file)["source"]["id"]
        set_material_details(sid, material_kind="assessment_brief", assessment_id=aid)
        import_material("BIO101", self.file, material_kind="lecture")  # duplicate
        replacement = Path(self.tmp.name) / "v2.pptx"
        replacement.write_bytes(b"v2")
        replace_material(sid, replacement)
        reassign_material(sid, "CHEM101", 1)
        self.assertEqual(self.source(sid)["source_class"], "STUDENT_ENTERED")

    def test_ai_context_describes_student_files_accurately(self) -> None:
        from university_jarvis.reasoning import STUDENT_SOURCE_NOTE, build_reasoning_context
        import university_jarvis.reasoning as reasoning
        sources = [{"id": "s1", "title": "Mine", "source_class": "STUDENT_ENTERED"}, {"id": "s2", "title": "Official", "source_class": "UNIVERSITY_MATERIAL"}]
        described = [reasoning._source_for_model(s, ("id", "title", "source_class")) for s in sources]
        self.assertEqual(described[0]["authority_note"], STUDENT_SOURCE_NOTE)
        self.assertNotIn("authority_note", described[1])
        self.assertIn("not verified", STUDENT_SOURCE_NOTE)

    def test_uploaded_material_stays_retrievable_for_study(self) -> None:
        import io, zipfile
        from university_jarvis.state import load_state as load
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>"); z.writestr("ppt/presentation.xml", "<p/>")
        deck = Path(self.tmp.name) / "deck.pptx"
        deck.write_bytes(buf.getvalue())
        sid = import_material("BIO101", deck, week=1, material_kind="lecture")["source"]["id"]
        state = load()
        source = next(s for s in state["sources"] if s["id"] == sid)
        week = next(w for w in state["modules"][0]["weeks"] if w["week"] == 1)
        self.assertIn(sid, week["source_ids"])  # week selection still lists it
        self.assertEqual((source["availability"], source["type"]), ("content_available", "course_material"))
        page = TestClient(create_app(reasoning_provider=lambda *a, **k: self.fail("no AI"))).get("/modules/BIO101/weeks/1")
        self.assertEqual(page.status_code, 200)


class MaterialTests(A2Base):
    def test_default_import_is_uncategorised_with_unchanged_authority(self) -> None:
        source = import_material("BIO101", self.file)["source"]
        self.assertNotIn("material_kind", source)
        self.assertNotIn("assessment_id", source)

    def test_kind_persists_and_does_not_change_authority(self) -> None:
        source = import_material("BIO101", self.file, material_kind="assessment_brief")["source"]
        stored = self.source(source["id"])
        self.assertEqual(stored["material_kind"], "assessment_brief")
        self.assertEqual(stored["source_class"], "STUDENT_ENTERED")
        self.assertEqual(stored["type"], "course_material")

    def test_invalid_kind_rejected(self) -> None:
        with self.assertRaises(StateError):
            import_material("BIO101", self.file, material_kind="exam")
        self.assertEqual(load_state()["sources"], [])

    def test_brief_link_rules(self) -> None:
        save_assessment("BIO101", title="Essay")
        save_assessment("BIO101", title="Lab report")
        save_assessment("CHEM101", title="Chem")
        essay, lab = [a["id"] for a in self.assessments()]
        chem = self.assessments("CHEM101")[0]["id"]
        sid = import_material("BIO101", self.file, material_kind="assessment_brief", assessment_id=essay)["source"]["id"]
        self.assertEqual(self.source(sid)["assessment_id"], essay)
        set_material_details(sid, material_kind="assessment_brief", assessment_id=lab)   # correct it
        self.assertEqual(self.source(sid)["assessment_id"], lab)
        with self.assertRaises(StateError):  # cross-module
            set_material_details(sid, material_kind="assessment_brief", assessment_id=chem)
        with self.assertRaises(StateError):  # unknown id
            set_material_details(sid, material_kind="assessment_brief", assessment_id="assessment-nope")
        with self.assertRaises(StateError):  # not a brief
            set_material_details(sid, material_kind="lecture", assessment_id=lab)
        self.assertEqual(self.source(sid)["assessment_id"], lab)
        set_material_details(sid, material_kind="assessment_brief", assessment_id="")  # clear
        self.assertNotIn("assessment_id", self.source(sid))
        set_material_details(sid, material_kind="")
        self.assertNotIn("material_kind", self.source(sid))

    def test_link_does_not_touch_assessment_truth(self) -> None:
        save_assessment("BIO101", title="Essay", requirements="Write 1000 words")
        before = copy.deepcopy(self.assessments()[0])
        aid = before["id"]
        import_material("BIO101", self.file, material_kind="assessment_brief", assessment_id=aid)
        self.assertEqual(self.assessments()[0], before)

    def test_removal_reassignment_and_replacement(self) -> None:
        save_assessment("BIO101", title="Essay")
        aid = self.assessments()[0]["id"]
        sid = import_material("BIO101", self.file, material_kind="assessment_brief", assessment_id=aid)["source"]["id"]
        replacement = Path(self.tmp.name) / "v2.pptx"
        replacement.write_bytes(b"v2")
        replace_material(sid, replacement)
        stored = self.source(sid)
        self.assertEqual((stored["material_kind"], stored["assessment_id"]), ("assessment_brief", aid))
        reassign_material(sid, "BIO101", 3)  # same module keeps link
        self.assertEqual(self.source(sid)["assessment_id"], aid)
        remove_assessment("BIO101", aid)  # file survives, link cleared
        stored = self.source(sid)
        self.assertNotIn("assessment_id", stored)
        self.assertEqual(stored["material_kind"], "assessment_brief")
        save_assessment("BIO101", title="Again")
        set_material_details(sid, material_kind="assessment_brief", assessment_id=self.assessments()[0]["id"])
        reassign_material(sid, "CHEM101", None)  # other module drops link, keeps kind
        stored = self.source(sid)
        self.assertNotIn("assessment_id", stored)
        self.assertEqual(stored["material_kind"], "assessment_brief")
        remove_material(sid)

    def test_duplicate_upload_applies_explicit_changes_and_keeps_omitted(self) -> None:
        save_assessment("BIO101", title="Essay")
        save_assessment("BIO101", title="Lab")
        essay, lab = [a["id"] for a in self.assessments()]
        first = import_material("BIO101", self.file, material_kind="assessment_brief", assessment_id=essay)
        sid = first["source"]["id"]
        locator = self.source(sid)["locator"]
        omitted = import_material("BIO101", self.file)  # nothing submitted: nothing changes
        self.assertTrue(omitted["duplicate"])
        self.assertEqual(omitted["metadata_changed"], [])
        self.assertEqual((self.source(sid)["material_kind"], self.source(sid)["assessment_id"]), ("assessment_brief", essay))
        moved = import_material("BIO101", self.file, material_kind="assessment_brief", assessment_id=lab)  # relink
        self.assertEqual(moved["metadata_changed"], ["assessment link"])
        self.assertEqual(self.source(sid)["assessment_id"], lab)
        link_only = import_material("BIO101", self.file, assessment_id=essay)  # existing brief, link only
        self.assertEqual(link_only["metadata_changed"], ["assessment link"])
        recat = import_material("BIO101", self.file, material_kind="reading")  # explicit reclassification drops the stale link
        self.assertEqual(recat["metadata_changed"], ["category"])
        stored = self.source(sid)
        self.assertEqual(stored["material_kind"], "reading")
        self.assertNotIn("assessment_id", stored)
        self.assertEqual((stored["id"], stored["locator"], stored["source_class"]), (sid, locator, "STUDENT_ENTERED"))
        self.assertEqual(len(load_state()["sources"]), 1)

    def test_duplicate_upload_with_invalid_metadata_changes_nothing(self) -> None:
        save_assessment("BIO101", title="Essay")
        save_assessment("CHEM101", title="Chem")
        essay = self.assessments()[0]["id"]
        chem = self.assessments("CHEM101")[0]["id"]
        sid = import_material("BIO101", self.file, material_kind="assessment_brief", assessment_id=essay)["source"]["id"]
        before = (self.home / "academic-state.json").read_bytes()
        for kwargs in ({"material_kind": "assessment_brief", "assessment_id": chem}, {"material_kind": "assessment_brief", "assessment_id": "assessment-nope"},
                       {"material_kind": "lecture", "assessment_id": essay}, {"material_kind": "exam"}):
            with self.assertRaises(StateError):
                import_material("BIO101", self.file, **kwargs)
        self.assertEqual((self.home / "academic-state.json").read_bytes(), before)
        self.assertEqual(self.source(sid)["assessment_id"], essay)

    def test_duplicate_with_category_fills_uncategorised_file(self) -> None:
        pid = import_material("BIO101", self.file)["source"]["id"]
        result = import_material("BIO101", self.file, material_kind="seminar")
        self.assertEqual(result["metadata_changed"], ["category"])
        self.assertEqual(self.source(pid)["material_kind"], "seminar")

    def test_hub_reports_duplicate_outcome_honestly(self) -> None:
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>"); z.writestr("ppt/presentation.xml", "<p/>")
        client = TestClient(create_app(reasoning_provider=lambda *a, **k: self.fail("no AI")))
        upload = lambda **data: client.post("/modules/BIO101/materials", files={"file": ("deck.pptx", buf.getvalue())}, data=data, follow_redirects=True)
        self.assertIn("Material added", upload(material_kind="reading").text)
        same = upload()
        self.assertNotIn("Material added", same.text)
        self.assertIn("already in your materials", same.text)
        self.assertIn("left as they were", same.text)
        changed = upload(material_kind="lecture")
        self.assertIn("Updated: category", changed.text)
        self.assertEqual(load_state()["sources"][0]["material_kind"], "lecture")
        bad = client.post("/modules/BIO101/materials", files={"file": ("deck.pptx", buf.getvalue())}, data={"material_kind": "exam"})
        self.assertEqual(bad.status_code, 400)

    def test_validator_rejects_tampered_state(self) -> None:
        save_assessment("BIO101", title="Essay")
        sid = import_material("BIO101", self.file)["source"]["id"]
        state = load_state()
        state["sources"][0]["assessment_id"] = self.assessments()[0]["id"]
        with self.assertRaises(StateError):
            from university_jarvis.student_setup import _validate_state
            _validate_state(state)
        state["sources"][0]["material_kind"] = "assessment_brief"
        state["sources"][0]["assessment_id"] = "assessment-nope"
        with self.assertRaises(StateError):
            _validate_state(state)


class HubFormTests(A2Base):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(create_app(reasoning_provider=lambda *a, **k: self.fail("no AI")))

    def test_failed_add_keeps_all_fields_and_saved_data(self) -> None:
        save_assessment("BIO101", title="Existing", deadline="2027-01-01")
        before = (self.home / "academic-state.json").read_bytes()
        r = self.client.post("/modules/BIO101/assessments", data={"title": "Lab <report>", "deadline": "next week", "weight": "30", "requirements": "line one\nline two"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Enter a date", r.text)
        self.assertIn('value="Lab &lt;report&gt;"', r.text)
        self.assertIn('value="30"', r.text)
        self.assertIn("line one\nline two", r.text)
        self.assertEqual((self.home / "academic-state.json").read_bytes(), before)
        r = self.client.post("/modules/BIO101/assessments", data={"title": "Lab report", "deadline": "2027-02-02", "weight": "30", "requirements": "line one"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(len(self.assessments()), 2)

    def test_failed_edit_keeps_attempt_and_leaves_record(self) -> None:
        save_assessment("BIO101", title="Essay", deadline="2027-01-01", weight_percent="10")
        aid = self.assessments()[0]["id"]
        before = (self.home / "academic-state.json").read_bytes()
        r = self.client.post(f"/modules/BIO101/assessments/{aid}/edit", data={"title": "Essay v2", "deadline": "", "deadline_tbc": "1", "weight": "999", "requirements": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn('value="Essay v2"', r.text)
        self.assertIn("checked", r.text)
        self.assertIn("Weight must be from 0 to 100", r.text)
        self.assertEqual((self.home / "academic-state.json").read_bytes(), before)

    def test_tbc_checkbox_and_contradiction(self) -> None:
        r = self.client.post("/modules/BIO101/assessments", data={"title": "Exam", "deadline_tbc": "1"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.assessments()[0]["deadline_status"], "TBC")
        page = self.client.get("/modules/BIO101").text
        self.assertIn('class="tag tbc"', page)
        r = self.client.post("/modules/BIO101/assessments", data={"title": "Bad", "deadline": "2027-01-01", "deadline_tbc": "1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not both", r.text)
        self.assertEqual(len(self.assessments()), 1)

    def test_material_category_and_brief_link_via_hub(self) -> None:
        save_assessment("BIO101", title="Essay")
        aid = self.assessments()[0]["id"]
        sid = import_material("BIO101", self.file)["source"]["id"]
        r = self.client.post(f"/materials/{sid}/details", data={"material_kind": "assessment_brief", "assessment_id": aid}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        page = self.client.get("/modules/BIO101").text
        self.assertIn("Assessment brief", page)
        self.assertIn("not verified or extracted", page)
        bad = self.client.post(f"/materials/{sid}/details", data={"material_kind": "lecture", "assessment_id": aid})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.source(sid)["material_kind"], "assessment_brief")
        self.assertEqual(self.source(sid)["source_class"], "STUDENT_ENTERED")

    def test_navigation_label_and_collapsed_module_edit(self) -> None:
        home = self.client.get("/").text
        self.assertIn("Blackboard check", home)
        check = self.client.get("/check").text
        self.assertIn("does not receive general university announcements", check)
        module = self.client.get("/modules/BIO101").text
        self.assertIn('<details class="section card" id="edit-module">', module)
        self.assertIn('href="#assessments"', module)
        import_material("BIO101", self.file)
        self.assertIn("Uncategorised", self.client.get("/modules/BIO101").text)

    def test_coach_page_shows_linked_brief_without_verifying(self) -> None:
        save_assessment("BIO101", title="Essay", requirements="Use sources")
        aid = self.assessments()[0]["id"]
        import_material("BIO101", self.file, material_kind="assessment_brief", assessment_id=aid)
        started = self.client.post(f"/modules/BIO101/assessments/{aid}/coach/start", data={"client_request_id": "r1"}, follow_redirects=True)
        self.assertEqual(started.status_code, 200)
        self.assertIn("Linked assessment brief", started.text)
        self.assertIn("brief.pptx", started.text)
        self.assertEqual(self.assessments()[0]["fact_provenance"]["requirements"]["status"], "NEEDS_VERIFICATION")


class CliRecoveryTests(A2Base):
    def test_cli_setup_reprompts_only_the_bad_field(self) -> None:
        from university_jarvis.cli import main
        answers = iter(["", "", "ENG101", "English", "y", "Essay", "not a date", "40", "Use sources", "",
                        "2027-05-01", "n", "n"])
        with patch("builtins.input", lambda *_: next(answers)), patch("builtins.print"):
            main(["setup", "--no-open"])
        record = self.assessments("ENG101")[0]
        self.assertEqual((record["title"], record["deadline"], record["weight_percent"], record["requirements"]), ("Essay", "2027-05-01", 40.0, ["Use sources"]))


if __name__ == "__main__":
    unittest.main()
