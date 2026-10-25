"""Persistent, resumable Assignment Coach sessions.

One session belongs to ONE assessment of ONE module and lives in a private JSON file under
``<workspace>/<MODULE>/assignment-coach/``. It is the student's working notebook for that
assignment and survives restarts:

* the assignment's requirements (from the assessment record, with its trust status) and the
  marking criteria the student enters, each with an explicit provenance and status;
* the student's own plan (main argument, sections, which requirement or criterion each section
  addresses), the evidence they still need or have found, and their open questions;
* a conversation in which the student leads and the coach replies from course material.

Authorship and trust rules (deliberate, and enforced in code rather than only in the prompt):

* The student's plan, evidence and questions are written by the student. The model never edits
  them. A coach reply may *suggest* follow-up questions and evidence to look for; they are stored
  as OPEN/NEEDED, tagged ``COACH``/``COACH_SUGGESTED``, and only the student can resolve them.
* Requirements and criteria are never promoted to CONFIRMED by this module. Requirements keep the
  assessment's own fact status; criteria the student types are ``NEEDS_VERIFICATION``.
* A request to write the assessed work is refused before any model call (``classify_request``),
  and a model reply that reads like submission text, or that contains a reference that is in
  neither the supplied course material nor the student's own text, is discarded
  (``check_reply``). These are heuristic safeguards, not a guarantee; see the pilot guidance.
* Gaps (unaddressed requirements, missing evidence, open questions, unverified facts) are computed
  deterministically from the session by ``gap_report``; progress is a set of counts, never a score.

Every model turn is claimed under the session lock, executed outside it and finalised under it
again, exactly like the Tutor, so a repeated ``client_turn_id`` retries instead of duplicating.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .coach_analysis import gap_report, progress_summary  # noqa: F401  (re-exported)
from .coach_integrity import (
    COACH_FORMAT,
    COACH_INSTRUCTIONS,
    FALLBACK_REPLY,
    REFUSAL_REPLY,  # noqa: F401  (re-exported)
    ReplyRejected,
    check_reply,
    classify_request,
)
from .coach_notes import (  # noqa: F401  (re-exported: the public API of this feature)
    add_brief_items,
    add_question,
    move_section,
    remove_brief_item,
    remove_evidence,
    remove_question,
    remove_section,
    resolve_question,
    save_evidence,
    save_plan_overview,
    save_section,
    set_stage,
)
from .coach_store import (  # noqa: F401
    EVIDENCE_KINDS,
    EVIDENCE_STATUSES,
    MAX_ID_CHARS,
    MAX_ITEMS,
    MAX_ITEM_CHARS,
    MAX_MESSAGE_CHARS,
    MAX_MODEL_CALLS,
    MAX_PLAN_TEXT_CHARS,
    MAX_REJECTED_REPLIES,
    MAX_TURNS,
    PROMPT_VERSION,
    RECENT_TURNS,
    SECTION_STATUSES,
    SESSION_SCHEMA_VERSION,
    STAGES,
    STALE_PENDING_SECONDS,
    CoachSessionError,
    _age_seconds,
    _clean_id,
    _find_assessment,
    _mutate,
    _next_id,
    _norm,
    _now,
    _private_dir,
    _read,
    _recoverable,
    _requirements_from,
    _room,
    _session_path,
    _sessions_dir,
    _snapshot,
    _student_turns,
    _text,
    _write,
    material_report,
    view,
)
from .locking import record_lock
from .reasoning import OBJECTIVE_INSTRUCTIONS, ReasoningError, ReasoningProvider
from .sources import render_source_location
from .state import StateError
from .workflows import build_assignment_coach_context
import re
import uuid

def start_session(state: dict[str, Any], module_code: str, assessment_id: str, *, client_request_id: str,
                  workspace_root: Path | None = None, force_new: bool = False) -> dict[str, Any]:
    """Open the assessment's coaching session: resume the active one, or create it. Never calls a model.

    A repeated ``client_request_id`` returns the same session. With ``force_new`` any active session for
    the assessment is ended first (kept on disk, read-only) and a fresh one begins, carrying over the
    student's own criteria, plan, sections, evidence and open questions (never the conversation), so a long
    session is never a dead end.
    """
    client_request_id = _clean_id(client_request_id, "client_request_id")
    module, assessment = _find_assessment(state, module_code, assessment_id)
    code = module["code"]
    directory = _sessions_dir(code, workspace_root)
    _private_dir(directory)
    with record_lock(directory / "index", create_dir=True):
        sessions = _all_sessions(code, workspace_root)
        for found in sessions:
            if found.get("client_request_id") == client_request_id:
                if found["assessment_id"] != assessment_id:
                    raise CoachSessionError("This request id was already used for a different assignment; reload the page.")
                return view(found)
        active = [s for s in sessions if s["assessment_id"] == assessment_id and s["status"] == "ACTIVE"]
        if active and not force_new:
            return view(active[-1])
        carried = None
        for old in active:
            old_path = _session_path(code, old["session_id"], workspace_root)
            with record_lock(old_path, create_dir=True):  # lock order: index, then session
                latest = _read(old_path, code)  # re-read: a reply may have been saved since the listing
                latest.update(status="ENDED", ended_at=_now(), end_reason="REPLACED_BY_NEW_SESSION")
                _write(old_path, latest)
                carried = latest
        now = _now()
        session_id = f"coach-{uuid.uuid4().hex[:12]}"
        session: dict[str, Any] = {
            "schema_version": SESSION_SCHEMA_VERSION, "session_id": session_id, "module_code": code,
            "assessment_id": assessment_id, "status": "ACTIVE", "client_request_id": client_request_id,
            "created_at": now, "ended_at": None, "end_reason": None, "stage": "UNDERSTAND",
            "assessment": _snapshot(assessment), "requirements": [], "criteria": [],
            "plan": {"main_argument": "", "notes": ""}, "sections": [], "evidence": [], "questions": [],
            "counters": {}, "turns": [], "model_calls": 0, "usage": {}, "provider": None,
            "prompt_version": PROMPT_VERSION, "materials": material_report(state, code), "revision": 0,
        }
        for text, status in _requirements_from(assessment):
            session["requirements"].append({
                "id": _next_id(session, "requirements"), "text": text, "origin": "ASSESSMENT_RECORD",
                "status": status, "removed_from_assessment": False})
        if carried is not None:
            _carry_over(session, carried)
        _write(_session_path(code, session_id, workspace_root), session)
        return view(session)


def _carry_over(new: dict[str, Any], old: dict[str, Any]) -> None:
    """Copy the student's own working notes into a fresh session, remapping ids so links stay valid."""
    mapping: dict[str, str] = {}
    for row in old["requirements"]:
        match = next((r for r in new["requirements"] if _norm(r["text"]) == _norm(row["text"])), None)
        if match is not None:
            mapping[row["id"]] = match["id"]
        elif row["origin"] == "STUDENT_ENTERED":
            copy = {**row, "id": _next_id(new, "requirements")}
            new["requirements"].append(copy)
            mapping[row["id"]] = copy["id"]
    for row in old["criteria"]:
        copy = {**row, "id": _next_id(new, "criteria")}
        new["criteria"].append(copy)
        mapping[row["id"]] = copy["id"]
    for row in old["evidence"]:
        copy = {**row, "evidence_id": _next_id(new, "evidence")}
        new["evidence"].append(copy)
        mapping[row["evidence_id"]] = copy["evidence_id"]
    for row in old["sections"]:
        new["sections"].append({**row, "section_id": _next_id(new, "sections"),
                                "addresses": [mapping[a] for a in row["addresses"] if a in mapping],
                                "evidence_ids": [mapping[e] for e in row["evidence_ids"] if e in mapping]})
    for row in old["questions"]:
        new["questions"].append({**row, "question_id": _next_id(new, "questions")})
    new["plan"] = dict(old["plan"])
    new["stage"] = old["stage"]
    new["carried_over_from"] = old["session_id"]


