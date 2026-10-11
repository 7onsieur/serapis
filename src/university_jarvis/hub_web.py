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
explicitly invoked by the student. Quiz generation persists its private
question/answer set in an existing workspace, while student responses are
saved by separate POST actions. Revision remains cache-backed:

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

Phase 3B adds the Tutor: ``GET .../tutor/{session_id}`` renders a saved session
read-only (no write, no provider call); ``POST .../tutor/start`` and
``POST .../tutor/{session_id}/{answer|hint|dont-know|dispute|reveal|end|delete}`` are thin
wrappers over ``tutoring`` that redirect (303) back to the GET page. Every turn
carries a ``client_turn_id`` so a resubmitted form is idempotent.

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
import os
import secrets
import sys
from typing import Any, Callable, ContextManager
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response
from fastapi.templating import Jinja2Templates

from . import hub_service, tutoring
from .hub_security import MAX_UPLOAD_BYTES, HubSecurityMiddleware
from .reasoning import OpenAIReasoningProvider, ReasoningProvider
from .state import StateError, load_state

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


_UPLOAD_CHUNK_BYTES = 1024 * 1024
_UPLOAD_SUFFIXES = (".pdf", ".pptx")


def _safe_upload_name(filename: str) -> str:
    """A filesystem-safe basename that keeps the (validated) extension."""
    name = Path(filename.replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    if suffix not in _UPLOAD_SUFFIXES:
        raise StateError("Choose a PDF or PowerPoint (.pptx) file.")
    stem = "".join(c if (c.isalnum() or c in " ._-()") else "_" for c in Path(name).stem).strip(" .")
    return (stem[:120] or "material") + suffix


async def _stream_upload_to_private_file(upload: Any, directory: Path) -> Path:
    """Copy an upload to ``directory`` in chunks, enforcing the size limit and
    checking the content matches the declared file type. The directory is
    private (0700) and caller-owned; the caller removes it."""
    from .student_setup import validate_material_content

    target = directory / _safe_upload_name(upload.filename)
    written = 0
    with target.open("xb") as handle:
        while True:
            chunk = await upload.read(_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise StateError(
                    f"File is too large. The limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB per file."
                )
            handle.write(chunk)
    if written == 0:
        raise StateError("The selected file is empty.")
    validate_material_content(target)
    return target


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
    allowed_hosts: tuple[str, ...] = (),
) -> FastAPI:
    """Build the Hub FastAPI app.

    ``blackboard_client_factory``/``reasoning_provider``/``cache_dir`` exist
    purely so tests can inject fakes; ``serapis hub`` calls this with no
    arguments, which makes every route use the real local files and the
    real credential-resolution path, exactly as ``hub_service``'s own
    defaults and ``cli.py``'s existing resolver do today.
    """
    app = FastAPI(title="Serapis Hub")
    app.add_middleware(HubSecurityMiddleware, allowed_hosts=allowed_hosts)
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
        active_task: dict[str, Any] | None = None,
        learning_recommendation: dict[str, Any] | None = None,
    ) -> HTMLResponse:
        learning = None
        quiz_questions = []
        if week.get("study_state", {}).get("record_found"):
            learning = hub_service.learning_view(module["module_code"], week["week"], workspace_root=request.app.state.hub_workspace_root)
            from .workspace import _learning_record
            record, *_ = _learning_record(module["module_code"], week["week"], request.app.state.hub_workspace_root)
            quizzes = record.get("learning", {}).get("quiz_history", {}).get("attempts", [])
            if quizzes:
                quiz_questions = [{"quiz_id": quizzes[-1]["quiz_id"], **q} for q in quizzes[-1].get("questions", [])]
        tutor = None
        if learning is not None:
            # Read-only: lists session files; never writes or calls the provider.
            tutor = {
                "sessions": tutoring.list_sessions(
                    module["module_code"], week["week"], workspace_root=request.app.state.hub_workspace_root),
                "request_id": secrets.token_hex(12),
            }
        return templates.TemplateResponse(
            request,
            "week.html",
            {
                "module": module,
                "week": week,
                "tutor": tutor,
                "active_nav": "modules",
                "action_rows": _present_action_result(action_result),
                "action_rendered": _action_rendered_text(action_result),
                "action_error": action_error,
                "learning": learning,
                "quiz_questions": quiz_questions,
                "active_task": active_task,
                "learning_recommendation": learning_recommendation,
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
                "setup_status": "Add a module to begin." if not picture["modules"] else f"{len(picture['modules'])} module(s) set up.",
            },
        )

    @app.post("/modules", response_class=HTMLResponse)
    async def add_module_route(request: Request) -> HTMLResponse:
        from .student_setup import add_module
        form = await _form_fields(request)
        try:
            add_module(form.get("code", ""), form.get("title", ""))
            return RedirectResponse("/modules", status_code=303)
        except StateError as exc:
            picture = _picture(request)
            return templates.TemplateResponse(request, "modules.html", {"modules": picture["modules"], "error": str(exc), "active_nav": "modules"}, status_code=400)

    @app.post("/modules/{module_code}/edit", response_class=HTMLResponse)
    async def edit_module_route(request: Request, module_code: str) -> HTMLResponse:
        from .student_setup import update_module
        form = await _form_fields(request)
        try:
            update_module(module_code, form.get("title", ""), new_code=form.get("code") or None)
            return RedirectResponse("/modules", status_code=303)
        except StateError as exc:
            return _not_found(request, str(exc))

    @app.post("/modules/{module_code}/remove")
    def remove_module_route(request: Request, module_code: str) -> Response:
        from .student_setup import remove_module
        try:
            remove_module(module_code)
            return RedirectResponse("/modules", status_code=303)
        except StateError as exc:
            return _not_found(request, f"Module was not removed: {exc}")

    @app.post("/modules/{module_code}/assessments", response_class=HTMLResponse)
    async def add_assessment_route(request: Request, module_code: str) -> HTMLResponse:
        from .student_setup import save_assessment
        form = await _form_fields(request)
        try:
            save_assessment(module_code, title=form.get("title", ""), deadline=form.get("deadline", ""), weight_percent=form.get("weight", ""), requirements=form.get("requirements", ""))
            return RedirectResponse(f"/modules/{module_code}", status_code=303)
        except StateError as exc:
            return _not_found(request, str(exc))

    @app.post("/modules/{module_code}/assessments/{assessment_id}/remove")
    def remove_assessment_route(request: Request, module_code: str, assessment_id: str) -> Response:
        from .student_setup import remove_assessment
        try:
            remove_assessment(module_code, assessment_id)
            return RedirectResponse(f"/modules/{module_code}", status_code=303)
        except StateError as exc:
            return _not_found(request, f"Assessment was not removed: {exc}")

    @app.post("/modules/{module_code}/assessments/{assessment_id}/edit")
    async def edit_assessment_route(request: Request, module_code: str, assessment_id: str) -> Response:
        from .student_setup import save_assessment
        form = await _form_fields(request)
        try:
            save_assessment(module_code, assessment_id=assessment_id, title=form.get("title", ""), deadline=form.get("deadline", ""), weight_percent=form.get("weight", ""), requirements=form.get("requirements", ""))
            return RedirectResponse(f"/modules/{module_code}", status_code=303)
        except StateError as exc:
            return _not_found(request, f"Assessment was not saved: {exc}")

    @app.post("/modules/{module_code}/materials", response_class=HTMLResponse)
    async def add_material_route(request: Request, module_code: str) -> HTMLResponse:
        from .student_setup import import_material
        from .state import StateError
        try:
            form = await request.form()
            upload = form.get("file")
            if upload is None or not getattr(upload, "filename", ""):
                raise StateError("Choose a PDF or PowerPoint (.pptx) file to add.")
            week_text = str(form.get("week", "")).strip()
            week = int(week_text) if week_text else None
            import shutil
            import tempfile
            scratch_dir = Path(tempfile.mkdtemp(prefix="serapis-upload-"))
            try:
                scratch = await _stream_upload_to_private_file(upload, scratch_dir)
                result = import_material(module_code, scratch, week=week)
            finally:
                shutil.rmtree(scratch_dir, ignore_errors=True)
            return RedirectResponse(f"/modules/{module_code}?imported=1", status_code=303)
        except (StateError, ValueError, OSError) as exc:
            return _not_found(request, f"Material could not be added: {exc}")

    @app.post("/materials/{source_id}/remove")
    def remove_material_route(request: Request, source_id: str) -> Response:
        from .student_setup import remove_material
        try:
            remove_material(source_id)
            return RedirectResponse("/modules", status_code=303)
        except StateError as exc:
            return _not_found(request, f"Material was not removed: {exc}")

    @app.post("/materials/{source_id}/replace")
    async def replace_material_route(request: Request, source_id: str) -> RedirectResponse:
        from .student_setup import replace_material
        form = await request.form()
        upload = form.get("file")
        if upload is None or not getattr(upload, "filename", ""):
            return _not_found(request, "Choose a replacement PDF or PowerPoint file.")
        import shutil
        import tempfile
        scratch_dir = Path(tempfile.mkdtemp(prefix="serapis-replace-"))
        try:
            scratch = await _stream_upload_to_private_file(upload, scratch_dir)
            result = replace_material(source_id, scratch)
            return RedirectResponse("/modules", status_code=303)
        except (StateError, OSError) as exc:
            return _not_found(request, f"Replacement was not saved: {exc}")
        finally:
            shutil.rmtree(scratch_dir, ignore_errors=True)

    @app.post("/materials/{source_id}/reassign")
    async def reassign_material_route(request: Request, source_id: str) -> RedirectResponse:
        from .student_setup import reassign_material
        form = await _form_fields(request)
        try:
            week = int(form["week"]) if form.get("week", "").strip() else None
            reassign_material(source_id, form.get("module_code", ""), week)
            return RedirectResponse("/modules", status_code=303)
        except (StateError, ValueError) as exc:
            return _not_found(request, f"Material location was not changed: {exc}")

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
        from .state import load_state
        state = request.app.state.hub_state or load_state()
        sources = [s for s in state.get("sources", []) if s.get("module_code", "").upper() == module_code.upper()]
        return templates.TemplateResponse(
            request, "module.html", {"module": module, "materials": sources, "is_macos": sys.platform == "darwin", "dataset_kind": picture.get("dataset_kind"), "active_nav": "modules"}
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
                workspace_root=request.app.state.hub_workspace_root,
            )
        except StateError as exc:
            action_error = str(exc)
        return _render_week(request, module, week, action_result=action_result, action_error=action_error)

    @app.post("/modules/{module_code}/weeks/{week_number}/learning/response", response_class=HTMLResponse)
    async def learning_response(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse): return found
        module, week = found
        form = await _form_fields(request)
        try:
            references = []
            if form.get("source_id"):
                references = [{"source_id": form["source_id"], "location": form.get("location", "") }]
            action_result = hub_service.submit_learning_response(
                module["module_code"], week_number, task=form.get("task", ""),
                capability=form.get("capability", "EXPLANATION"), origin=form.get("origin", "TEACH"),
                response=form.get("response", ""), expected_answer=form.get("expected_answer") or None,
                source_references=references, assistance_status="PROMPTED" if form.get("prompted") == "yes" else "UNAIDED",
                prompt_help=[form["prompt_help"]] if form.get("prompt_help") else [],
                workspace_root=request.app.state.hub_workspace_root)
            return _render_week(request, module, week, action_result={"attempted_at": action_result["attempted_at"]})
        except StateError as exc:
            return _render_week(request, module, week, action_error=str(exc))

    @app.post("/modules/{module_code}/weeks/{week_number}/learning/continue", response_class=HTMLResponse)
    def learning_continue(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse): return found
        module, week = found
        try:
            result = hub_service.continue_learning_task(module["module_code"], week_number,
                state=request.app.state.hub_state, provider=request.app.state.hub_reasoning_provider,
                workspace_root=request.app.state.hub_workspace_root)
            return _render_week(request, module, week, active_task=result["task"],
                                learning_recommendation=result["recommendation"])
        except StateError as exc:
            return _render_week(request, module, week, action_error=str(exc))

    @app.post("/modules/{module_code}/weeks/{week_number}/learning/recommended-response", response_class=HTMLResponse)
    async def recommended_response(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse): return found
        module, week = found
        form = await _form_fields(request)
        try:
            result = hub_service.submit_recommended_response(module["module_code"], week_number,
                form.get("task_id", ""), form.get("response", ""), prompted=form.get("prompted") == "yes",
                prompt_help=[form["prompt_help"]] if form.get("prompt_help") else [],
                workspace_root=request.app.state.hub_workspace_root)
            return _render_week(request, module, week, action_result={"attempted_at": result["attempted_at"]})
        except StateError as exc:
            return _render_week(request, module, week, action_error=str(exc))

    @app.post("/modules/{module_code}/weeks/{week_number}/learning/quiz-answer", response_class=HTMLResponse)
    async def quiz_answer(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse): return found
        module, week = found
        form = await _form_fields(request)
        try:
            hub_service.answer_quiz_question(module["module_code"], week_number, form.get("quiz_id", ""),
                form.get("question_id", ""), form.get("response", ""), workspace_root=request.app.state.hub_workspace_root)
            return _render_week(request, module, week, action_result={"message": "Quiz response saved before evaluation."})
        except StateError as exc:
            return _render_week(request, module, week, action_error=str(exc))

    @app.post("/modules/{module_code}/weeks/{week_number}/learning/evaluate", response_class=HTMLResponse)
    async def learning_evaluate(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse): return found
        module, week = found
        form = await _form_fields(request)
        try:
            result = hub_service.evaluate_learning_attempt(module["module_code"], week_number,
                form.get("attempt_id", ""), state=request.app.state.hub_state,
                provider=request.app.state.hub_reasoning_provider,
                workspace_root=request.app.state.hub_workspace_root)
            return _render_week(request, module, week, action_result={"evaluation_outcome": result["evaluation"]["outcome"]})
        except StateError as exc:
            return _render_week(request, module, week, action_error=str(exc))

    # --- Tutor (Phase 3B): thin wrappers over ``tutoring``; no tutoring logic lives here. ---
    # GET renders a saved session read-only. Every action is a POST carrying a
    # client_turn_id, then redirects (303) back to the GET page.

    def _tutor_url(module: dict[str, Any], week_number: int, session_id: str) -> str:
        return f"/modules/{module['module_code']}/weeks/{week_number}/tutor/{session_id}"

    def _render_tutor(request: Request, module: dict[str, Any], week: dict[str, Any],
                      view: dict[str, Any], *, error: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "tutor.html",
            {"module": module, "week": week, "session": view, "error": error,
             "new_turn_id": secrets.token_hex(12), "active_nav": "modules"},
        )

    @app.get("/modules/{module_code}/weeks/{week_number}/tutor/{session_id}", response_class=HTMLResponse)
    def tutor_session(request: Request, module_code: str, week_number: int, session_id: str) -> HTMLResponse:
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, week = found
        try:
            view = tutoring.load_session(
                module["module_code"], week_number, session_id,
                workspace_root=request.app.state.hub_workspace_root)
        except StateError:
            return _not_found(request, "That tutoring session was not found. It may have been deleted.")
        return _render_tutor(request, module, week, view)

    @app.post("/modules/{module_code}/weeks/{week_number}/tutor/start", response_class=HTMLResponse)
    async def tutor_start(request: Request, module_code: str, week_number: int) -> Response:
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, week = found
        form = await _form_fields(request)
        try:
            view = tutoring.create_session(
                request.app.state.hub_state if request.app.state.hub_state is not None else load_state(),
                module["module_code"], week_number,
                intention=form.get("intention", ""), client_request_id=form.get("client_request_id", ""),
                provider=request.app.state.hub_reasoning_provider or OpenAIReasoningProvider(),
                workspace_root=request.app.state.hub_workspace_root)
        except StateError as exc:
            return _render_week(request, module, week, action_error=str(exc))
        return RedirectResponse(_tutor_url(module, week_number, view["session_id"]), status_code=303)

    @app.post("/modules/{module_code}/weeks/{week_number}/tutor/{session_id}/{action}", response_class=HTMLResponse)
    async def tutor_action(request: Request, module_code: str, week_number: int, session_id: str,
                           action: str) -> Response:
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, week = found
        if action not in {"answer", "hint", "dont-know", "dispute", "reveal", "end", "delete"}:
            return _not_found(request, "Unknown tutoring action.")
        form = await _form_fields(request)
        root = request.app.state.hub_workspace_root
        code = module["module_code"]
        turn_id = form.get("client_turn_id", "")
        provider = request.app.state.hub_reasoning_provider or OpenAIReasoningProvider()
        state = request.app.state.hub_state if request.app.state.hub_state is not None else load_state()
        url = _tutor_url(module, week_number, session_id)
        error: str | None = None
        try:
            if action == "answer":
                tutoring.submit_response(state, code, week_number, session_id, client_turn_id=turn_id,
                                         text=form.get("response", ""), provider=provider, workspace_root=root,
                                         confidence=form.get("confidence") or None)
            elif action == "dispute":
                tutoring.dispute_diagnosis(state, code, week_number, session_id, client_turn_id=turn_id,
                                           target_turn_id=form.get("target", ""), provider=provider,
                                           workspace_root=root)
            elif action in ("hint", "dont-know"):
                # "I don't know" asks for the next hint; the answer is only ever shown on request.
                tutoring.request_hint(state, code, week_number, session_id, client_turn_id=turn_id,
                                      provider=provider, workspace_root=root)
            elif action == "reveal":
                if form.get("confirm") != "yes":
                    raise StateError("Tick the box to confirm you want the answer shown.")
                tutoring.reveal_answer(state, code, week_number, session_id, client_turn_id=turn_id,
                                       provider=provider, workspace_root=root)
            elif action == "end":
                tutoring.end_session(code, week_number, session_id, workspace_root=root)
            else:
                if form.get("confirm") != "yes":
                    raise StateError("Tick the box to confirm you want this transcript deleted.")
                tutoring.delete_session(code, week_number, session_id, workspace_root=root)
                return RedirectResponse(f"/modules/{code}/weeks/{week_number}", status_code=303)
        except StateError as exc:
            error = str(exc)
        if error is None:
            return RedirectResponse(url, status_code=303)
        try:
            view = tutoring.load_session(code, week_number, session_id, workspace_root=root)
        except StateError:
            return _render_week(request, module, week, action_error=error)
        return _render_tutor(request, module, week, view, error=error)

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
