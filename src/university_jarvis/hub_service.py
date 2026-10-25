"""Hub Slice 1: the structured service boundary over the existing backend.

This module exists so the Hub (and, later, a voice interface) can call
Serapis the same way the CLI does -- by importing and calling the
already-tested domain functions directly -- without either shelling out to
``jarvis`` and parsing its printed text, or reimplementing any business
logic here. Every function below does exactly two things: (1) resolve the
same optional defaults ``cli.py`` already resolves (``load_state()``,
``load_ledger()``) when the caller omits them, and (2) convert the resulting
dataclasses into plain, JSON-safe dicts/lists/strings so any transport
(in-process call, HTTP, or a future voice tool call) can consume them
without depending on ``pathlib.Path`` or dataclass internals.

Side-effect boundary, matching the classification used to design the Hub:

- READ-ONLY (no external call, no local write): ``get_academic_picture``,
  ``get_attention``.
- LOCAL WRITE only (no network/model call): ``capture_after_lecture_note``.
- EXTERNAL READ (Blackboard; Drive write only if ``sync_to_drive=True`` and
  a Drive client is supplied): ``run_university_check``.
- EXTERNAL WRITE / MODEL CALL (may call the OpenAI provider; always writes
  the workspace record/docx/markdown locally): ``materialize_workspace``,
  ``teach_topic``.

None of these functions is ever called as a side effect of another -- each
is one explicit action a caller (Hub route, voice intent, or test) chooses
to invoke. Callers that need an authenticated Blackboard/Drive client
resolve one the same way ``cli.py`` already does (see
``cli._resolve_blackboard_client``); this module deliberately does not
duplicate that resolution, mirroring how ``university.check_university``
itself only ever accepts an already-authenticated client.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from .academic_picture import build_academic_picture
from .attention import build_attention_picture
from .blackboard import WEEK_AMBIGUOUS_DUPLICATE, WEEK_NOT_YET_PUBLISHED
from .drive import DriveClient
from .intake import AMBIGUOUS, FAILED
from .intake_ledger import load_ledger
from .reasoning import (
    ASSIGNMENT_WORKFLOW,
    REVISE_WORKFLOW,
    OpenAIReasoningProvider,
    ReasoningProvider,
    SectionWorkflow,
    build_source_location_index,
    generate_quiz_brief,
    generate_sectioned_brief,
    render_quiz_brief,
    render_sectioned_brief,
    render_teach_brief,
)
from .reconcile import CHANGED, METADATA_CHANGED, MISSING_SINCE_LAST_CHECK, NEW, UNCHANGED
from .locking import record_lock
from .state import StateError, load_state
from .tutor_policy import reference_problem, requires_calculation
from .university import check_university
from .workflows import build_assignment_context, build_week_context
from .workspace import (capture_after_lecture, materialize_week_workspace, teach_week,
                        record_learning_attempt, save_learning_evaluation, _learning_record,
                        _workspace_paths, _write_record, LEARNING_CAPABILITIES, task_exposure_keys,
                        exposed_task_hashes, task_text_hash, effective_outcome)
from .reasoning import ReasoningError, supplied_units
import json
import re
from datetime import datetime, timezone


def _jsonable(value: Any) -> Any:
    """Recursively convert a (possibly nested) dataclass result into plain data.

    Only handles the shapes actually returned by this module's backend
    calls: frozen dataclasses, lists/tuples, dicts, ``Path``, and JSON-plain
    leaves. A dataclass ``success`` property (e.g. on
    ``WeekReconcileResult``) is included alongside its declared fields since
    it is already-derived, existing information, not a new computation.
    """
    if is_dataclass(value) and not isinstance(value, type):
        result = {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
        success = getattr(value, "success", None)
        if isinstance(success, bool) and "success" not in result:
            result["success"] = success
        return result
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def get_academic_picture(
    *,
    state: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """READ-ONLY: the full academic picture (Milestone 6A), as plain data.

    Delegates entirely to ``academic_picture.build_academic_picture``, which
    already resolves ``state``/``ledger`` to their real, gitignored files
    when omitted. Never mutates any source; every provenance tag
    (``STUDENT_ENTERED``/``MACHINE_OBSERVED``/``DERIVED_WORKSPACE``) and
    ``UNLINKED`` marker survives serialization unchanged.
    """
    picture = build_academic_picture(state=state, ledger=ledger, workspace_root=workspace_root)
    return _jsonable(picture)


def get_attention(
    *,
    state: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """READ-ONLY: the deterministic attention view (Milestone 6B), as plain data.

    Builds the same picture ``get_academic_picture`` would, then derives
    attention from it via ``attention.build_attention_picture`` -- no
    scoring, ranking, or urgency is added here or in the backend function it
    calls; ``TBC``/``UNKNOWN`` values pass through exactly as recorded.
    """
    picture = build_academic_picture(state=state, ledger=ledger, workspace_root=workspace_root)
    attention = build_attention_picture(picture)
    return _jsonable(attention)


def capture_after_lecture_note(
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
) -> dict[str, Any]:
    """LOCAL WRITE only: record a student after-lecture report.

    Delegates entirely to ``workspace.capture_after_lecture`` -- no network
    or model call. Raises ``state.StateError`` (unchanged) if no
    academic-record.json exists yet for this module/week, exactly as the
    CLI's ``after-lecture`` command does today.
    """
    result = capture_after_lecture(
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
        workspace_root=workspace_root,
        captured_at=captured_at,
    )
    return _jsonable(result)


def materialize_workspace(
    module_code: str,
    week_number: int,
    *,
    state: dict[str, Any] | None = None,
    provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """EXTERNAL WRITE / MODEL CALL: materialize one week's study workspace.

    Delegates entirely to ``workspace.materialize_week_workspace``. Only
    calls the OpenAI provider on a local prepare-cache miss -- an existing,
    tested cache-first behaviour this function does not alter. Always an
    explicit caller action; never invoked by any read function above.
    """
    resolved_state = state if state is not None else load_state()
    # Cache-first: a matching local PREPARE_ME result is reused; only a miss calls the provider (once) and
    # caches it, which is what the Hub button promises. The CLI-facing default of the workspace function
    # stays strictly cache-backed.
    result = materialize_week_workspace(
        resolved_state,
        module_code,
        week_number,
        provider=provider,
        cache_dir=cache_dir,
        workspace_root=workspace_root,
        generate_if_missing=True,
    )
    return _jsonable(result)


def teach_topic(
    module_code: str,
    week_number: int,
    *,
    topic: str | None = None,
    state: dict[str, Any] | None = None,
    provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
    workspace_root: Path | None = None,
    taught_at: str | None = None,
) -> dict[str, Any]:
    """EXTERNAL WRITE / MODEL CALL: teach one source-grounded concept.

    Delegates entirely to ``workspace.teach_week``, which always calls the
    reasoning provider. An explicit caller action; never invoked by any read
    function above. The returned dict's ``rendered`` field is the actual
    lesson text -- built by calling the CLI's own, already-tested
    ``render_teach_brief`` (via ``cli._record_source_location_index``, the
    exact citation-location lookup the CLI's own terminal output already
    uses) against the record ``teach_week`` just wrote. This is a read of
    the just-written record, not a second model call.
    """
    from .cli import _record_source_location_index

    resolved_state = state if state is not None else load_state()
    result = teach_week(
        resolved_state,
        module_code,
        week_number,
        topic=topic,
        provider=provider,
        cache_dir=cache_dir,
        workspace_root=workspace_root,
        taught_at=taught_at,
    )
    location_index = _record_source_location_index(result.record_path)
    with result.record_path.open(encoding="utf-8") as handle:
        for source in json.load(handle).get("sources", []):
            if source.get("source_id") in location_index and source.get("title"):
                location_index[source["source_id"]]["title"] = source["title"]  # students see file names, not ids
    rendered = render_teach_brief(result.brief, {"topic": result.topic}, result.student_context, location_index)
    payload = _jsonable(result)
    payload["rendered"] = rendered
    return payload


def run_university_check(
    blackboard_client: Any,
    *,
    drive_client: DriveClient | None = None,
    ledger: dict[str, Any] | None = None,
    sync_to_drive: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    """EXTERNAL READ (EXTERNAL WRITE if ``sync_to_drive=True``): university-wide check.

    Delegates entirely to ``university.check_university``, which discovers
    this account's teaching modules/weeks fresh every call and reconciles
    each against the persisted ledger, saving successful weeks immediately.
    The caller supplies an already-authenticated ``blackboard_client`` --
    this module never resolves or stores Blackboard/Drive credentials
    itself, the same boundary ``check_university`` already enforces.
    """
    resolved_ledger = ledger if ledger is not None else load_ledger()
    result = check_university(
        blackboard_client,
        drive_client,
        resolved_ledger,
        sync_to_drive=sync_to_drive,
        now=now,
    )
    return _jsonable(result)


def _run_sectioned_workflow(
    context: dict[str, Any],
    workflow: SectionWorkflow,
    *,
    provider: ReasoningProvider | None,
    cache_dir: Path | None,
) -> dict[str, Any]:
    selected_provider = provider or OpenAIReasoningProvider()
    result = generate_sectioned_brief(context, selected_provider, workflow, cache_dir=cache_dir)
    location_index = build_source_location_index(context, show_titles=True)
    rendered = render_sectioned_brief(result.brief, workflow, location_index)
    return {"cache_status": result.cache_status, "rendered": rendered}


def generate_quiz(
    module_code: str,
    week_number: int,
    *,
    state: dict[str, Any] | None = None,
    provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Generate a quiz and persist its question/answer set when a workspace exists.

    The answer key stays in the local academic record; rendered output contains
    questions only. No student evidence is written until a response is submitted.
    """
    resolved_state = state if state is not None else load_state()
    context = build_week_context(resolved_state, module_code, week_number, "QUIZ")
    selected_provider = provider or OpenAIReasoningProvider()
    result = generate_quiz_brief(context, selected_provider, cache_dir=cache_dir)
    location_index = build_source_location_index(context, show_titles=True)
    rendered = render_quiz_brief(result.brief, location_index).split("\nAnswers", 1)[0]
    record_path = _workspace_paths(context["module"]["code"], week_number, workspace_root)[0]
    fingerprints = {s["id"]: s.get("extraction", {}).get("fingerprint") for s in context["sources"]}
    questions = [_jsonable(q) for q in result.brief.questions]
    answers = [_jsonable(a) for a in result.brief.answers]
    for item in questions + answers:
        for ref in item.get("provenance", []):
            ref["fingerprint"] = fingerprints.get(ref["source_id"])
    no_workspace = {"module_code": context["module"]["code"], "week": week_number,
                    "cache_status": result.cache_status, "rendered": rendered}
    if not record_path.exists():
        # Quiz generation remains usable without a materialized workspace;
        # attempts become persistent only after the student has one to save into.
        # (Return before locking: locking must not create workspace directories.)
        return no_workspace
    # The model call is finished; take the record lock only for the
    # read-modify-write so concurrent attempts or evaluations are preserved.
    with record_lock(record_path):
        try:
            record, record_path, _, _ = _learning_record(
                context["module"]["code"], week_number, workspace_root
            )
        except StateError:
            return no_workspace
        # Keep answer keys in the local record, but render only the questions.
        quiz_id = f"quiz-{len(record.get('learning', {}).get('quiz_history', {}).get('attempts', []))+1:04d}"
        quiz = {"quiz_id": quiz_id, "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "questions": questions, "answers": answers}
        quiz_history = record.setdefault("learning", {}).setdefault("quiz_history", {"status": "not_recorded", "attempts": []})
        quiz_history.setdefault("attempts", []).append(quiz)
        quiz_history["status"] = "recorded"
        _write_record(record, record_path)
    return {
        "module_code": context["module"]["code"],
        "week": week_number,
        "cache_status": result.cache_status,
        "rendered": rendered,
        "quiz_id": quiz_id,
        "questions": quiz["questions"],
    }


def learning_view(module_code: str, week_number: int, *, workspace_root: Path | None = None) -> dict[str, Any]:
    record, *_ = _learning_record(module_code, week_number, workspace_root)
    attempts = record["learning"]["evidence"]
    summary = {}
    for capability in LEARNING_CAPABILITIES:
        rows = [a for a in attempts if a["capability"] == capability]
        latest = rows[-1] if rows else None
        if latest is None: status = "Not yet tested"
        elif latest["evaluation"] is None: status = "Attempted — awaiting evaluation"
        elif latest["assistance_status"] == "REVEALED": status = "Attempted after the answer was shown"
        elif effective_outcome(latest["evaluation"]) == "SUPPORTED" and latest["assistance_status"] == "UNAIDED": status = "Demonstrated unaided"
        elif effective_outcome(latest["evaluation"]) == "SUPPORTED": status = "Demonstrated after help"
        else: status = "Needs another attempt"
        summary[capability] = {"status": status, "latest_attempt_id": latest["attempt_id"] if latest else None}
    pending = next((a["attempt_id"] for a in reversed(attempts) if a.get("evaluation") is None), None)
    teach_questions = []
    for interaction in record.get("workflows", {}).get("teach", {}).get("interactions", []):
        generated = interaction.get("generated_learning", {})
        refs = []
        for q in generated.get("check_questions", []):
            teach_questions.append({"task": q.get("text", ""), "topic": interaction.get("topic"),
                                    "source_references": q.get("provenance", [])})
    return {"summary": summary, "recommendation": select_next_study_task(attempts, record.get("sources", [])),
            "latest_unevaluated": pending, "teach_questions": teach_questions}


def select_next_study_task(attempts: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, str]:
    """Pure, explainable selection; absence is an evidence gap, not weakness."""
    latest = {cap: next((a for a in reversed(attempts) if a["capability"] == cap), None) for cap in LEARNING_CAPABILITIES}
    for cap in LEARNING_CAPABILITIES:
        row = latest[cap]
        outcome = effective_outcome(row.get("evaluation")) if row else None
        if outcome in {"NOT_SUPPORTED", "UNCLEAR", "PARTLY_SUPPORTED"}:
            return {"action": f"Review and retry {cap.lower()}", "reason": f"The latest task-level evaluation was {outcome.lower().replace('_',' ')}.", "capability": cap, "mode": "RETRY"}
        if row is not None and row["assistance_status"] in {"PROMPTED", "REVEALED"}:
            return {"action": f"Retest {cap.lower()} unaided", "reason": "The latest response followed help, so an unaided retest would add different evidence.", "capability": cap, "mode": "UNAIDED_RETEST"}
    for cap in LEARNING_CAPABILITIES:
        if latest[cap] is None:
            if not any(s.get("extraction", {}).get("character_count", 0) > 0 for s in sources):
                return {"action": "No reliable recommendation", "reason": "No usable source context is available to create a grounded task."}
            return {"action": f"Try a {cap.lower()} task", "reason": f"{cap.title()} has not yet been tested; this is an evidence gap, not a weakness.", "capability": cap, "mode": "INITIAL"}
    return {"action": "Choose another source-grounded task", "reason": "Current evidence does not justify a stronger claim or a more specific priority.", "capability": "", "mode": "NONE"}


def _learning_task_candidates(record: dict[str, Any], capability: str) -> list[dict[str, Any]]:
    attempts = record.get("learning", {}).get("evidence", [])
    used = {a.get("origin") for a in attempts} | task_exposure_keys(record)
    spent_wording = exposed_task_hashes(record)  # identical wording under a new id is the same task
    candidates = []
    for quiz in record.get("learning", {}).get("quiz_history", {}).get("attempts", []):
        answers = {a["question_id"]: a for a in quiz.get("answers", [])}
        for question in quiz.get("questions", []):
            kind = question.get("question_type", "").upper()
            kind = "APPLICATION" if kind == "CONNECTION" else kind
            origin = f"QUIZ:{quiz['quiz_id']}:{question['question_id']}"
            if kind == capability and origin not in used:
                answer = answers.get(question["question_id"], {})
                candidates.append({"task_id": origin, "task": question["question"], "capability": kind,
                    "origin": origin, "expected_answer": answer.get("answer"),
                    "source_references": question.get("provenance", []), "assistance_status": "UNAIDED", "prompt_help": []})
    for interaction in record.get("workflows", {}).get("teach", {}).get("interactions", []):
        teach_id = interaction.get("teach_id", "teach")
        for index, question in enumerate(interaction.get("generated_learning", {}).get("check_questions", []), 1):
            origin = f"TEACH:{teach_id}:{index}"
            # Check questions follow an explanatory lesson, so they are prompted evidence.
            if capability == "EXPLANATION" and origin not in used:
                candidates.append({"task_id": origin, "task": question.get("text", ""), "capability": capability,
                    "origin": origin, "expected_answer": None, "source_references": question.get("provenance", []),
                    "assistance_status": "PROMPTED", "prompt_help": ["Source-grounded TEACH lesson shown before this check question"]})
    for task in record.get("learning", {}).get("generated_tasks", []):
        if task.get("capability") == capability and f"GENERATED:{task.get('task_id')}" not in used:
            candidates.append({**task, "origin": f"GENERATED:{task['task_id']}", "assistance_status": "UNAIDED", "prompt_help": []})
    return [c for c in candidates if task_text_hash(c.get("task")) not in spent_wording]


MAX_UNVERIFIED_GENERATED = 2  # unverifiable generated tasks per capability before generation is refused


def _ref_fingerprints(task: dict[str, Any]) -> list[Any]:
    return sorted((str(r.get("source_id")), json.dumps(r.get("fingerprint"), sort_keys=True))
                  for r in task.get("source_references") or [])


def _unverified_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    return record.get("learning", {}).get("unverified_tasks", [])


def reject_unverified_task(module_code: str, week_number: int, task: dict[str, Any], reason: str, *,
                           workspace_root: Path | None = None) -> None:
    """Remember that a task's reference answer failed verification so it is not recommended again.

    Only a marker is stored: the task, its attempts and every other piece of evidence are untouched, and
    the marker stops applying if the task's cited sources change (the reference may then verify).
    """
    _, record_path, _, _ = _learning_record(module_code, week_number, workspace_root)
    with record_lock(record_path):
        record, record_path, _, _ = _learning_record(module_code, week_number, workspace_root)
        entries = record["learning"].setdefault("unverified_tasks", [])
        fingerprints = [list(f) for f in _ref_fingerprints(task)]
        if any(e.get("origin") == task["origin"] and e.get("fingerprints") == fingerprints for e in entries):
            return
        entries.append({"origin": task["origin"], "capability": task.get("capability"),
                        "task_text_hash": task_text_hash(task.get("task")), "reason": reason,
                        "fingerprints": fingerprints,
                        "rejected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()})
        _write_record(record, record_path)


def _is_rejected(entries: list[dict[str, Any]], task: dict[str, Any]) -> bool:
    fingerprints = [list(f) for f in _ref_fingerprints(task)]
    return any((e.get("origin") == task.get("origin") or e.get("task_text_hash") == task_text_hash(task.get("task")))
               and e.get("fingerprints") == fingerprints for e in entries)


def continue_learning_task(module_code: str, week_number: int, *, state: dict[str, Any],
                           provider: ReasoningProvider, workspace_root: Path | None = None,
                           allow_generation: bool = True) -> dict[str, Any]:
    """Fulfil the deterministic recommendation; only this explicit POST may generate a task.

    A task whose reference answer was rejected as unverifiable (``reject_unverified_task``) is skipped while
    its sources are unchanged. ``allow_generation=False`` never calls the model, and generation is refused
    once ``MAX_UNVERIFIED_GENERATED`` generated tasks for this capability have already failed verification.
    """
    state = state if state is not None else load_state()
    record, record_path, study_pack_path, notebooklm_path = _learning_record(module_code, week_number, workspace_root)
    recommendation = select_next_study_task(record["learning"].get("evidence", []), record.get("sources", []))
    capability = recommendation.get("capability", "")
    if not capability:
        return {"recommendation": recommendation, "task": None, "generated": False}
    current_context = build_week_context(state, module_code, week_number, "LEARNING_TASK_SELECTION")
    current_fingerprints = {s["id"]: s.get("extraction", {}).get("fingerprint") for s in current_context["sources"]}
    candidates = _learning_task_candidates(record, capability)
    candidates = [task for task in candidates if task.get("source_references") and all(
        ref.get("source_id") in current_fingerprints and ref.get("fingerprint") is not None and
        ref.get("fingerprint") == current_fingerprints[ref["source_id"]]
        for ref in task["source_references"])]
    # For a requested unaided retest, discard TEACH checks and any task with recorded assistance.
    if recommendation["mode"] == "UNAIDED_RETEST":
        candidates = [task for task in candidates if task["assistance_status"] == "UNAIDED" and not task["prompt_help"]]
    rejected = _unverified_entries(record)
    candidates = [task for task in candidates if not _is_rejected(rejected, task)]
    if candidates:
        return {"recommendation": recommendation, "task": candidates[0], "generated": False}
    failed_generated = sum(1 for e in rejected if e.get("capability") == capability
                           and str(e.get("origin", "")).startswith("GENERATED:")
                           and all(current_fingerprints.get(sid) is not None
                                   and json.dumps(current_fingerprints[sid], sort_keys=True) == fp
                                   for sid, fp in e.get("fingerprints", [])))
    if not allow_generation or failed_generated >= MAX_UNVERIFIED_GENERATED:
        return {"recommendation": recommendation, "task": None, "generated": False,
                "reason": "NO_VERIFIABLE_TASK"}

    context = build_week_context(state, module_code, week_number, "LEARNING_TASK")
    if not context.get("source_contexts"):
        return {"recommendation": {"action": "No reliable recommendation", "reason": "No usable source excerpts are available to create a grounded task.", "capability": "", "mode": "NONE"}, "task": None, "generated": False}
    schema = {"type":"json_schema", "name":"learning_task", "strict":True, "schema":{"type":"object","properties":{"task":{"type":"string"},"expected_answer_or_rubric":{"type":"string"},"source_references":{"type":"array","items":{"type":"object","properties":{"source_id":{"type":"string"},"pdf_page":{"type":["integer","null"]}},"required":["source_id","pdf_page"],"additionalProperties":False}}},"required":["task","expected_answer_or_rubric","source_references"],"additionalProperties":False}}
    bounded = {"capability": capability, "source_contexts": context["source_contexts"]}
    raw = provider.generate_structured_output(bounded, f"Create exactly one concise source-grounded {capability.lower()} learning question. The capability is fixed; do not change it. Give a separate expected answer or brief rubric. Cite only supplied sources.", schema)
    allowed = {s["id"] for s in context["sources"]}
    refs = raw.get("source_references", [])
    if not isinstance(raw.get("task"), str) or not raw["task"].strip() or not raw.get("expected_answer_or_rubric") or not refs or any(r.get("source_id") not in allowed for r in refs):
        raise ReasoningError("Generated learning task was incomplete or cited an unavailable source")
    cited_pages = [e.get("text", "") for sc in context["source_contexts"] for e in sc.get("excerpts", []) or []
                   if any(sc.get("source_id") == r.get("source_id") and e.get("pdf_page") == r.get("pdf_page") for r in refs)]
    if (why := requires_calculation(raw["task"], str(raw["expected_answer_or_rubric"]), cited_pages)):
        # This path has no way to carry a calculation, so a computed answer here could never be verified.
        raise ReasoningError(f"Generated learning task needs a numerical computation that cannot be verified: {why}")
    # Reload under the lock: the model call may have been slow and the record
    # may have gained attempts or tasks in the meantime.
    with record_lock(record_path):
        record, record_path, _, _ = _learning_record(module_code, week_number, workspace_root)
        task_id = f"generated-{len(record['learning'].get('generated_tasks', []))+1:04d}"
        source_index = {s.get("source_id"): s for s in record.get("sources", [])}
        refs = [{**r, "fingerprint": source_index.get(r["source_id"], {}).get("extraction", {}).get("fingerprint")} for r in refs]
        task = {"task_id": task_id, "capability": capability, "task": raw["task"],
                "expected_answer": raw["expected_answer_or_rubric"], "source_references": refs,
                "origin": f"GENERATED:{task_id}", "assistance_status": "UNAIDED", "prompt_help": []}
        record["learning"].setdefault("generated_tasks", []).append(task)
        _write_record(record, record_path)
    return {"recommendation": recommendation, "task": task, "generated": True}


def submit_recommended_response(module_code: str, week_number: int, task_id: str, response: str, *,
                                prompted: bool = False, prompt_help: list[str] | None = None,
                                workspace_root: Path | None = None) -> dict[str, Any]:
    record, *_ = _learning_record(module_code, week_number, workspace_root)
    task = next((t for t in _learning_task_candidates(record, "RECALL") +
                 _learning_task_candidates(record, "EXPLANATION") +
                 _learning_task_candidates(record, "APPLICATION") if t["task_id"] == task_id), None)
    if task is None:
        # Already used tasks are intentionally unavailable for another attempt.
        raise StateError("This task is no longer available; continue for a fresh task")
    is_prompted = prompted or task["assistance_status"] == "PROMPTED"
    help_items = list(task.get("prompt_help", [])) + list(prompt_help or [])
    return record_learning_attempt(module_code, week_number, capability=task["capability"], task=task["task"],
        origin=task["origin"], response=response, expected_answer=task.get("expected_answer"),
        source_references=task.get("source_references", []), assistance_status="PROMPTED" if is_prompted else "UNAIDED",
        prompt_help=help_items, root=workspace_root)


def submit_learning_response(module_code: str, week_number: int, *, task: str, capability: str,
                             origin: str, response: str, expected_answer: str | None = None,
                             source_references: list[dict[str, Any]] | None = None,
                             assistance_status: str = "UNAIDED", prompt_help: list[str] | None = None,
                             workspace_root: Path | None = None) -> dict[str, Any]:
    return record_learning_attempt(module_code, week_number, capability=capability, task=task,
                                   origin=origin, response=response, expected_answer=expected_answer,
                                   source_references=source_references, assistance_status=assistance_status,
                                   prompt_help=prompt_help, root=workspace_root)


def answer_quiz_question(module_code: str, week_number: int, quiz_id: str, question_id: str,
                         response: str, *, workspace_root: Path | None = None) -> dict[str, Any]:
    record, *_ = _learning_record(module_code, week_number, workspace_root)
    quiz = next((q for q in record.get("learning", {}).get("quiz_history", {}).get("attempts", []) if q.get("quiz_id") == quiz_id), None)
    if quiz is None: raise StateError("Quiz not found")
    question = next((q for q in quiz["questions"] if q["question_id"] == question_id), None)
    if question is None: raise StateError("Quiz question not found")
    answer = next((a for a in quiz["answers"] if a["question_id"] == question_id), None)
    capability = question["question_type"].upper()
    if capability == "CONNECTION": capability = "APPLICATION"
    if capability not in LEARNING_CAPABILITIES: capability = "EXPLANATION"
    return record_learning_attempt(module_code, week_number, capability=capability,
        task=question["question"], origin=f"QUIZ:{quiz_id}:{question_id}", response=response,
        expected_answer=answer["answer"] if answer else None, source_references=question.get("provenance", []),
        root=workspace_root)


def evaluate_learning_attempt(module_code: str, week_number: int, attempt_id: str, *, state: dict[str, Any],
                              provider: ReasoningProvider, workspace_root: Path | None = None) -> dict[str, Any]:
    """Explicit bounded evaluation; raw attempt is already durably saved."""
    state = state if state is not None else load_state()
    record, *_ = _learning_record(module_code, week_number, workspace_root)
    attempt = next((a for a in record["learning"]["evidence"] if a["attempt_id"] == attempt_id), None)
    if attempt is None: raise StateError("Learning attempt not found")
    refs = attempt["source_references"]
    # Retrieve evidence for what was asked; cited units are always kept.
    context = build_week_context(
        state, module_code, week_number, "LEARNING_EVALUATION",
        # The student's response is deliberately excluded: it could pull in text that
        # echoes a wrong answer and hide text that contradicts it.
        query=" ".join(str(attempt.get(k) or "") for k in ("task", "expected_answer")),
        source_ids=[r["source_id"] for r in refs if r.get("source_id")],
        pinned=[(r["source_id"], r["pdf_page"]) for r in refs if r.get("source_id") and isinstance(r.get("pdf_page"), int)],
    )
    ids = {s["id"] for s in context["sources"]}
    if any(r.get("source_id") not in ids for r in refs): raise StateError("Task source context is no longer available")
    current_sources = {s["id"]: s for s in context["sources"]}
    for ref in refs:
        old_fingerprint = ref.get("fingerprint")
        current_fingerprint = current_sources[ref["source_id"]].get("extraction", {}).get("fingerprint")
        if old_fingerprint is not None and old_fingerprint != current_fingerprint:
            raise StateError("Task source has changed since the response; its original context is retained, but re-evaluation needs a new task")
    referenced_ids = {r["source_id"] for r in refs}
    if any(c.get("retrieval", {}).get("status", "matched") != "matched" for c in context["source_contexts"]):
        evaluation = {"outcome": "UNCLEAR", "reason": "No supporting source passage could be retrieved for this task, so the response cannot be judged against the sources.",
                      "evidence_references": [], "basis": "NO_EVIDENCE_RETRIEVED", "provider": None,
                      "evaluated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
        return save_learning_evaluation(module_code, week_number, attempt_id, evaluation, root=workspace_root)
    if (problem := reference_problem(attempt["expected_answer"], refs, context["source_contexts"])):
        # An unverified reference is never sent to the model or used to judge; the response stays as saved.
        evaluation = {"outcome": "UNCLEAR", "reason": "The reference answer for this task could not be verified against "
                      f"the supplied sources ({problem}), so the response was not judged against it.",
                      "evidence_references": [], "basis": "REFERENCE_NOT_SUPPORTED", "provider": None,
                      "evaluated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
        return save_learning_evaluation(module_code, week_number, attempt_id, evaluation, root=workspace_root)
    bounded = {"task": attempt["task"], "expected_answer_or_rubric": attempt["expected_answer"],
               "student_response": attempt["student_response"], "assistance_status": attempt["assistance_status"],
               "prompt_help": attempt["prompt_help"], "source_contexts": [x for x in context["source_contexts"] if x.get("source_id") in referenced_ids],
               "source_references": refs}
    schema = {"type":"json_schema", "name":"learning_evaluation", "strict":True, "schema":{"type":"object","properties":{"outcome":{"type":"string","enum":["SUPPORTED","PARTLY_SUPPORTED","NOT_SUPPORTED","UNCLEAR"]},"reason":{"type":"string"},"evidence_references":{"type":"array","items":{"type":"object","properties":{"source_id":{"type":"string"},"location":{"type":"string"}},"required":["source_id","location"],"additionalProperties":False}}},"required":["outcome","reason","evidence_references"],"additionalProperties":False}}
    raw = provider.generate_structured_output(bounded, "Evaluate only this response against the supplied expected answer and source excerpts. This is a provisional task-level model judgement, not a mastery or psychometric claim. Cite only supplied source IDs; use UNCLEAR when evidence is insufficient.", schema)
    allowed = {r["source_id"] for r in refs}
    units = supplied_units(bounded["source_contexts"])
    for ref in raw.get("evidence_references", []) if isinstance(raw.get("evidence_references"), list) else []:
        for number in re.findall(r"(?:p\.?|pages?|slides?)\s*(\d+)", str(ref.get("location", "")), re.I):
            if int(number) not in units.get(ref.get("source_id"), set()):
                raise ReasoningError("Evaluation cited a page or slide that was not supplied")
    if raw.get("outcome") not in {"SUPPORTED","PARTLY_SUPPORTED","NOT_SUPPORTED","UNCLEAR"} or any(r.get("source_id") not in allowed for r in raw.get("evidence_references", [])):
        raise ReasoningError("Evaluation returned invalid outcome or source references")
    evaluation = {**raw, "basis":"MODEL_JUDGEMENT", "provider":provider.cache_identity(), "evaluated_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    return save_learning_evaluation(module_code, week_number, attempt_id, evaluation, root=workspace_root)


def generate_revision_brief(
    module_code: str,
    week_number: int,
    *,
    state: dict[str, Any] | None = None,
    provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """MODEL CALL (cache-first): a source-grounded revision brief for one module/week.

    Delegates entirely to ``reasoning.generate_sectioned_brief`` (with
    ``REVISE_WORKFLOW``) + ``reasoning.render_sectioned_brief``. Ephemeral,
    same boundary as ``generate_quiz``: only the local reasoning cache is
    touched, never the workspace record.
    """
    resolved_state = state if state is not None else load_state()
    context = build_week_context(resolved_state, module_code, week_number, "REVISE")
    result = _run_sectioned_workflow(
        context, REVISE_WORKFLOW, provider=provider, cache_dir=cache_dir
    )
    return {"module_code": context["module"]["code"], "week": week_number, **result}


def generate_assignment_coaching(
    module_code: str,
    *,
    state: dict[str, Any] | None = None,
    provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """MODEL CALL (cache-first): assignment-planning coaching for one module.

    Delegates entirely to ``workflows.build_assignment_context`` +
    ``reasoning.generate_sectioned_brief`` (with ``ASSIGNMENT_WORKFLOW``) +
    ``reasoning.render_sectioned_brief``. Module-scoped, not week-scoped.
    The backend workflow's own instructions already forbid producing a
    finished, submittable assignment response; this function does not add
    or relax that constraint. Ephemeral: only the local reasoning cache is
    touched, never the workspace record.
    """
    resolved_state = state if state is not None else load_state()
    context = build_assignment_context(resolved_state, module_code)
    result = _run_sectioned_workflow(
        context, ASSIGNMENT_WORKFLOW, provider=provider, cache_dir=cache_dir
    )
    return {"module_code": context["module"]["code"], **result}


_CHECK_SUMMARY_ITEM_STATUSES = (
    ("new", NEW),
    ("changed", CHANGED),
    ("metadata_changed", METADATA_CHANGED),
    ("unchanged", UNCHANGED),
    ("missing", MISSING_SINCE_LAST_CHECK),
    ("ambiguous", AMBIGUOUS),
    ("failed", FAILED),
)


def summarize_university_check(result: dict[str, Any]) -> dict[str, int]:
    """Pure count aggregation over an already-returned ``run_university_check`` result.

    Deliberately mirrors ``cli._run_check_university``'s own summary-counting
    (same label set, same rule: a week with no items and a
    ``WEEK_NOT_YET_PUBLISHED``/``AMBIGUOUS_DUPLICATE_WEEK`` status counts once
    under "not_yet_published"/"ambiguous"; every other week's counts come from
    its items' own ``status``), so the Hub's counts agree with the CLI's.
    Reads only the dict ``run_university_check`` already returned -- no new
    reconciliation, no invented status, no double counting. Labels with a
    zero count are simply absent from the returned dict.
    """
    counts: dict[str, int] = {}

    def _bump(label: str) -> None:
        counts[label] = counts.get(label, 0) + 1

    for module in result.get("modules", []):
        for week in module.get("weeks", []):
            if week.get("status") in (WEEK_NOT_YET_PUBLISHED, WEEK_AMBIGUOUS_DUPLICATE):
                _bump("not_yet_published" if week["status"] == WEEK_NOT_YET_PUBLISHED else "ambiguous")
                continue
            for item in week.get("items") or []:
                for label, status in _CHECK_SUMMARY_ITEM_STATUSES:
                    if item.get("status") == status:
                        _bump(label)
                        break
    return counts


def has_any_observed_material(picture: dict[str, Any]) -> bool:
    """Pure aggregation over an already-returned ``get_academic_picture`` result.

    True if any known week has at least one MACHINE_OBSERVED material entry
    -- used only to distinguish "nothing has ever been observed" from
    "observed material exists and currently has no evidence gaps" on Home.
    Derives nothing new: it only checks whether ``materials`` lists already
    present in the picture are non-empty.
    """
    return any(
        week.get("materials")
        for module in picture.get("modules", [])
        for week in module.get("weeks", [])
    )


def build_student_journey(
    state: dict[str, Any],
    picture: dict[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """READ-ONLY: where the student is in the setup-to-assignment journey, and what to resume.

    Derived only from saved local files (state, week records, tutor and Assignment Coach
    sessions); makes no model, network or write call. A step is "done" when its evidence
    exists, never because the student was told to do it; the next step is simply the first
    one without evidence.
    """
    from . import assignment_coach, tutoring

    student = state.get("student", {})
    modules = picture.get("modules", [])
    first_module = modules[0]["module_code"] if modules else None
    assessments = [(m["module_code"], a) for m in modules for a in m.get("assessments", [])]
    material_modules = {s.get("module_code") for s in state.get("sources", []) if s.get("module_code")}
    built_weeks = [(m["module_code"], w["week"]) for m in modules for w in m.get("weeks", [])
                   if (w.get("study_state") or {}).get("record_found")]
    attempts = 0
    for code, week in built_weeks:
        try:
            record, *_ = _learning_record(code, week, workspace_root)
            attempts += len(record.get("learning", {}).get("evidence", []))
        except StateError:
            continue
    coach_rows: list[dict[str, Any]] = []
    for module in modules:
        coach_rows.extend(assignment_coach.list_sessions(module["module_code"], workspace_root=workspace_root))
    has_plan = False
    for row in coach_rows:
        try:
            loaded = assignment_coach.load_session(row["module_code"], row["session_id"], workspace_root=workspace_root)
        except StateError:
            continue
        if loaded["sections"] or loaded["plan"].get("main_argument"):
            has_plan = True
            break
    week_href = (f"/modules/{built_weeks[0][0]}/weeks/{built_weeks[0][1]}" if built_weeks else
                 (f"/modules/{first_module}" if first_module else "/modules"))
    steps = [
        {"id": "profile", "label": "Set up your profile", "done": bool(student.get("university") or student.get("programme")),
         "href": "/profile", "detail": "University and programme. Both are optional and stay on this device."},
        {"id": "module", "label": "Add a module", "done": bool(modules), "href": "/modules",
         "detail": "A module code and title is enough to begin."},
        {"id": "assessment", "label": "Add an assessment", "done": bool(assessments),
         "href": f"/modules/{first_module}#assessments" if first_module else "/modules",
         "detail": "Title, plus deadline, weight and requirements if you know them."},
        {"id": "materials", "label": "Add course materials", "done": bool(material_modules),
         "href": f"/modules/{first_module}#materials" if first_module else "/modules",
         "detail": "PDF or PowerPoint files, attached to a week."},
        {"id": "study_week", "label": "Prepare a week to study", "done": bool(built_weeks), "href": week_href,
         "detail": "Open a week and build its study workspace (uses AI once you confirm)."},
        {"id": "practice", "label": "Answer a practice question", "done": attempts > 0, "href": week_href,
         "detail": "Quiz, Tutor or TEACH checks. Your answers are saved as study evidence."},
        {"id": "coach", "label": "Open an assignment in the Assignment Coach", "done": bool(coach_rows),
         "href": f"/modules/{assessments[0][0]}#assessments" if assessments else "/modules",
         "detail": "Coaching is tied to one assessment and keeps your notes."},
        {"id": "plan", "label": "Save an assignment plan", "done": has_plan,
         "href": (f"/modules/{coach_rows[0]['module_code']}/coach/{coach_rows[0]['session_id']}#plan" if coach_rows else
                  (f"/modules/{assessments[0][0]}#assessments" if assessments else "/modules")),
         "detail": "Your argument, sections and the evidence each needs."},
    ]
    resume: list[dict[str, Any]] = []
    for row in coach_rows:
        if row["status"] == "ACTIVE":
            resume.append({"kind": "COACH", "title": f"{row['module_code']} — {row['assessment_title']}",
                           "detail": f"Assignment Coach, stage {row['stage'].title()}. Next: {row['next_step']}",
                           "href": f"/modules/{row['module_code']}/coach/{row['session_id']}",
                           "updated_at": row["updated_at"]})
    for code, week in built_weeks:
        for row in tutoring.list_sessions(code, week, workspace_root=workspace_root):
            if row.get("status") == "ACTIVE":
                resume.append({"kind": "TUTOR", "title": f"{code} Week {week}",
                               "detail": f"Tutor session ({row['intention'].replace('_', ' ').title()}): {row['task']}",
                               "href": f"/modules/{code}/weeks/{week}/tutor/{row['session_id']}",
                               "updated_at": row.get("updated_at", row["created_at"])})
    resume.sort(key=lambda r: r["updated_at"], reverse=True)
    next_step = next((s for s in steps if not s["done"]), None)
    return {"steps": steps, "next": next_step, "resume": resume,
            "complete": next_step is None, "done_count": sum(s["done"] for s in steps)}
