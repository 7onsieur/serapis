"""Pure views over a student's after-lecture reflections (no I/O, no model call).

A reflection is a *student-reported* capture stored append-only in
``workflows.after_lecture.captures``. A later correction never rewrites a capture: it is an entry in
``workflows.after_lecture.corrections`` that points at the capture entry it changes. These helpers fold the
two together into the "effective" reflections that exports, TEACH, REVISE and recommendations use, while
the original wording stays available for audit.

Nothing here is evidence of understanding or of what the university requires. Reflections describe what
the student chose to write down; assessment comments in particular are unverified remarks.
"""

from __future__ import annotations

import re
from typing import Any

#: (field, label shown to the student). Order is the order used on the page and in exports.
CAPTURE_FIELDS: tuple[tuple[str, str], ...] = (
    ("covered", "What the lecture covered"),
    ("understood", "What I understood"),
    ("uncertainties", "What I found confusing"),
    ("questions", "Questions I want answered"),
    ("examples_cases", "Examples the lecturer mentioned"),
    ("lecturer_emphasis", "What the lecturer emphasised"),
    ("assessment_comments", "Assessment-related comments (unconfirmed)"),
    ("lecture_notes", "My own notes and reflections"),
)
FIELD_LABELS = dict(CAPTURE_FIELDS)

#: Fields whose entries can be marked answered / reopened (they feed the open-items list).
OPEN_ITEM_FIELDS = {"uncertainties": "uncertainty", "questions": "question"}
CORRECTION_ACTIONS = ("correct", "withdraw", "resolve", "reopen")
#: Unresolved-item statuses that mean "no longer open" (the item and its history are kept).
CLOSED_ITEM_STATUSES = frozenset({"superseded", "withdrawn", "student_resolved"})

MAX_ENTRY_CHARS = 8000
MAX_ENTRIES_PER_FIELD = 40

ASSESSMENT_CAVEAT = (
    "Student-reported remark. It is not a confirmed deadline, weighting or requirement; "
    "check the module handbook, Blackboard or your lecturer."
)

_ENTRY_ID = re.compile(r"^(capture-\d{4}):([a-z_]+):(\d{1,4})$")


def make_entry_id(capture_id: str, field: str, index: int) -> str:
    return f"{capture_id}:{field}:{index}"


def parse_entry_id(entry_id: str) -> tuple[str, str, int] | None:
    match = _ENTRY_ID.match(entry_id or "")
    if not match or match.group(2) not in FIELD_LABELS:
        return None
    return match.group(1), match.group(2), int(match.group(3))


def _after_lecture(record: dict[str, Any] | None) -> dict[str, Any]:
    return ((record or {}).get("workflows") or {}).get("after_lecture") or {}


