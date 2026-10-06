"""Milestone 7 follow-up: format-correct source-location citations.

Proves ``reasoning.py`` no longer mislabels a PPTX slide citation as a PDF
page, without changing the wire schema (``pdf_page`` stays the JSON-schema
key sent to/from the reasoning provider) or the default rendering behaviour
any existing caller/cache relies on.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.reasoning import (
    PreparationBrief,
    build_source_location_index,
    render_prepare_brief,
)
from university_jarvis.sources import (
    PDF_EXTRACTION_METHOD,
    PPTX_EXTRACTION_METHOD,
    render_source_location,
)


def _brief_citing(source_id: str, unit_number: int) -> PreparationBrief:
    section_names = (
        "week_overview",
        "before_class",
        "core_concepts",
        "examples_cases",
        "lecture_attention",
        "after_class_questions",
        "assessment_connections",
    )
    return PreparationBrief.from_dict(
        {
            section: [
                {
                    "text": f"Grounded content for {section}.",
                    "provenance": [{"source_id": source_id, "pdf_page": unit_number}],
                }
            ]
            for section in section_names
        }
    )


class RenderSourceLocationTests(unittest.TestCase):
    def test_pdf_method_renders_page(self) -> None:
        self.assertEqual(render_source_location(PDF_EXTRACTION_METHOD, 3), ", PDF p. 3")

    def test_pptx_method_renders_slide(self) -> None:
        self.assertEqual(render_source_location(PPTX_EXTRACTION_METHOD, 5), ", Slide 5")

    def test_pptx_method_with_title_renders_slide_and_title(self) -> None:
        self.assertEqual(
            render_source_location(PPTX_EXTRACTION_METHOD, 5, title="Module Introduction"),
            ", Slide 5 (Module Introduction)",
        )

    def test_pptx_without_title_renders_slide_only_no_pdf_wording(self) -> None:
        result = render_source_location(PPTX_EXTRACTION_METHOD, 5, title=None)
        self.assertEqual(result, ", Slide 5")
        self.assertNotIn("PDF", result)

    def test_unknown_or_missing_method_defaults_to_pdf_wording(self) -> None:
        """Pre-Milestone-7 recorded/cached data has no non-PDF method to compare against."""
        self.assertEqual(render_source_location(None, 3), ", PDF p. 3")
        self.assertEqual(render_source_location("some_future_method", 3), ", PDF p. 3")

    def test_no_unit_number_renders_nothing(self) -> None:
        self.assertEqual(render_source_location(PPTX_EXTRACTION_METHOD, None), "")


class BuildSourceLocationIndexTests(unittest.TestCase):
    def _context(self) -> dict:
        return {
            "sources": [
                {
                    "id": "syn101-w01-lecture-01-pdf",
                    "extraction": {"method": PDF_EXTRACTION_METHOD},
                },
                {
                    "id": "syn102-w01-lecture-01-pptx",
                    "extraction": {"method": PPTX_EXTRACTION_METHOD},
                },
            ],
            "source_contexts": [
                {
                    "source_id": "syn102-w01-lecture-01-pptx",
                    "excerpts": [
                        {"pdf_page": 1, "text": "...", "title": "Module Introduction"},
                        {"pdf_page": 2, "text": "...", "title": None},
                    ],
                },
            ],
        }

    def test_pdf_source_location_remains_page_based(self) -> None:
        brief = _brief_citing("syn101-w01-lecture-01-pdf", 3)
        index = build_source_location_index(self._context())
        rendered = render_prepare_brief(brief, index)
        self.assertIn("syn101-w01-lecture-01-pdf, PDF p. 3", rendered)
        self.assertNotIn("Slide", rendered)

    def test_pptx_source_location_is_slide_based(self) -> None:
        brief = _brief_citing("syn102-w01-lecture-01-pptx", 1)
        index = build_source_location_index(self._context())
        rendered = render_prepare_brief(brief, index)
        self.assertIn("syn102-w01-lecture-01-pptx, Slide 1 (Module Introduction)", rendered)
        self.assertNotIn("PDF p.", rendered)

    def test_pptx_slide_without_title_still_cites_slide_number(self) -> None:
        brief = _brief_citing("syn102-w01-lecture-01-pptx", 2)
        index = build_source_location_index(self._context())
        rendered = render_prepare_brief(brief, index)
        self.assertIn("syn102-w01-lecture-01-pptx, Slide 2]", rendered)
        self.assertNotIn("PDF p.", rendered)

    def test_no_pptx_output_ever_says_pdf_p(self) -> None:
        brief = _brief_citing("syn102-w01-lecture-01-pptx", 1)
        index = build_source_location_index(self._context())
        rendered = render_prepare_brief(brief, index)
        self.assertNotIn("PDF p.", rendered)

    def test_missing_location_index_preserves_original_pdf_wording(self) -> None:
        """No index passed (every existing caller/test before this milestone) -- unchanged."""
        brief = _brief_citing("syn101-w01-lecture-01-pdf", 3)
        rendered = render_prepare_brief(brief)
        self.assertIn("syn101-w01-lecture-01-pdf, PDF p. 3", rendered)

    def test_source_without_extraction_metadata_is_backward_compatible(self) -> None:
        """A context shaped like pre-Milestone-7 data (no extraction.method at all)."""
        context = {
            "sources": [{"id": "syn101-w01-lecture-01-pdf", "extraction": {}}],
            "source_contexts": [],
        }
        brief = _brief_citing("syn101-w01-lecture-01-pdf", 3)
        rendered = render_prepare_brief(brief, build_source_location_index(context))
        self.assertIn("syn101-w01-lecture-01-pdf, PDF p. 3", rendered)


if __name__ == "__main__":
    unittest.main()
