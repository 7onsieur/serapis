"""Persistent, deterministic academic workspace artefacts."""

from __future__ import annotations

import io
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .reasoning import (
    OBJECTIVE_INSTRUCTION_VERSION,
    PREPARATION_SCHEMA_VERSION,
    PREPARE_PROMPT_VERSION,
    TEACH_PROMPT_VERSION,
    TEACH_SCHEMA_VERSION,
    OpenAIReasoningProvider,
    PreparationResult,
    ReasoningProvider,
    TeachBrief,
    generate_teach_brief,
    load_cached_prepare_brief,
)
from .sources import PROJECT_ROOT, render_source_location
from .state import StateError, personal_data_dir
from .workflows import build_prepare_context, build_week_context


WORKSPACE_SCHEMA_VERSION = 4
LEARNING_CAPABILITIES = ("RECALL", "EXPLANATION", "APPLICATION")

_CAPTURE_FIELDS = (
    ("lecture_notes", "Lecture notes"),
    ("lecturer_emphasis", "Lecturer emphasis"),
    ("examples_cases", "Examples and cases discussed"),
    ("understood", "What I understood"),
    ("uncertainties", "What I did not understand"),
    ("questions", "Questions I still have"),
    ("assessment_comments", "Assessment comments"),
)


def _knowledge_classification() -> dict[str, dict[str, str]]:
    return {
        "source_grounded": {
            "location": "workflows.prepare_me.result",
            "meaning": "Claims derived from identified university sources.",
        },
        "student_reported": {
            "location": "workflows.after_lecture.captures",
            "meaning": "The student's report after the lecture; not proof that a claim appears in an official source.",
        },
        "generated_learning": {
            "location": "workflows.teach.interactions[].generated_learning",
            "meaning": "Generated teaching derived from official sources and student context; useful for learning but not canonical source evidence.",
        },
        "unknown_unverified": {
            "meaning": "Anything not established by an identified source or explicitly reported by the student remains unknown or unverified.",
        },
    }

