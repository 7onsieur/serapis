"""Storage primitives and read-only views for Assignment Coach sessions.

Paths, atomic private writes, damaged-file detection, the locked read-modify-write helper and the
student-safe ``view`` live here so the lifecycle, notes and conversation modules share one definition.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coach_analysis import gap_report, progress_summary
from .locking import record_lock
from .state import StateError, get_module, normalize_academic_truth
from .workspace import _safe_component, default_workspace_root

SESSION_SCHEMA_VERSION = 1
PROMPT_VERSION = "assignment-coach-turn-v3"
STAGES = ("UNDERSTAND", "PLAN", "EVIDENCE", "DRAFT", "REVIEW")
SECTION_STATUSES = ("PLANNED", "DRAFTING", "DONE")
EVIDENCE_KINDS = ("COURSE_MATERIAL", "EXTERNAL_SOURCE", "OWN_WORK")
EVIDENCE_STATUSES = ("NEEDED", "FOUND")

MAX_MESSAGE_CHARS = 4_000
MAX_ITEM_CHARS = 600
MAX_PLAN_TEXT_CHARS = 2_000
MAX_ITEMS = 40  # per list: requirements, criteria, sections, evidence, questions
MAX_MODEL_CALLS = 40
MAX_TURNS = 120
MAX_REJECTED_REPLIES = 2
RECENT_TURNS = 6
STALE_PENDING_SECONDS = 120
MAX_ID_CHARS = 80

_SESSION_ID = re.compile(r"coach-[0-9a-f]{12}")
_ID_PREFIX = {"requirements": "r", "criteria": "c", "sections": "s", "evidence": "e", "questions": "q"}

class CoachSessionError(StateError):
    """An Assignment Coach request that cannot proceed (conflict, limit, ended session)."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _age_seconds(timestamp: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds()




def _sessions_dir(module_code: str, root: Path | None) -> Path:
    return (root or default_workspace_root()) / _safe_component(module_code.upper()) / "assignment-coach"


def _session_path(module_code: str, session_id: str, root: Path | None) -> Path:
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise CoachSessionError("Invalid Assignment Coach session id")
    return _sessions_dir(module_code, root) / f"{session_id}.json"


def _private_dir(directory: Path) -> None:
    """Create the folder owner-only and self-ignoring for Git (it holds the student's own notes)."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    ignore = directory / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")


def _write(path: Path, session: dict[str, Any]) -> None:
    session["updated_at"] = _now()
    session["revision"] = session.get("revision", 0) + 1
    _private_dir(path.parent)
    temp = path.with_suffix(".json.tmp")
    with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as handle:
        handle.write((json.dumps(session, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def _read(path: Path, module_code: str) -> dict[str, Any]:
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CoachSessionError("Assignment Coach session not found") from exc
    except json.JSONDecodeError as exc:
        raise CoachSessionError(f"Assignment Coach session file is corrupt: {path.name}") from exc
    if (
        not isinstance(session, dict)
        or session.get("schema_version") != SESSION_SCHEMA_VERSION
        or session.get("session_id") != path.stem
        or str(session.get("module_code", "")).upper() != module_code.upper()
    ):
        raise CoachSessionError("Assignment Coach session file does not match this module")
    # A hand-edited or damaged file must fail here, with a clear message, not as a KeyError deep in a page.
    lists = ("turns", "requirements", "criteria", "sections", "evidence", "questions", "materials")
    if (any(not isinstance(session.get(key), list) for key in lists)
            or not isinstance(session.get("plan"), dict) or not isinstance(session.get("assessment"), dict)
            or not isinstance(session.get("counters", {}), dict) or not isinstance(session.get("usage", {}), dict)
            or session.get("status") not in ("ACTIVE", "ENDED") or session.get("stage") not in STAGES
            or not isinstance(session.get("assessment_id"), str) or not isinstance(session.get("model_calls"), int)
            or any(not isinstance(item, dict) for key in lists for item in session[key])):
        raise CoachSessionError(f"Assignment Coach session file is damaged: {path.name}")
    return session


def _clean_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_ID_CHARS:
        raise CoachSessionError(f"{label} must be a non-empty string of at most {MAX_ID_CHARS} characters")
    return value.strip()


def _text(value: Any, label: str, *, limit: int = MAX_ITEM_CHARS, required: bool = True) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if required and not text:
        raise CoachSessionError(f"{label} cannot be empty.")
    if len(text) > limit:
        raise CoachSessionError(f"{label} must be at most {limit} characters.")
    return text


def _next_id(session: dict[str, Any], collection: str) -> str:
    counters = session.setdefault("counters", {})
    counters[collection] = counters.get(collection, 0) + 1
    return f"{_ID_PREFIX[collection]}{counters[collection]}"


def _room(session: dict[str, Any], collection: str, label: str) -> None:
    if len(session[collection]) >= MAX_ITEMS:
        raise CoachSessionError(f"This session already has the maximum of {MAX_ITEMS} {label}.")


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _mutate(module_code: str, session_id: str, root: Path | None, change, *, allow_ended: bool = False) -> dict[str, Any]:
    path = _session_path(module_code, session_id, root)
    with record_lock(path, create_dir=True):
        session = _read(path, module_code)
        if session["status"] != "ACTIVE" and not allow_ended:
            raise CoachSessionError("This session has ended. Reopen it to keep editing, or start a new one.")
        change(session)
        _write(path, session)
        return view(session)



def _find_assessment(state: dict[str, Any], module_code: str, assessment_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    module = get_module(normalize_academic_truth(state), module_code)
    assessment = next((a for a in module.get("assessments", []) if a.get("id") == assessment_id), None)
    if assessment is None:
        raise CoachSessionError("That assessment was not found in this module. Add or reopen it from the module page.")
    return module, assessment


def material_report(state: dict[str, Any], module_code: str) -> list[dict[str, Any]]:
    """Cheap, deterministic view of a module's materials and whether this platform can read their text."""
    state = normalize_academic_truth(state)
    rows = []
    for source in state.get("sources", []):
        if str(source.get("module_code", "")).upper() != module_code.upper():
            continue
        suffix = Path(str(source.get("locator", ""))).suffix.lower()
        if suffix == ".pptx":
            readable, note = True, "PowerPoint text can be read."
        elif suffix == ".pdf":
            import sys
            readable = sys.platform == "darwin"
            note = "PDF text can be read." if readable else "PDF text extraction is macOS-only; this file cannot be searched here."
        else:
            readable, note = False, "This file type is not supported for text extraction."
        rows.append({"source_id": source["id"], "title": source.get("title") or source["id"],
                     "week": source.get("week"), "readable": readable, "note": note})
    return rows


