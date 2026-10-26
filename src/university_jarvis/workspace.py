"""Persistent, deterministic academic workspace artefacts."""

from __future__ import annotations

import io
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
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
    generate_prepare_brief,
    generate_teach_brief,
    load_cached_prepare_brief,
)
from .locking import record_lock
from .reflections import (
    ASSESSMENT_CAVEAT,
    CAPTURE_FIELDS,
    CLOSED_ITEM_STATUSES,
    CORRECTION_ACTIONS,
    MAX_ENTRIES_PER_FIELD,
    MAX_ENTRY_CHARS,
    OPEN_ITEM_FIELDS,
    effective_entries,
    effective_values,
    make_entry_id,
    parse_entry_id,
    resolved_values,
)
from .sources import PROJECT_ROOT, render_source_location
from .state import env_setting, StateError, personal_data_dir
from .workflows import build_prepare_context, build_week_context


WORKSPACE_SCHEMA_VERSION = 4
LEARNING_CAPABILITIES = ("RECALL", "EXPLANATION", "APPLICATION")

_CAPTURE_FIELDS = CAPTURE_FIELDS


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
    evidence_used: list[dict[str, Any]] = field(default_factory=list)


def default_workspace_root() -> Path:
    configured = env_setting("WORKSPACE_DIR")
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


def _base_record(context: dict[str, Any], prepare_me: dict[str, Any]) -> dict[str, Any]:
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
            "prepare_me": prepare_me,
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


