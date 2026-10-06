"""Hub Slice 2/3: the local web shell over ``hub_service`` -- read-only
pages plus a small set of explicit, POST-only actions.

Slice 2 boundary (unchanged): every GET route calls only
``hub_service.get_academic_picture``/``get_attention``, which only ever read
local JSON files. No GET route performs an external call or a local write.

Slice 3 adds four explicit actions, each POST-only, each a thin call into
``hub_service`` with no business logic duplicated here:

- ``POST /check``                                            -- EXTERNAL READ
  (Blackboard; Drive sync stays off -- ``sync_to_drive`` is never passed as
  anything but its default ``False``). Delegates to
  ``hub_service.run_university_check``.
- ``POST /modules/{code}/weeks/{n}/build``                    -- EXTERNAL
  WRITE / MODEL CALL (only on a local prepare-cache miss; otherwise a plain
  local write). Delegates to ``hub_service.materialize_workspace``.
- ``POST /modules/{code}/weeks/{n}/teach``                    -- EXTERNAL
  WRITE / MODEL CALL (always). Delegates to ``hub_service.teach_topic``.
- ``POST /modules/{code}/weeks/{n}/after-lecture``            -- LOCAL WRITE
  only. Delegates to ``hub_service.capture_after_lecture_note``.

Slice 4 adds three more POST-only, MODEL CALL (cache-first) actions -- each
ephemeral: they only ever read/write the local reasoning cache
(``.jarvis-cache/``), never ``academic-record.json``/the study-pack
docx/the NotebookLM markdown. ``learning.quiz_history``/
``learning.revision_priorities`` in the workspace record are never updated
by these or any existing backend function -- the Hub does not claim they are:

- ``POST /modules/{code}/weeks/{n}/quiz``   -- delegates to
  ``hub_service.generate_quiz``.
- ``POST /modules/{code}/weeks/{n}/revise`` -- delegates to
  ``hub_service.generate_revision_brief``.
- ``POST /modules/{code}/assignment``       -- module-scoped, not
  week-scoped; delegates to ``hub_service.generate_assignment_coaching``.

None of these ever runs from a GET/page load; each requires its own POST.
Every backend ``StateError`` (and subclasses: ``ReasoningError``,
``BlackboardError``, ``DriveError``) is caught at the route and rendered as
plain text on the page that triggered it -- never as an uncaught 500, and
never re-interpreted into a different, invented status.

Hub Slice 5 (presentation-only, no new backend calls): Teach's action result
now includes its actual rendered lesson (built by calling the CLI's own
``render_teach_brief``, see ``hub_service.teach_topic``); every action
result is translated through ``_present_action_result`` before reaching a
template, so raw filesystem paths and internal ids never do; the Check page
gets a deterministic status-count summary from
``hub_service.summarize_university_check``; and Home distinguishes "no
material observed at all" from "material observed, no gaps identified"
from "gaps exist" via ``hub_service.has_any_observed_material`` -- never
"all studying complete".

Route handlers never construct or resolve credentials themselves. The
Blackboard client used by ``/check`` is produced by
``blackboard_client_factory`` -- a zero-argument callable returning a
context manager, exactly the shape ``cli._resolve_blackboard_client``
already returns. ``create_app`` defaults it to that existing resolver
(imported lazily, only when ``/check`` is actually invoked, so importing
this module never pulls in Blackboard/Playwright/Keychain code). Tests
inject a fake factory instead; no real credential is ever read, held, or
rendered by this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, ContextManager
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import hub_service
from .reasoning import ReasoningProvider
from .state import StateError

TEMPLATES_DIR = Path(__file__).resolve().parent / "hub_templates"


def _find_module(picture: dict[str, Any], module_code: str) -> dict[str, Any] | None:
    normalized = module_code.upper()
    for module in picture.get("modules", []):
        if module["module_code"] == normalized:
            return module
    return None


def _find_week(module: dict[str, Any], week_number: int) -> dict[str, Any] | None:
    for week in module.get("weeks", []):
        if week["week"] == week_number:
            return week
    return None


_CACHE_STATUS_TEXT = {
    "generated": "Generated just now (used the AI model)",
    "cached": "Reused a previously generated result (no new AI call)",
}

_ARTIFACT_LABELS = {
    "record_path": "Academic record",
    "study_pack_path": "Study pack (Word document)",
    "notebooklm_path": "NotebookLM source",
}

_FRIENDLY_LABELS = {
    "cache_status": "Generation status",
    "captured_at": "Saved at",
    "taught_at": "Taught at",
    "topic": "Topic",
    "module_code": "Module",
    "week": "Week",
}

# Internal sequence-counter ids (teach_id/capture_id): traceability keys in
# the real academic-record.json, not information a student needs on this
# page -- omitted here, never deleted from the underlying record.
_OMITTED_ACTION_RESULT_KEYS = {"teach_id", "capture_id", "rendered"}


def _present_action_result(action_result: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Turn one hub_service action result into student-facing (label, value)
    rows: no absolute filesystem paths, no raw cache/id jargon, nothing
    dropped that isn't already excluded above.
    """
    if not action_result:
        return []
    rows: list[tuple[str, str]] = []
    for key, value in action_result.items():
        if key in _OMITTED_ACTION_RESULT_KEYS or value is None:
            continue
        if key in _ARTIFACT_LABELS:
            filename = Path(value).name if isinstance(value, str) else value
            rows.append((_ARTIFACT_LABELS[key], f"{filename} updated"))
            continue
        if key == "cache_status":
            rows.append((_FRIENDLY_LABELS[key], _CACHE_STATUS_TEXT.get(value, str(value))))
            continue
        if isinstance(value, (str, int, float, bool)):
            label = _FRIENDLY_LABELS.get(key, key.replace("_", " ").capitalize())
            rows.append((label, str(value)))
    return rows


