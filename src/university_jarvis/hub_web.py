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
``POST .../tutor/{session_id}/{answer|hint|dont-know|dispute|reveal|next|skip|end|delete}`` are thin
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

from . import assignment_coach, hub_service, tutoring
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
_OMITTED_ACTION_RESULT_KEYS = {"teach_id", "capture_id", "rendered", "evidence_rendered", "evidence_status",
                               "evidence_items", "evidence_used", "attempts", "usage"}


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


def _action_evidence_text(action_result: dict[str, Any] | None) -> str | None:
    """The deterministic 'what your recorded answers show' block that accompanies REVISE and TEACH."""
    return action_result.get("evidence_rendered") if action_result else None


async def _form_fields(request: Request) -> dict[str, str]:
    """Parse an ``application/x-www-form-urlencoded`` POST body without
    depending on ``python-multipart`` -- every Hub form is plain text
    fields, never a file upload, so the stdlib urlencoded parser is enough.
    """
    body = await request.body()
    return dict(parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True))


async def _form_pairs(request: Request) -> list[tuple[str, str]]:
    """Like ``_form_fields`` but keeps repeated fields (checkbox groups)."""
    body = await request.body()
    return parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True)


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
    demo_mode: bool = False,
) -> FastAPI:
    """Build the Hub FastAPI app.

    ``blackboard_client_factory``/``reasoning_provider``/``cache_dir`` exist
    purely so tests can inject fakes; ``serapis hub`` calls this with no
    arguments, which makes every route use the real local files and the
    real credential-resolution path, exactly as ``hub_service``'s own
    defaults and ``cli.py``'s existing resolver do today.
    """
    if demo_mode:
        # The synthetic demonstration never reaches Blackboard, whatever the student's machine is set up for.
        def blackboard_client_factory() -> ContextManager[Any]:  # type: ignore[misc]
            raise StateError("Blackboard is switched off in the synthetic demonstration.")
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
    templates.env.globals["demo_mode"] = demo_mode

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

    def _render_module(
        request: Request,
        module_code: str,
        *,
        status_code: int = 200,
        action_result: dict[str, Any] | None = None,
        action_error: str | None = None,
    ) -> HTMLResponse:
        picture = _picture(request)
        module = _find_module(picture, module_code)
        if module is None:
            return _not_found(request, f"No module known as {module_code.upper()}.")
        state = request.app.state.hub_state or load_state()
        sources = [s for s in state.get("sources", []) if s.get("module_code", "").upper() == module_code.upper()]
        root = request.app.state.hub_workspace_root
        coach = {}
        for row in assignment_coach.list_sessions(module["module_code"], workspace_root=root):
            if row["status"] == "ACTIVE":
                coach.setdefault(row["assessment_id"], row)
        return templates.TemplateResponse(
            request,
            "module.html",
            {
                "module": module,
                "materials": sources,
                "is_macos": sys.platform == "darwin",
                "dataset_kind": picture.get("dataset_kind"),
                "active_nav": "modules",
                "coach_sessions": coach,
                "coach_request_id": secrets.token_hex(12),
                "imported": request.query_params.get("imported") == "1",
                "action_rows": _present_action_result(action_result),
                "action_rendered": _action_rendered_text(action_result),
                "action_evidence": _action_evidence_text(action_result),
                "action_error": action_error,
            },
            status_code=status_code,
        )

    def _render_modules_error(request: Request, error: str) -> HTMLResponse:
        picture = _picture(request)
        return templates.TemplateResponse(
            request, "modules.html",
            {"modules": picture["modules"], "dataset_kind": picture.get("dataset_kind"), "error": error, "active_nav": "modules"},
            status_code=400,
        )

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
        root = request.app.state.hub_workspace_root
        reflections = hub_service.reflection_overview(module["module_code"], week["week"], workspace_root=root)
        journey = hub_service.week_journey(module["module_code"], week["week"], workspace_root=root)
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
                "action_evidence": _action_evidence_text(action_result),
                "action_error": action_error,
                "learning": learning,
                "reflections": reflections,
                "journey": journey,
                "has_record": bool(week.get("study_state", {}).get("record_found")),
                "quiz_questions": quiz_questions,
                "active_task": active_task,
                "learning_recommendation": learning_recommendation,
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        picture = _picture(request)
        attention = _attention(request)
        try:
            journey = hub_service.build_student_journey(
                _state(request), picture, workspace_root=request.app.state.hub_workspace_root)
        except (StateError, OSError, ValueError, KeyError, TypeError):
            journey = None  # Home must always render; a damaged record only hides the checklist
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
                "journey": journey,
            },
        )

    def _state(request: Request) -> dict[str, Any]:
        return request.app.state.hub_state if request.app.state.hub_state is not None else load_state()

    @app.post("/workspace/start", response_class=HTMLResponse)
    def start_personal_workspace(request: Request) -> Response:
        """LOCAL WRITE: create the student's own empty workspace so they stop looking at the fictional sample."""
        from .student_setup import initialize_personal_state
        try:
            initialize_personal_state()
        except StateError as exc:
            return _render_modules_error(request, str(exc))
        return RedirectResponse("/profile", status_code=303)

    @app.get("/profile", response_class=HTMLResponse)
    def profile(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "profile.html",
            {"student": _state(request).get("student", {}), "active_nav": "profile", "saved": request.query_params.get("saved") == "1"},
        )

    @app.post("/profile", response_class=HTMLResponse)
    async def save_profile(request: Request) -> Response:
        from .student_setup import edit_profile
        form = await _form_fields(request)
        try:
            edit_profile(university=form.get("university", ""), programme=form.get("programme", ""))
        except StateError as exc:
            student = {"university": form.get("university", ""), "programme": form.get("programme", "")}
            return templates.TemplateResponse(
                request, "profile.html", {"student": student, "error": str(exc), "active_nav": "profile"}, status_code=400)
        return RedirectResponse("/profile?saved=1", status_code=303)

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
            return _render_module(request, module_code, status_code=400, action_error=f"Module was not saved: {exc}")

    @app.post("/modules/{module_code}/remove")
    def remove_module_route(request: Request, module_code: str) -> Response:
        from .student_setup import remove_module
        try:
            remove_module(module_code)
            return RedirectResponse("/modules", status_code=303)
        except StateError as exc:
            return _render_module(request, module_code, status_code=400, action_error=f"Module was not removed: {exc}")

    @app.post("/modules/{module_code}/assessments", response_class=HTMLResponse)
    async def add_assessment_route(request: Request, module_code: str) -> HTMLResponse:
        from .student_setup import save_assessment
        form = await _form_fields(request)
        try:
            save_assessment(module_code, title=form.get("title", ""), deadline=form.get("deadline", ""), weight_percent=form.get("weight", ""), requirements=form.get("requirements", ""))
            return RedirectResponse(f"/modules/{module_code}#assessments", status_code=303)
        except StateError as exc:
            return _render_module(request, module_code, status_code=400, action_error=f"Assessment was not saved: {exc}")

    @app.post("/modules/{module_code}/assessments/{assessment_id}/remove")
    def remove_assessment_route(request: Request, module_code: str, assessment_id: str) -> Response:
        from .student_setup import remove_assessment
        try:
            remove_assessment(module_code, assessment_id)
            return RedirectResponse(f"/modules/{module_code}#assessments", status_code=303)
        except StateError as exc:
            return _render_module(request, module_code, status_code=400, action_error=f"Assessment was not removed: {exc}")

    @app.post("/modules/{module_code}/assessments/{assessment_id}/edit")
    async def edit_assessment_route(request: Request, module_code: str, assessment_id: str) -> Response:
        from .student_setup import save_assessment
        form = await _form_fields(request)
        try:
            save_assessment(module_code, assessment_id=assessment_id, title=form.get("title", ""), deadline=form.get("deadline", ""), weight_percent=form.get("weight", ""), requirements=form.get("requirements", ""))
            return RedirectResponse(f"/modules/{module_code}#assessments", status_code=303)
        except StateError as exc:
            return _render_module(request, module_code, status_code=400, action_error=f"Assessment was not saved: {exc}")

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
            return RedirectResponse(f"/modules/{module_code}?imported=1#materials", status_code=303)
        except (StateError, ValueError, OSError) as exc:
            message = "Week must be a whole number." if isinstance(exc, ValueError) and not isinstance(exc, StateError) else str(exc)
            return _render_module(request, module_code, status_code=400, action_error=f"Material could not be added: {message}")

    @app.post("/materials/{source_id}/remove")
    def remove_material_route(request: Request, source_id: str) -> Response:
        from .student_setup import remove_material
        try:
            remove_material(source_id)
            return RedirectResponse("/modules", status_code=303)
        except StateError as exc:
            return _render_modules_error(request, f"Material was not removed: {exc}")

    @app.post("/materials/{source_id}/replace")
    async def replace_material_route(request: Request, source_id: str) -> RedirectResponse:
        from .student_setup import replace_material
        form = await request.form()
        upload = form.get("file")
        if upload is None or not getattr(upload, "filename", ""):
            return _render_modules_error(request, "Choose a replacement PDF or PowerPoint file.")
        import shutil
        import tempfile
        scratch_dir = Path(tempfile.mkdtemp(prefix="serapis-replace-"))
        try:
            scratch = await _stream_upload_to_private_file(upload, scratch_dir)
            result = replace_material(source_id, scratch)
            return RedirectResponse("/modules", status_code=303)
        except (StateError, OSError) as exc:
            return _render_modules_error(request, f"Replacement was not saved: {exc}")
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
            return _render_modules_error(request, f"Material location was not changed: {exc}")

    @app.get("/modules", response_class=HTMLResponse)
    def modules(request: Request) -> HTMLResponse:
        picture = _picture(request)
        return templates.TemplateResponse(
            request, "modules.html", {"modules": picture["modules"], "dataset_kind": picture.get("dataset_kind"), "active_nav": "modules"}
        )

    @app.get("/modules/{module_code}", response_class=HTMLResponse)
    def module_detail(request: Request, module_code: str) -> HTMLResponse:
        return _render_module(request, module_code)

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
                state=_state(request), provider=request.app.state.hub_reasoning_provider,
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
                form.get("attempt_id", ""), state=_state(request),
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
        if action not in {"answer", "hint", "dont-know", "dispute", "reveal", "next", "skip", "end", "delete"}:
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
            elif action == "next":
                tutoring.next_question(state, code, week_number, session_id, client_turn_id=turn_id,
                                       provider=provider, workspace_root=root)
            elif action == "skip":
                tutoring.skip_question(state, code, week_number, session_id, client_turn_id=turn_id,
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
                workspace_root=request.app.state.hub_workspace_root,
            )
        except StateError as exc:
            action_error = str(exc)
        return _render_week(request, module, week, action_result=action_result, action_error=action_error)

    @app.post("/modules/{module_code}/assignment", response_class=HTMLResponse)
    def assignment(request: Request, module_code: str) -> HTMLResponse:
        """MODEL CALL (cache-first), module-scoped one-off planning brief. Ephemeral: never touches the workspace record.

        The resumable, per-assignment coaching lives under ``/modules/{code}/coach/{session}``.
        """
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
        return _render_module(request, module["module_code"], action_result=action_result, action_error=action_error)

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

        def lines(name: str) -> list[str] | None:
            """One entry per non-empty line; a blank field records nothing."""
            values = [line.strip() for line in form.get(name, "").splitlines() if line.strip()]
            return values or None

        def block(name: str) -> list[str] | None:
            text = form.get(name, "").strip()
            return [text] if text else None

        action_result: dict[str, Any] | None = None
        action_error: str | None = None
        try:
            action_result = hub_service.capture_after_lecture_note(
                module["module_code"],
                week_number,
                covered=block("covered"),
                notes=block("notes"),
                understood=lines("understood"),
                uncertainties=lines("uncertainty"),
                questions=lines("question"),
                examples_cases=lines("examples"),
                assessment_comments=lines("assessment"),
                lecturer_emphasis=lines("emphasis"),
                state=_state(request),
                workspace_root=request.app.state.hub_workspace_root,
            )
        except StateError as exc:
            action_error = str(exc)
        refreshed = _week_or_404(request, module_code, week_number)
        if isinstance(refreshed, HTMLResponse):
            return refreshed
        module, week = refreshed
        return _render_week(request, module, week, action_result=action_result, action_error=action_error)

    @app.post(
        "/modules/{module_code}/weeks/{week_number}/reflections/correct", response_class=HTMLResponse
    )
    async def correct_reflection(request: Request, module_code: str, week_number: int) -> HTMLResponse:
        """LOCAL WRITE only. Appends a correction; the original reflection is never edited."""
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, _week = found
        form = await _form_fields(request)
        action_result: dict[str, Any] | None = None
        action_error: str | None = None
        try:
            action_result = hub_service.correct_reflection(
                module["module_code"],
                week_number,
                form.get("entry_id", ""),
                action=form.get("action", ""),
                new_text=form.get("new_text"),
                reason=form.get("reason"),
                workspace_root=request.app.state.hub_workspace_root,
            )
        except StateError as exc:
            action_error = str(exc)
        refreshed = _week_or_404(request, module_code, week_number)
        if isinstance(refreshed, HTMLResponse):
            return refreshed
        module, week = refreshed
        return _render_week(request, module, week, action_result=action_result, action_error=action_error)

    @app.get("/modules/{module_code}/weeks/{week_number}/export/{kind}")
    def export_download(request: Request, module_code: str, week_number: int, kind: str) -> Response:
        """READ-ONLY download of the week's study pack (.docx) or NotebookLM source (.md).

        Built in memory from the current record on every request: no local write, no model call, no
        network. The NotebookLM file is for manual upload only; nothing is ever imported back.
        """
        found = _week_or_404(request, module_code, week_number)
        if isinstance(found, HTMLResponse):
            return found
        module, _week = found
        try:
            filename, media_type, content = hub_service.export_week(
                module["module_code"], week_number, kind, workspace_root=request.app.state.hub_workspace_root)
        except StateError as exc:
            return _not_found(request, str(exc))
        return Response(
            content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    # ----- Assignment Coach ------------------------------------------------------------------------------
    # GET is read-only. Every POST is one explicit action; only ``message``/``retry`` can call the model,
    # and a refused or recovered message does not. Student-authored notes (plan, evidence, questions,
    # criteria) are local writes.

    def _coach_url(module_code: str, session_id: str, anchor: str = "") -> str:
        return f"/modules/{module_code}/coach/{session_id}" + (f"#{anchor}" if anchor else "")

    def _render_coach(
        request: Request, module: dict[str, Any], session_view: dict[str, Any], *,
        error: str | None = None, draft: str = "", draft_shared: bool = False, status_code: int = 200,
    ) -> HTMLResponse:
        state = _state(request)
        assessment = next((a for a in module.get("assessments", []) if a["assessment_id"] == session_view["assessment_id"]), None)
        loaded = assignment_coach.load_session(
            module["module_code"], session_view["session_id"],
            workspace_root=request.app.state.hub_workspace_root, state=state)
        return templates.TemplateResponse(
            request, "coach.html",
            {"module": module, "session": loaded, "assessment": assessment, "error": error, "draft": draft,
             "draft_shared": draft_shared, "new_turn_id": secrets.token_hex(12), "active_nav": "modules",
             "stages": assignment_coach.STAGES, "section_statuses": assignment_coach.SECTION_STATUSES,
             "evidence_kinds": assignment_coach.EVIDENCE_KINDS,
             "max_message_chars": assignment_coach.MAX_MESSAGE_CHARS},
            status_code=status_code,
        )

    @app.post("/modules/{module_code}/assessments/{assessment_id}/coach/start", response_class=HTMLResponse)
    async def coach_start(request: Request, module_code: str, assessment_id: str) -> Response:
        picture = _picture(request)
        module = _find_module(picture, module_code)
        if module is None:
            return _not_found(request, f"No module known as {module_code.upper()}.")
        form = await _form_fields(request)
        try:
            started = assignment_coach.start_session(
                _state(request), module["module_code"], assessment_id,
                client_request_id=form.get("client_request_id", ""), force_new=form.get("new") == "yes",
                workspace_root=request.app.state.hub_workspace_root)
        except StateError as exc:
            return _render_module(request, module["module_code"], status_code=400, action_error=str(exc))
        return RedirectResponse(_coach_url(module["module_code"], started["session_id"]), status_code=303)

    @app.get("/modules/{module_code}/coach/{session_id}", response_class=HTMLResponse)
    def coach_session(request: Request, module_code: str, session_id: str) -> HTMLResponse:
        picture = _picture(request)
        module = _find_module(picture, module_code)
        if module is None:
            return _not_found(request, f"No module known as {module_code.upper()}.")
        try:
            loaded = assignment_coach.load_session(
                module["module_code"], session_id, workspace_root=request.app.state.hub_workspace_root)
        except StateError as exc:
            return _not_found(request, f"That Assignment Coach session could not be opened: {exc}")
        return _render_coach(request, module, loaded)

    _COACH_ANCHORS = {
        "brief-add": "brief", "brief-remove": "brief", "sync": "brief", "plan": "plan", "section-save": "plan",
        "section-remove": "plan", "section-move": "plan", "evidence-save": "evidence", "evidence-remove": "evidence",
        "question-add": "questions", "question-resolve": "questions", "question-remove": "questions",
        "stage": "progress", "message": "conversation", "retry": "conversation", "discard": "conversation", "end": "", "reopen": "",
    }

    @app.post("/modules/{module_code}/coach/{session_id}/{action}", response_class=HTMLResponse)
    async def coach_action(request: Request, module_code: str, session_id: str, action: str) -> Response:
        picture = _picture(request)
        module = _find_module(picture, module_code)
        if module is None:
            return _not_found(request, f"No module known as {module_code.upper()}.")
        if action not in {*_COACH_ANCHORS, "delete"}:
            return _not_found(request, "Unknown Assignment Coach action.")
        pairs = await _form_pairs(request)
        form = dict(pairs)
        many = lambda key: [v for k, v in pairs if k == key]  # noqa: E731
        code = module["module_code"]
        root = request.app.state.hub_workspace_root
        draft, shared = "", False
        try:
            if action in ("message", "retry"):
                text, shared = form.get("message", ""), form.get("shared_work") == "yes"
                turn_id = form.get("client_turn_id", "")
                if action == "retry":
                    pending = assignment_coach.load_session(code, session_id, workspace_root=root)["recovery"]
                    if pending is None:
                        raise StateError("There is no unfinished message to retry.")
                    text, shared, turn_id = pending["text"], pending["shared_work"], pending["client_turn_id"]
                draft = text
                assignment_coach.send_message(
                    _state(request), code, session_id, client_turn_id=turn_id, text=text, shared_work=shared,
                    provider=request.app.state.hub_reasoning_provider or OpenAIReasoningProvider(),
                    workspace_root=root)
            elif action == "discard":
                assignment_coach.discard_unfinished(code, session_id, workspace_root=root)
            elif action == "brief-add":
                assignment_coach.add_brief_items(code, session_id, kind=form.get("kind", ""), text=form.get("text", ""), workspace_root=root)
            elif action == "brief-remove":
                assignment_coach.remove_brief_item(code, session_id, form.get("item_id", ""), workspace_root=root)
            elif action == "sync":
                assignment_coach.sync_with_assessment(_state(request), code, session_id, workspace_root=root)
            elif action == "plan":
                assignment_coach.save_plan_overview(code, session_id, main_argument=form.get("main_argument", ""), notes=form.get("notes", ""), workspace_root=root)
            elif action == "section-save":
                assignment_coach.save_section(
                    code, session_id, section_id=form.get("section_id") or None, heading=form.get("heading", ""),
                    point=form.get("point", ""), addresses=many("addresses"), evidence_ids=many("evidence_ids"),
                    status=form.get("status", "PLANNED"), workspace_root=root)
            elif action == "section-remove":
                assignment_coach.remove_section(code, session_id, form.get("section_id", ""), workspace_root=root)
            elif action == "section-move":
                assignment_coach.move_section(code, session_id, form.get("section_id", ""), form.get("direction", ""), workspace_root=root)
            elif action == "evidence-save":
                page = form.get("pdf_page", "").strip()
                if page and not page.isdigit():
                    raise StateError("Page or slide must be a whole number.")
                assignment_coach.save_evidence(
                    code, session_id, evidence_id=form.get("evidence_id") or None, description=form.get("description", ""),
                    kind=form.get("kind", "COURSE_MATERIAL"), status=form.get("status", "NEEDED"),
                    source_id=form.get("source_id") or None, pdf_page=int(page) if page else None,
                    note=form.get("note", ""), workspace_root=root, state=_state(request))
            elif action == "evidence-remove":
                assignment_coach.remove_evidence(code, session_id, form.get("evidence_id", ""), workspace_root=root)
            elif action == "question-add":
                assignment_coach.add_question(code, session_id, text=form.get("text", ""), workspace_root=root)
            elif action == "question-resolve":
                assignment_coach.resolve_question(code, session_id, form.get("question_id", ""), answer=form.get("answer", ""), reopen=form.get("reopen") == "yes", workspace_root=root)
            elif action == "question-remove":
                assignment_coach.remove_question(code, session_id, form.get("question_id", ""), workspace_root=root)
            elif action == "stage":
                assignment_coach.set_stage(code, session_id, form.get("stage", ""), workspace_root=root)
            elif action == "end":
                assignment_coach.end_session(code, session_id, workspace_root=root)
            elif action == "reopen":
                assignment_coach.reopen_session(code, session_id, workspace_root=root)
            else:
                if form.get("confirm") != "yes":
                    raise StateError("Tick the box to confirm you want this session deleted.")
                assignment_coach.delete_session(code, session_id, workspace_root=root)
                return RedirectResponse(f"/modules/{code}#assessments", status_code=303)
        except StateError as exc:
            try:
                loaded = assignment_coach.load_session(code, session_id, workspace_root=root)
            except StateError:
                return _render_module(request, code, status_code=400, action_error=str(exc))
            return _render_coach(request, module, loaded, error=str(exc), draft=draft or form.get("message", ""),
                                 draft_shared=shared or form.get("shared_work") == "yes", status_code=400)
        return RedirectResponse(_coach_url(code, session_id, _COACH_ANCHORS.get(action, "")), status_code=303)

    return app