def build_academic_record(
    context: dict[str, Any],
    result: PreparationResult,
    provider: ReasoningProvider,
) -> dict[str, Any]:
    """Build the canonical record from known state and one cached brief."""
    usage = result.usage.to_dict() if result.usage else None
    return _base_record(
        context,
        {
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
    )


def _bare_record(state: dict[str, Any], module_code: str, week_number: int) -> dict[str, Any]:
    """An in-memory record with no AI preparation, so reflections work without a provider.

    Built only from local state and the week's selected sources (a local text extraction, no model call).
    A later "Prepare" fills in ``prepare_me`` and keeps everything else.
    """
    context = build_prepare_context(state, module_code, week_number)
    return _base_record(context, {"status": "not_generated", "result": {}})


def _qn(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def _xml_bytes(element: ET.Element) -> bytes:
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _xml_safe(text: str) -> str:
    """Drop characters XML 1.0 cannot carry, so pasted text can never corrupt the Word file."""
    return _XML_ILLEGAL.sub("", text)


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
        node = ET.SubElement(run, _qn(_W, "t"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
        node.text = _xml_safe(text)
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


def _reflection_items(record: dict[str, Any], field: str) -> list[dict[str, Any]]:
    """Current wording of the student's entries for one field, de-duplicated, with date and correction flag.

    Corrections are applied here (the capture itself is never edited); withdrawn and answered entries are
    left out, and ``corrected`` lets exports say so.
    """
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in effective_entries(record):
        if entry["field"] != field or entry["status"] not in ("active", "corrected"):
            continue
        texts = [entry["text"]]
        if field == "lecture_notes":
            # Labelled questions and uncertainties already have a dedicated open-items section, so omit
            # those lines from the notes surface to avoid duplication.
            texts = [
                line.strip() for line in _xml_safe(entry["text"]).splitlines()
                if line.strip()
                and not _extract_explicit_uncertainties([line.strip()])
                and not _extract_explicit_questions([line.strip()])
            ]
        for text in texts:
            key = " ".join(text.split()).casefold()
            if key and key not in seen:
                seen.add(key)
                items.append({
                    "text": text.strip(),
                    "date": (entry.get("captured_at") or "")[:10] or None,
                    "corrected": entry["status"] == "corrected",
                })
    return items


def _reflection_suffix(item: dict[str, Any], dated: bool) -> str:
    parts = []
    if item.get("corrected"):
        parts.append("corrected by student")
    if dated and item.get("date"):
        parts.append(f"recorded {item['date']}")
    return f" ({'; '.join(parts)})" if parts else ""


def _has_multiple_captures(record: dict[str, Any]) -> bool:
    return len(record.get("workflows", {}).get("after_lecture", {}).get("captures", [])) > 1


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
            if move.get("basis") == "GENERAL_GUIDANCE":
                _paragraph(body, "General study guidance, not from your course materials", style="StudyNote")
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
    checks = generated.get("check_questions", [])
    if checks:
        _paragraph(body, "Check your understanding (try before looking back)", style="Heading3")
        for check in checks:
            _paragraph(body, check.get("text", ""), bullet=True)
    unknowns = generated.get("unknowns", [])
    if unknowns:
        _paragraph(body, "Limits and unknowns", style="Heading3")
        for item in unknowns:
            _paragraph(body, item, bullet=True)


# ----- shared export model ---------------------------------------------------------------------------------

_LABEL_UNIVERSITY = "University source"
_LABEL_STUDENT = "Student-reported"
_LABEL_AI = "AI-generated study aid"

_REFLECTION_NOTE_FIELDS = (
    ("covered", "What the lecture covered"),
    ("understood", "What I understood"),
    ("examples_cases", "Examples the lecturer mentioned"),
    ("lecturer_emphasis", "What the lecturer emphasised"),
    ("lecture_notes", "My own notes and reflections"),
)


def _quiz_questions(record: dict[str, Any]) -> list[dict[str, str]]:
    """Quiz questions only (TEACH check questions appear under their taught topic). Reference answers are never exported."""
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for quiz in record.get("learning", {}).get("quiz_history", {}).get("attempts", []):
        for question in quiz.get("questions", []):
            text = str(question.get("question", "")).strip()
            key = task_text_hash(text)
            if text and key not in seen:
                seen.add(key)
                result.append({"text": text, "kind": str(question.get("question_type", "")).title()})
    return result


def _evidence_and_priorities(record: dict[str, Any]) -> dict[str, Any]:
    """Recorded-answer standings and revision priorities, from fixed rules over the local record only."""
    from .learning_digest import ACTIVITY, DEMONSTRATED, STANDING_TEXT, build_learning_digest, _short
    from .reflections import open_reflection_items

    digest = build_learning_digest(record)
    evidence = [{"standing": STANDING_TEXT[i["standing"]], "task": i["task"], "attempts": i["attempts"]}
                for i in digest["items"]]
    priorities = [{"activity": ACTIVITY[i["standing"]], "task": _short(i["task"]), "basis": "Recorded answer"}
                  for i in digest["items"] if i["standing"] != DEMONSTRATED]
    for item in open_reflection_items(record, limit=5):
        verb = "Get an answer to" if item["kind"] == "question" else "Clarify"
        priorities.append({"activity": f"{verb} your own {item['kind']}.", "task": _short(item["text"]),
                           "basis": "Student-reported"})
    return {
        "evidence": evidence,
        "priorities": priorities,
        "untested": digest["untested_capabilities"] if digest["status"] == "SOME" else [],
        "limits": digest["limits"] if digest["status"] == "SOME" else [],
        "has_evidence": digest["status"] == "SOME",
    }


def _export_model(record: dict[str, Any]) -> dict[str, Any]:
    prepare = record.get("workflows", {}).get("prepare_me", {}) or {}
    brief = prepare.get("result") or {}
    sources = record.get("sources", [])
    module = record.get("module", {})
    week = record.get("week", {})
    return {
        "module": module,
        "week": week,
        "brief": brief,
        "prepared": bool(brief),
        "sources": sources,
        "source_by_id": {s["source_id"]: s for s in sources if "source_id" in s},
        "dated": _has_multiple_captures(record),
        "reflections": [
            (title, _reflection_items(record, field)) for field, title in _REFLECTION_NOTE_FIELDS
            if _reflection_items(record, field)
        ],
        "assessment_remarks": _reflection_items(record, "assessment_comments"),
        "open_items": _open_learning_items(record),
        "resolved": resolved_values(record),
        "interactions": _current_teach_interactions(record),
        "questions": _quiz_questions(record),
        **_evidence_and_priorities(record),
    }


def _week_line(model: dict[str, Any]) -> str:
    week = model["week"]
    parts = [f"Week {week.get('number')}"]
    if week.get("topic"):
        parts.append(str(week["topic"]))
    if week.get("date"):
        parts.append(str(week["date"]))
    return " — ".join(parts)


_LEGEND = (
    (_LABEL_UNIVERSITY, "Cited from the course sources listed at the end, with source name and page. Summaries are produced by AI from those sources, but each claim cites them."),
    (_LABEL_STUDENT, "Written by you after the lecture. Your recollection, not verified university material."),
    (_LABEL_AI, "Generated from the sources and your context. A study aid, not a source, and not proof of mastery."),
)


# ----- DOCX -------------------------------------------------------------------------------------------------

def _document_xml(record: dict[str, Any]) -> bytes:
    document = ET.Element(_qn(_W, "document"))
    body = ET.SubElement(document, _qn(_W, "body"))
    model = _export_model(record)
    module, brief = model["module"], model["brief"]
    source_by_id, dated = model["source_by_id"], model["dated"]

    _paragraph(body, module.get("code", ""), style="Eyebrow")
    _paragraph(body, f"Week {model['week'].get('number')} Study Pack", style="Title")
    _paragraph(body, module.get("title", ""), style="Subtitle")
    _paragraph(body, _week_line(model), style="Intro")
    _paragraph(
        body,
        "Module code and title are as entered in your Serapis setup. Use this pack to prepare, consolidate "
        "your own notes, work through taught topics, and keep open questions visible. It is regenerated "
        "from your academic record, so download it again after you add reflections or answers.",
        style="StudyNote",
    )
    _paragraph(body, "How to read the labels", style="Heading3")
    for label, meaning in _LEGEND:
        _paragraph(body, f"{label}: {meaning}", bullet=True)

    _paragraph(body, "1. Orientation", style="Heading1")
    if not model["prepared"]:
        _paragraph(
            body,
            "No source-based preparation has been generated for this week yet, so this part is empty. "
            "Use “Prepare study workspace” in the Hub to add it. Your own reflections below are still included.",
            style="Muted",
        )
    for field, title in (
        ("week_overview", "Week overview"),
        ("before_class", "Before class"),
        ("lecture_attention", "Lecture focus"),
    ):
        if brief.get(field):
            _paragraph(body, f"{title} (from university sources, AI-summarised)", style="Heading2")
            _source_items(body, brief[field], source_by_id)

    _paragraph(body, "2. Core concepts and examples", style="Heading1")
    if brief.get("core_concepts") or brief.get("examples_cases"):
        _paragraph(body, "Core concepts", style="Heading2")
        _source_items(body, brief.get("core_concepts", []), source_by_id)
        _paragraph(body, "Important examples and cases", style="Heading2")
        _source_items(body, brief.get("examples_cases", []), source_by_id)
    else:
        _paragraph(body, "Nothing recorded yet.", style="Muted")

    _paragraph(body, page_break=True)
    _paragraph(body, "3. My reflections", style="Heading1")
    _paragraph(
        body,
        f"{_LABEL_STUDENT} — your recollection, not verified university evidence. Corrections you made "
        "are shown with their current wording; the original is kept in your record.",
        style="StudentReported",
    )
    if model["reflections"]:
        for title, items in model["reflections"]:
            _paragraph(body, title, style="Heading3")
            for item in items:
                _paragraph(body, item["text"] + _reflection_suffix(item, dated), bullet=True)
    else:
        _paragraph(body, "No reflections have been recorded yet.", style="Muted")

    _paragraph(body, "4. Questions to resolve", style="Heading1")
    if brief.get("after_class_questions"):
        _paragraph(body, "Questions suggested by the source material (from university sources)", style="Heading2")
        _source_items(body, brief["after_class_questions"], source_by_id)
    _paragraph(body, f"My open questions and uncertainties ({_LABEL_STUDENT.lower()})", style="Heading2")
    if model["open_items"]:
        for item in model["open_items"]:
            _paragraph(body, f"{item.get('kind', 'item').title()}: {item['text']}", bullet=True)
    else:
        _paragraph(body, "No student-reported open questions are recorded.", style="Muted")
    if model["resolved"]:
        _paragraph(body, "Marked as answered by me (not verified)", style="Heading3")
        for item in model["resolved"]:
            _paragraph(body, f"{item['kind'].title()}: {item['text']}", bullet=True)

    _paragraph(body, page_break=True)
    _paragraph(body, "5. Taught topics", style="Heading1")
    _paragraph(
        body,
        f"{_LABEL_AI}, derived from cited sources and your context. It is not a substitute for the "
        "university source material, and it does not establish mastery.",
        style="StudyNote",
    )
    if not model["interactions"]:
        _paragraph(body, "No taught topic has been recorded yet.", style="Muted")
    for interaction in model["interactions"]:
        _render_teach_interaction(body, interaction, source_by_id)

    _paragraph(body, "6. Practice questions and recorded answers", style="Heading1")
    _paragraph(
        body,
        f"Questions are an {_LABEL_AI}. Reference answers are deliberately not included, so you can "
        "try each question before checking the cited sources. Standings are provisional judgements of single "
        "answers, not grades.",
        style="StudyNote",
    )
    if model["questions"]:
        for question in model["questions"]:
            _paragraph(body, f"{question['kind']}: {question['text']}" if question["kind"] else question["text"], bullet=True)
    else:
        _paragraph(body, "No quiz or check questions have been generated yet.", style="Muted")
    _paragraph(body, "What your recorded answers show", style="Heading2")
    if model["evidence"]:
        for item in model["evidence"]:
            _paragraph(body, f"{item['standing']} Question: {item['task']}", bullet=True)
        for limit in model["limits"]:
            _paragraph(body, limit, style="Muted")
    else:
        _paragraph(body, "No answers are recorded for this week yet. That is an evidence gap, not a weakness.", style="Muted")

    _paragraph(body, "7. Revision priorities", style="Heading1")
    if model["priorities"]:
        _paragraph(body, "Suggested from your recorded answers and open questions by fixed rules; a suggestion, "
                   "not a measure of how well you know the topics.", style="StudyNote")
        for number, item in enumerate(model["priorities"], start=1):
            _paragraph(body, f"{number}. {item['activity']} ({item['task']}) — {item['basis']}", bullet=True)
    else:
        _paragraph(body, "No revision priorities can be drawn yet. Record answers or open questions first.", style="Muted")
    if model["untested"]:
        _paragraph(body, "Not tested yet (an evidence gap, not a weakness): "
                   + ", ".join(c.lower() for c in model["untested"]) + ".", style="Muted")

    _paragraph(body, "8. Assessment connections", style="Heading1")
    if brief.get("assessment_connections"):
        _paragraph(body, "Connections grounded in university sources", style="Heading2")
        _source_items(body, brief["assessment_connections"], source_by_id)
    if model["assessment_remarks"]:
        _paragraph(body, "My captured assessment remarks", style="Heading2")
        _paragraph(body, ASSESSMENT_CAVEAT, style="StudentReported")
        for item in model["assessment_remarks"]:
            _paragraph(body, item["text"] + _reflection_suffix(item, dated), bullet=True)
    if not brief.get("assessment_connections") and not model["assessment_remarks"]:
        _paragraph(body, "Nothing recorded yet.", style="Muted")

    _paragraph(body, "9. Sources and provenance", style="Heading1")
    _paragraph(
        body,
        "Use the source names, IDs and PDF page numbers below to trace cited claims back to the "
        "university material.",
        style="Muted",
    )
    if not model["sources"]:
        _paragraph(body, "No course sources are attached to this week yet.", style="Muted")
    for source in model["sources"]:
        details = [source.get("title", source.get("source_id", "")), f"ID: {source.get('source_id', '')}"]
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


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|])")
_MD_LINE_START = re.compile(r"^(\s*)([#>+\-=~]|\d+[.)])")


def _md_lines(text: str) -> list[str]:
    """Escape untrusted text so it renders as plain text: no headings, links, HTML, tables or fences."""
    lines = []
    for line in _xml_safe(str(text)).splitlines() or [""]:
        line = _MD_SPECIAL.sub(r"\\\1", line.rstrip())
        lines.append(_MD_LINE_START.sub(r"\1\\\2", line))
    return lines


def _md(text: str) -> str:
    """Escaped single-line form of ``text``."""
    return " ".join(line.strip() for line in _md_lines(text) if line.strip())


def _md_bullet(lines: list[str], text: str, *, label: str | None = None, suffix: str = "") -> None:
    parts = _md_lines(text)
    prefix = f"**{label}:** " if label else ""
    lines.append(f"- {prefix}{parts[0]}" + ("" if len(parts) > 1 else suffix))
    for extra in parts[1:-1]:
        lines.append(f"  {extra}")
    if len(parts) > 1:
        lines.append(f"  {parts[-1]}{suffix}")


def _markdown_citation(
    provenance: list[dict[str, Any]], source_by_id: dict[str, dict[str, Any]]
) -> str:
    return f"_{_md(_citation_text(provenance, source_by_id))}_"


def _markdown_source_items(
    lines: list[str],
    items: list[dict[str, Any]],
    source_by_id: dict[str, dict[str, Any]],
) -> None:
    if not items:
        lines.extend(["No material is currently recorded.", ""])
        return
    for item in items:
        _md_bullet(lines, item["text"], label=_LABEL_UNIVERSITY if item.get("provenance") else _LABEL_AI)
        if item.get("provenance"):
            lines.append(f"  {_markdown_citation(item['provenance'], source_by_id)}")
    lines.append("")


def _notebooklm_markdown(record: dict[str, Any]) -> str:
    """Create a readable, stable upload source without changing canonical state.

    Every section heading and every student or generated bullet carries its provenance label, because
    NotebookLM splits a source into passages and a heading alone may not travel with a quoted passage.
    All free text is escaped, so a pasted note cannot create headings, links or fake provenance.
    """
    model = _export_model(record)
    module, week, brief = model["module"], model["week"], model["brief"]
    source_by_id, dated = model["source_by_id"], model["dated"]
    lines = [
        f"# {_md(module.get('code', ''))} — Week {week.get('number')} Study Source",
        "",
        f"## {_md(module.get('title', ''))}",
        "",
        f"Week: {_md(_week_line(model))}",
        "",
        "> Study source exported from Serapis for manual upload to NotebookLM. Module code and title are "
        "as entered by the student. Claims from university materials include source names and PDF page "
        "numbers. Student notes and generated explanations are labelled separately.",
        "",
        "Provenance labels used in this file:",
        "",
    ]
    lines.extend(f"- **{label}:** {meaning}" for label, meaning in _LEGEND)
    lines.extend([
        "",
        "Nothing in this file is confirmed by the university unless it carries a University source "
        "citation. Answers generated by NotebookLM from this file are study aids, not university evidence.",
        "",
        f"# 1. Orientation — {_LABEL_UNIVERSITY}",
        "",
    ])
    if not model["prepared"]:
        lines.extend(["No source-based preparation has been generated for this week yet.", ""])
    for field, title in (
        ("week_overview", "Week overview"),
        ("before_class", "Before class"),
        ("lecture_attention", "Lecture focus"),
    ):
        if brief.get(field):
            lines.extend([f"## {title}", ""])
            _markdown_source_items(lines, brief[field], source_by_id)

    lines.extend([f"# 2. Core concepts and examples — {_LABEL_UNIVERSITY}", ""])
    if brief.get("core_concepts") or brief.get("examples_cases"):
        lines.extend(["## Core concepts", ""])
        _markdown_source_items(lines, brief.get("core_concepts", []), source_by_id)
        lines.extend(["## Important examples and cases", ""])
        _markdown_source_items(lines, brief.get("examples_cases", []), source_by_id)
    else:
        lines.extend(["Nothing recorded yet.", ""])

    lines.extend([
        f"# 3. My reflections — {_LABEL_STUDENT} (unverified)",
        "",
        "> Student-reported recollection; not verified against official university sources.",
        "",
    ])
    if model["reflections"]:
        for title, items in model["reflections"]:
            lines.extend([f"## {title}", ""])
            for item in items:
                _md_bullet(lines, item["text"], label=_LABEL_STUDENT, suffix=_reflection_suffix(item, dated))
            lines.append("")
    else:
        lines.extend(["No reflections have been recorded yet.", ""])

    lines.extend(["# 4. Questions to resolve", "", f"## Questions suggested by the sources — {_LABEL_UNIVERSITY}", ""])
    if brief.get("after_class_questions"):
        _markdown_source_items(lines, brief["after_class_questions"], source_by_id)
    else:
        lines.extend(["No material is currently recorded.", ""])
    lines.extend([f"## My open questions and uncertainties — {_LABEL_STUDENT}", ""])
    if model["open_items"]:
        for item in model["open_items"]:
            _md_bullet(lines, item["text"], label=f"{_LABEL_STUDENT} {item.get('kind', 'item')}")
        lines.append("")
    else:
        lines.extend(["No student-reported open questions are recorded.", ""])
    if model["resolved"]:
        lines.extend(["## Marked as answered by the student (not verified)", ""])
        for item in model["resolved"]:
            _md_bullet(lines, item["text"], label=f"{_LABEL_STUDENT} {item['kind']}")
        lines.append("")

    lines.extend([
        f"# 5. Taught topics — {_LABEL_AI}",
        "",
        "> Generated learning derived from the cited sources. This section is a study aid, not a substitute for the university source material, and does not establish mastery.",
        "",
    ])
    if not model["interactions"]:
        lines.extend(["No taught topic has been recorded yet.", ""])
    for interaction in model["interactions"]:
        topic = interaction["topic"]
        lines.extend([f"## {_md(topic[:1].upper() + topic[1:])}", ""])
        generated = interaction["generated_learning"]
        if "teaching_sequence" in generated:
            direct = generated["direct_explanation"]
            _md_bullet(lines, direct["text"], label=_LABEL_AI)
            lines.extend([f"  {_markdown_citation(direct['provenance'], source_by_id)}", ""])
            for move in generated["teaching_sequence"]:
                lines.extend([f"### {_md(move['title'])}", ""])
                if move.get("basis") == "GENERAL_GUIDANCE":
                    lines.extend(["> General study guidance, not from your course materials", ""])
                lines.extend([*_md_lines(move["explanation"]), ""])
                if move.get("why_it_follows"):
                    lines.extend([f"> Why it follows: {_md(move['why_it_follows'])}", ""])
                lines.extend([_markdown_citation(move["provenance"], source_by_id), ""])
            mental_model = generated["mental_model"]
            lines.extend(["### Mental model", "", *_md_lines(mental_model["text"]), "",
                          _markdown_citation(mental_model["provenance"], source_by_id), ""])
        else:
            for field, title in (
                ("explanation", "Explanation"),
                ("connections", "Connections"),
                ("source_examples", "Source examples"),
                ("takeaways", "Takeaways"),
            ):
                lines.extend([f"### {title}", ""])
                _markdown_source_items(lines, generated.get(field, []), source_by_id)
        checks = generated.get("check_questions", [])
        if checks:
            lines.extend(["### Check your understanding (try before looking back)", ""])
            for check in checks:
                _md_bullet(lines, check.get("text", ""), label=_LABEL_AI)
            lines.append("")
        if generated.get("unknowns"):
            lines.extend(["### Limits and unknowns", ""])
            for item in generated["unknowns"]:
                _md_bullet(lines, item)
            lines.append("")

    lines.extend([
        f"# 6. Practice questions and recorded answers — {_LABEL_AI}",
        "",
        "> Questions only. Reference answers are not included so the student can attempt them first. Standings are provisional judgements of single answers, not grades.",
        "",
    ])
    if model["questions"]:
        for question in model["questions"]:
            _md_bullet(lines, question["text"], label=question["kind"] or "Question")
        lines.append("")
    else:
        lines.extend(["No quiz or check questions have been generated yet.", ""])
    lines.extend(["## What the recorded answers show", ""])
    if model["evidence"]:
        for item in model["evidence"]:
            lines.append(f"- {_md(item['standing'])} Question: {_md(item['task'])}")
        lines.extend(f"- {_md(limit)}" for limit in model["limits"])
        lines.append("")
    else:
        lines.extend(["No answers are recorded for this week yet. That is an evidence gap, not a weakness.", ""])

    lines.extend(["# 7. Revision priorities — suggested", ""])
    if model["priorities"]:
        lines.extend(["> Suggested from recorded answers and the student's open questions by fixed rules; not a measure of how well the topics are known.", ""])
        for number, item in enumerate(model["priorities"], start=1):
            lines.append(f"- {number}\\. {_md(item['activity'])} ({_md(item['task'])}) — {_md(item['basis'])}")
        lines.append("")
    else:
        lines.extend(["No revision priorities can be drawn yet.", ""])
    if model["untested"]:
        lines.extend(["Not tested yet (an evidence gap, not a weakness): " + ", ".join(c.lower() for c in model["untested"]) + ".", ""])

    lines.extend(["# 8. Assessment connections", "", f"## Grounded connections — {_LABEL_UNIVERSITY}", ""])
    if brief.get("assessment_connections"):
        _markdown_source_items(lines, brief["assessment_connections"], source_by_id)
    else:
        lines.extend(["No grounded assessment connections are recorded.", ""])
    if model["assessment_remarks"]:
        lines.extend([
            f"## Assessment remarks — {_LABEL_STUDENT}, unconfirmed",
            "",
            f"> {ASSESSMENT_CAVEAT}",
            "",
        ])
        for item in model["assessment_remarks"]:
            _md_bullet(lines, item["text"], label=_LABEL_STUDENT, suffix=_reflection_suffix(item, dated))
        lines.append("")

    lines.extend([
        "# 9. Source guide",
        "",
        "Use these source names, stable IDs and PDF page numbers to trace claims back to the university material.",
        "",
    ])
    if not model["sources"]:
        lines.extend(["No course sources are attached to this week yet.", ""])
    for source in model["sources"]:
        details = [source.get("title", source.get("source_id", "")), f"ID: {source.get('source_id', '')}"]
        if source.get("authors"):
            details.insert(1, source["authors"])
        if source.get("academic_page_range"):
            details.append(f"assigned pages {source['academic_page_range']}")
        lines.append(f"- {_md(' — '.join(details))}")
    lines.extend([
        "",
        "---",
        "",
        "Use NotebookLM to ask questions and generate study aids from this file. Verify important claims against the cited university sources; NotebookLM output is not itself university evidence and should not be imported back into Serapis as such.",
        "",
    ])
    return "\n".join(lines)


def build_study_pack_docx(record: dict[str, Any]) -> bytes:
    """The Word study pack for ``record``, built in memory (no write, no model call)."""
    return _docx_bytes(record)


def build_notebooklm_markdown(record: dict[str, Any]) -> str:
    """The NotebookLM-ready Markdown source for ``record``, built in memory (no write, no model call)."""
    return _notebooklm_markdown(record)


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


def _write_record(record: dict[str, Any], record_path: Path) -> None:
    """Atomically persist only the canonical academic record (no exports)."""
    record_bytes = (
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_temp = record_path.with_suffix(".json.tmp")
    record_temp.write_bytes(record_bytes)
    record_temp.replace(record_path)


def _write_workspace(
    record: dict[str, Any],
    record_path: Path,
    study_pack_path: Path,
    notebooklm_path: Path,
) -> None:
    """Persist the record and regenerate both derived exports.

    Learning-evidence writes (attempts, evaluations, quizzes, generated tasks)
    do not alter anything the exports render, so they use ``_write_record``.
    """
    study_pack_bytes = _docx_bytes(record)
    notebooklm_bytes = _notebooklm_markdown(record).encode("utf-8")

    study_pack_temp = study_pack_path.with_suffix(".docx.tmp")
    notebooklm_temp = notebooklm_path.with_suffix(".md.tmp")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    study_pack_temp.write_bytes(study_pack_bytes)
    notebooklm_temp.write_bytes(notebooklm_bytes)
    _write_record(record, record_path)
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
    covered: list[str] | None = None,
    state: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
    captured_at: str | None = None,
) -> CaptureResult:
    """Append a deterministic student report and rebuild its derived study pack.

    The whole read-modify-write runs under the record lock so a concurrent
    Hub/CLI write cannot be lost.
    """
    record_path, _, _ = _workspace_paths(module_code, week_number, workspace_root)
    # A week with no record yet starts from a bare in-memory one, written only if the capture succeeds. It is
    # built before locking so an unknown module or week fails without creating any directory.
    bare = _bare_record(state, module_code, week_number) if state is not None and not record_path.exists() else None
    with record_lock(record_path, create_dir=bare is not None):
        if bare is not None and record_path.exists():
            bare = None  # another writer created the record while this one was being built
        return _capture_after_lecture_locked(
            module_code,
            week_number,
            notes=notes,
            notes_file=notes_file,
            lecturer_emphasis=lecturer_emphasis,
            examples_cases=examples_cases,
            understood=understood,
            uncertainties=uncertainties,
            questions=questions,
            assessment_comments=assessment_comments,
            covered=covered,
            workspace_root=workspace_root,
            captured_at=captured_at,
            initial_record=bare,
        )


def _capture_after_lecture_locked(
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
    covered: list[str] | None = None,
    workspace_root: Path | None = None,
    captured_at: str | None = None,
    initial_record: dict[str, Any] | None = None,
) -> CaptureResult:
    """Append a deterministic student report and rebuild its derived study pack."""
    record_path, study_pack_path, notebooklm_path = _workspace_paths(
        module_code, week_number, workspace_root
    )
    if initial_record is not None:
        record = initial_record
    else:
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
        "covered": _normalise_entries(covered),
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
    for field, values in entries.items():
        if len(values) > MAX_ENTRIES_PER_FIELD:
            raise StateError(f"Too many entries for '{field}' (at most {MAX_ENTRIES_PER_FIELD} per reflection)")
        if any(len(value) > MAX_ENTRY_CHARS for value in values):
            raise StateError(f"An entry for '{field}' is longer than {MAX_ENTRY_CHARS} characters; split it up")
    previous = (record.get("workflows", {}).get("after_lecture", {}).get("captures") or [{}])[-1]
    if previous.get("entries") and {k: v for k, v in previous["entries"].items() if v} == {
        k: v for k, v in entries.items() if v
    }:
        raise StateError("This reflection is identical to your last one, so it was not saved twice")
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
    for kind, field, values in (
        ("uncertainty", "uncertainties", explicit_uncertainties),
        ("question", "questions", explicit_questions),
    ):
        for index, text in enumerate(values):
            unresolved.setdefault("items", []).append(
                {
                    "item_id": f"{capture_id}-{kind}-{len(unresolved['items']) + 1:04d}",
                    "entry_id": make_entry_id(capture_id, field, index),
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


def correct_after_lecture_entry(
    module_code: str,
    week_number: int,
    entry_id: str,
    *,
    action: str,
    new_text: str | None = None,
    reason: str | None = None,
    workspace_root: Path | None = None,
    corrected_at: str | None = None,
) -> dict[str, Any]:
    """Append a correction to one reflection entry; the original capture is never edited.

    ``action`` is ``correct`` (new wording), ``withdraw`` (retract), ``resolve`` (mark a question or
    confusion answered) or ``reopen``. Open-item status follows so TEACH and recommendations use the
    current wording, while superseded items stay in the record with their status.
    """
    record_path, study_pack_path, notebooklm_path = _workspace_paths(module_code, week_number, workspace_root)
    if action not in CORRECTION_ACTIONS:
        raise StateError(f"Unknown correction action: {action!r}")
    parsed = parse_entry_id(entry_id)
    if parsed is None:
        raise StateError("That reflection entry could not be identified")
    capture_id, field, index = parsed
    with record_lock(record_path):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise StateError("No reflections are recorded for this week yet") from exc
        except json.JSONDecodeError as exc:
            raise StateError(f"Invalid academic record JSON: {record_path}") from exc
        if record.get("module", {}).get("code", "").upper() != module_code.upper() or record.get(
            "week", {}
        ).get("number") != week_number:
            raise StateError("Academic record module/week does not match the requested correction")
        entry = next((e for e in effective_entries(record) if e["entry_id"] == entry_id), None)
        if entry is None:
            raise StateError("That reflection entry does not exist in this module and week")
        status = entry["status"]
        cleaned_reason = " ".join((reason or "").split())[:500] or None
        text = (new_text or "").strip()
        if action == "correct":
            if not text:
                raise StateError("Write the corrected wording, or withdraw the entry instead")
            if len(text) > MAX_ENTRY_CHARS:
                raise StateError(f"The corrected entry is longer than {MAX_ENTRY_CHARS} characters")
            if text == entry["text"] and status != "withdrawn":
                raise StateError("The corrected wording is the same as the current wording")
        elif action == "withdraw" and status == "withdrawn":
            raise StateError("That entry is already withdrawn")
        elif action in ("resolve", "reopen"):
            if field not in OPEN_ITEM_FIELDS:
                raise StateError("Only questions and points you found confusing can be marked answered")
            if action == "resolve" and status != "active" and status != "corrected":
                raise StateError("That entry is not open")
            if action == "reopen" and status != "resolved":
                raise StateError("That entry is not marked answered")
        if status == "withdrawn" and action != "correct":
            raise StateError("A withdrawn entry can only be restored by writing it again")

        after = record.setdefault("workflows", {}).setdefault("after_lecture", {"status": "recorded", "captures": []})
        corrections = after.setdefault("corrections", [])
        correction_id = f"correction-{len(corrections) + 1:04d}"
        timestamp = corrected_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        correction = {
            "correction_id": correction_id,
            "corrected_at": timestamp,
            "action": action,
            "corrects": {"capture_id": capture_id, "field": field, "index": index},
            "previous_text": entry["text"],
            "reason": cleaned_reason,
            "provenance": {
                "classification": "student_reported",
                "verification_status": "unverified_against_official_sources",
            },
        }
        if action == "correct":
            correction["corrected_text"] = text
        corrections.append(correction)

        if field in OPEN_ITEM_FIELDS:
            _sync_open_item(record, entry, correction, text if action == "correct" else None)
        record["workspace_schema_version"] = WORKSPACE_SCHEMA_VERSION
        _write_workspace(record, record_path, study_pack_path, notebooklm_path)
    return {"module_code": module_code.upper(), "week": week_number, "correction_id": correction_id,
            "corrected_at": timestamp, "action": action}


def _sync_open_item(
    record: dict[str, Any], entry: dict[str, Any], correction: dict[str, Any], new_text: str | None
) -> None:
    """Keep ``learning.unresolved_items`` consistent with a correction without deleting any item."""
    unresolved = record.setdefault("learning", {}).setdefault(
        "unresolved_items", {"status": "none_recorded", "items": []}
    )
    items = unresolved.setdefault("items", [])
    kind = OPEN_ITEM_FIELDS[entry["field"]]
    current = " ".join(entry["text"].split()).casefold()
    target = next(
        (
            item for item in reversed(items)
            if item.get("capture_id") == entry["capture_id"] and item.get("kind") == kind
            and (item.get("entry_id") == entry["entry_id"]
                 or (not item.get("entry_id") and " ".join(item.get("text", "").split()).casefold() == current))
        ),
        None,
    )
    action = correction["action"]
    stamp = {"status_changed_at": correction["corrected_at"], "status_changed_by": correction["correction_id"]}
    if action == "correct":
        if target is not None:
            target.update({"status": "superseded", "superseded_by": correction["correction_id"], **stamp})
        provenance = {
            "classification": "student_reported",
            "capture_id": entry["capture_id"],
            "captured_at": entry["captured_at"],
            "corrected_at": correction["corrected_at"],
            "correction_id": correction["correction_id"],
            "verification_status": "unverified_against_official_sources",
        }
        items.append({
            "item_id": f"{entry['capture_id']}-{kind}-{len(items) + 1:04d}",
            "entry_id": entry["entry_id"],
            "capture_id": entry["capture_id"],
            "kind": kind,
            "text": new_text,
            "status": "open",
            "provenance": provenance,
        })
    elif target is not None:
        target.update({"status": {"withdraw": "withdrawn", "resolve": "student_resolved", "reopen": "open"}[action], **stamp})
    unresolved["status"] = "open" if any(i.get("status") == "open" for i in items) else "none_open"


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

    teach_request, student_context = _teach_target(record, topic)
    retrieval_query = " ".join(
        [teach_request["topic"], *(item["text"] for item in student_context)]
    )
    context = build_week_context(
        state, module_code, week_number, "TEACH", query=retrieval_query
    )
    unmatched = next(
        (
            c["retrieval"]
            for c in context["source_contexts"]
            if c.get("retrieval", {}).get("status", "matched") != "matched"
        ),
        None,
    )
    if unmatched is not None:
        raise StateError(
            f"No passage in this week's sources matches '{teach_request['topic']}', so Serapis "
            "will not explain it from unrelated material. Try the wording used in the slides or "
            "reading, check the topic belongs to this week, or ask your lecturer."
        )
    current_source_ids = {source["id"] for source in context["sources"]}
    record_source_ids = {source["source_id"] for source in record.get("sources", [])}
    if current_source_ids != record_source_ids:
        raise StateError(
            "Configured week sources no longer match the academic record; rematerialize the workspace"
        )
    context["teach_request"] = teach_request
    context["prepare_me"] = {
        "classification": "source_grounded_preparation",
        "note": "Generated PREPARE_ME material is guidance, not an additional official source.",
        "result": deepcopy(record["workflows"]["prepare_me"].get("result") or {}),
    }
    context["student_context"] = deepcopy(student_context)
    from .learning_digest import build_learning_digest, model_view, relevant_to_topic

    digest = relevant_to_topic(build_learning_digest(record), teach_request["topic"])
    if (evidence := model_view(digest)) is not None:
        context["learning_evidence"] = evidence  # only answers about this topic; absent means no personalisation
    evidence_used = [{"task": i["task"], "standing": i["standing"], "attempts": i["attempts"]} for i in digest["items"]]
    selected_provider = provider or OpenAIReasoningProvider()
    result = generate_teach_brief(context, selected_provider, cache_dir=cache_dir)

    # The model call above can be slow, so the lock is taken only now and the
    # record is reloaded: writes made by other operations meanwhile are kept.
    with record_lock(record_path):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise StateError(f"Academic record could not be re-read: {record_path}") from exc
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
                "evidence_used": deepcopy(evidence_used),
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
                    "attempts": list(result.attempts),
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
        evidence_used=evidence_used,
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
    generate_if_missing: bool = False,
) -> WorkspaceResult:
    """Create the canonical record and DOCX from a matching local PREPARE_ME result.

    By default this is strictly cache-backed and never calls a model (the CLI runs ``prepare`` first).
    With ``generate_if_missing`` a cache miss calls the provider once, caches the result and uses it, so
    the Hub's single "Prepare" action works without a separate CLI step.
    """
    context = build_prepare_context(state, module_code, week_number)
    selected_provider = provider or OpenAIReasoningProvider()
    if generate_if_missing:
        result = generate_prepare_brief(context, selected_provider, cache_dir=cache_dir)
    else:
        result = load_cached_prepare_brief(context, selected_provider, cache_dir=cache_dir)
    record = build_academic_record(context, result, selected_provider)

    record_path, study_pack_path, notebooklm_path = _workspace_paths(
        context["module"]["code"], week_number, workspace_root
    )
    with record_lock(record_path, create_dir=True):
        if record_path.exists():
            existing = json.loads(record_path.read_text(encoding="utf-8"))
            existing_after_lecture = existing.get("workflows", {}).get("after_lecture", {})
            existing_teach = existing.get("workflows", {}).get("teach", {})
            record["sources"] = existing.get("sources", record["sources"])
            fresh_prepare = record["workflows"]["prepare_me"]
            record["workflows"] = existing.get("workflows", record["workflows"])
            if (record["workflows"].get("prepare_me") or {}).get("status") != "completed":
                record["workflows"]["prepare_me"] = fresh_prepare  # reflections-only record: now prepared
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


ASSISTANCE_RANK = {"UNAIDED": 0, "PROMPTED": 1, "REVEALED": 2}
EXPOSURE_KINDS = {"HINT": "PROMPTED", "EXPLANATION": "PROMPTED", "FEEDBACK": "PROMPTED", "REVEAL": "REVEALED"}


def task_text_hash(text: str | None) -> str | None:
    """Stable identity of a task's wording (case, punctuation and spacing ignored)."""
    words = " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return sha256(words.encode("utf-8")).hexdigest() if words else None


def task_exposure_keys(record: dict[str, Any]) -> set[str]:
    """Task keys the student has already been helped with, even if never answered."""
    return {e.get("task_key") for e in record.get("learning", {}).get("task_exposures", [])}


def exposed_task_hashes(record: dict[str, Any]) -> set[str]:
    """Wording hashes of helped tasks, so an identical question under another id is also spent."""
    return {e["task_text_hash"] for e in record.get("learning", {}).get("task_exposures", []) if e.get("task_text_hash")}


def _assistance_floor(record: dict[str, Any], task_key: str, task_text: str | None = None) -> tuple[str, list[str]]:
    """Weakest assistance status this task can honestly carry, with the reasons.

    "This task" means the same task key OR identical wording (so the same question
    reappearing in a later quiz is still the same task). A different question on
    the same concept is a different task and starts unaided. Derived only from the
    evidence record, so it holds across sessions and cannot be lowered by the caller.
    """
    text_hash = task_text_hash(task_text)
    floor, reasons = "UNAIDED", []

    def raise_to(status: str, reason: str) -> None:
        nonlocal floor
        if ASSISTANCE_RANK[status] > ASSISTANCE_RANK[floor]:
            floor = status
        if reason not in reasons:
            reasons.append(reason)

    for exposure in record.get("learning", {}).get("task_exposures", []):
        if exposure.get("task_key") == task_key or (text_hash and exposure.get("task_text_hash") == text_hash):
            raise_to(EXPOSURE_KINDS[exposure["kind"]], f"Earlier {exposure['kind'].lower()} on this task")
    for attempt in record.get("learning", {}).get("evidence", []):
        same_task = task_key in (attempt.get("task_key"), attempt.get("origin")) or (
            text_hash is not None and task_text_hash(attempt.get("task")) == text_hash)
        if same_task and attempt.get("assistance_status") in ("PROMPTED", "REVEALED"):
            raise_to(attempt["assistance_status"], "Earlier assisted attempt on this task")
    return floor, reasons


def record_task_exposure(module_code: str, week_number: int, *, task_key: str, kind: str,
                         session_id: str, turn_id: str, hint_level: int | None = None,
                         task_text: str | None = None, root: Path | None = None,
                         exposed_at: str | None = None) -> dict[str, Any]:
    """Durably note that a hint, explanation, feedback or answer was shown for a task.

    Idempotent on (session_id, turn_id, kind). Conservative rule: callers record the
    exposure immediately BEFORE the help is stored for display, so a crash in that
    narrow window can over-count help (the task is then treated as assisted although
    the student may not have seen it) but never under-count it. Callers must not
    record an exposure for help that was never produced (e.g. a failed model call).
    """
    if kind not in EXPOSURE_KINDS:
        raise StateError("Unsupported task exposure kind")
    record_path = _workspace_paths(module_code, week_number, root)[0]
    with record_lock(record_path):
        record, record_path, _, _ = _learning_record(module_code, week_number, root)
        exposures = record["learning"].setdefault("task_exposures", [])
        existing = next((e for e in exposures if (e["session_id"], e["turn_id"], e["kind"]) == (session_id, turn_id, kind)), None)
        if existing is not None:
            return deepcopy(existing)
        exposure = {"exposure_id": f"exposure-{len(exposures)+1:06d}", "task_key": task_key, "kind": kind,
                    "hint_level": hint_level, "session_id": session_id, "turn_id": turn_id,
                    "task_text_hash": task_text_hash(task_text),
                    "exposed_at": exposed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
        exposures.append(exposure)
        _write_record(record, record_path)
        return deepcopy(exposure)


def record_learning_attempt(module_code: str, week_number: int, *, capability: str, task: str,
                            origin: str, response: str, assistance_status: str = "UNAIDED",
                            prompt_help: list[str] | None = None, expected_answer: str | None = None,
                            source_references: list[dict[str, Any]] | None = None,
                            topic: str | None = None, root: Path | None = None,
                            attempted_at: str | None = None, session_id: str | None = None,
                            turn_id: str | None = None, hint_level: int | None = None,
                            task_key: str | None = None,
                            self_confidence: str | None = None,
                            lineage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append a raw student response before any evaluation is considered.

    With ``session_id`` and ``turn_id`` the call is idempotent: repeating it returns
    the stored attempt and never appends a second one. The stored assistance status
    can never be weaker than the task's recorded exposures and earlier assisted attempts.
    """
    if capability not in LEARNING_CAPABILITIES:
        raise StateError("Unsupported learning capability")
    if assistance_status not in ASSISTANCE_RANK:
        raise StateError("Assistance must be UNAIDED, PROMPTED or REVEALED")
    if (session_id is None) != (turn_id is None):
        raise StateError("session_id and turn_id must be supplied together")
    if not task.strip() or not response.strip():
        raise StateError("Task and response must not be empty")
    parsed_time = datetime.fromisoformat(attempted_at) if attempted_at else datetime.now(timezone.utc)
    if parsed_time.tzinfo is None:
        raise StateError("Learning attempt timestamp must include a timezone")
    timestamp = parsed_time.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    record_path = _workspace_paths(module_code, week_number, root)[0]
    with record_lock(record_path):
        record, record_path, _, _ = _learning_record(module_code, week_number, root)
        evidence = record["learning"]["evidence"]
        if session_id is not None:
            previous = next((a for a in evidence if (a.get("session_id"), a.get("turn_id")) == (session_id, turn_id)), None)
            if previous is not None:
                if previous["student_response"] != response:
                    raise StateError("This turn was already recorded with a different response")
                return deepcopy(previous)
        prompt_help = list(prompt_help or [])
        # Applies to every caller: the status can never be weaker than the task's history.
        floor, reasons = _assistance_floor(record, task_key or origin, task)
        if ASSISTANCE_RANK[floor] > ASSISTANCE_RANK[assistance_status]:
            assistance_status = floor
        prompt_help += [reason for reason in reasons if reason not in prompt_help]
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
            "assistance_status": assistance_status, "prompt_help": prompt_help,
            "source_references": stable_refs,
            "expected_answer": expected_answer, "evaluation": None,
        }
        if session_id is not None:
            attempt.update({"session_id": session_id, "turn_id": turn_id, "hint_level": hint_level,
                            "task_key": task_key})
        if lineage is not None:
            # Which question this was and what help came before it; classification is derived from it.
            attempt["lineage"] = deepcopy(lineage)
        if self_confidence is not None:
            # Student self-report: kept for the record, never an input to any evaluation.
            attempt["self_reported_confidence"] = self_confidence
        evidence.append(attempt)
        record["workspace_schema_version"] = WORKSPACE_SCHEMA_VERSION
        # Exports do not render learning evidence, so only the record is written.
        _write_record(record, record_path)
    return deepcopy(attempt)


def save_learning_evaluation(module_code: str, week_number: int, attempt_id: str,
                             evaluation: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    record_path = _workspace_paths(module_code, week_number, root)[0]
    with record_lock(record_path):
        record, record_path, _, _ = _learning_record(module_code, week_number, root)
        attempt = next((item for item in record["learning"]["evidence"] if item["attempt_id"] == attempt_id), None)
        if attempt is None:
            raise StateError("Learning attempt not found")
        if attempt.get("evaluation") is not None:
            raise StateError("Learning attempt already has an evaluation")
        attempt["evaluation"] = deepcopy(evaluation)
        _write_record(record, record_path)
        return deepcopy(attempt)


def effective_outcome(evaluation: dict[str, Any] | None) -> str | None:
    """The outcome other features should act on.

    The stored ``outcome`` is the model's historical judgement and is never rewritten. A
    NOT_SUPPORTED judgement the student disputed is read as UNCLEAR: it is neither counted
    against them nor treated as confirmed.
    """
    if not evaluation:
        return None
    outcome = evaluation.get("outcome")
    return "UNCLEAR" if outcome == "NOT_SUPPORTED" and evaluation.get("dispute") else outcome


def dispute_learning_evaluation(module_code: str, week_number: int, attempt_id: str, *, session_id: str,
                                turn_id: str, root: Path | None = None) -> dict[str, Any]:
    """Mark the model's diagnosis of an attempt as disputed by the student.

    Nothing is erased or rewritten: the raw response, assistance status, exposures and the
    evaluation's own outcome and reason stay as the model gave them. A ``dispute`` note is
    added beside them, and readers use ``effective_outcome``. Idempotent.
    """
    record_path = _workspace_paths(module_code, week_number, root)[0]
    with record_lock(record_path):
        record, record_path, _, _ = _learning_record(module_code, week_number, root)
        attempt = next((item for item in record["learning"]["evidence"] if item["attempt_id"] == attempt_id), None)
        if attempt is None:
            raise StateError("Learning attempt not found")
        evaluation = attempt.get("evaluation")
        if evaluation is None or evaluation.get("dispute"):
            return deepcopy(attempt)
        evaluation["dispute"] = {
            "status": "DISPUTED_BY_STUDENT", "session_id": session_id, "turn_id": turn_id,
            "disputed_outcome": evaluation.get("outcome"),
            "disputed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
        _write_record(record, record_path)
        return deepcopy(attempt)