def _requirements_from(assessment: dict[str, Any]) -> list[tuple[str, str]]:
    status = assessment.get("fact_provenance", {}).get("requirements", {}).get("status", "UNKNOWN")
    return [(item, status) for item in assessment.get("requirements") or []]


def _snapshot(assessment: dict[str, Any]) -> dict[str, Any]:
    facts = assessment.get("fact_provenance", {})
    return {
        "title": assessment.get("title"),
        "deadline": assessment.get("deadline"),
        "weight_percent": assessment.get("weight_percent"),
        "fact_status": {f: facts.get(f, {}).get("status", "UNKNOWN") for f in ("title", "deadline", "weight_percent", "requirements")},
        "taken_at": _now(),
    }


def _student_turns(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in session["turns"] if t["role"] == "student"]


def _recoverable(session: dict[str, Any]) -> dict[str, Any] | None:
    turns = _student_turns(session)
    return turns[-1] if turns and turns[-1]["status"] in ("PENDING", "FAILED") else None


def view(session: dict[str, Any], *, state: dict[str, Any] | None = None) -> dict[str, Any]:
    out = deepcopy(session)
    if state is not None:
        # Read-only refresh: materials added or removed since the session began are shown (and counted in the
        # gaps) without writing anything.
        out["materials"] = material_report(state, session["module_code"])
    pending = _recoverable(session)
    in_flight = (pending is not None and pending["status"] == "PENDING"
                 and _age_seconds(pending["started_at"]) < STALE_PENDING_SECONDS)
    out["recovery"] = ({"client_turn_id": pending["client_turn_id"], "text": pending["text"],
                        "shared_work": pending.get("shared_work", False),
                        "state": "IN_PROGRESS" if in_flight else "RETRY"} if pending else None)
    out["gaps"] = gap_report(out)
    out["progress"] = progress_summary(session)
    out["calls_remaining"] = max(0, MAX_MODEL_CALLS - session["model_calls"])
    out["can_send"] = session["status"] == "ACTIVE" and (pending is None or not in_flight)
    if state is not None:
        try:
            _module, assessment = _find_assessment(state, session["module_code"], session["assessment_id"])
            current = [_norm(t) for t, _ in _requirements_from(assessment)]
            known = [_norm(r["text"]) for r in session["requirements"] if r["origin"] == "ASSESSMENT_RECORD" and not r.get("removed_from_assessment")]
            out["assessment_changed"] = (sorted(current) != sorted(known)
                                         or assessment.get("title") != session["assessment"].get("title")
                                         or assessment.get("deadline") != session["assessment"].get("deadline"))
        except StateError:
            out["assessment_changed"] = None
            out["assessment_missing"] = True
    return out