def effective_entries(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every captured entry with its latest state, oldest capture first.

    ``status``: ``active`` (as first written), ``corrected`` (latest wording differs), ``withdrawn``
    (student retracted it) or ``resolved`` (student marked a question/uncertainty answered). ``text`` is the
    current wording; ``original_text`` is always what was first written.
    """
    after = _after_lecture(record)
    by_entry: dict[str, list[dict[str, Any]]] = {}
    for correction in after.get("corrections", []):
        target = correction.get("corrects") or {}
        key = make_entry_id(target.get("capture_id", ""), target.get("field", ""), int(target.get("index", -1)))
        by_entry.setdefault(key, []).append(correction)
    entries: list[dict[str, Any]] = []
    for capture in after.get("captures", []):
        capture_id = capture.get("capture_id", "")
        for field, label in CAPTURE_FIELDS:
            for index, original in enumerate((capture.get("entries") or {}).get(field, [])):
                entry_id = make_entry_id(capture_id, field, index)
                history = by_entry.get(entry_id, [])
                text, status = original, "active"
                for correction in history:
                    action = correction.get("action")
                    if action == "correct":
                        text, status = correction.get("corrected_text", text), "corrected"
                    elif action == "withdraw":
                        status = "withdrawn"
                    elif action == "resolve":
                        status = "resolved"
                    elif action == "reopen":
                        status = "corrected" if text != original else "active"
                entries.append({
                    "entry_id": entry_id,
                    "capture_id": capture_id,
                    "captured_at": capture.get("captured_at"),
                    "field": field,
                    "label": label,
                    "index": index,
                    "original_text": original,
                    "text": text,
                    "status": status,
                    "history": history,
                    "can_resolve": field in OPEN_ITEM_FIELDS,
                })
    return entries


def effective_values(record: dict[str, Any] | None, field: str) -> list[str]:
    """Current wording of every entry in ``field`` the student has not withdrawn or marked answered."""
    return [e["text"] for e in effective_entries(record)
            if e["field"] == field and e["status"] in ("active", "corrected")]


def resolved_values(record: dict[str, Any] | None) -> list[dict[str, str]]:
    return [{"kind": OPEN_ITEM_FIELDS[e["field"]], "text": e["text"]}
            for e in effective_entries(record) if e["status"] == "resolved"]


def reflection_view(record: dict[str, Any] | None) -> dict[str, Any]:
    """Page-ready structure: captures newest first, each with its entries and their correction history."""
    entries = effective_entries(record)
    captures: dict[str, dict[str, Any]] = {}
    for entry in entries:
        group = captures.setdefault(entry["capture_id"], {
            "capture_id": entry["capture_id"], "captured_at": entry["captured_at"], "entries": []})
        group["entries"].append(entry)
    ordered = list(reversed(list(captures.values())))
    return {"captures": ordered, "count": len(captures),
            "open_count": len(open_reflection_items(record))}


def open_reflection_items(record: dict[str, Any] | None, *, limit: int = 8) -> list[dict[str, str]]:
    """Open student questions and confusions (current wording), questions first."""
    items = [{"kind": OPEN_ITEM_FIELDS[e["field"]], "text": e["text"], "entry_id": e["entry_id"]}
             for e in effective_entries(record)
             if e["field"] in OPEN_ITEM_FIELDS and e["status"] in ("active", "corrected")]
    items.sort(key=lambda i: 0 if i["kind"] == "question" else 1)
    return items[:limit]


def reflection_context(record: dict[str, Any] | None, *, per_field: int = 6, max_chars: int = 400) -> dict[str, Any] | None:
    """What a model may see for REVISE: the student's current open questions, confusions and remarks.

    Bounded and labelled. The student's words are untrusted data and are never official-source claims.
    Returns None when the student has recorded nothing, so a revision brief stays general and says so.
    """
    def clip(values: list[str]) -> list[str]:
        return [" ".join(v.split())[:max_chars] for v in values[:per_field]]

    open_questions = clip(effective_values(record, "questions"))
    confusions = clip(effective_values(record, "uncertainties"))
    emphasis = clip(effective_values(record, "lecturer_emphasis"))
    assessment = clip(effective_values(record, "assessment_comments"))
    if not (open_questions or confusions or emphasis or assessment):
        return None
    view: dict[str, Any] = {
        "classification": "student_reported",
        "note": ("The student's own after-lecture remarks. They show what the student chose to write down, "
                 "not what they know or what the university requires. Use them only to decide what to "
                 "cover first; never present them as official-source claims."),
        "open_questions": open_questions,
        "found_confusing": confusions,
        "lecturer_emphasis_reported": emphasis,
        "assessment_remarks_unconfirmed": assessment,
    }
    return {k: v for k, v in view.items() if v}


def next_step_from_reflections(record: dict[str, Any] | None) -> dict[str, str] | None:
    """A modest suggestion from open reflections, or None. Never a claim about understanding."""
    items = open_reflection_items(record, limit=1)
    if not items:
        return None
    item = items[0]
    what = "question" if item["kind"] == "question" else "point you found confusing"
    return {
        "action": f"Ask TEACH about your open {what}",
        "reason": ("You noted it after the lecture, so it is a good place to start. This shows what you "
                   "wanted to clarify, not what you do or do not know."),
        "topic": item["text"],
    }
