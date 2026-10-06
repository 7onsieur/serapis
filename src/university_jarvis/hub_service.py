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
from .state import load_state
from .university import check_university
from .workflows import build_assignment_context, build_week_context
from .workspace import capture_after_lecture, materialize_week_workspace, teach_week


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
    result = materialize_week_workspace(
        resolved_state,
        module_code,
        week_number,
        provider=provider,
        cache_dir=cache_dir,
        workspace_root=workspace_root,
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
    rendered = render_teach_brief(
        result.brief,
        {"topic": result.topic},
        result.student_context,
        _record_source_location_index(result.record_path),
    )
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
    location_index = build_source_location_index(context)
    rendered = render_sectioned_brief(result.brief, workflow, location_index)
    return {"cache_status": result.cache_status, "rendered": rendered}


def generate_quiz(
    module_code: str,
    week_number: int,
    *,
    state: dict[str, Any] | None = None,
    provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """MODEL CALL (cache-first): a source-grounded quiz for one module/week.

    Delegates entirely to ``reasoning.generate_quiz_brief`` +
    ``reasoning.render_quiz_brief``. Ephemeral: this only reads/writes the
    local reasoning cache (``.jarvis-cache/``) -- it never touches
    ``academic-record.json``, the study-pack docx, or the NotebookLM
    markdown. ``learning.quiz_history`` in the workspace record is never
    updated by this or any existing backend function.
    """
    resolved_state = state if state is not None else load_state()
    context = build_week_context(resolved_state, module_code, week_number, "QUIZ")
    selected_provider = provider or OpenAIReasoningProvider()
    result = generate_quiz_brief(context, selected_provider, cache_dir=cache_dir)
    location_index = build_source_location_index(context)
    rendered = render_quiz_brief(result.brief, location_index)
    return {
        "module_code": context["module"]["code"],
        "week": week_number,
        "cache_status": result.cache_status,
        "rendered": rendered,
    }


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
