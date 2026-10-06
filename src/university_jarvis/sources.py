"""Load local academic sources without storing their full text in state."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .state import StateError


class SourceError(StateError):
    """Raised when a configured academic source cannot provide usable text."""


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONTEXT_CHARACTER_LIMIT = 8_000

PDF_EXTRACTION_METHOD = "macos_pdfkit_direct_text"
PPTX_EXTRACTION_METHOD = "ooxml_pptx_direct_text"


def render_source_location(
    method: str | None, unit_number: int | None, *, title: str | None = None
) -> str:
    """Render a citation suffix (e.g. ``", Slide 3 (Intro)"``) for one bounded-context unit.

    ``method`` is a source's ``extraction.method`` (see ``extract_pdf_text``/
    ``extract_pptx_text``); it is the single place format-correctness for
    citations is decided, so no caller ever hardcodes "PDF p." for a unit that
    might be a PPTX slide. An unrecognised or missing method (including all
    pre-Milestone-7 recorded data, which predates ``extract_pptx_text`` and
    was always a PDF) falls back to the original PDF-page phrasing, so
    existing PDF citations render identically to before.
    """
    if unit_number is None:
        return ""
    if method == PPTX_EXTRACTION_METHOD:
        location = f"Slide {unit_number}"
        if title:
            location += f" ({title})"
        return f", {location}"
    return f", PDF p. {unit_number}"

_PDFKIT_SCRIPT = r"""
ObjC.import("Foundation");
ObjC.import("PDFKit");
const args = $.NSProcessInfo.processInfo.arguments.js.map(ObjC.unwrap);
const path = args[args.length - 1];
const document = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(path));
if (!document) {
  throw new Error("PDFKit could not open the PDF");
}
const pages = [];
for (let index = 0; index < document.pageCount; index++) {
  const value = ObjC.unwrap(document.pageAtIndex(index).string);
  pages.push(typeof value === "string" ? value : "");
}
JSON.stringify({page_count: document.pageCount, pages: pages});
"""


def resolve_source_path(locator: str) -> Path:
    """Resolve a source locator relative to the project root."""
    path = Path(locator)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _source_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf_text(path: Path) -> dict[str, Any]:
    """Extract page-level text through the macOS PDFKit already on the system."""
    if not path.is_file():
        raise SourceError(f"Source file not found: {path}")

    try:
        completed = subprocess.run(
            [
                "/usr/bin/osascript",
                "-l",
                "JavaScript",
                "-e",
                _PDFKIT_SCRIPT,
                "--",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError(f"PDF extraction failed for {path}: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or "unknown PDFKit error"
        raise SourceError(f"PDF extraction failed for {path}: {detail}")

    try:
        extracted = json.loads(completed.stdout)
        pages = extracted["pages"]
        page_count = int(extracted["page_count"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SourceError(f"PDF extraction returned invalid output for {path}") from exc

    if (
        not isinstance(pages, list)
        or not all(isinstance(page, str) for page in pages)
        or page_count != len(pages)
    ):
        raise SourceError(f"PDF extraction returned inconsistent pages for {path}")
    if not any(isinstance(page, str) and page.strip() for page in pages):
        raise SourceError(f"PDF contains no directly extractable text: {path}")

    return {
        "method": "macos_pdfkit_direct_text",
        "page_count": page_count,
        "pages": pages,
    }


_PPTX_NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
_PPTX_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PPTX_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_PPTX_TITLE_PLACEHOLDER_TYPES = ("title", "ctrTitle")


def _pptx_slide_order(archive: zipfile.ZipFile) -> list[str]:
    """Resolve true visual slide order from presentation.xml + its relationships.

    Slide part filenames (slideN.xml) are not a reliable order: PowerPoint
    never guarantees they match the presentation's ``sldIdLst`` sequence.
    """
    try:
        presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
        rels = ET.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
    except KeyError as exc:
        raise SourceError(f"PPTX is missing required presentation parts: {exc}") from exc
    except ET.ParseError as exc:
        raise SourceError(f"PPTX presentation XML is malformed: {exc}") from exc

    rel_targets = {
        relationship.get("Id"): relationship.get("Target")
        for relationship in rels.findall(f"{{{_PPTX_PKG_REL_NS}}}Relationship")
    }

    order: list[str] = []
    for sld_id in presentation.findall("p:sldIdLst/p:sldId", _PPTX_NS):
        r_id = sld_id.get(f"{{{_PPTX_R_NS}}}id")
        target = rel_targets.get(r_id)
        if not target:
            continue
        order.append(target if target.startswith("ppt/") else f"ppt/{target}")

    if not order:
        raise SourceError("PPTX has no slides listed in presentation.xml")
    return order


def _pptx_slide_text_and_title(xml_bytes: bytes, slide_path: str) -> tuple[str, str | None]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise SourceError(f"PPTX slide XML is malformed: {slide_path}: {exc}") from exc

    text = "".join(node.text or "" for node in root.iter(f"{{{_PPTX_NS['a']}}}t"))

    title: str | None = None
    for shape in root.iter("{%s}sp" % _PPTX_NS["p"]):
        placeholder = shape.find("p:nvSpPr/p:nvPr/p:ph", _PPTX_NS)
        if placeholder is None or placeholder.get("type") not in _PPTX_TITLE_PLACEHOLDER_TYPES:
            continue
        shape_text = "".join(
            node.text or "" for node in shape.iter(f"{{{_PPTX_NS['a']}}}t")
        ).strip()
        if shape_text:
            title = shape_text
            break

    return text, title


def extract_pptx_text(path: Path) -> dict[str, Any]:
    """Extract per-slide text in true visual order through stdlib zip/XML parsing."""
    if not path.is_file():
        raise SourceError(f"Source file not found: {path}")

    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourceError(f"PPTX extraction failed for {path}: {exc}") from exc

    with archive:
        slide_paths = _pptx_slide_order(archive)
        slides: list[dict[str, Any]] = []
        for slide_number, slide_path in enumerate(slide_paths, start=1):
            try:
                xml_bytes = archive.read(slide_path)
            except KeyError as exc:
                raise SourceError(
                    f"PPTX references missing slide part: {slide_path}"
                ) from exc
            text, title = _pptx_slide_text_and_title(xml_bytes, slide_path)
            slides.append({"slide_number": slide_number, "title": title, "text": text})

    if not any(slide["text"].strip() for slide in slides):
        raise SourceError(f"PPTX contains no directly extractable text: {path}")

    return {
        "method": "ooxml_pptx_direct_text",
        "slide_count": len(slides),
        "slides": slides,
    }


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _bounded_page_excerpts(
    pages: list[str], character_limit: int = SOURCE_CONTEXT_CHARACTER_LIMIT
) -> list[dict[str, Any]]:
    """Use the budget across all non-empty pages, retaining document order."""
    normalized = {
        page_number: text
        for page_number, raw in enumerate(pages, start=1)
        if (text := _normalize_text(raw))
    }
    allocations: dict[int, int] = {}
    remaining = list(normalized)
    remaining_budget = character_limit

    while remaining:
        quota, remainder = divmod(remaining_budget, len(remaining))
        completed_pages = [
            page_number
            for page_number in remaining
            if len(normalized[page_number]) <= quota
        ]
        if not completed_pages:
            for offset, page_number in enumerate(remaining):
                allocations[page_number] = quota + (1 if offset < remainder else 0)
            break
        for page_number in completed_pages:
            length = len(normalized[page_number])
            allocations[page_number] = length
            remaining_budget -= length
            remaining.remove(page_number)

    return [
        {
            "pdf_page": page_number,
            "text": text[: allocations[page_number]],
            "truncated": allocations[page_number] < len(text),
        }
        for page_number, text in normalized.items()
        if allocations.get(page_number, 0) > 0
    ]


def load_source_context(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load one configured source and return extraction metadata plus bounded text."""
    source_id = source.get("id", "unknown")
    if source.get("availability") != "content_available":
        raise SourceError(f"Source content is not available: {source_id}")
    locator = source.get("locator")
    if not locator:
        raise SourceError(f"Source has no local file locator: {source_id}")

    path = resolve_source_path(locator)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        extracted = extract_pdf_text(path)
        units = extracted.pop("pages")
        excerpts = _bounded_page_excerpts(units)
    elif suffix == ".pptx":
        extracted = extract_pptx_text(path)
        slides = extracted.pop("slides")
        units = [slide["text"] for slide in slides]
        excerpts = _bounded_page_excerpts(units)
        titles_by_slide = {slide["slide_number"]: slide["title"] for slide in slides}
        for excerpt in excerpts:
            excerpt["title"] = titles_by_slide.get(excerpt["pdf_page"])
    else:
        raise SourceError(f"Unsupported source format for {source_id}: {path.suffix}")

    extraction = {
        **extracted,
        "nonempty_page_count": sum(bool(unit.strip()) for unit in units),
        "character_count": sum(len(unit) for unit in units),
        "fingerprint": {
            "algorithm": "sha256",
            "value": _source_fingerprint(path),
        },
    }
    bounded_context = {
        "source_id": source_id,
        "source_type": source["type"],
        "title": source["title"],
        "academic_page_range": source.get("pages"),
        "selection": "ordered page coverage with leading excerpts",
        "character_limit": SOURCE_CONTEXT_CHARACTER_LIMIT,
        "character_count": sum(len(excerpt["text"]) for excerpt in excerpts),
        "excerpts": excerpts,
    }
    return extraction, bounded_context
