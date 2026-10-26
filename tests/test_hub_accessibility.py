"""Static accessibility and responsiveness checks on the Hub templates (no browser needed).

A real-browser pass (360px iframe measurement, keyboard order) was done separately and is recorded in
docs/pilot/PILOT_READINESS.md; these tests keep the findings from regressing."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "university_jarvis" / "hub_templates"


def sources():
    return {p.name: p.read_text(encoding="utf-8") for p in TEMPLATES.glob("*.html")}


class TemplateAccessibilityTests(unittest.TestCase):
    def test_every_textarea_has_an_accessible_name(self):
        for name, text in sources().items():
            for match in re.finditer(r"<textarea\b[^>]*>", text):
                tag = match.group(0)
                before = text[:match.start()]
                inside_label = before.rfind("<label") > before.rfind("</label>")
                with self.subTest(template=name, tag=tag[:60]):
                    self.assertTrue("aria-label" in tag or "aria-labelledby" in tag or inside_label or "id=" in tag, tag)

    def test_errors_are_announced_and_results_are_status_regions(self):
        for name, text in sources().items():
            for match in re.finditer(r'<div class="action-error"[^>]*>', text):
                with self.subTest(template=name):
                    self.assertIn('role="alert"', match.group(0))
            for match in re.finditer(r'<div class="action-result"[^>]*>', text):
                with self.subTest(template=name):
                    self.assertIn('role="status"', match.group(0))

    def test_no_positive_tabindex_and_no_click_handlers_on_non_controls(self):
        for name, text in sources().items():
            with self.subTest(template=name):
                self.assertNotRegex(text, r'tabindex="[1-9]')
                self.assertNotRegex(text, r"<(?:div|span|li|p)\b[^>]*\bonclick=")

    def test_students_never_see_internal_source_ids_in_templates(self):
        for name, text in sources().items():
            with self.subTest(template=name):
                self.assertNotRegex(text, r"\{\{\s*c\.source_id\s*\}\}")

    def test_tags_wrap_on_narrow_screens_and_the_page_has_skip_link_and_landmarks(self):
        base = sources()["base.html"]
        narrow = base[base.index("@media (max-width: 40rem)"):]
        self.assertIn(".tag { white-space: normal", narrow)
        self.assertIn("skip-link", base)
        self.assertIn("<main", base)
        self.assertIn(":focus-visible", base)
        self.assertIn("prefers-reduced-motion", base)
        self.assertIn('name="viewport"', base)

    def test_ai_buttons_on_the_week_page_are_distinct(self):
        week = sources()["week.html"]
        labels = re.findall(r'<button type="submit">([^<]+)</button>', week)
        ai = [label for label in labels if "AI" in label]
        self.assertEqual(len(ai), len(set(ai)), ai)
        self.assertNotIn("Generate with AI", week)
        self.assertNotIn("Cache-first", week)

    def test_action_outcomes_take_focus(self):
        self.assertIn("outcome.focus(", sources()["base.html"])