def _action_rendered_text(action_result: dict[str, Any] | None) -> str | None:
    return action_result.get("rendered") if action_result else None


async def _form_fields(request: Request) -> dict[str, str]:
    """Parse an ``application/x-www-form-urlencoded`` POST body without
    depending on ``python-multipart`` -- every Hub form is plain text
    fields, never a file upload, so the stdlib urlencoded parser is enough.
    """
    body = await request.body()
    return dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))


def _default_blackboard_client_factory() -> ContextManager[Any]:
    from .blackboard import DEFAULT_BASE_URL
    from .cli import _resolve_blackboard_client

    return _resolve_blackboard_client(DEFAULT_BASE_URL)


def create_app(
    *,
    state: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
    blackboard_client_factory: Callable[[], ContextManager[Any]] | None = None,
    reasoning_provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
) -> FastAPI:
    """Build the Hub FastAPI app.

    ``blackboard_client_factory``/``reasoning_provider``/``cache_dir`` exist
    purely so tests can inject fakes; ``serapis hub`` calls this with no
    arguments, which makes every route use the real local files and the
    real credential-resolution path, exactly as ``hub_service``'s own
    defaults and ``cli.py``'s existing resolver do today.
    """
    app = FastAPI(title="Serapis Hub")
    app.state.hub_state = state
    app.state.hub_ledger = ledger
    app.state.hub_workspace_root = workspace_root
    app.state.hub_blackboard_client_factory = (
        blackboard_client_factory or _default_blackboard_client_factory
    )
    app.state.hub_reasoning_provider = reasoning_provider
    app.state.hub_cache_dir = cache_dir

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def _picture(request: Request) -> dict[str, Any]:
        return hub_service.get_academic_picture(
            state=request.app.state.hub_state,
            ledger=request.app.state.hub_ledger,
            workspace_root=request.app.state.hub_workspace_root,
        )

    def _attention(request: Request) -> dict[str, Any]:
        return hub_service.get_attention(
            state=request.app.state.hub_state,
            ledger=request.app.state.hub_ledger,
            workspace_root=request.app.state.hub_workspace_root,
        )

    def _not_found(request: Request, message: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "not_found.html", {"active_nav": "modules", "message": message}, status_code=404
        )

    def _week_or_404(
        request: Request, module_code: str, week_number: int
    ) -> tuple[dict[str, Any], dict[str, Any]] | HTMLResponse:
        picture = _picture(request)
        module = _find_module(picture, module_code)
        if module is None:
            return _not_found(request, f"No module known as {module_code.upper()}.")
        week = _find_week(module, week_number)
        if week is None:
            return _not_found(
                request, f"No Week {week_number} known for {module['module_code']}."
            )
        return module, week

    def _render_week(
        request: Request,
        module: dict[str, Any],
        week: dict[str, Any],
        *,
        action_result: dict[str, Any] | None = None,
        action_error: str | None = None,
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "week.html",
            {
                "module": module,
                "week": week,
                "active_nav": "modules",
                "action_rows": _present_action_result(action_result),
                "action_rendered": _action_rendered_text(action_result),
                "action_error": action_error,
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        picture = _picture(request)
        attention = _attention(request)
        if not hub_service.has_any_observed_material(picture):
            material_state = "none_observed"
        elif attention["study_state_unknown"]:
            material_state = "gaps_exist"
        else:
            material_state = "no_gaps"
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "attention": attention,
                "material_state": material_state,
                # Already-fetched real picture data, exposed for Home's
                # module-count/entry-point display -- no new query, no new logic.
                "modules": picture["modules"],
                "dataset_kind": picture.get("dataset_kind"),
                "active_nav": "home",
            },
        )

    @app.get("/modules", response_class=HTMLResponse)
    def modules(request: Request) -> HTMLResponse:
        picture = _picture(request)
        return templates.TemplateResponse(
            request, "modules.html", {"modules": picture["modules"], "dataset_kind": picture.get("dataset_kind"), "active_nav": "modules"}
        )

    @app.get("/modules/{module_code}", response_class=HTMLResponse)
    def module_detail(request: Request, module_code: str) -> HTMLResponse:
        picture = _picture(request)
        module = _find_module(picture, module_code)
        if module is None:
            return _not_found(request, f"No module known as {module_code.upper()}.")
        return templates.TemplateResponse(
            request, "module.html", {"module": module, "dataset_kind": picture.get("dataset_kind"), "active_nav": "modules"}
        )

    @app.get("/modules/{module_code}/weeks/{week_number}", response_class=HTMLResponse)
    def week_detail(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, week = found
        return _render_week(request, module, week)

    @app.get("/assessments", response_class=HTMLResponse)
    def assessments(request: Request) -> HTMLResponse:
        picture = _picture(request)
        return templates.TemplateResponse(
            request,
            "assessments.html",
            {"modules": picture["modules"], "dataset_kind": picture.get("dataset_kind"), "active_nav": "assessments"},
        )

    @app.get("/check", response_class=HTMLResponse)
    def check_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "check.html",
            {"active_nav": "check", "result": None, "summary": None, "error": None},
        )

    @app.post("/check", response_class=HTMLResponse)
    def check_run(request: Request) -> HTMLResponse:
        """EXTERNAL READ, human-triggered only. Drive sync always stays off."""
        result: dict[str, Any] | None = None
        summary: dict[str, int] | None = None
        error: str | None = None
        try:
            factory = request.app.state.hub_blackboard_client_factory
            with factory() as client:
                result = hub_service.run_university_check(
                    client, ledger=request.app.state.hub_ledger, sync_to_drive=False
                )
            summary = hub_service.summarize_university_check(result)
        except StateError as exc:
            error = str(exc)
        return templates.TemplateResponse(
            request,
            "check.html",
            {"active_nav": "check", "result": result, "summary": summary, "error": error},
        )

    @app.post("/modules/{module_code}/weeks/{week_number}/build", response_class=HTMLResponse)
    def build_workspace(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        """EXTERNAL WRITE / MODEL CALL only on a local prepare-cache miss."""
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, _week = found
        action_result: dict[str, Any] | None = None
        action_error: str | None = None
        try:
            action_result = hub_service.materialize_workspace(
                module["module_code"],
                week_number,
                state=request.app.state.hub_state,
                provider=request.app.state.hub_reasoning_provider,
                cache_dir=request.app.state.hub_cache_dir,
                workspace_root=request.app.state.hub_workspace_root,
            )
        except StateError as exc:
            action_error = str(exc)
        refreshed = _week_or_404(request, module_code, week_number)
        if isinstance(refreshed, HTMLResponse):
            return refreshed
        module, week = refreshed
        return _render_week(request, module, week, action_result=action_result, action_error=action_error)

    @app.post("/modules/{module_code}/weeks/{week_number}/teach", response_class=HTMLResponse)
    async def teach(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        """EXTERNAL WRITE / MODEL CALL, always. Topic is the only exposed field."""
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, _week = found
        form = await _form_fields(request)
        topic = form.get("topic", "").strip() or None
        action_result: dict[str, Any] | None = None
        action_error: str | None = None
        try:
            action_result = hub_service.teach_topic(
                module["module_code"],
                week_number,
                topic=topic,
                state=request.app.state.hub_state,
                provider=request.app.state.hub_reasoning_provider,
                cache_dir=request.app.state.hub_cache_dir,
                workspace_root=request.app.state.hub_workspace_root,
            )
        except StateError as exc:
            action_error = str(exc)
        refreshed = _week_or_404(request, module_code, week_number)
        if isinstance(refreshed, HTMLResponse):
            return refreshed
        module, week = refreshed
        return _render_week(request, module, week, action_result=action_result, action_error=action_error)

    @app.post("/modules/{module_code}/weeks/{week_number}/quiz", response_class=HTMLResponse)
    def quiz(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        """MODEL CALL (cache-first). Ephemeral: never touches the workspace record."""
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, week = found
        action_result: dict[str, Any] | None = None
        action_error: str | None = None
        try:
            action_result = hub_service.generate_quiz(
                module["module_code"],
                week_number,
                state=request.app.state.hub_state,
                provider=request.app.state.hub_reasoning_provider,
                cache_dir=request.app.state.hub_cache_dir,
            )
        except StateError as exc:
            action_error = str(exc)
        return _render_week(request, module, week, action_result=action_result, action_error=action_error)

    @app.post("/modules/{module_code}/weeks/{week_number}/revise", response_class=HTMLResponse)
    def revise(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        """MODEL CALL (cache-first). Ephemeral: never touches the workspace record."""
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, week = found
        action_result: dict[str, Any] | None = None
        action_error: str | None = None
        try:
            action_result = hub_service.generate_revision_brief(
                module["module_code"],
                week_number,
                state=request.app.state.hub_state,
                provider=request.app.state.hub_reasoning_provider,
                cache_dir=request.app.state.hub_cache_dir,
            )
        except StateError as exc:
            action_error = str(exc)
        return _render_week(request, module, week, action_result=action_result, action_error=action_error)

    @app.post("/modules/{module_code}/assignment", response_class=HTMLResponse)
    def assignment(request: Request, module_code: str) -> HTMLResponse:
        """MODEL CALL (cache-first), module-scoped. Ephemeral: never touches the workspace record."""
        picture = _picture(request)
        module = _find_module(picture, module_code)
        if module is None:
            return _not_found(request, f"No module known as {module_code.upper()}.")
        action_result: dict[str, Any] | None = None
        action_error: str | None = None
        try:
            action_result = hub_service.generate_assignment_coaching(
                module["module_code"],
                state=request.app.state.hub_state,
                provider=request.app.state.hub_reasoning_provider,
                cache_dir=request.app.state.hub_cache_dir,
            )
        except StateError as exc:
            action_error = str(exc)
        return templates.TemplateResponse(
            request,
            "module.html",
            {
                "module": module,
                "active_nav": "modules",
                "action_rows": _present_action_result(action_result),
                "action_rendered": _action_rendered_text(action_result),
                "action_error": action_error,
            },
        )

    @app.post(
        "/modules/{module_code}/weeks/{week_number}/after-lecture", response_class=HTMLResponse
    )
    async def after_lecture(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        """LOCAL WRITE only. Never makes a network or model call."""
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, _week = found
        form = await _form_fields(request)
        notes_text = form.get("notes", "").strip()
        uncertainty_text = form.get("uncertainty", "").strip()
        question_text = form.get("question", "").strip()
        action_result: dict[str, Any] | None = None
        action_error: str | None = None
        try:
            action_result = hub_service.capture_after_lecture_note(
                module["module_code"],
                week_number,
                notes=[notes_text] if notes_text else None,
                uncertainties=[uncertainty_text] if uncertainty_text else None,
                questions=[question_text] if question_text else None,
                workspace_root=request.app.state.hub_workspace_root,
            )
        except StateError as exc:
            action_error = str(exc)
        refreshed = _week_or_404(request, module_code, week_number)
        if isinstance(refreshed, HTMLResponse):
            return refreshed
        module, week = refreshed
        return _render_week(request, module, week, action_result=action_result, action_error=action_error)

    return app
