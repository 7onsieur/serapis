"""BROWSER-002: assessment entry, TBC deadlines and recovery in a real browser."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from university_jarvis.state import load_state
from university_jarvis.student_setup import add_module, initialize_personal_state, save_assessment


@pytest.fixture
def workspace(hub):
    initialize_personal_state()
    add_module("SYN101", "Synthetic Studies")
    return hub


def assessments():
    return load_state()["modules"][0]["assessments"]


def test_add_reopen_and_tbc(page, workspace):
    page.goto("/modules/SYN101")
    form = page.locator("form[data-assessment-form]").last
    form.get_by_label("Title").fill("Essay")
    form.get_by_label("Deadline date").fill("2027-03-01")
    form.get_by_label("Weight %").fill("40")
    form.get_by_label("Requirements").fill("Use five sources")
    form.get_by_role("button", name="Add assessment").click()
    expect(page.get_by_role("cell", name="Essay")).to_be_visible()
    assert assessments()[0]["deadline"] == "2027-03-01"

    # Reopen the saved record via Edit (real reload).
    page.reload()
    page.get_by_text("Edit", exact=True).first.click()
    edit = page.locator("form[data-assessment-form]").first
    expect(edit.get_by_label("Deadline date")).to_have_value("2027-03-01")
    expect(edit.get_by_label("Weight %")).to_have_value(re.compile(r"^40(\.0)?$"))

    # Ticking TBC disables and clears the date; saving stores TBC without inventing a date.
    edit.get_by_label("Deadline not announced yet (TBC)").check()
    expect(edit.get_by_label("Deadline date")).to_be_disabled()
    expect(edit.get_by_label("Deadline date")).to_have_value("")
    edit.get_by_role("button", name="Save assessment").click()
    record = assessments()[0]
    assert (record["deadline"], record["deadline_status"]) == (None, "TBC")
    expect(page.locator(".tag.tbc").first).to_be_visible()

    # Switching back to a date re-enables the field.
    page.get_by_text("Edit", exact=True).first.click()
    edit = page.locator("form[data-assessment-form]").first
    expect(edit.get_by_label("Deadline not announced yet (TBC)")).to_be_checked()
    edit.get_by_label("Deadline not announced yet (TBC)").uncheck()
    expect(edit.get_by_label("Deadline date")).to_be_enabled()
    edit.get_by_label("Deadline date").fill("2027-05-06")
    edit.get_by_role("button", name="Save assessment").click()
    assert (assessments()[0]["deadline"], assessments()[0]["deadline_status"]) == ("2027-05-06", "unverified")


def test_server_validation_recovery_after_real_submit(page, workspace):
    """Out-of-range weight passes... only server-side: native validation is bypassed with novalidate,
    so this exercises the server error + preserved form through a real browser submit."""
    page.goto("/modules/SYN101")
    form = page.locator("form[data-assessment-form]").last
    form.evaluate("f => f.noValidate = true")
    form.get_by_label("Title").fill("Lab report")
    form.get_by_label("Deadline date").fill("2027-06-01")
    form.get_by_label("Weight %").fill("500")
    form.get_by_label("Requirements").fill("Line A\nLine B")
    form.get_by_role("button", name="Add assessment").click()
    expect(page.get_by_role("alert").first).to_contain_text("Weight must be from 0 to 100")
    fixed = page.locator("form[data-assessment-form]").last
    expect(fixed.get_by_label("Title")).to_have_value("Lab report")
    expect(fixed.get_by_label("Deadline date")).to_have_value("2027-06-01")
    expect(fixed.get_by_label("Requirements")).to_have_value("Line A\nLine B")
    assert assessments() == []
    fixed.get_by_label("Weight %").fill("25")
    fixed.get_by_role("button", name="Add assessment").click()
    assert assessments()[0]["weight_percent"] == 25.0


def test_failed_edit_leaves_saved_record_intact(page, workspace):
    save_assessment("SYN101", title="Exam", deadline="2027-01-10", weight_percent="60", requirements="Revise")
    before = assessments()[0]
    page.goto("/modules/SYN101")
    page.get_by_text("Edit", exact=True).first.click()
    edit = page.locator("form[data-assessment-form]").first
    edit.evaluate("f => f.noValidate = true")
    edit.get_by_label("Title").fill("Exam renamed")
    edit.get_by_label("Weight %").fill("-5")
    edit.get_by_role("button", name="Save assessment").click()
    expect(page.get_by_role("alert").first).to_contain_text("Weight must be from 0 to 100")
    expect(page.locator("form[data-assessment-form]").first.get_by_label("Title")).to_have_value("Exam renamed")
    assert assessments()[0] == before


def test_material_category_and_brief_link_form(page, workspace, tmp_path):
    save_assessment("SYN101", title="Essay")
    save_assessment("SYN101", title="Lab report")
    brief = tmp_path / "brief.pptx"
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/presentation.xml", "<p/>")
    brief.write_bytes(buf.getvalue())
    page.goto("/modules/SYN101")
    upload = page.locator("form[action$='/materials']")
    upload.get_by_label("Choose PDF or PowerPoint file").set_input_files(str(brief))
    upload.get_by_label("Type (optional)").select_option("assessment_brief")
    upload.get_by_label("Brief for assessment").select_option(label="Lab report")
    upload.get_by_role("button", name="Add material").click()
    expect(page.get_by_text("Material added")).to_be_visible()
    source = load_state()["sources"][0]
    lab = [a for a in assessments() if a["title"] == "Lab report"][0]["id"]
    assert (source["material_kind"], source["assessment_id"], source["source_class"]) == ("assessment_brief", lab, "STUDENT_ENTERED")
    expect(page.get_by_text("Brief for: Lab report")).to_be_visible()
    expect(page.get_by_text("not verified or extracted")).to_be_visible()
    page.reload()
    expect(page.get_by_text("Brief for: Lab report")).to_be_visible()


def test_keyboard_and_narrow_viewport(page, workspace):
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto("/modules/SYN101")
    summary = page.get_by_text("Edit module (rename or remove)")
    summary.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("button", name="Save module")).to_be_visible()
    tbc = page.locator("form[data-assessment-form]").last.get_by_label("Deadline not announced yet (TBC)")
    tbc.focus()
    page.keyboard.press("Space")
    expect(tbc).to_be_checked()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
