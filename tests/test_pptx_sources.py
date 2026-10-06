"""Milestone 7: stdlib-only PPTX source-format extraction.

All fixtures here are small synthetic OOXML zips built in a temp directory --
never the real SYN102 deck, which stays untouched in ``sources/``.
"""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.sources import (
    SourceError,
    extract_pdf_text,
    extract_pptx_text,
    load_source_context,
)

_PRESENTATION_NS = (
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _presentation_xml(sld_id_to_rid: list[tuple[int, str]]) -> str:
    entries = "".join(
        f'<p:sldId id="{sld_id}" r:id="{r_id}"/>' for sld_id, r_id in sld_id_to_rid
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:presentation {_PRESENTATION_NS}><p:sldIdLst>{entries}</p:sldIdLst>'
        "</p:presentation>"
    )


def _rels_xml(rid_to_target: list[tuple[str, str]]) -> str:
    entries = "".join(
        f'<Relationship Id="{r_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
        f'Target="{target}"/>'
        for r_id, target in rid_to_target
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_RELS_NS}">{entries}</Relationships>'
    )


def _slide_xml(*, title: str | None, body_lines: list[str]) -> str:
    title_shape = ""
    if title is not None:
        title_shape = (
            "<p:sp><p:nvSpPr><p:nvPr><p:ph type=\"title\"/></p:nvPr></p:nvSpPr>"
            f'<p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>'
        )
    body_runs = "".join(f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in body_lines)
    body_shape = (
        "<p:sp><p:nvSpPr><p:nvPr/></p:nvSpPr>"
        f"<p:txBody>{body_runs}</p:txBody></p:sp>"
        if body_lines
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        f"<p:cSld><p:spTree>{title_shape}{body_shape}</p:spTree></p:cSld></p:sld>"
    )