_SECTION_TITLES = (
    ("week_overview", "Week overview"),
    ("before_class", "Before-class preparation"),
    ("core_concepts", "Core concepts"),
    ("examples_cases", "Important examples and cases"),
    ("lecture_attention", "What to pay attention to"),
    ("after_class_questions", "Questions to answer"),
    ("assessment_connections", "Assessment connections"),
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC = "http://purl.org/dc/elements/1.1/"
_DCTERMS = "http://purl.org/dc/terms/"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"

for prefix, namespace in (
    ("w", _W),
    ("r", _R),
    ("cp", _CP),
    ("dc", _DC),
    ("dcterms", _DCTERMS),
    ("xsi", _XSI),
):
    ET.register_namespace(prefix, namespace)


@dataclass(frozen=True)
class WorkspaceResult:
    record_path: Path
    study_pack_path: Path
    notebooklm_path: Path
    cache_status: str


@dataclass(frozen=True)
class CaptureResult:
    record_path: Path
    study_pack_path: Path
    notebooklm_path: Path
    capture_id: str
    captured_at: str


@dataclass(frozen=True)
class TeachResult:
    record_path: Path
    study_pack_path: Path
    notebooklm_path: Path
    teach_id: str
    taught_at: str
    topic: str
    brief: TeachBrief
    student_context: list[dict[str, Any]]
    cache_status: str


def default_workspace_root() -> Path:
    configured = os.environ.get("JARVIS_WORKSPACE_DIR")
    if configured:
        return Path(configured)
    legacy = PROJECT_ROOT / "workspace"
    if legacy.exists():
        return legacy
    return personal_data_dir() / "workspace"


def _safe_component(value: str) -> str:
    component = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    if not component:
        raise ValueError("Workspace path component is empty")
    return component


def _source_record(source: dict[str, Any]) -> dict[str, Any]:
    extraction = source["extraction"]
    return {
        key: value
        for key, value in (
            ("source_id", source["id"]),
            ("type", source["type"]),
            ("title", source["title"]),
            ("authors", source.get("authors")),
            ("academic_page_range", source.get("pages")),
            (
                "extraction",
                {
                    key: extraction[key]
                    for key in (
                        "method",
                        "page_count",
                        "slide_count",
                        "nonempty_page_count",
                        "character_count",
                        "fingerprint",
                    )
                    if key in extraction
                },
            ),
        )
        if value is not None
    }


def build_academic_record(
    context: dict[str, Any],
    result: PreparationResult,
    provider: ReasoningProvider,
) -> dict[str, Any]:
    """Build the canonical record from known state and one cached brief."""
    usage = result.usage.to_dict() if result.usage else None
    return {
        "workspace_schema_version": WORKSPACE_SCHEMA_VERSION,
        "record_type": "academic_week",
        "knowledge_classification": _knowledge_classification(),
        "module": dict(context["module"]),
        "week": {
            "number": context["week"]["number"],
            "date": context["week"].get("date"),
            "topic": context["week"].get("topic"),
            "declared_progress": context["week"].get("progress", "unknown"),
        },
        "sources": [_source_record(source) for source in context["sources"]],
        "workflows": {
            "prepare_me": {
                "status": "completed",
                "result": result.brief.to_dict(),
                "generation": {
                    "source": "matching_local_cache",
                    "cache_status": result.cache_status,
                    "cache_key": result.cache_key,
                    "prompt_version": PREPARE_PROMPT_VERSION,
                    "objective_instruction_version": OBJECTIVE_INSTRUCTION_VERSION,
                    "schema_version": PREPARATION_SCHEMA_VERSION,
                    "provider": provider.cache_identity(),
                    "usage": usage,
                },
            },
            "after_lecture": {"status": "not_recorded", "captures": []},
            "teach": {"status": "not_recorded", "interactions": []},
            "quiz": {"status": "not_recorded"},
            "revise": {"status": "not_recorded"},
        },
        "learning": {
            "notes": {"status": "not_recorded", "items": []},
            "flashcards": {
                "status": "not_generated",
                "generation_method": None,
                "items": [],
            },
            "quiz_history": {"status": "not_recorded", "attempts": []},
            "evidence": [],
            "misconceptions": {"status": "unknown", "items": []},
            "mastery": {"status": "unknown", "concepts": []},
            "revision_priorities": {"status": "unknown", "items": []},
            "unresolved_items": {"status": "none_recorded", "items": []},
        },
    }


def _qn(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def _xml_bytes(element: ET.Element) -> bytes:
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def _paragraph(
    parent: ET.Element,
    text: str = "",
    *,
    style: str | None = None,
    bullet: bool = False,
    page_break: bool = False,
) -> ET.Element:
    paragraph = ET.SubElement(parent, _qn(_W, "p"))
    properties = ET.SubElement(paragraph, _qn(_W, "pPr"))
    if style:
        ET.SubElement(properties, _qn(_W, "pStyle"), {_qn(_W, "val"): style})
    if bullet:
        numbering = ET.SubElement(properties, _qn(_W, "numPr"))
        ET.SubElement(numbering, _qn(_W, "ilvl"), {_qn(_W, "val"): "0"})
        ET.SubElement(numbering, _qn(_W, "numId"), {_qn(_W, "val"): "1"})
    run = ET.SubElement(paragraph, _qn(_W, "r"))
    if page_break:
        ET.SubElement(run, _qn(_W, "br"), {_qn(_W, "type"): "page"})
    elif text:
        node = ET.SubElement(run, _qn(_W, "t"))
        node.text = text
    return paragraph


def _citation_text(
    provenance: list[dict[str, Any]], source_by_id: dict[str, dict[str, Any]]
) -> str:
    citations = []
    for reference in provenance:
        source_id = reference["source_id"]
        source = source_by_id.get(source_id, {})
        label = source.get("title", source_id)
        method = (source.get("extraction") or {}).get("method")
        location = render_source_location(method, reference.get("pdf_page"))
        citations.append(f"{label} [{source_id}]{location}")
    return "Sources: " + "; ".join(citations)


def _dedupe_texts(values: list[str]) -> list[str]:
    """Keep the first useful occurrence without rewriting the canonical record."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = " ".join(value.split()).casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(value.strip())
    return result


def _captured_values(record: dict[str, Any], field: str) -> list[str]:
    values: list[str] = []
    captures = record.get("workflows", {}).get("after_lecture", {}).get("captures", [])
    for capture in captures:
        captured = capture.get("entries", {}).get(field, [])
        if field != "lecture_notes":
            values.extend(captured)
            continue
        # Labelled questions and uncertainties already have a dedicated open-items
        # section, so omit those lines from the notes surface to avoid duplication.
        for note in captured:
            for line in note.splitlines():
                cleaned = line.strip()
                if not cleaned:
                    continue
                if _extract_explicit_uncertainties([cleaned]) or _extract_explicit_questions([cleaned]):
                    continue
                values.append(cleaned)
    return _dedupe_texts(values)


def _open_learning_items(record: dict[str, Any]) -> list[dict[str, Any]]:
    items = record.get("learning", {}).get("unresolved_items", {}).get("items", [])
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if item.get("status") != "open":
            continue
        key = (item.get("kind", "item"), " ".join(item.get("text", "").split()).casefold())
        if key[1] and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _current_teach_interactions(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the latest interaction for each topic, in first-topic order."""
    interactions = record.get("workflows", {}).get("teach", {}).get("interactions", [])
    order: list[str] = []
    latest: dict[str, dict[str, Any]] = {}
    for interaction in interactions:
        key = " ".join(interaction.get("topic", "").split()).casefold()
        if key not in latest:
            order.append(key)
        latest[key] = interaction
    return [latest[key] for key in order if key]


def _source_items(
    body: ET.Element,
    items: list[dict[str, Any]],
    source_by_id: dict[str, dict[str, Any]],
) -> None:
    for item in items:
        _paragraph(body, item["text"], bullet=True)
        if item.get("provenance"):
            _paragraph(body, _citation_text(item["provenance"], source_by_id), style="Citation")


def _render_teach_interaction(
    body: ET.Element,
    interaction: dict[str, Any],
    source_by_id: dict[str, dict[str, Any]],
) -> None:
    topic = interaction["topic"]
    _paragraph(body, topic[:1].upper() + topic[1:], style="Heading2")
    generated = interaction["generated_learning"]
    if "teaching_sequence" in generated:
        direct = generated["direct_explanation"]
        _paragraph(body, direct["text"])
        _paragraph(body, _citation_text(direct["provenance"], source_by_id), style="Citation")
        for move in generated["teaching_sequence"]:
            _paragraph(body, move["title"], style="Heading3")
            _paragraph(body, move["explanation"])
            if move.get("why_it_follows"):
                _paragraph(body, f"Why it follows: {move['why_it_follows']}", style="StudyNote")
            _paragraph(body, _citation_text(move["provenance"], source_by_id), style="Citation")
        _paragraph(body, "Mental model", style="Heading3")
        mental_model = generated["mental_model"]
        _paragraph(body, mental_model["text"])
        _paragraph(body, _citation_text(mental_model["provenance"], source_by_id), style="Citation")
    else:
        for field, title in (
            ("explanation", "Explanation"),
            ("connections", "Connections"),
            ("source_examples", "Source examples"),
            ("takeaways", "Takeaways"),
        ):
            _paragraph(body, title, style="Heading3")
            _source_items(body, generated.get(field, []), source_by_id)
    unknowns = generated.get("unknowns", [])
    if unknowns:
        _paragraph(body, "Limits and unknowns", style="Heading3")
        for item in unknowns:
            _paragraph(body, item, bullet=True)


def _document_xml(record: dict[str, Any]) -> bytes:
    document = ET.Element(_qn(_W, "document"))
    body = ET.SubElement(document, _qn(_W, "body"))
    module = record["module"]
    week = record["week"]
    brief = record["workflows"]["prepare_me"]["result"]
    sources = record["sources"]
    source_by_id = {source["source_id"]: source for source in sources}

    _paragraph(body, module["code"], style="Eyebrow")
    _paragraph(body, f"Week {week['number']} Study Pack", style="Title")
    _paragraph(body, module["title"], style="Subtitle")
    _paragraph(body, f"A coherent learning resource for {module['code']} Week {week['number']}.", style="Intro")
    _paragraph(
        body,
        "Use this pack to prepare, consolidate your own notes, work through taught topics, "
        "and keep open questions visible. Citations identify official university sources; "
        "student notes and generated teaching are labelled separately.",
        style="StudyNote",
    )

    _paragraph(body, "1. Orientation", style="Heading1")
    for field, title in (
        ("week_overview", "Week overview"),
        ("before_class", "Before class"),
        ("lecture_attention", "Lecture focus"),
    ):
        _paragraph(body, title, style="Heading2")
        _source_items(body, brief.get(field, []), source_by_id)

    _paragraph(body, "2. Core concepts and examples", style="Heading1")
    _paragraph(body, "Core concepts", style="Heading2")
    _source_items(body, brief.get("core_concepts", []), source_by_id)
    _paragraph(body, "Important examples and cases", style="Heading2")
    _source_items(body, brief.get("examples_cases", []), source_by_id)

    _paragraph(body, page_break=True)
    _paragraph(body, "3. My lecture notes", style="Heading1")
    _paragraph(
        body,
        "Student-reported material — your recollection, not verified university evidence.",
        style="StudentReported",
    )
    note_sections = (
        ("lecture_notes", "Lecture notes"),
        ("lecturer_emphasis", "Lecturer emphasis"),
        ("examples_cases", "Examples and cases discussed"),
        ("understood", "What I understood"),
    )
    has_notes = False
    for field, title in note_sections:
        values = _captured_values(record, field)
        if values:
            has_notes = True
            _paragraph(body, title, style="Heading3")
            for item in values:
                _paragraph(body, item, bullet=True)
    if not has_notes:
        _paragraph(body, "No lecture notes have been captured yet.", style="Muted")

    _paragraph(body, "4. Questions to resolve", style="Heading1")
    _paragraph(body, "Questions suggested by the source material", style="Heading2")
    _source_items(body, brief.get("after_class_questions", []), source_by_id)
    _paragraph(body, "My open questions and uncertainties", style="Heading2")
    open_items = _open_learning_items(record)
    if open_items:
        for item in open_items:
            label = item.get("kind", "item").title()
            _paragraph(body, f"{label}: {item['text']}", bullet=True)
    else:
        _paragraph(body, "No student-reported open questions are recorded.", style="Muted")

    _paragraph(body, page_break=True)
    _paragraph(body, "5. Taught topics", style="Heading1")
    _paragraph(
        body,
        "Generated learning derived from cited sources and student context. It is a study aid, "
        "not a substitute for the university source material, and it does not establish mastery.",
        style="StudyNote",
    )
    interactions = _current_teach_interactions(record)
    if not interactions:
        _paragraph(body, "No taught topic has been recorded yet.", style="Muted")
    for interaction in interactions:
        _render_teach_interaction(body, interaction, source_by_id)

    _paragraph(body, "6. Assessment connections", style="Heading1")
    _paragraph(body, "Connections grounded in university sources", style="Heading2")
    _source_items(body, brief.get("assessment_connections", []), source_by_id)
    assessment_notes = _captured_values(record, "assessment_comments")
    if assessment_notes:
        _paragraph(body, "My captured assessment notes", style="Heading2")
        _paragraph(body, "Student-reported and not verified against official sources.", style="StudentReported")
        for item in assessment_notes:
            _paragraph(body, item, bullet=True)

    _paragraph(body, "7. Sources and provenance", style="Heading1")
    _paragraph(
        body,
        "Use the source names, IDs and PDF page numbers below to trace cited claims back to the "
        "university material.",
        style="Muted",
    )
    for source in sources:
        details = [source["title"], f"ID: {source['source_id']}"]
        if source.get("authors"):
            details.insert(1, source["authors"])
        if source.get("academic_page_range"):
            details.append(f"assigned pages {source['academic_page_range']}")
        _paragraph(body, " — ".join(details), bullet=True)

    section = ET.SubElement(body, _qn(_W, "sectPr"))
    ET.SubElement(
        section,
        _qn(_W, "pgSz"),
        {_qn(_W, "w"): "11906", _qn(_W, "h"): "16838"},
    )
    ET.SubElement(
        section,
        _qn(_W, "pgMar"),
        {
            _qn(_W, "top"): "1134",
            _qn(_W, "right"): "1276",
            _qn(_W, "bottom"): "1134",
            _qn(_W, "left"): "1276",
            _qn(_W, "header"): "708",
            _qn(_W, "footer"): "708",
            _qn(_W, "gutter"): "0",
        },
    )
    return _xml_bytes(document)


def _styles_xml() -> bytes:
    styles = ET.Element(_qn(_W, "styles"))
    defaults = ET.SubElement(styles, _qn(_W, "docDefaults"))
    run_defaults = ET.SubElement(defaults, _qn(_W, "rPrDefault"))
    run_properties = ET.SubElement(run_defaults, _qn(_W, "rPr"))
    ET.SubElement(
        run_properties,
        _qn(_W, "rFonts"),
        {
            _qn(_W, "ascii"): "Aptos",
            _qn(_W, "hAnsi"): "Aptos",
            _qn(_W, "cs"): "Aptos",
        },
    )
    ET.SubElement(run_properties, _qn(_W, "sz"), {_qn(_W, "val"): "21"})
    paragraph_defaults = ET.SubElement(defaults, _qn(_W, "pPrDefault"))
    paragraph_properties = ET.SubElement(paragraph_defaults, _qn(_W, "pPr"))
    ET.SubElement(
        paragraph_properties,
        _qn(_W, "spacing"),
        {_qn(_W, "after"): "140", _qn(_W, "line"): "276", _qn(_W, "lineRule"): "auto"},
    )

    def add_style(
        style_id: str,
        name: str,
        *,
        size: int,
        colour: str,
        bold: bool = False,
        italic: bool = False,
        before: int = 0,
        after: int = 100,
        border: bool = False,
        shading: str | None = None,
    ) -> None:
        style = ET.SubElement(
            styles,
            _qn(_W, "style"),
            {_qn(_W, "type"): "paragraph", _qn(_W, "styleId"): style_id},
        )
        ET.SubElement(style, _qn(_W, "name"), {_qn(_W, "val"): name})
        if style_id == "Normal":
            style.set(_qn(_W, "default"), "1")
        else:
            ET.SubElement(style, _qn(_W, "basedOn"), {_qn(_W, "val"): "Normal"})
        paragraph = ET.SubElement(style, _qn(_W, "pPr"))
        ET.SubElement(
            paragraph,
            _qn(_W, "spacing"),
            {_qn(_W, "before"): str(before), _qn(_W, "after"): str(after)},
        )
        if border:
            borders = ET.SubElement(paragraph, _qn(_W, "pBdr"))
            ET.SubElement(
                borders,
                _qn(_W, "bottom"),
                {
                    _qn(_W, "val"): "single",
                    _qn(_W, "sz"): "12",
                    _qn(_W, "space"): "6",
                    _qn(_W, "color"): "36A3A8",
                },
            )
        if shading:
            ET.SubElement(paragraph, _qn(_W, "shd"), {_qn(_W, "fill"): shading})
            ET.SubElement(
                paragraph,
                _qn(_W, "ind"),
                {_qn(_W, "left"): "180", _qn(_W, "right"): "180"},
            )
        run = ET.SubElement(style, _qn(_W, "rPr"))
        ET.SubElement(run, _qn(_W, "color"), {_qn(_W, "val"): colour})
        ET.SubElement(run, _qn(_W, "sz"), {_qn(_W, "val"): str(size)})
        if bold:
            ET.SubElement(run, _qn(_W, "b"))
        if italic:
            ET.SubElement(run, _qn(_W, "i"))

    add_style("Normal", "Normal", size=21, colour="243447")
    add_style("Eyebrow", "Eyebrow", size=18, colour="23757A", bold=True, after=80)
    add_style("Title", "Title", size=48, colour="17365D", bold=True, after=100)
    add_style("Subtitle", "Subtitle", size=27, colour="4C6378", after=260)
    add_style("Intro", "Intro", size=23, colour="243447", after=180)
    add_style(
        "StudyNote",
        "Study note",
        size=20,
        colour="17365D",
        before=80,
        after=240,
        shading="E8F3F4",
    )
    add_style(
        "Heading1",
        "Heading 1",
        size=30,
        colour="17365D",
        bold=True,
        before=300,
        after=160,
        border=True,
    )
    add_style("Heading2", "Heading 2", size=25, colour="23757A", bold=True, before=220, after=100)
    add_style("Heading3", "Heading 3", size=22, colour="36566F", bold=True, before=160, after=80)
    add_style("Citation", "Citation", size=17, colour="607486", italic=True, after=150)
    add_style("Muted", "Muted", size=19, colour="607486", italic=True, after=140)
    add_style(
        "StudentReported",
        "Student-reported material",
        size=20,
        colour="603A17",
        italic=True,
        before=80,
        after=180,
        shading="FFF3D6",
    )
    add_style(
        "StudentProvenance",
        "Student provenance",
        size=17,
        colour="7A5A2B",
        italic=True,
        after=180,
    )
    return _xml_bytes(styles)


def _numbering_xml() -> bytes:
    numbering = ET.Element(_qn(_W, "numbering"))
    abstract = ET.SubElement(numbering, _qn(_W, "abstractNum"), {_qn(_W, "abstractNumId"): "0"})
    level = ET.SubElement(abstract, _qn(_W, "lvl"), {_qn(_W, "ilvl"): "0"})
    ET.SubElement(level, _qn(_W, "start"), {_qn(_W, "val"): "1"})
    ET.SubElement(level, _qn(_W, "numFmt"), {_qn(_W, "val"): "bullet"})
    ET.SubElement(level, _qn(_W, "lvlText"), {_qn(_W, "val"): "•"})
    paragraph = ET.SubElement(level, _qn(_W, "pPr"))
    ET.SubElement(
        paragraph,
        _qn(_W, "tabs"),
    ).append(ET.Element(_qn(_W, "tab"), {_qn(_W, "val"): "num", _qn(_W, "pos"): "540"}))
    ET.SubElement(
        paragraph,
        _qn(_W, "ind"),
        {_qn(_W, "left"): "540", _qn(_W, "hanging"): "270"},
    )
    instance = ET.SubElement(numbering, _qn(_W, "num"), {_qn(_W, "numId"): "1"})
    ET.SubElement(instance, _qn(_W, "abstractNumId"), {_qn(_W, "val"): "0"})
    return _xml_bytes(numbering)


def _relationships_xml() -> bytes:
    namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    relationships = ET.Element("Relationships", {"xmlns": namespace})
    ET.SubElement(
        relationships,
        "Relationship",
        {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
            "Target": "word/document.xml",
        },
    )
    ET.SubElement(
        relationships,
        "Relationship",
        {
            "Id": "rId2",
            "Type": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
            "Target": "docProps/core.xml",
        },
    )
    ET.SubElement(
        relationships,
        "Relationship",
        {
            "Id": "rId3",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties",
            "Target": "docProps/app.xml",
        },
    )
    return _xml_bytes(relationships)


def _document_relationships_xml() -> bytes:
    namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    relationships = ET.Element("Relationships", {"xmlns": namespace})
    ET.SubElement(
        relationships,
        "Relationship",
        {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
            "Target": "styles.xml",
        },
    )
    ET.SubElement(
        relationships,
        "Relationship",
        {
            "Id": "rId2",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering",
            "Target": "numbering.xml",
        },
    )
    return _xml_bytes(relationships)


def _content_types_xml() -> bytes:
    namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    types = ET.Element("Types", {"xmlns": namespace})
    ET.SubElement(
        types,
        "Default",
        {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"},
    )
    ET.SubElement(types, "Default", {"Extension": "xml", "ContentType": "application/xml"})
    for part, content_type in (
        ("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
        ("/word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
        ("/word/numbering.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"),
        ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        ("/docProps/app.xml", "application/vnd.openxmlformats-officedocument.extended-properties+xml"),
    ):
        ET.SubElement(types, "Override", {"PartName": part, "ContentType": content_type})
    return _xml_bytes(types)


def _core_properties_xml(record: dict[str, Any]) -> bytes:
    properties = ET.Element(_qn(_CP, "coreProperties"))
    ET.SubElement(properties, _qn(_DC, "title")).text = (
        f"{record['module']['code']} Week {record['week']['number']} Study Pack"
    )
    ET.SubElement(properties, _qn(_DC, "subject")).text = record["module"]["title"]
    ET.SubElement(properties, _qn(_DC, "creator")).text = "Serapis"
    ET.SubElement(properties, _qn(_CP, "keywords")).text = "study pack; university; source-grounded"
    ET.SubElement(properties, _qn(_DC, "description")).text = (
        "Derived from the canonical Serapis academic record."
    )
    return _xml_bytes(properties)


def _app_properties_xml() -> bytes:
    namespace = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
    properties = ET.Element("Properties", {"xmlns": namespace})
    ET.SubElement(properties, "Application").text = "Serapis"
    ET.SubElement(properties, "AppVersion").text = "1.0"
    return _xml_bytes(properties)


def _docx_bytes(record: dict[str, Any]) -> bytes:
    parts = {
        "[Content_Types].xml": _content_types_xml(),
        "_rels/.rels": _relationships_xml(),
        "docProps/core.xml": _core_properties_xml(record),
        "docProps/app.xml": _app_properties_xml(),
        "word/document.xml": _document_xml(record),
        "word/styles.xml": _styles_xml(),
        "word/numbering.xml": _numbering_xml(),
        "word/_rels/document.xml.rels": _document_relationships_xml(),
    }
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in parts.items():
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def _markdown_citation(
    provenance: list[dict[str, Any]], source_by_id: dict[str, dict[str, Any]]
) -> str:
    return f"_{_citation_text(provenance, source_by_id)}_"


def _markdown_source_items(
    lines: list[str],
    items: list[dict[str, Any]],
    source_by_id: dict[str, dict[str, Any]],
) -> None:
    if not items:
        lines.extend(["No material is currently recorded.", ""])
        return
    for item in items:
        lines.append(f"- {item['text']}")
        if item.get("provenance"):
            lines.append(f"  {_markdown_citation(item['provenance'], source_by_id)}")
    lines.append("")


def _notebooklm_markdown(record: dict[str, Any]) -> str:
    """Create a readable, stable upload source without changing canonical state."""
    module = record["module"]
    week = record["week"]
    brief = record["workflows"]["prepare_me"]["result"]
    sources = record["sources"]
    source_by_id = {source["source_id"]: source for source in sources}
    lines = [
        f"# {module['code']} — Week {week['number']} Study Source",
        "",
        f"## {module['title']}",
        "",
        "> Study source generated from Serapis. Claims from university materials include source names and PDF page numbers. Student notes and generated explanations are labelled separately.",
        "",
        "Official-source claims carry source IDs and PDF pages. Student notes are explicitly labelled as unverified. Generated teaching is a derived explanation, not a university source.",
        "",
        "# 1. Orientation",
        "",
    ]
    for field, title in (
        ("week_overview", "Week overview"),
        ("before_class", "Before class"),
        ("lecture_attention", "Lecture focus"),
    ):
        lines.extend([f"## {title}", ""])
        _markdown_source_items(lines, brief.get(field, []), source_by_id)

    lines.extend(["# 2. Core concepts and examples", "", "## Core concepts", ""])
    _markdown_source_items(lines, brief.get("core_concepts", []), source_by_id)
    lines.extend(["## Important examples and cases", ""])
    _markdown_source_items(lines, brief.get("examples_cases", []), source_by_id)

    lines.extend([
        "# 3. My lecture notes",
        "",
        "> Student-reported recollection; not verified against official university sources.",
        "",
    ])
    any_notes = False
    for field, title in (
        ("lecture_notes", "Lecture notes"),
        ("lecturer_emphasis", "Lecturer emphasis"),
        ("examples_cases", "Examples and cases discussed"),
        ("understood", "What I understood"),
    ):
        values = _captured_values(record, field)
        if values:
            any_notes = True
            lines.extend([f"## {title}", ""])
            lines.extend(f"- {value}" for value in values)
            lines.append("")
    if not any_notes:
        lines.extend(["No lecture notes have been captured yet.", ""])

    lines.extend(["# 4. Questions to resolve", "", "## Questions suggested by the sources", ""])
    _markdown_source_items(lines, brief.get("after_class_questions", []), source_by_id)
    lines.extend(["## My open questions and uncertainties", ""])
    open_items = _open_learning_items(record)
    if open_items:
        for item in open_items:
            lines.append(f"- **{item.get('kind', 'item').title()}:** {item['text']}")
        lines.append("")
    else:
        lines.extend(["No student-reported open questions are recorded.", ""])

    lines.extend([
        "# 5. Taught topics",
        "",
        "> Generated learning derived from the cited sources. This section is a study aid, not a substitute for the university source material, and does not establish mastery.",
        "",
    ])
    interactions = _current_teach_interactions(record)
    if not interactions:
        lines.extend(["No taught topic has been recorded yet.", ""])
    for interaction in interactions:
        topic = interaction["topic"]
        lines.extend([f"## {topic[:1].upper() + topic[1:]}", ""])
        generated = interaction["generated_learning"]
        if "teaching_sequence" in generated:
            direct = generated["direct_explanation"]
            lines.extend([direct["text"], "", _markdown_citation(direct["provenance"], source_by_id), ""])
            for move in generated["teaching_sequence"]:
                lines.extend([f"### {move['title']}", "", move["explanation"], ""])
                if move.get("why_it_follows"):
                    lines.extend([f"> Why it follows: {move['why_it_follows']}", ""])
                lines.extend([_markdown_citation(move["provenance"], source_by_id), ""])
            mental_model = generated["mental_model"]
            lines.extend(["### Mental model", "", mental_model["text"], "", _markdown_citation(mental_model["provenance"], source_by_id), ""])
        else:
            for field, title in (
                ("explanation", "Explanation"),
                ("connections", "Connections"),
                ("source_examples", "Source examples"),
                ("takeaways", "Takeaways"),
            ):
                lines.extend([f"### {title}", ""])
                _markdown_source_items(lines, generated.get(field, []), source_by_id)
        if generated.get("unknowns"):
            lines.extend(["### Limits and unknowns", ""])
            lines.extend(f"- {item}" for item in generated["unknowns"])
            lines.append("")

    lines.extend(["# 6. Assessment connections", "", "## Grounded connections", ""])
    _markdown_source_items(lines, brief.get("assessment_connections", []), source_by_id)
    assessment_notes = _captured_values(record, "assessment_comments")
    if assessment_notes:
        lines.extend([
            "## My captured assessment notes",
            "",
            "> Student-reported and not verified against official sources.",
            "",
        ])
        lines.extend(f"- {item}" for item in assessment_notes)
        lines.append("")

    lines.extend([
        "# 7. Source guide",
        "",
        "Use these source names, stable IDs and PDF page numbers to trace claims back to the university material.",
        "",
    ])
    for source in sources:
        details = [source["title"], f"ID: {source['source_id']}"]
        if source.get("authors"):
            details.insert(1, source["authors"])
        if source.get("academic_page_range"):
            details.append(f"assigned pages {source['academic_page_range']}")
        lines.append(f"- {' — '.join(details)}")
    lines.extend([
        "",
        "---",
        "",
        "Use NotebookLM to ask questions and generate study aids from this file. Verify important claims against the cited university sources; NotebookLM output is not itself university evidence.",
        "",
    ])
    return "\n".join(lines)


def _workspace_paths(
    module_code: str, week_number: int, workspace_root: Path | None
) -> tuple[Path, Path, Path]:
    module_component = _safe_component(module_code.upper())
    target_dir = (workspace_root or default_workspace_root()) / module_component / f"week-{week_number:02d}"
    return (
        target_dir / "academic-record.json",
        target_dir / f"{module_component}-Week-{week_number:02d}-Study-Pack.docx",
        target_dir / f"{module_component}-Week-{week_number:02d}-NotebookLM.md",
    )


def _write_workspace(
    record: dict[str, Any],
    record_path: Path,
    study_pack_path: Path,
    notebooklm_path: Path,
) -> None:
    record_bytes = (
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")
    study_pack_bytes = _docx_bytes(record)
    notebooklm_bytes = _notebooklm_markdown(record).encode("utf-8")

    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_temp = record_path.with_suffix(".json.tmp")
    study_pack_temp = study_pack_path.with_suffix(".docx.tmp")
    notebooklm_temp = notebooklm_path.with_suffix(".md.tmp")
    record_temp.write_bytes(record_bytes)
    study_pack_temp.write_bytes(study_pack_bytes)
    notebooklm_temp.write_bytes(notebooklm_bytes)
    record_temp.replace(record_path)
    study_pack_temp.replace(study_pack_path)
    notebooklm_temp.replace(notebooklm_path)


def _student_provenance(capture_id: str, captured_at: str) -> dict[str, str]:
    return {
        "classification": "student_reported",
        "capture_id": capture_id,
        "captured_at": captured_at,
        "verification_status": "unverified_against_official_sources",
    }


def _normalise_entries(values: list[str] | None) -> list[str]:
    return [value.strip() for value in (values or []) if value.strip()]


def _extract_explicit_uncertainties(notes: list[str]) -> list[str]:
    """Extract only conspicuously self-labelled uncertainty lines from free-form notes."""
    patterns = (
        re.compile(r"^(?:uncertainty|unclear|did not understand)\s*:\s*(.+)$", re.I),
        re.compile(
            r"^i (?:still )?(?:do not|don't) (?:really )?understand\s+(.+)$", re.I
        ),
    )
    extracted: list[str] = []
    for note in notes:
        for line in note.splitlines():
            candidate = line.strip().lstrip("-*• ").strip()
            for pattern in patterns:
                match = pattern.match(candidate)
                if match:
                    text = match.group(1).strip()
                    if text and text not in extracted:
                        extracted.append(text)
                    break
    return extracted


def _extract_explicit_questions(notes: list[str]) -> list[str]:
    pattern = re.compile(r"^(?:question|still need to know)\s*:\s*(.+)$", re.I)
    extracted: list[str] = []
    for note in notes:
        for line in note.splitlines():
            candidate = line.strip().lstrip("-*• ").strip()
            match = pattern.match(candidate)
            if match:
                text = match.group(1).strip()
                if text and text not in extracted:
                    extracted.append(text)
    return extracted


def capture_after_lecture(
    module_code: str,
    week_number: int,
    *,
    notes: list[str] | None = None,
    notes_file: Path | None = None,
    lecturer_emphasis: list[str] | None = None,
    examples_cases: list[str] | None = None,
    understood: list[str] | None = None,
    uncertainties: list[str] | None = None,
    questions: list[str] | None = None,
    assessment_comments: list[str] | None = None,
    workspace_root: Path | None = None,
    captured_at: str | None = None,
) -> CaptureResult:
    """Append a deterministic student report and rebuild its derived study pack."""
    record_path, study_pack_path, notebooklm_path = _workspace_paths(
        module_code, week_number, workspace_root
    )
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateError(
            f"Academic record not found: {record_path}; run workspace first"
        ) from exc
    except json.JSONDecodeError as exc:
        raise StateError(f"Invalid academic record JSON: {record_path}") from exc

    if record.get("module", {}).get("code", "").upper() != module_code.upper() or record.get(
        "week", {}
    ).get("number") != week_number:
        raise StateError("Academic record module/week does not match the requested capture")

    direct_notes = _normalise_entries(notes)
    input_sources: list[dict[str, Any]] = []
    if direct_notes:
        input_sources.append({"type": "direct_text"})
    file_notes: list[str] = []
    if notes_file is not None:
        try:
            raw_file = notes_file.read_bytes()
            file_text = raw_file.decode("utf-8").strip()
        except FileNotFoundError as exc:
            raise StateError(f"Notes file not found: {notes_file}") from exc
        except UnicodeDecodeError as exc:
            raise StateError("Notes file must be UTF-8 text") from exc
        if file_text:
            file_notes.append(file_text)
        input_sources.append(
            {
                "type": "local_notes_file",
                "file_name": notes_file.name,
                "fingerprint": {"algorithm": "sha256", "value": sha256(raw_file).hexdigest()},
            }
        )

    lecture_notes = direct_notes + file_notes
    explicit_uncertainties = _normalise_entries(uncertainties)
    for item in _extract_explicit_uncertainties(lecture_notes):
        if item not in explicit_uncertainties:
            explicit_uncertainties.append(item)
    explicit_questions = _normalise_entries(questions)
    for item in _extract_explicit_questions(lecture_notes):
        if item not in explicit_questions:
            explicit_questions.append(item)

    entries = {
        "lecture_notes": lecture_notes,
        "lecturer_emphasis": _normalise_entries(lecturer_emphasis),
        "examples_cases": _normalise_entries(examples_cases),
        "understood": _normalise_entries(understood),
        "uncertainties": explicit_uncertainties,
        "questions": explicit_questions,
        "assessment_comments": _normalise_entries(assessment_comments),
    }
    if not any(entries.values()):
        raise StateError("After-lecture capture requires notes or at least one reported item")
    if any(entries[field] for field, _ in _CAPTURE_FIELDS if field != "lecture_notes") and not any(
        source["type"] == "direct_text" for source in input_sources
    ):
        input_sources.insert(0, {"type": "direct_text"})

    after_lecture = record.setdefault("workflows", {}).setdefault(
        "after_lecture", {"status": "not_recorded", "captures": []}
    )
    captures = after_lecture.setdefault("captures", [])
    capture_id = f"capture-{len(captures) + 1:04d}"
    timestamp = captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    provenance = _student_provenance(capture_id, timestamp)
    capture = {
        "capture_id": capture_id,
        "captured_at": timestamp,
        "capture_type": "after_lecture_student_report",
        "input_sources": input_sources,
        "provenance": provenance,
        "entries": entries,
    }
    captures.append(capture)
    after_lecture["status"] = "recorded"

    learning = record.setdefault("learning", {})
    notes_state = learning.setdefault("notes", {"status": "not_recorded", "items": []})
    for category, _ in _CAPTURE_FIELDS:
        for text in entries[category]:
            notes_state.setdefault("items", []).append(
                {
                    "capture_id": capture_id,
                    "category": category,
                    "text": text,
                    "provenance": deepcopy(provenance),
                }
            )
    notes_state["status"] = "recorded"

    unresolved = learning.setdefault(
        "unresolved_items", {"status": "none_recorded", "items": []}
    )
    for kind, values in (("uncertainty", explicit_uncertainties), ("question", explicit_questions)):
        for text in values:
            unresolved.setdefault("items", []).append(
                {
                    "item_id": f"{capture_id}-{kind}-{len(unresolved['items']) + 1:04d}",
                    "capture_id": capture_id,
                    "kind": kind,
                    "text": text,
                    "status": "open",
                    "provenance": deepcopy(provenance),
                }
            )
    if unresolved.get("items"):
        unresolved["status"] = "open"

    record["workspace_schema_version"] = WORKSPACE_SCHEMA_VERSION
    record.setdefault("knowledge_classification", _knowledge_classification())
    _write_workspace(record, record_path, study_pack_path, notebooklm_path)
    return CaptureResult(record_path, study_pack_path, notebooklm_path, capture_id, timestamp)


def _topic_terms(value: str) -> set[str]:
    ignored = {"about", "difference", "between", "really", "should", "understand", "what"}
    return {
        term
        for term in re.findall(r"[a-z0-9]+", value.lower())
        if len(term) >= 3 and term not in ignored
    }


def _teach_target(
    record: dict[str, Any], topic: str | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    open_items = [
        item
        for item in record.get("learning", {}).get("unresolved_items", {}).get("items", [])
        if item.get("status") == "open"
    ]
    if topic is None:
        if not open_items:
            raise StateError(
                "No open after-lecture question or uncertainty is available; supply --topic"
            )
        selected = next(
            (item for item in open_items if item.get("kind") == "question"),
            open_items[0],
        )
        requested = {
            "selection": "automatic_open_unresolved_item",
            "topic": selected["text"],
            "learning_item_id": selected["item_id"],
        }
        relevant = [selected]
    else:
        cleaned = topic.strip()
        if not cleaned:
            raise StateError("TEACH topic must not be empty")
        topic_terms = _topic_terms(cleaned)
        ranked = [
            (len(topic_terms & _topic_terms(item["text"])), -index, item)
            for index, item in enumerate(open_items)
        ]
        best = max(ranked, default=(0, 0, None))
        relevant = [best[2]] if best[0] > 0 and best[2] is not None else []
        requested = {
            "selection": "explicit_topic",
            "topic": cleaned,
            "learning_item_id": relevant[0]["item_id"] if relevant else None,
        }
    student_context = [
        {
            "item_id": item["item_id"],
            "capture_id": item["capture_id"],
            "kind": item["kind"],
            "text": item["text"],
            "provenance": deepcopy(item["provenance"]),
        }
        for item in relevant
    ]
    return requested, student_context


def teach_week(
    state: dict[str, Any],
    module_code: str,
    week_number: int,
    *,
    topic: str | None = None,
    provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
    workspace_root: Path | None = None,
    taught_at: str | None = None,
) -> TeachResult:
    """Teach one concept from official sources while retaining student provenance."""
    record_path, study_pack_path, notebooklm_path = _workspace_paths(
        module_code, week_number, workspace_root
    )
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateError(
            f"Academic record not found: {record_path}; run workspace first"
        ) from exc
    except json.JSONDecodeError as exc:
        raise StateError(f"Invalid academic record JSON: {record_path}") from exc
    if record.get("module", {}).get("code", "").upper() != module_code.upper() or record.get(
        "week", {}
    ).get("number") != week_number:
        raise StateError("Academic record module/week does not match the requested TEACH interaction")

    context = build_week_context(state, module_code, week_number, "TEACH")
    current_source_ids = {source["id"] for source in context["sources"]}
    record_source_ids = {source["source_id"] for source in record.get("sources", [])}
    if current_source_ids != record_source_ids:
        raise StateError(
            "Configured week sources no longer match the academic record; rematerialize the workspace"
        )
    teach_request, student_context = _teach_target(record, topic)
    context["teach_request"] = teach_request
    context["prepare_me"] = {
        "classification": "source_grounded_preparation",
        "note": "Generated PREPARE_ME material is guidance, not an additional official source.",
        "result": deepcopy(record["workflows"]["prepare_me"]["result"]),
    }
    context["student_context"] = deepcopy(student_context)
    selected_provider = provider or OpenAIReasoningProvider()
    result = generate_teach_brief(context, selected_provider, cache_dir=cache_dir)

    teach_state = record.setdefault("workflows", {}).setdefault(
        "teach", {"status": "not_recorded", "interactions": []}
    )
    interactions = teach_state.setdefault("interactions", [])
    teach_id = f"teach-{len(interactions) + 1:04d}"
    timestamp = taught_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    usage = result.usage.to_dict() if result.usage else None
    generated_learning = result.brief.to_dict()
    source_fingerprints = {s.get("source_id"): s.get("extraction", {}).get("fingerprint") for s in record.get("sources", [])}
    for question in generated_learning.get("check_questions", []):
        for reference in question.get("provenance", []):
            reference["fingerprint"] = source_fingerprints.get(reference.get("source_id"))
    interactions.append(
        {
            "teach_id": teach_id,
            "taught_at": timestamp,
            "topic": teach_request["topic"],
            "addressed_learning_item_id": teach_request["learning_item_id"],
            "selection": teach_request["selection"],
            "student_context": deepcopy(student_context),
            "generated_learning": generated_learning,
            "provenance": {
                "classification": "generated_learning",
                "canonical_source_evidence": False,
            },
            "generation": {
                "cache_status": result.cache_status,
                "cache_key": result.cache_key,
                "prompt_version": TEACH_PROMPT_VERSION,
                "schema_version": TEACH_SCHEMA_VERSION,
                "provider": selected_provider.cache_identity(),
                "usage": usage,
            },
        }
    )
    teach_state["status"] = "recorded"
    record["workspace_schema_version"] = WORKSPACE_SCHEMA_VERSION
    record["knowledge_classification"] = _knowledge_classification()
    _write_workspace(record, record_path, study_pack_path, notebooklm_path)
    return TeachResult(
        record_path=record_path,
        study_pack_path=study_pack_path,
        notebooklm_path=notebooklm_path,
        teach_id=teach_id,
        taught_at=timestamp,
        topic=teach_request["topic"],
        brief=result.brief,
        student_context=student_context,
        cache_status=result.cache_status,
    )


def materialize_week_workspace(
    state: dict[str, Any],
    module_code: str,
    week_number: int,
    *,
    provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
    workspace_root: Path | None = None,
) -> WorkspaceResult:
    """Create the canonical record and DOCX strictly from a matching local cache."""
    context = build_prepare_context(state, module_code, week_number)
    selected_provider = provider or OpenAIReasoningProvider()
    result = load_cached_prepare_brief(context, selected_provider, cache_dir=cache_dir)
    record = build_academic_record(context, result, selected_provider)

    record_path, study_pack_path, notebooklm_path = _workspace_paths(
        context["module"]["code"], week_number, workspace_root
    )
    if record_path.exists():
        existing = json.loads(record_path.read_text(encoding="utf-8"))
        existing_after_lecture = existing.get("workflows", {}).get("after_lecture", {})
        existing_teach = existing.get("workflows", {}).get("teach", {})
        record["sources"] = existing.get("sources", record["sources"])
        record["workflows"] = existing.get("workflows", record["workflows"])
        prior_learning = existing.get("learning", {})
        record["learning"].update(prior_learning)
        record["learning"].setdefault("evidence", [])
        record["knowledge_classification"] = existing.get(
            "knowledge_classification", record["knowledge_classification"]
        )
        record["workspace_schema_version"] = max(
            WORKSPACE_SCHEMA_VERSION, existing.get("workspace_schema_version", 1)
        )
    _write_workspace(record, record_path, study_pack_path, notebooklm_path)

    return WorkspaceResult(
        record_path=record_path,
        study_pack_path=study_pack_path,
        notebooklm_path=notebooklm_path,
        cache_status=result.cache_status,
    )


def _learning_record(module_code: str, week_number: int, root: Path | None) -> tuple[dict[str, Any], Path, Path, Path]:
    paths = _workspace_paths(module_code, week_number, root)
    record_path, study_pack_path, notebooklm_path = paths
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateError("Academic record not found; prepare the week first") from exc
    record.setdefault("learning", {}).setdefault("evidence", [])
    return record, record_path, study_pack_path, notebooklm_path


def record_learning_attempt(module_code: str, week_number: int, *, capability: str, task: str,
                            origin: str, response: str, assistance_status: str = "UNAIDED",
                            prompt_help: list[str] | None = None, expected_answer: str | None = None,
                            source_references: list[dict[str, Any]] | None = None,
                            topic: str | None = None, root: Path | None = None,
                            attempted_at: str | None = None) -> dict[str, Any]:
    """Append a raw student response before any evaluation is considered."""
    if capability not in LEARNING_CAPABILITIES:
        raise StateError("Unsupported learning capability")
    if assistance_status not in {"UNAIDED", "PROMPTED"}:
        raise StateError("Assistance must be UNAIDED or PROMPTED")
    if not task.strip() or not response.strip():
        raise StateError("Task and response must not be empty")
    record, record_path, study_pack_path, notebooklm_path = _learning_record(module_code, week_number, root)
    evidence = record["learning"]["evidence"]
    parsed_time = datetime.fromisoformat(attempted_at) if attempted_at else datetime.now(timezone.utc)
    if parsed_time.tzinfo is None:
        raise StateError("Learning attempt timestamp must include a timezone")
    timestamp = parsed_time.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    source_index = {s.get("source_id"): s for s in record.get("sources", [])}
    stable_refs = []
    for ref in source_references or []:
        source = source_index.get(ref.get("source_id"), {})
        stable_refs.append({**deepcopy(ref), "source_title": source.get("title"),
                            "source_type": source.get("type"),
                            "fingerprint": source.get("extraction", {}).get("fingerprint")})
    attempt = {
        "attempt_id": f"attempt-{len(evidence)+1:06d}", "attempted_at": timestamp,
        "module_code": module_code.upper(), "week": week_number,
        "topic": topic or record.get("week", {}).get("topic"), "capability": capability,
        "task": task, "origin": origin, "student_response": response,
        "assistance_status": assistance_status, "prompt_help": list(prompt_help or []),
        "source_references": stable_refs,
        "expected_answer": expected_answer, "evaluation": None,
    }
    evidence.append(attempt)
    record["workspace_schema_version"] = WORKSPACE_SCHEMA_VERSION
    _write_workspace(record, record_path, study_pack_path, notebooklm_path)
    return deepcopy(attempt)


def save_learning_evaluation(module_code: str, week_number: int, attempt_id: str,
                             evaluation: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    record, record_path, study_pack_path, notebooklm_path = _learning_record(module_code, week_number, root)
    attempt = next((item for item in record["learning"]["evidence"] if item["attempt_id"] == attempt_id), None)
    if attempt is None:
        raise StateError("Learning attempt not found")
    if attempt.get("evaluation") is not None:
        raise StateError("Learning attempt already has an evaluation")
    attempt["evaluation"] = deepcopy(evaluation)
    _write_workspace(record, record_path, study_pack_path, notebooklm_path)
    return deepcopy(attempt)
