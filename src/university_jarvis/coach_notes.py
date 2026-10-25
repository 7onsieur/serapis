"""The student's own working notes for one assignment: criteria, plan, sections, evidence, questions, stage.

Every function here is a local, locked read-modify-write of the session file. None calls a model, and none
can mark anything CONFIRMED: the student authors and resolves everything in these lists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .coach_store import (
    EVIDENCE_KINDS,
    EVIDENCE_STATUSES,
    MAX_PLAN_TEXT_CHARS,
    SECTION_STATUSES,
    STAGES,
    CoachSessionError,
    _mutate,
    _next_id,
    _norm,
    _now,
    _room,
    _text,
    material_report,
)

def _lines(value: str, label: str) -> list[str]:
    rows = [line.strip(" \t-*•") for line in (value or "").splitlines()]
    rows = [r for r in rows if r]
    if not rows:
        raise CoachSessionError(f"Enter at least one {label}.")
    for row in rows:
        _text(row, label.capitalize())
    return rows


def add_brief_items(module_code: str, session_id: str, *, kind: str, text: str,
                    workspace_root: Path | None = None) -> dict[str, Any]:
    """Add requirements or marking criteria (one per line) that the student read in their brief."""
    if kind not in ("requirements", "criteria"):
        raise CoachSessionError("Unknown brief item type.")
    rows = _lines(text, "requirement" if kind == "requirements" else "marking criterion")

    def change(s: dict[str, Any]) -> None:
        existing = {_norm(i["text"]) for i in s[kind]}
        for row in rows:
            if _norm(row) in existing:
                continue
            _room(s, kind, kind)
            s[kind].append({"id": _next_id(s, kind), "text": row, "origin": "STUDENT_ENTERED",
                            "status": "NEEDS_VERIFICATION", "removed_from_assessment": False})
            existing.add(_norm(row))
    return _mutate(module_code, session_id, workspace_root, change)


def remove_brief_item(module_code: str, session_id: str, item_id: str, *, workspace_root: Path | None = None) -> dict[str, Any]:
    def change(s: dict[str, Any]) -> None:
        for kind in ("requirements", "criteria"):
            if any(i["id"] == item_id for i in s[kind]):
                s[kind] = [i for i in s[kind] if i["id"] != item_id]
                for section in s["sections"]:
                    section["addresses"] = [a for a in section["addresses"] if a != item_id]
                return
        raise CoachSessionError("That requirement or criterion was not found.")
    return _mutate(module_code, session_id, workspace_root, change)


def save_plan_overview(module_code: str, session_id: str, *, main_argument: str, notes: str,
                       workspace_root: Path | None = None) -> dict[str, Any]:
    argument = _text(main_argument, "Main argument", limit=MAX_PLAN_TEXT_CHARS, required=False)
    note = _text(notes, "Notes", limit=MAX_PLAN_TEXT_CHARS, required=False)

    def change(s: dict[str, Any]) -> None:
        s["plan"] = {"main_argument": argument, "notes": note, "updated_at": _now()}
    return _mutate(module_code, session_id, workspace_root, change)


def _valid_links(s: dict[str, Any], addresses: list[str], evidence_ids: list[str]) -> tuple[list[str], list[str]]:
    brief_ids = {i["id"] for kind in ("requirements", "criteria") for i in s[kind]}
    evidence = {e["evidence_id"] for e in s["evidence"]}
    if any(a not in brief_ids for a in addresses) or any(e not in evidence for e in evidence_ids):
        raise CoachSessionError("A section can only link to requirements, criteria and evidence in this session.")
    return list(dict.fromkeys(addresses)), list(dict.fromkeys(evidence_ids))


def save_section(module_code: str, session_id: str, *, section_id: str | None = None, heading: str, point: str = "",
                 addresses: list[str] | None = None, evidence_ids: list[str] | None = None, status: str = "PLANNED",
                 workspace_root: Path | None = None) -> dict[str, Any]:
    """Add (no ``section_id``) or update one section of the student's plan."""
    heading = _text(heading, "Section heading")
    point = _text(point, "Key point", limit=MAX_PLAN_TEXT_CHARS, required=False)
    if status not in SECTION_STATUSES:
        raise CoachSessionError("Unknown section status.")

    def change(s: dict[str, Any]) -> None:
        links = _valid_links(s, addresses or [], evidence_ids or [])
        row = {"heading": heading, "point": point, "addresses": links[0], "evidence_ids": links[1], "status": status}
        if section_id is None:
            _room(s, "sections", "sections")
            s["sections"].append({"section_id": _next_id(s, "sections"), **row})
            return
        target = next((x for x in s["sections"] if x["section_id"] == section_id), None)
        if target is None:
            raise CoachSessionError("That section was not found.")
        target.update(row)
    return _mutate(module_code, session_id, workspace_root, change)


def move_section(module_code: str, session_id: str, section_id: str, direction: str, *,
                 workspace_root: Path | None = None) -> dict[str, Any]:
    def change(s: dict[str, Any]) -> None:
        index = next((i for i, x in enumerate(s["sections"]) if x["section_id"] == section_id), None)
        if index is None:
            raise CoachSessionError("That section was not found.")
        swap = index - 1 if direction == "up" else index + 1
        if 0 <= swap < len(s["sections"]):
            s["sections"][index], s["sections"][swap] = s["sections"][swap], s["sections"][index]
    return _mutate(module_code, session_id, workspace_root, change)