def _build_pptx(
    path: Path,
    *,
    sld_id_to_rid: list[tuple[int, str]],
    rid_to_target: list[tuple[str, str]],
    slides_by_filename: dict[str, str],
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/presentation.xml", _presentation_xml(sld_id_to_rid))
        archive.writestr("ppt/_rels/presentation.xml.rels", _rels_xml(rid_to_target))
        for filename, xml in slides_by_filename.items():
            archive.writestr(f"ppt/slides/{filename}", xml)


class PptxExtractionTests(unittest.TestCase):
    def test_visual_order_follows_relationships_not_filename(self) -> None:
        # Filenames run 1, 2; presentation/rels deliberately list slide2 first.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.pptx"
            _build_pptx(
                path,
                sld_id_to_rid=[(256, "rId2"), (257, "rId3")],
                rid_to_target=[
                    ("rId2", "slides/slide2.xml"),
                    ("rId3", "slides/slide1.xml"),
                ],
                slides_by_filename={
                    "slide1.xml": _slide_xml(title=None, body_lines=["First filename, second visually"]),
                    "slide2.xml": _slide_xml(title=None, body_lines=["Second filename, first visually"]),
                },
            )
            extracted = extract_pptx_text(path)

        self.assertEqual(extracted["slide_count"], 2)
        self.assertIn("Second filename, first visually", extracted["slides"][0]["text"])
        self.assertIn("First filename, second visually", extracted["slides"][1]["text"])

    def test_slide_boundaries_and_numbers_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.pptx"
            _build_pptx(
                path,
                sld_id_to_rid=[(1, "rId1"), (2, "rId2"), (3, "rId3")],
                rid_to_target=[
                    ("rId1", "slides/slide1.xml"),
                    ("rId2", "slides/slide2.xml"),
                    ("rId3", "slides/slide3.xml"),
                ],
                slides_by_filename={
                    "slide1.xml": _slide_xml(title=None, body_lines=["Alpha content"]),
                    "slide2.xml": _slide_xml(title=None, body_lines=["Beta content"]),
                    "slide3.xml": _slide_xml(title=None, body_lines=["Gamma content"]),
                },
            )
            extracted = extract_pptx_text(path)

        self.assertEqual([slide["slide_number"] for slide in extracted["slides"]], [1, 2, 3])
        self.assertIn("Alpha content", extracted["slides"][0]["text"])
        self.assertIn("Beta content", extracted["slides"][1]["text"])
        self.assertIn("Gamma content", extracted["slides"][2]["text"])
        self.assertNotIn("Beta", extracted["slides"][0]["text"])

    def test_slide_title_preserved_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.pptx"
            _build_pptx(
                path,
                sld_id_to_rid=[(1, "rId1")],
                rid_to_target=[("rId1", "slides/slide1.xml")],
                slides_by_filename={
                    "slide1.xml": _slide_xml(
                        title="Module Introduction", body_lines=["Some body content"]
                    ),
                },
            )
            extracted = extract_pptx_text(path)

        self.assertEqual(extracted["slides"][0]["title"], "Module Introduction")

    def test_title_absence_handled_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.pptx"
            _build_pptx(
                path,
                sld_id_to_rid=[(1, "rId1")],
                rid_to_target=[("rId1", "slides/slide1.xml")],
                slides_by_filename={
                    "slide1.xml": _slide_xml(title=None, body_lines=["Body only, no title shape"]),
                },
            )
            extracted = extract_pptx_text(path)

        self.assertIsNone(extracted["slides"][0]["title"])
        self.assertIn("Body only, no title shape", extracted["slides"][0]["text"])

    def test_zero_text_deck_raises_source_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.pptx"
            _build_pptx(
                path,
                sld_id_to_rid=[(1, "rId1"), (2, "rId2")],
                rid_to_target=[
                    ("rId1", "slides/slide1.xml"),
                    ("rId2", "slides/slide2.xml"),
                ],
                slides_by_filename={
                    "slide1.xml": _slide_xml(title=None, body_lines=[]),
                    "slide2.xml": _slide_xml(title=None, body_lines=[]),
                },
            )
            with self.assertRaisesRegex(
                SourceError, "PPTX contains no directly extractable text"
            ):
                extract_pptx_text(path)

    def test_malformed_pptx_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.pptx"
            path.write_bytes(b"not actually a zip archive")
            with self.assertRaisesRegex(SourceError, "PPTX extraction failed"):
                extract_pptx_text(path)

    def test_missing_presentation_parts_fail_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.pptx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", _slide_xml(title=None, body_lines=["x"]))
            with self.assertRaisesRegex(
                SourceError, "PPTX is missing required presentation parts"
            ):
                extract_pptx_text(path)

    def test_missing_file_reports_not_found(self) -> None:
        with self.assertRaisesRegex(SourceError, "Source file not found"):
            extract_pptx_text(Path("/nonexistent/deck.pptx"))


class PdfRegressionTests(unittest.TestCase):
    def test_synthetic_pdf_extraction_works(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        extracted = extract_pdf_text(
            project_root / "sources" / "SYN101" / "week-01" / "example-week-1.pdf"
        )
        self.assertEqual(extracted["page_count"], 1)
        self.assertGreater(sum(len(page) for page in extracted["pages"]), 100)
        self.assertEqual(extracted["method"], "macos_pdfkit_direct_text")


class LoadSourceContextDispatchTests(unittest.TestCase):
    def _pptx_source(self, path: Path) -> dict[str, Any]:
        return {
            "id": "synthetic-pptx-source",
            "type": "lecture_pptx",
            "title": "Synthetic Lecture Deck",
            "availability": "content_available",
            "locator": str(path),
        }

    def test_pptx_dispatch_builds_bounded_context_with_titles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.pptx"
            _build_pptx(
                path,
                sld_id_to_rid=[(1, "rId1"), (2, "rId2")],
                rid_to_target=[
                    ("rId1", "slides/slide1.xml"),
                    ("rId2", "slides/slide2.xml"),
                ],
                slides_by_filename={
                    "slide1.xml": _slide_xml(title="Intro", body_lines=["Welcome content"]),
                    "slide2.xml": _slide_xml(title=None, body_lines=["Second slide content"]),
                },
            )
            extraction, bounded_context = load_source_context(self._pptx_source(path))

        self.assertEqual(extraction["method"], "ooxml_pptx_direct_text")
        self.assertEqual(extraction["slide_count"], 2)
        self.assertEqual(len(extraction["fingerprint"]["value"]), 64)
        excerpts = bounded_context["excerpts"]
        self.assertEqual(len(excerpts), 2)
        self.assertEqual(excerpts[0]["pdf_page"], 1)
        self.assertEqual(excerpts[0]["title"], "Intro")
        self.assertIn("Welcome content", excerpts[0]["text"])
        self.assertEqual(excerpts[1]["title"], None)
        self.assertIn("Second slide content", excerpts[1]["text"])

    def test_unsupported_extension_still_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.docx"
            path.write_text("irrelevant", encoding="utf-8")
            source = {
                "id": "unsupported-source",
                "type": "lecture_docx",
                "title": "Unsupported",
                "availability": "content_available",
                "locator": str(path),
            }
            with self.assertRaisesRegex(SourceError, "Unsupported source format"):
                load_source_context(source)


if __name__ == "__main__":
    unittest.main()
