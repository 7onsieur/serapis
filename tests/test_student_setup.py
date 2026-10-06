from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.state import load_state
from university_jarvis.cli import main
from university_jarvis.student_setup import (
    add_module, edit_profile, existing_user_state_path, import_material, initialize_personal_state,
    material_capability, remove_assessment, remove_material, remove_module,
    reassign_material, replace_material, save_assessment, update_module,
)
from university_jarvis.hub_web import create_app
from fastapi.testclient import TestClient


class StudentSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.env = patch.dict(os.environ, {"SERAPIS_HOME": str(self.home)}, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_fresh_and_rerun_setup_are_separate_from_fictional_sample(self) -> None:
        sample = Path(__file__).parents[1] / "data" / "academic-state.json"
        original = sample.read_bytes()
        path = initialize_personal_state()
        self.assertEqual(path, self.home / "academic-state.json")
        self.assertEqual(load_state(path)["modules"], [])
        self.assertEqual(initialize_personal_state(), path)
        self.assertEqual(sample.read_bytes(), original)

    def test_custom_legacy_state_requires_explicit_copy_and_keeps_original(self) -> None:
        work = Path(self.tmp.name) / "legacy-project"
        (work / "data").mkdir(parents=True)
        sample = Path(__file__).parents[1] / "data" / "academic-state.json"
        legacy = json.loads(sample.read_text(encoding="utf-8"))
        legacy["dataset_kind"] = "personal"
        legacy["student"]["university"] = "Existing University"
        legacy_path = work / "data" / "academic-state.json"
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        original = legacy_path.read_bytes()
        with patch("pathlib.Path.cwd", return_value=work):
            self.assertEqual(existing_user_state_path(), legacy_path)
            personal = initialize_personal_state(copy_existing=True)
        self.assertEqual(load_state(personal)["student"]["university"], "Existing University")
        self.assertEqual(legacy_path.read_bytes(), original)

    def test_cli_setup_creates_personal_course_without_touching_sample(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout
        sample = Path(__file__).parents[1] / "data" / "academic-state.json"
        original = sample.read_bytes()
        answers = iter(["University", "BA Course", "BIO101", "Biology", "n", "n", "n"])
        with patch("builtins.input", side_effect=lambda _prompt="": next(answers)), redirect_stdout(StringIO()):
            self.assertEqual(main(["setup", "--no-open"]), 0)
        self.assertEqual(load_state()["modules"][0]["code"], "BIO101")
        self.assertEqual(sample.read_bytes(), original)

    def test_module_and_assessment_crud_preserve_safe_trust(self) -> None:
        initialize_personal_state()
        edit_profile(university="Test University", programme="BA Tests")
        state = add_module("BIO101", "Biology")
        state = save_assessment("BIO101", title="Essay", deadline="2027-04-02", weight_percent="40", requirements="Use sources\n1,500 words")
        assessment = state["modules"][0]["assessments"][0]
        self.assertEqual(assessment["fact_provenance"]["deadline"]["status"], "NEEDS_VERIFICATION")
        self.assertEqual(assessment["fact_provenance"]["requirements"]["status"], "NEEDS_VERIFICATION")
        assessment_id = assessment["id"]
        state = save_assessment("BIO101", assessment_id=assessment_id, title="Updated", deadline="", weight_percent="", requirements="")
        assessment = state["modules"][0]["assessments"][0]
        self.assertEqual(assessment["fact_provenance"]["deadline"]["status"], "UNKNOWN")
        state = update_module("BIO101", "Biological Science", new_code="BIO102")
        self.assertEqual(state["modules"][0]["fact_provenance"]["title"]["status"], "NEEDS_VERIFICATION")
        self.assertEqual(remove_assessment("BIO102", assessment_id)["modules"][0]["assessments"], [])
        self.assertEqual(remove_module("BIO102")["modules"], [])

    def test_material_import_collision_reassign_replace_and_remove(self) -> None:
        initialize_personal_state()
        add_module("BIO101", "Biology")
        add_module("CHEM101", "Chemistry")
        with tempfile.TemporaryDirectory() as srcdir:
            src = Path(srcdir) / "slides.pptx"
            src.write_bytes(b"fake-pptx")
            result = import_material("BIO101", src, week=1)
            sid = result["source"]["id"]
            self.assertIn("Text extraction", result["capability"])
            collision_dir = Path(srcdir) / "other"
            collision_dir.mkdir()
            collision = collision_dir / "slides.pptx"
            collision.write_bytes(b"different")
            imported2 = import_material("BIO101", collision)
            self.assertNotEqual(imported2["source"]["locator"], result["source"]["locator"])
            duplicate = import_material("BIO101", src, week=2)
            self.assertTrue(duplicate["duplicate"])
            reassign_material(sid, "CHEM101", 2)
            self.assertEqual(load_state()["sources"][0]["module_code"], "CHEM101")
            replacement = Path(srcdir) / "new.pptx"
            replacement.write_bytes(b"replacement")
            replaced = replace_material(sid, replacement)
            self.assertEqual(Path(replaced["source"]["locator"]).read_bytes(), b"replacement")
            remove_material(sid)
            self.assertNotIn(sid, [s["id"] for s in load_state()["sources"]])

    def test_unsupported_format_and_duplicate_module_are_rejected(self) -> None:
        initialize_personal_state()
        add_module("BIO101", "Biology")
        with self.assertRaisesRegex(Exception, "already exists"):
            add_module("bio101", "Duplicate")
        with self.assertRaisesRegex(Exception, "PDF and PowerPoint"):
            material_capability(Path("notes.docx"))
        with patch("university_jarvis.student_setup.sys.platform", "linux"):
            self.assertIn("stored", material_capability(Path("notes.pdf")))

    def test_failed_material_state_write_rolls_back_copied_file(self) -> None:
        initialize_personal_state()
        add_module("BIO101", "Biology")
        with tempfile.TemporaryDirectory() as srcdir:
            src = Path(srcdir) / "deck.pptx"
            src.write_bytes(b"synthetic")
            with patch("university_jarvis.student_setup._save", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    import_material("BIO101", src)
        self.assertEqual(list((self.home / "materials" / "BIO101").glob("*")), [])

    def test_hub_setup_material_and_assessment_actions_are_local(self) -> None:
        initialize_personal_state()
        def no_ai(*_args, **_kwargs):
            raise AssertionError("ordinary Hub use invoked AI")
        client = TestClient(create_app(reasoning_provider=no_ai))
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.post("/modules", data={"code": "BIO101", "title": "Biology"}, follow_redirects=False).status_code, 303)
        page = client.get("/modules/BIO101")
        self.assertIn("Add material", page.text)
        response = client.post("/modules/BIO101/assessments", data={"title": "Essay", "deadline": "2027-05-02", "weight": "50", "requirements": "Use sources"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        state = load_state()
        assessment = state["modules"][0]["assessments"][0]
        self.assertEqual(assessment["fact_provenance"]["deadline"]["status"], "NEEDS_VERIFICATION")
        class FakeUpload:
            filename = "lecture.pptx"
            async def read(self): return b"synthetic bytes"
        async def fake_form(_request): return {"week": "1", "file": FakeUpload()}
        with patch("starlette.requests.Request.form", fake_form):
            upload = client.post("/modules/BIO101/materials", content=b"synthetic", headers={"content-type": "multipart/form-data; boundary=x"}, follow_redirects=False)
        self.assertEqual(upload.status_code, 303)
        self.assertEqual(client.get("/").status_code, 200)