def _all_sessions(module_code: str, root: Path | None) -> list[dict[str, Any]]:
    directory = _sessions_dir(module_code, root)
    sessions = []
    for path in sorted(directory.glob("coach-*.json")) if directory.is_dir() else []:
        try:
            sessions.append(_read(path, module_code))
        except CoachSessionError:
            continue
    return sorted(sessions, key=lambda s: s["created_at"])


def load_session(module_code: str, session_id: str, *, workspace_root: Path | None = None,
                 state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read-only: the stored session plus computed gaps and progress. Never writes, never calls a model."""
    session = _read(_session_path(module_code, session_id, workspace_root), module_code)
    return view(session, state=state)


def list_sessions(module_code: str, *, workspace_root: Path | None = None,
                  assessment_id: str | None = None) -> list[dict[str, Any]]:
    """Read-only summaries, most recently updated first."""
    rows = []
    for s in _all_sessions(module_code, workspace_root):
        if assessment_id is not None and s["assessment_id"] != assessment_id:
            continue
        progress = progress_summary(s)
        rows.append({"session_id": s["session_id"], "module_code": s["module_code"],
                     "assessment_id": s["assessment_id"], "assessment_title": s["assessment"].get("title"),
                     "status": s["status"], "stage": s["stage"], "created_at": s["created_at"],
                     "updated_at": s.get("updated_at", s["created_at"]), "next_step": progress["next_step"],
                     "open_questions": progress["questions"]["open"], "gap_count": len(gap_report(s))})
    return sorted(rows, key=lambda r: r["updated_at"], reverse=True)


def end_session(module_code: str, session_id: str, *, workspace_root: Path | None = None) -> dict[str, Any]:
    def change(s: dict[str, Any]) -> None:
        s.update(status="ENDED", ended_at=_now(), end_reason="STUDENT_ENDED")
    return _mutate(module_code, session_id, workspace_root, change, allow_ended=True)


def reopen_session(module_code: str, session_id: str, *, workspace_root: Path | None = None) -> dict[str, Any]:
    path = _session_path(module_code, session_id, workspace_root)
    with record_lock(_sessions_dir(module_code, workspace_root) / "index", create_dir=True):
        with record_lock(path, create_dir=True):
            session = _read(path, module_code)
            clash = [s for s in _all_sessions(module_code, workspace_root)
                     if s["assessment_id"] == session["assessment_id"] and s["status"] == "ACTIVE" and s["session_id"] != session_id]
            if clash:
                raise CoachSessionError("Another session for this assignment is active. End it first, or keep using it.")
            session.update(status="ACTIVE", ended_at=None, end_reason=None)
            _write(path, session)
            return view(session)


def delete_session(module_code: str, session_id: str, *, workspace_root: Path | None = None) -> None:
    """Delete the session file (the student's notes and transcript). Refused while a message is in flight."""
    path = _session_path(module_code, session_id, workspace_root)
    with record_lock(path, create_dir=True):
        session = _read(path, module_code)
        pending = _recoverable(session)
        if pending is not None and pending["status"] == "PENDING" and _age_seconds(pending["started_at"]) < STALE_PENDING_SECONDS:
            raise CoachSessionError("A message in this session is still being processed; try again shortly.")
        path.unlink()
        path.with_suffix(".json.tmp").unlink(missing_ok=True)
    path.with_name(path.name + ".lock").unlink(missing_ok=True)


def discard_unfinished(module_code: str, session_id: str, *, workspace_root: Path | None = None) -> dict[str, Any]:
    """Drop an interrupted message the student no longer wants to retry (for example no AI key is set up).

    A message that is still being processed (fresh PENDING) cannot be discarded. The text is kept in the
    transcript, marked ABANDONED, so nothing the student typed silently vanishes.
    """
    def change(s: dict[str, Any]) -> None:
        turn = _recoverable(s)
        if turn is None:
            raise CoachSessionError("There is no unfinished message to discard.")
        if turn["status"] == "PENDING" and _age_seconds(turn["started_at"]) < STALE_PENDING_SECONDS:
            raise CoachSessionError("That message is still being processed; try again shortly.")
        turn["status"] = "ABANDONED"
    return _mutate(module_code, session_id, workspace_root, change)


def sync_with_assessment(state: dict[str, Any], module_code: str, session_id: str, *,
                         workspace_root: Path | None = None) -> dict[str, Any]:
    """Pull edits made to the assessment record into the session without losing the student's plan.

    New requirement text is added; a requirement no longer in the assessment is flagged
    (``removed_from_assessment``) rather than deleted, because plan sections may already address it.
    """
    session = _read(_session_path(module_code, session_id, workspace_root), module_code)
    _module, assessment = _find_assessment(state, module_code, session["assessment_id"])

    def change(s: dict[str, Any]) -> None:
        current = _requirements_from(assessment)
        have = {_norm(r["text"]): r for r in s["requirements"] if r["origin"] == "ASSESSMENT_RECORD"}
        for text, status in current:
            row = have.get(_norm(text))
            if row is not None:
                row.update(status=status, removed_from_assessment=False)
            else:
                _room(s, "requirements", "requirements")
                s["requirements"].append({"id": _next_id(s, "requirements"), "text": text,
                                          "origin": "ASSESSMENT_RECORD", "status": status,
                                          "removed_from_assessment": False})
        keep = {_norm(t) for t, _ in current}
        for row in s["requirements"]:
            if row["origin"] == "ASSESSMENT_RECORD" and _norm(row["text"]) not in keep:
                row["removed_from_assessment"] = True
        s["assessment"] = _snapshot(assessment)
        s["materials"] = material_report(state, s["module_code"])
    return _mutate(module_code, session_id, workspace_root, change)


# ---------------------------------------------------------------------------------------------------------
def _claim(path: Path, module_code: str, client_turn_id: str, text: str, shared_work: bool) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Claim (or recover) a turn under the lock. Returns (session, turn, already_done)."""
    with record_lock(path, create_dir=True):
        session = _read(path, module_code)
        turn = next((t for t in _student_turns(session) if t["client_turn_id"] == client_turn_id), None)
        if turn is not None:
            if turn["text"] != text or bool(turn.get("shared_work")) != shared_work:
                raise CoachSessionError("This message id was already used for a different message")
            if turn["status"] in ("COMPLETE", "BLOCKED"):
                return session, turn, True
            if session["status"] != "ACTIVE":
                raise CoachSessionError("This session has ended. Reopen it to continue.")
            if turn["status"] == "PENDING" and _age_seconds(turn["started_at"]) < STALE_PENDING_SECONDS:
                raise CoachSessionError("This message is still being processed; try again shortly")
        else:
            if session["status"] != "ACTIVE":
                raise CoachSessionError("This session has ended. Reopen it to continue.")
            if _recoverable(session) is not None:
                raise CoachSessionError("Your last message did not finish. Retry it before sending a new one.")
            if len(session["turns"]) >= MAX_TURNS:
                raise CoachSessionError("This session has reached its message limit. Use “Start a fresh session”: your criteria, plan, evidence and questions carry over.")
            if not text.strip():
                raise CoachSessionError("Write a message first.")
            if len(text) > MAX_MESSAGE_CHARS:
                raise CoachSessionError(f"Messages can be at most {MAX_MESSAGE_CHARS} characters; send one passage at a time.")
            turn = {"turn_id": f"t{len(session['turns'])+1:04d}", "role": "student", "client_turn_id": client_turn_id,
                    "text": text, "shared_work": shared_work, "status": "PENDING", "started_at": _now(), "error": None}
            session["turns"].append(turn)
            blocked = classify_request(text)
            if blocked is not None:
                turn.update(status="BLOCKED", block_reason=blocked["reason"])
                session["turns"].append({"turn_id": f"t{len(session['turns'])+1:04d}", "role": "coach",
                                         "in_reply_to": turn["turn_id"], "kind": "REFUSAL", "text": blocked["reply"],
                                         "citations": [], "follow_up_questions": [], "evidence_needs": [],
                                         "created_at": _now()})
                _write(path, session)
                return session, turn, True
        if session["model_calls"] >= MAX_MODEL_CALLS:
            raise CoachSessionError("This session has reached its AI-call limit. Use “Start a fresh session”: your criteria, plan, evidence and questions carry over.")
        if turn.get("rejected_replies", 0) < MAX_REJECTED_REPLIES:
            session["model_calls"] += 1
        turn.update(status="PENDING", started_at=_now(), error=None)
        _write(path, session)
        return session, turn, False


def _known_text(session: dict[str, Any]) -> str:
    """Everything the coach legitimately knows about this assignment besides course excerpts (for reply checks)."""
    facts = session["assessment"]
    return " ".join(
        [str(facts.get("title") or ""), str(facts.get("deadline") or ""),
         f"{facts['weight_percent']}%" if facts.get("weight_percent") is not None else "",
         session["plan"].get("main_argument", ""), session["plan"].get("notes", "")]
        + [r["text"] for r in session["requirements"]] + [c["text"] for c in session["criteria"]]
        + [f"{s['heading']} {s['point']}" for s in session["sections"]]
        + [e["description"] for e in session["evidence"]] + [q["text"] + " " + q.get("answer", "") for q in session["questions"]]
        + [t["text"] for t in session["turns"] if t["role"] == "student"])


def _bounded(session: dict[str, Any], turn: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    recent = [{"role": t["role"], "text": t["text"]} for t in session["turns"]
              if t.get("text") and t["turn_id"] != turn["turn_id"] and t.get("status", "COMPLETE") != "FAILED"]
    feedback = {"previous_attempt_feedback": (
        f"Your previous reply to this message was discarded by an automatic check: {turn['last_rejection']}. "
        "Write a new reply that fixes this, keeping every other rule.")} if turn.get("last_rejection") else {}
    return {
        **feedback,
        "workflow": "ASSIGNMENT_COACH_TURN", "prompt_version": PROMPT_VERSION,
        "objective_context": context["objective_context"], "stage": session["stage"],
        "assessment": {**session["assessment"]},
        "requirements": [{"id": r["id"], "text": r["text"], "status": r["status"]} for r in session["requirements"] if not r.get("removed_from_assessment")],
        "marking_criteria": [{"id": c["id"], "text": c["text"], "status": c["status"]} for c in session["criteria"]],
        "student_plan": {"main_argument": session["plan"].get("main_argument", ""), "notes": session["plan"].get("notes", ""),
                         "sections": [{"id": s["section_id"], "heading": s["heading"], "point": s["point"],
                                       "addresses": s["addresses"], "status": s["status"]} for s in session["sections"]]},
        "evidence": [{"id": e["evidence_id"], "description": e["description"], "status": e["status"], "kind": e["kind"]} for e in session["evidence"]],
        "open_questions": [q["text"] for q in session["questions"] if q["status"] == "OPEN"],
        "student_message": turn["text"], "shared_work": bool(turn.get("shared_work")),
        "recent_turns": recent[-RECENT_TURNS:], "retrieval_status": context["retrieval_status"],
        "unreadable_materials": [u["title"] for u in context["unreadable"]],
        "source_contexts": context["source_contexts"],
    }


SHORT_FOLLOW_UP_WORDS = 10
_ASSIGNMENT_INTENT = re.compile(
    r"\b(?:assign\w*|assess\w*|coursework|brief|submi\w*|hand(?:ing)? (?:it |this )?in|deadline|due|word limit|how long|length|"
    r"format|marking|marks?|criteri\w*|rubric|requirement\w*|asked|asking|expect\w*|task)\b", re.I)
_BRIEF_TERMS = "assessment brief marking criteria submission requirements"


def _query(session: dict[str, Any], text: str) -> str:
    """The retrieval query for one message: what the student asked.

    A question about the assignment itself ("what is this assignment asking?", "how long should it be?") rarely
    shares words with the brief ("assessment", "submission"), so a plain lexical match found nothing and the coach
    claimed there was no course material. For those questions only, the query is widened with the brief's own
    vocabulary and the assignment's title. Other questions are matched on their own words alone, so the title does
    not make every message "match" the brief.
    """
    if _ASSIGNMENT_INTENT.search(text):
        return f"{text} {_BRIEF_TERMS} {session['assessment'].get('title') or ''}"
    if len(text.split()) <= SHORT_FOLLOW_UP_WORDS:
        # A short follow-up ("OK, so what should I do next?") carries no topic of its own: it continues the
        # student's previous message, so retrieval also follows that message.
        earlier = [t["text"] for t in _student_turns(session) if t.get("text") and t["text"] != text and t.get("status") != "BLOCKED"]
        if earlier:
            return f"{earlier[-1][:400]} {text}"
    return text


def _finish(path: Path, module_code: str, turn_id: str, *, status: str, reply: dict[str, Any] | None,
            fields: dict[str, Any], usage: dict[str, Any] | None, provider: dict[str, str] | None,
            materials: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    with record_lock(path, create_dir=True):
        session = _read(path, module_code)
        turn = next(t for t in session["turns"] if t["turn_id"] == turn_id)
        if turn["status"] in ("COMPLETE", "BLOCKED"):
            return _result(session, turn)
        turn.update(fields)
        turn["status"] = status
        if reply is not None:
            session["turns"].append({"turn_id": f"t{len(session['turns'])+1:04d}", "role": "coach", "in_reply_to": turn_id,
                                     "created_at": _now(), **reply})
            _suggest(session, reply)
        if usage:
            for key, value in usage.items():
                session["usage"][key] = session["usage"].get(key, 0) + value
        session["provider"] = provider or session.get("provider")
        if materials is not None:
            session["materials"] = materials
        _write(path, session)
        return _result(session, turn)


def _suggest(session: dict[str, Any], reply: dict[str, Any]) -> None:
    """Store coach suggestions as OPEN/NEEDED items the student must resolve; never overwrite their own."""
    questions = {_norm(q["text"]) for q in session["questions"]}
    for text in reply.get("follow_up_questions", []):
        if _norm(text) not in questions and len(session["questions"]) < MAX_ITEMS:
            session["questions"].append({"question_id": _next_id(session, "questions"), "text": text, "origin": "COACH",
                                         "status": "OPEN", "answer": "", "created_at": _now(), "resolved_at": None})
            questions.add(_norm(text))
    evidence = {_norm(e["description"]) for e in session["evidence"]}
    for text in reply.get("evidence_needs", []):
        if _norm(text) not in evidence and len(session["evidence"]) < MAX_ITEMS:
            session["evidence"].append({"evidence_id": _next_id(session, "evidence"), "description": text,
                                        "kind": "COURSE_MATERIAL" if reply.get("citations") else "EXTERNAL_SOURCE",
                                        "status": "NEEDED", "source_id": None, "pdf_page": None, "note": "",
                                        "origin": "COACH_SUGGESTED"})
            evidence.add(_norm(text))


def _fail(path: Path, module_code: str, turn_id: str, exc: Exception) -> None:
    with record_lock(path, create_dir=True):
        session = _read(path, module_code)
        turn = next(t for t in session["turns"] if t["turn_id"] == turn_id)
        if turn["status"] == "PENDING":
            if isinstance(exc, ReplyRejected):
                turn["rejected_replies"] = turn.get("rejected_replies", 0) + 1
                turn["last_rejection"] = str(exc)[:200]
            turn["status"] = "FAILED"
            turn["error"] = (str(exc) if isinstance(exc, (ReasoningError, StateError)) else type(exc).__name__)[:200]
            _write(path, session)


def _result(session: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    reply = next((t for t in session["turns"] if t.get("in_reply_to") == turn["turn_id"]), None)
    return {"session": view(session), "turn_id": turn["turn_id"], "status": turn["status"], "coach": deepcopy(reply)}


def _locate(context: dict[str, Any], citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a student-readable title and location to each citation."""
    sources = {s["id"]: s for s in context["sources"]}
    titles = {(sc["source_id"], e.get("pdf_page")): e.get("title")
              for sc in context["source_contexts"] for e in sc.get("excerpts", []) or []}
    located = []
    for c in citations:
        source = sources.get(c["source_id"], {})
        method = (source.get("extraction") or {}).get("method")
        location = render_source_location(method, c["pdf_page"], title=titles.get((c["source_id"], c["pdf_page"]))).lstrip(", ")
        located.append({**c, "title": source.get("title") or c["source_id"], "location": location})
    return located


def _readable_sources(text: str, context: dict[str, Any]) -> str:
    """Show a material's title where the model wrote its internal id (``src-…``), after every check has passed."""
    for source in sorted(context["sources"], key=lambda s: -len(s["id"])):
        if source.get("title"):
            text = text.replace(source["id"], source["title"])
    return text


def send_message(state: dict[str, Any], module_code: str, session_id: str, *, client_turn_id: str, text: str,
                 shared_work: bool = False, provider: ReasoningProvider,
                 workspace_root: Path | None = None) -> dict[str, Any]:
    """MODEL CALL (unless refused or recovered). One student message and the coach's reply.

    Repeating the same ``client_turn_id`` with the same text retries an unfinished turn or returns the
    finished one; it never sends the message twice.
    """
    client_turn_id = _clean_id(client_turn_id, "client_turn_id")
    path = _session_path(module_code, session_id, workspace_root)
    session, turn, done = _claim(path, module_code, client_turn_id, text, bool(shared_work))
    if done:
        return _result(session, turn)
    turn_id = turn["turn_id"]
    materials = material_report(state, module_code)
    try:
        # Context is built from the latest saved state; the student's text is part of the query so
        # retrieval follows what they are asking about.
        context = build_assignment_coach_context(state, module_code, _query(session, text))
        context["source_contexts"] = [sc for sc in context["source_contexts"] if sc.get("excerpts")]
        identity = getattr(provider, "cache_identity", None)
        provider_identity = identity() if callable(identity) else None
        if turn.get("rejected_replies", 0) >= MAX_REJECTED_REPLIES:
            return _finish(path, module_code, turn_id, status="COMPLETE", usage=None, provider=provider_identity, materials=materials,
                           fields={"retrieval_status": context["retrieval_status"]},
                           reply={"kind": "FALLBACK", "text": FALLBACK_REPLY, "citations": [], "follow_up_questions": [],
                                  "evidence_needs": [], "grounded": False})
        bounded = _bounded(session, turn, context)
        raw = provider.generate_structured_output(bounded, f"{OBJECTIVE_INSTRUCTIONS}\n\n{COACH_INSTRUCTIONS}", COACH_FORMAT)
        usage = getattr(provider, "last_usage", None)
        usage = usage.to_dict() if hasattr(usage, "to_dict") else None
        try:
            checked = check_reply(raw, context=context, student_text=text, known_text=_known_text(session))
        except ReplyRejected:
            raise
        except ReasoningError as exc:
            raise ReplyRejected(str(exc)) from exc
        grounded = bool(checked["citations"])
        return _finish(path, module_code, turn_id, status="COMPLETE", usage=usage, provider=provider_identity, materials=materials,
                       fields={"retrieval_status": context["retrieval_status"],
                               "unreadable_materials": [u["title"] for u in context["unreadable"]]},
                       reply={"kind": "COACHING", "text": _readable_sources(checked["message"], context),
                              "citations": _locate(context, checked["citations"]),
                              "follow_up_questions": checked["follow_up_questions"],
                              "evidence_needs": checked["evidence_needs"], "grounded": grounded,
                              "retrieval_status": context["retrieval_status"]})
    except (StateError, ReasoningError) as exc:
        _fail(path, module_code, turn_id, exc)
        raise
    except Exception as exc:  # an unexpected provider or file error must not become a server error page
        _fail(path, module_code, turn_id, exc)
        raise CoachSessionError(f"The coach could not answer ({type(exc).__name__}). Your message is saved; you can retry it.") from exc