def remove_section(module_code: str, session_id: str, section_id: str, *, workspace_root: Path | None = None) -> dict[str, Any]:
    def change(s: dict[str, Any]) -> None:
        if not any(x["section_id"] == section_id for x in s["sections"]):
            raise CoachSessionError("That section was not found.")
        s["sections"] = [x for x in s["sections"] if x["section_id"] != section_id]
    return _mutate(module_code, session_id, workspace_root, change)


def save_evidence(module_code: str, session_id: str, *, evidence_id: str | None = None, description: str,
                  kind: str = "COURSE_MATERIAL", status: str = "NEEDED", source_id: str | None = None,
                  pdf_page: int | None = None, note: str = "", workspace_root: Path | None = None,
                  state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add or update an evidence item. The student alone marks it FOUND.

    With ``state`` the material is checked against the module's current materials, so a file added after the
    session began can be cited.
    """
    description = _text(description, "Evidence description")
    note = _text(note, "Note", required=False)
    if kind not in EVIDENCE_KINDS or status not in EVIDENCE_STATUSES:
        raise CoachSessionError("Unknown evidence type or status.")
    source_id = (source_id or "").strip() or None
    if pdf_page is not None and (isinstance(pdf_page, bool) or not isinstance(pdf_page, int) or pdf_page < 1):
        raise CoachSessionError("Page or slide must be a positive number.")

    def change(s: dict[str, Any]) -> None:
        if state is not None:
            s["materials"] = material_report(state, s["module_code"])
        if source_id is not None and source_id not in {m["source_id"] for m in s["materials"]}:
            raise CoachSessionError("That course material is not part of this module.")
        row = {"description": description, "kind": kind, "status": status, "source_id": source_id,
               "pdf_page": pdf_page if source_id else None, "note": note}
        if evidence_id is None:
            _room(s, "evidence", "evidence items")
            s["evidence"].append({"evidence_id": _next_id(s, "evidence"), "origin": "STUDENT", **row})
            return
        target = next((e for e in s["evidence"] if e["evidence_id"] == evidence_id), None)
        if target is None:
            raise CoachSessionError("That evidence item was not found.")
        target.update(row)
    return _mutate(module_code, session_id, workspace_root, change)


def remove_evidence(module_code: str, session_id: str, evidence_id: str, *, workspace_root: Path | None = None) -> dict[str, Any]:
    def change(s: dict[str, Any]) -> None:
        if not any(e["evidence_id"] == evidence_id for e in s["evidence"]):
            raise CoachSessionError("That evidence item was not found.")
        s["evidence"] = [e for e in s["evidence"] if e["evidence_id"] != evidence_id]
        for section in s["sections"]:
            section["evidence_ids"] = [e for e in section["evidence_ids"] if e != evidence_id]
    return _mutate(module_code, session_id, workspace_root, change)


def add_question(module_code: str, session_id: str, *, text: str, workspace_root: Path | None = None) -> dict[str, Any]:
    text = _text(text, "Question")

    def change(s: dict[str, Any]) -> None:
        _room(s, "questions", "questions")
        s["questions"].append({"question_id": _next_id(s, "questions"), "text": text, "origin": "STUDENT",
                               "status": "OPEN", "answer": "", "created_at": _now(), "resolved_at": None})
    return _mutate(module_code, session_id, workspace_root, change)


def resolve_question(module_code: str, session_id: str, question_id: str, *, answer: str = "", reopen: bool = False,
                     workspace_root: Path | None = None) -> dict[str, Any]:
    answer = _text(answer, "Answer", limit=MAX_PLAN_TEXT_CHARS, required=False)

    def change(s: dict[str, Any]) -> None:
        target = next((q for q in s["questions"] if q["question_id"] == question_id), None)
        if target is None:
            raise CoachSessionError("That question was not found.")
        if reopen:
            target.update(status="OPEN", resolved_at=None)
        else:
            target.update(status="RESOLVED", answer=answer, resolved_at=_now())
    return _mutate(module_code, session_id, workspace_root, change)


def remove_question(module_code: str, session_id: str, question_id: str, *, workspace_root: Path | None = None) -> dict[str, Any]:
    def change(s: dict[str, Any]) -> None:
        if not any(q["question_id"] == question_id for q in s["questions"]):
            raise CoachSessionError("That question was not found.")
        s["questions"] = [q for q in s["questions"] if q["question_id"] != question_id]
    return _mutate(module_code, session_id, workspace_root, change)


def set_stage(module_code: str, session_id: str, stage: str, *, workspace_root: Path | None = None) -> dict[str, Any]:
    if stage not in STAGES:
        raise CoachSessionError("Unknown stage.")

    def change(s: dict[str, Any]) -> None:
        s["stage"] = stage
    return _mutate(module_code, session_id, workspace_root, change)


# ---------------------------------------------------------------------------------------------------------
