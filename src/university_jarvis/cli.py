"""Command-line interface for Serapis."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .blackboard import (
    BlackboardClient,
    BlackboardError,
    BlackboardSession,
    DEFAULT_BASE_URL,
    WEEK_AMBIGUOUS_DUPLICATE,
    WEEK_NOT_YET_PUBLISHED,
    resolve_course,
    retrieve_attachment,
)
from .academic_picture import build_academic_picture, render_picture_text
from .attention import build_attention_picture, render_attention_text
from .blackboard_browser import (
    browser_profile_exists,
    open_browser_client,
    run_interactive_authentication,
)
from .credentials import (
    get_blackboard_session_cookie,
    get_google_drive_token_json,
    get_google_oauth_client_json,
    store_google_drive_token,
)
from .drive import (
    DriveClient,
    DriveError,
    build_drive_credentials,
    build_drive_service,
    build_oauth_client_config,
    refresh_if_needed,
    run_oauth_consent_flow,
    sync_file,
)
from .intake import (
    AMBIGUOUS,
    FAILED,
    RETRIEVED,
    SKIPPED,
    SYNCED,
    WEEK_NOT_FOUND,
    intake_week,
)
from .intake_ledger import load_ledger, save_ledger
from .reconcile import (
    CHANGED,
    METADATA_CHANGED,
    MISSING_SINCE_LAST_CHECK,
    NEW,
    UNCHANGED,
    reconcile_week,
)
from .university import check_university
from .reasoning import (
    ASSIGNMENT_WORKFLOW,
    OpenAIReasoningProvider,
    REVISE_WORKFLOW,
    ReasoningProvider,
    generate_prepare_brief,
    generate_quiz_brief,
    generate_sectioned_brief,
    build_source_location_index,
    render_prepare_brief,
    render_quiz_brief,
    render_sectioned_brief,
    render_teach_brief,
)
from .state import StateError, get_module, load_state
from .workflows import build_assignment_context, build_prepare_context, build_week_context
from .workspace import capture_after_lecture, materialize_week_workspace, teach_week


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="serapis")
    subparsers = parser.add_subparsers(dest="command", required=True)
    setup = subparsers.add_parser("setup", help="create or continue your private Serapis workspace")
    setup.add_argument("--no-open", action="store_true", help="do not open the Hub when setup finishes")
    subparsers.add_parser("status", help="show known academic state")

    subparsers.add_parser(
        "picture",
        help=(
            "read-only academic picture: aggregate academic-state.json, "
            "intake-ledger.json, and per-week academic-record.json without "
            "changing any of them"
        ),
    )

    subparsers.add_parser(
        "attention",
        help=(
            "deterministic university-wide attention view derived from the "
            "academic picture: study-state gaps, open unresolved items, and "
            "known assessments -- no scoring, ranking, or urgency"
        ),
    )

    prepare = subparsers.add_parser("prepare", help="prepare bounded context for a lecture")
    prepare.add_argument("module", help="module code, for example SYN101")
    prepare.add_argument("--week", required=True, type=int, help="teaching week number")

    workspace = subparsers.add_parser(
        "workspace", help="build a persistent study workspace from cached preparation"
    )
    workspace.add_argument("module", help="module code, for example SYN101")
    workspace.add_argument("--week", required=True, type=int, help="teaching week number")

    after_lecture = subparsers.add_parser(
        "after-lecture", help="capture your report after a completed lecture"
    )
    after_lecture.add_argument("module", help="module code, for example SYN101")
    after_lecture.add_argument("--week", required=True, type=int, help="teaching week number")
    after_lecture.add_argument("--notes", action="append", help="free-form lecture notes")
    after_lecture.add_argument("--notes-file", type=Path, help="UTF-8 local notes file")
    after_lecture.add_argument("--emphasis", action="append", help="lecturer emphasis")
    after_lecture.add_argument("--example", action="append", help="example or case discussed")
    after_lecture.add_argument("--understood", action="append", help="something you understood")
    after_lecture.add_argument("--uncertainty", action="append", help="something not understood")
    after_lecture.add_argument("--question", action="append", help="an unresolved question")
    after_lecture.add_argument(
        "--assessment-comment", action="append", help="useful assessment comment"
    )

    teach = subparsers.add_parser("teach", help="teach one source-grounded concept")
    teach.add_argument("module", help="module code, for example SYN101")
    teach.add_argument("--week", required=True, type=int, help="teaching week number")
    teach.add_argument(
        "--topic",
        help="concept to teach; omit to target the first open captured question or uncertainty",
    )

    for command, help_text in (
        ("quiz", "generate a source-grounded quiz"),
        ("revise", "build a revision brief"),
    ):
        workflow = subparsers.add_parser(command, help=help_text)
        workflow.add_argument("module", help="module code, for example SYN101")
        workflow.add_argument("--week", required=True, type=int, help="teaching week number")

    assignment = subparsers.add_parser(
        "assignment", help="coach planning for a module assignment"
    )
    assignment.add_argument("module", help="module code, for example SYN101")

    blackboard_fetch = subparsers.add_parser(
        "blackboard-fetch",
        help="retrieve one named Blackboard attachment into the local sources/ cache (read-only)",
    )
    blackboard_fetch.add_argument("module", help="module code, for example SYN101")
    blackboard_fetch.add_argument("--week", required=True, type=int, help="teaching week number")
    blackboard_fetch.add_argument(
        "--title", required=True, help="content title to match, e.g. 'This Week'"
    )
    blackboard_fetch.add_argument(
        "--course-needle",
        help="text to match against your Blackboard course memberships; defaults to the module code",
    )
    blackboard_fetch.add_argument(
        "--base-url", default=os.environ.get("JARVIS_BLACKBOARD_BASE_URL"),
        help="Blackboard host (or set JARVIS_BLACKBOARD_BASE_URL)"
    )

    intake = subparsers.add_parser(
        "intake",
        help=(
            "discover, retrieve, and idempotently sync this module/week's Blackboard "
            "attachments to Google Drive (University/<MODULE>/Week NN/) -- no title needed"
        ),
    )
    intake.add_argument("module", help="module code, for example SYN101")
    intake.add_argument("--week", required=True, type=int, help="teaching week number")
    intake.add_argument(
        "--course-needle",
        help="text to match against your Blackboard course memberships; defaults to the module code",
    )
    intake.add_argument(
        "--base-url", default=os.environ.get("JARVIS_BLACKBOARD_BASE_URL"),
        help="Blackboard host (or set JARVIS_BLACKBOARD_BASE_URL)"
    )
    intake.add_argument(
        "--no-drive-sync",
        action="store_true",
        help="retrieve attachments locally only; skip the Google Drive sync step",
    )

    check = subparsers.add_parser(
        "check",
        help=(
            "reconcile this module/week's Blackboard attachments against the persisted "
            "intake ledger (data/intake-ledger.json) and report NEW/CHANGED/UNCHANGED "
            "-- Drive sync is off by default"
        ),
    )
    check.add_argument("module", help="module code, for example SYN101")
    check.add_argument("--week", required=True, type=int, help="teaching week number")
    check.add_argument(
        "--course-needle",
        help="text to match against your Blackboard course memberships; defaults to the module code",
    )
    check.add_argument(
        "--base-url", default=os.environ.get("JARVIS_BLACKBOARD_BASE_URL"),
        help="Blackboard host (or set JARVIS_BLACKBOARD_BASE_URL)"
    )
    check.add_argument(
        "--sync-to-drive",
        action="store_true",
        help="also sync new/changed attachments to Google Drive (default: off)",
    )

    check_university = subparsers.add_parser(
        "check-university",
        help=(
            "discover teaching modules/weeks from your institution's Blackboard automatically "
            "and reconcile each against the persisted intake ledger -- no module/week input "
            "needed; Drive sync is off by default"
        ),
    )
    check_university.add_argument(
        "--base-url", default=os.environ.get("JARVIS_BLACKBOARD_BASE_URL"),
        help="Blackboard host (or set JARVIS_BLACKBOARD_BASE_URL)"
    )
    check_university.add_argument(
        "--sync-to-drive",
        action="store_true",
        help="also sync new/changed attachments to Google Drive (default: off)",
    )

    blackboard_auth = subparsers.add_parser(
        "blackboard-auth",
        help=(
            "one-time interactive sign-in/SSO for your institution in the dedicated Serapis browser "
            "profile (Auth V2); the session then persists across future blackboard-fetch runs"
        ),
    )
    blackboard_auth.add_argument(
        "--base-url", default=os.environ.get("JARVIS_BLACKBOARD_BASE_URL"),
        help="Blackboard host (or set JARVIS_BLACKBOARD_BASE_URL)"
    )

    drive_sync = subparsers.add_parser(
        "drive-sync",
        help="idempotently upload/update one local file into University/<MODULE>/Week NN/ on Google Drive",
    )
    drive_sync.add_argument("module", help="module code, for example SYN101")
    drive_sync.add_argument("--week", required=True, type=int, help="teaching week number")
    drive_sync.add_argument("--file", required=True, type=Path, help="local file path to sync")

    subparsers.add_parser(
        "drive-auth",
        help=(
            "one-time interactive Google Drive OAuth consent (drive.file scope); "
            "stores the resulting token in the macOS Keychain"
        ),
    )

    hub = subparsers.add_parser(
        "hub",
        help=(
            "run the local, read-only Hub web interface (Slice 2): binds "
            "127.0.0.1 only by default; never makes a Blackboard/Drive/model "
            "call on page load"
        ),
    )
    hub.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind host (default: %(default)s; do not expose beyond localhost)",
    )
    hub.add_argument("--port", type=int, default=8765, help="bind port (default: %(default)s)")
    return parser


def _print_status(state: dict[str, Any]) -> None:
    student = state["student"]
    print("Serapis — academic status")
    print(
        f"Student: {student['programme']}, Year {student['year_of_study']} "
        f"(Level {student['level']}), {student['academic_year']}"
    )
    print(f"Overall progress: {state['progress']['overall_status']}")
    print("Modules:")
    for module in state["modules"]:
        print(f"  {module['code']} — {module['title']} (Semester {module['semester']})")
        known_weeks = len(module.get("weeks", []))
        print(f"    Known teaching weeks: {known_weeks}; progress: {module['progress']['status']}")
        for assessment in module.get("assessments", []):
            deadline = assessment["deadline"] or "unknown"
            if assessment.get("deadline_status") == "TBC":
                deadline += " [TBC]"
            weighting = assessment.get("weight_percent")
            suffix = f"; {weighting}%" if weighting is not None else ""
            print(f"    {assessment['title']}: {deadline}{suffix}")


def _print_prepare(context: dict[str, Any], result: Any) -> None:
    module = context["module"]
    week = context["week"]
    print(f"PREPARE_ME — {module['code']} Week {week['number']}")
    print(f"Module: {module['title']}")
    print("Result: source-grounded preparation brief ready.")
    print(f"Reasoning result: {result.cache_status}")
    print("Extracted sources:")
    for source in context["sources"]:
        extraction = source["extraction"]
        if "slide_count" in extraction:
            unit_count, unit_label = extraction["slide_count"], "slides"
        else:
            unit_count, unit_label = extraction["page_count"], "pages"
        print(
            f"  {source['id']}: {extraction['character_count']:,} characters "
            f"from {extraction['nonempty_page_count']}/{unit_count} {unit_label}"
        )
    print()
    print(render_prepare_brief(result.brief, build_source_location_index(context)))


def _print_workflow(
    context: dict[str, Any], result: Any, label: str, rendered: str
) -> None:
    module = context["module"]
    week = context.get("week")
    suffix = f" Week {week['number']}" if week else ""
    print(f"{label} — {module['code']}{suffix}")
    print(f"Module: {module['title']}")
    print(f"Reasoning result: {result.cache_status}")
    print()
    print(rendered)


def _record_source_location_index(record_path: Path) -> dict[str, Any]:
    """Build a citation location index from an already-written academic-record.json.

    TEACH's terminal display only builds a minimal module/week ``context`` (no
    source list), so the location index needed for correct PDF-vs-slide
    citations is read from the record ``teach_week`` just wrote instead.
    """
    with record_path.open(encoding="utf-8") as handle:
        record = json.load(handle)
    return {
        source["source_id"]: {
            "method": (source.get("extraction") or {}).get("method"),
            "titles": {},
        }
        for source in record.get("sources", [])
    }


def _run_blackboard_fetch(client: BlackboardClient, args: argparse.Namespace) -> None:
    memberships = client.list_courses()
    course = resolve_course(client, memberships, args.course_needle or args.module)
    course_system_id = course.get("id")
    if not course_system_id:
        raise BlackboardError(f"Resolved course record has no id: {course}")
    dest = retrieve_attachment(client, course_system_id, args.title, args.module, args.week)
    print(f"Retrieved attachment to {dest}")


_INTAKE_STATUS_LABELS = {
    RETRIEVED: "retrieved",
    SYNCED: "synced",
    SKIPPED: "skipped",
    AMBIGUOUS: "ambiguous",
    FAILED: "failed",
}


def _resolve_drive_client(drive_client: DriveClient | None) -> DriveClient:
    if drive_client is not None:
        return drive_client
    token_json = get_google_drive_token_json()
    if not token_json:
        raise DriveError(
            "No Google Drive credential found. Complete the one-time OAuth consent "
            "flow and store the resulting token in the macOS Keychain under "
            "'Serapis-GoogleDrive' first."
        )
    credentials = refresh_if_needed(build_drive_credentials(token_json))
    return DriveClient(build_drive_service(credentials))


def _run_intake(
    client: BlackboardClient, drive_client: DriveClient | None, args: argparse.Namespace
) -> None:
    memberships = client.list_courses()
    course = resolve_course(client, memberships, args.course_needle or args.module)
    course_system_id = course.get("id")
    if not course_system_id:
        raise BlackboardError(f"Resolved course record has no id: {course}")

    resolved_drive_client = None if args.no_drive_sync else _resolve_drive_client(drive_client)
    result = intake_week(
        client,
        resolved_drive_client,
        course_system_id,
        args.module,
        args.week,
        sync_to_drive=not args.no_drive_sync,
    )

    print(f"INTAKE — {args.module.upper()} Week {args.week}")
    if result.status == WEEK_NOT_FOUND:
        print("Result: no matching teaching week found for this module.")
        return
    print(f"Week status: {result.status}")
    if not result.items:
        print("No content items discovered.")
    for item in result.items:
        label = _INTAKE_STATUS_LABELS.get(item.status, item.status)
        name = item.file_name or (item.source_path[-1].title if item.source_path else "?")
        detail = ""
        if item.status == SYNCED:
            detail = f" (drive file id {item.drive_file_id})"
        elif item.status == RETRIEVED:
            detail = f" ({item.local_path})"
        elif item.reason:
            detail = f" ({item.reason})"
        elif item.error:
            detail = f" ({item.error})"
        print(f"  [{label}] {name}{detail}")
    print(f"Overall: {'success' if result.success else 'incomplete'}")


def _run_check(client: BlackboardClient, args: argparse.Namespace) -> None:
    memberships = client.list_courses()
    course = resolve_course(client, memberships, args.course_needle or args.module)
    course_system_id = course.get("id")
    if not course_system_id:
        raise BlackboardError(f"Resolved course record has no id: {course}")

    ledger = load_ledger()
    result = reconcile_week(
        client,
        None,
        course_system_id,
        args.module,
        args.week,
        ledger,
        sync_to_drive=args.sync_to_drive,
    )

    print(f"CHECK — {args.module.upper()} Week {args.week}")
    if result.status == WEEK_NOT_FOUND:
        print("Result: no matching teaching week found for this module.")
        return
    print(f"Week status: {result.status}")
    if not result.items:
        print("No content items discovered.")
    for item in result.items:
        name = item.file_name or (item.source_path[-1].title if item.source_path else "?")
        detail = ""
        if item.status not in (FAILED, AMBIGUOUS) and item.local_path is not None:
            detail = f" ({item.local_path})"
        elif item.reason:
            detail = f" ({item.reason})"
        elif item.error:
            detail = f" ({item.error})"
        print(f"  [{item.status}] {name}{detail}")

    if result.success:
        save_ledger(ledger)
    print(f"Overall: {'success' if result.success else 'incomplete'}")


_WEEK_SUMMARY_KEYS = (
    ("new", NEW),
    ("changed", CHANGED),
    ("metadata changed", METADATA_CHANGED),
    ("unchanged", UNCHANGED),
    ("not yet published", WEEK_NOT_YET_PUBLISHED),
    ("missing", MISSING_SINCE_LAST_CHECK),
    ("ambiguous", AMBIGUOUS),
    ("failed", FAILED),
)


def _run_check_university(client: BlackboardClient, args: argparse.Namespace) -> None:
    ledger = load_ledger()
    result = check_university(client, None, ledger, sync_to_drive=args.sync_to_drive)

    print("CHECK UNIVERSITY")
    print()

    counts = {label: 0 for label, _status in _WEEK_SUMMARY_KEYS}
    weeks_checked = 0
    overall_success = not result.scope_issues

    for module_result in result.modules:
        print(module_result.module_code)
        for week_result in module_result.weeks:
            weeks_checked += 1
            if not week_result.success:
                overall_success = False

            if week_result.status in (WEEK_NOT_YET_PUBLISHED, WEEK_AMBIGUOUS_DUPLICATE):
                label = "not yet published" if week_result.status == WEEK_NOT_YET_PUBLISHED else "ambiguous"
                counts[label] += 1
                print(f"  Week {week_result.week}")
                print(f"    [{week_result.status}]")
                continue

            print(f"  Week {week_result.week}")
            if not week_result.items:
                print("    No content items discovered.")
            for item in week_result.items:
                for label, status in _WEEK_SUMMARY_KEYS:
                    if item.status == status:
                        counts[label] += 1
                        break
                name = item.file_name or (item.source_path[-1].title if item.source_path else "?")
                detail = ""
                if item.status not in (FAILED, AMBIGUOUS) and item.local_path is not None:
                    detail = f" ({item.local_path})"
                elif item.reason:
                    detail = f" ({item.reason})"
                elif item.error:
                    detail = f" ({item.error})"
                print(f"    [{item.status}] {name}{detail}")
        print()

    for issue in result.scope_issues:
        print(f"SCOPE ISSUE [{issue.reason}] course {issue.course_system_id}: {issue.detail or ''}")
    if result.scope_issues:
        print()

    print("Summary:")
    print(f"  teaching modules checked: {len(result.modules)}")
    print(f"  weeks checked: {weeks_checked}")
    for label, _status in _WEEK_SUMMARY_KEYS:
        print(f"  {label}: {counts[label]}")
    print(f"Overall: {'success' if overall_success else 'incomplete'}")


def _resolve_blackboard_client(base_url: str) -> contextlib.AbstractContextManager[BlackboardClient]:
    """Pick an authenticated Blackboard transport: Auth V2 browser, else legacy cookie.

    The Auth V2 persistent browser profile is the intended path and always
    wins when it exists, even if a stale legacy cookie is also present. The
    cookie env var/Keychain path is only a deprecated fallback for when no
    browser profile has been set up at all.
    """
    if not base_url:
        raise BlackboardError(
            "Blackboard host is required. Set JARVIS_BLACKBOARD_BASE_URL or pass --base-url."
        )
    if browser_profile_exists():
        return open_browser_client(base_url=base_url)
    cookie = get_blackboard_session_cookie()
    if cookie:
        session = BlackboardSession(base_url=base_url, cookie_header=cookie)
        return contextlib.nullcontext(BlackboardClient(session))
    raise BlackboardError(
        "No Blackboard session found. Run `serapis blackboard-auth` once to authenticate the "
        "dedicated Serapis browser profile (Auth V2), or set BLACKBOARD_SESSION_COOKIE / store a "
        "cookie in the macOS Keychain under 'Serapis-Blackboard' (legacy, deprecated)."
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    reasoning_provider: ReasoningProvider | None = None,
    cache_dir: Path | None = None,
    workspace_root: Path | None = None,
    blackboard_client: BlackboardClient | None = None,
    drive_client: DriveClient | None = None,
    oauth_flow_runner: Any | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "setup":
        from .student_setup import add_module, edit_profile, initialize_personal_state, save_assessment
        from .state import personal_data_dir
        try:
            from .student_setup import existing_user_state_path
            legacy_path = existing_user_state_path()
            copy_existing = False
            if legacy_path is not None:
                copy_existing = input(
                    f"An existing course setup was found at {legacy_path}. Copy it into your personal Serapis workspace? The original will remain unchanged. [y/N] "
                ).strip().lower() == "y"
            initialize_personal_state(copy_existing=copy_existing)
            print("Welcome to Serapis setup. Press Enter to skip any optional detail.")
            university = input("University (optional): ").strip()
            programme = input("Programme or course (optional): ").strip()
            edit_profile(university=university, programme=programme)
            while True:
                code = input("Module code (leave blank when finished): ").strip()
                if not code: break
                title = input("Module title: ").strip()
                try:
                    add_module(code, title)
                    print(f"Added {code.upper()}.")
                except StateError as exc:
                    print(f"Could not add module: {exc}")
                    continue
                if input("Add an assessment now? [y/N] ").strip().lower() == "y":
                    atitle = input("Assessment title: ").strip()
                    deadline = input("Deadline (YYYY-MM-DD, optional): ").strip()
                    weight = input("Weight % (optional): ").strip()
                    requirements = []
                    while True:
                        line = input("Requirement (press Enter when finished): ").strip()
                        if not line: break
                        requirements.append(line)
                    try:
                        save_assessment(code, title=atitle, deadline=deadline, weight_percent=weight, requirements="\n".join(requirements))
                    except StateError as exc:
                        print(f"Assessment was not saved: {exc}")
                if input("Add a course file now? [y/N] ").strip().lower() == "y":
                    from .student_setup import import_material
                    from pathlib import Path
                    file_name = input("File path (PDF or PPTX): ").strip()
                    week_text = input("Week number (optional): ").strip()
                    try:
                        imported = import_material(code, Path(file_name), week=int(week_text) if week_text else None)
                        print(imported["capability"])
                    except (StateError, ValueError) as exc:
                        print(f"Material was not added: {exc}")
                if input("Add another module? [y/N] ").strip().lower() != "y": break
            print(f"Your private Serapis data is stored in: {personal_data_dir()}")
            print("Next: run 'serapis hub' to inspect your modules and add course materials.")
            if not args.no_open and input("Open the Hub now? [y/N] ").strip().lower() == "y":
                import webbrowser
                import threading
                import uvicorn
                from .hub_web import create_app
                threading.Timer(1.0, webbrowser.open, args=("http://127.0.0.1:8765",)).start()
                uvicorn.run(create_app(), host="127.0.0.1", port=8765)
            return 0
        except (StateError, OSError) as exc:
            print(f"serapis setup: {exc}", file=sys.stderr)
            return 2
    try:
        state = load_state()
        if args.command == "status":
            _print_status(state)
        elif args.command == "picture":
            ledger = load_ledger()
            picture = build_academic_picture(
                state=state, ledger=ledger, workspace_root=workspace_root
            )
            print(render_picture_text(picture))
        elif args.command == "attention":
            ledger = load_ledger()
            picture = build_academic_picture(
                state=state, ledger=ledger, workspace_root=workspace_root
            )
            attention = build_attention_picture(picture)
            print(render_attention_text(attention))
        elif args.command == "prepare":
            context = build_prepare_context(state, args.module, args.week)
            provider = reasoning_provider or OpenAIReasoningProvider()
            result = generate_prepare_brief(context, provider, cache_dir=cache_dir)
            _print_prepare(context, result)
        elif args.command == "workspace":
            provider = reasoning_provider or OpenAIReasoningProvider()
            result = materialize_week_workspace(
                state,
                args.module,
                args.week,
                provider=provider,
                cache_dir=cache_dir,
                workspace_root=workspace_root,
            )
            print(f"Academic workspace ready from {result.cache_status} PREPARE_ME result.")
            print(f"Academic record: {result.record_path}")
            print(f"Word study pack: {result.study_pack_path}")
            print(f"NotebookLM upload source: {result.notebooklm_path}")
        elif args.command == "after-lecture":
            result = capture_after_lecture(
                args.module,
                args.week,
                notes=args.notes,
                notes_file=args.notes_file,
                lecturer_emphasis=args.emphasis,
                examples_cases=args.example,
                understood=args.understood,
                uncertainties=args.uncertainty,
                questions=args.question,
                assessment_comments=args.assessment_comment,
                workspace_root=workspace_root,
            )
            print(f"After-lecture capture saved: {result.capture_id} at {result.captured_at}")
            print(f"Academic record: {result.record_path}")
            print(f"Word study pack: {result.study_pack_path}")
            print(f"NotebookLM upload source: {result.notebooklm_path}")
        elif args.command == "teach":
            provider = reasoning_provider or OpenAIReasoningProvider()
            result = teach_week(
                state,
                args.module,
                args.week,
                topic=args.topic,
                provider=provider,
                cache_dir=cache_dir,
                workspace_root=workspace_root,
            )
            context = {
                "module": {
                    "code": args.module.upper(),
                    "title": get_module(state, args.module)["title"],
                },
                "week": {"number": args.week},
            }
            _print_workflow(
                context,
                result,
                "TEACH",
                render_teach_brief(
                    result.brief,
                    {"topic": result.topic},
                    result.student_context,
                    _record_source_location_index(result.record_path),
                ),
            )
            print()
            print(f"Academic record: {result.record_path}")
            print(f"Word study pack: {result.study_pack_path}")
            print(f"NotebookLM upload source: {result.notebooklm_path}")
        elif args.command in {"quiz", "revise"}:
            provider = reasoning_provider or OpenAIReasoningProvider()
            workflow_name = args.command.replace("-", "_").upper()
            context = build_week_context(
                state, args.module, args.week, workflow_name
            )
            location_index = build_source_location_index(context)
            if args.command == "quiz":
                result = generate_quiz_brief(context, provider, cache_dir=cache_dir)
                rendered = render_quiz_brief(result.brief, location_index)
                label = "QUIZ"
            else:
                workflow = REVISE_WORKFLOW
                result = generate_sectioned_brief(
                    context, provider, workflow, cache_dir=cache_dir
                )
                rendered = render_sectioned_brief(result.brief, workflow, location_index)
                label = workflow.name
            _print_workflow(context, result, label, rendered)
        elif args.command == "assignment":
            provider = reasoning_provider or OpenAIReasoningProvider()
            context = build_assignment_context(state, args.module)
            result = generate_sectioned_brief(
                context, provider, ASSIGNMENT_WORKFLOW, cache_dir=cache_dir
            )
            _print_workflow(
                context,
                result,
                ASSIGNMENT_WORKFLOW.name,
                render_sectioned_brief(
                    result.brief, ASSIGNMENT_WORKFLOW, build_source_location_index(context)
                ),
            )
        elif args.command == "blackboard-fetch":
            if blackboard_client is not None:
                _run_blackboard_fetch(blackboard_client, args)
            else:
                with _resolve_blackboard_client(args.base_url) as client:
                    _run_blackboard_fetch(client, args)
        elif args.command == "blackboard-auth":
            if not args.base_url:
                raise BlackboardError(
                    "Blackboard host is required. Set JARVIS_BLACKBOARD_BASE_URL or pass --base-url."
                )
            run_interactive_authentication(base_url=args.base_url)
            print("Serapis browser profile authenticated (Auth V2).")
        elif args.command == "drive-sync":
            client = _resolve_drive_client(drive_client)
            file_id = sync_file(client, args.file, args.module, args.week)
            print(f"Synced to Google Drive: file id {file_id}")
        elif args.command == "intake":
            if blackboard_client is not None:
                _run_intake(blackboard_client, drive_client, args)
            else:
                with _resolve_blackboard_client(args.base_url) as client:
                    _run_intake(client, drive_client, args)
        elif args.command == "check":
            if blackboard_client is not None:
                _run_check(blackboard_client, args)
            else:
                with _resolve_blackboard_client(args.base_url) as client:
                    _run_check(client, args)
        elif args.command == "check-university":
            if blackboard_client is not None:
                _run_check_university(blackboard_client, args)
            else:
                with _resolve_blackboard_client(args.base_url) as client:
                    _run_check_university(client, args)
        elif args.command == "drive-auth":
            client_json = get_google_oauth_client_json()
            if not client_json:
                raise DriveError(
                    "No Google OAuth client found. Store your Desktop client id/secret first: "
                    "security add-generic-password -a \"$(whoami)\" "
                    "-s Serapis-GoogleOAuthClient -w -U"
                )
            client_config = build_oauth_client_config(client_json)
            runner = oauth_flow_runner or run_oauth_consent_flow
            credentials = runner(client_config)
            token_json = credentials.to_json()
            if not store_google_drive_token(token_json):
                raise DriveError("Failed to store the Google Drive token in the macOS Keychain.")
            print("Google Drive credential stored in the macOS Keychain under 'Serapis-GoogleDrive'.")
        elif args.command == "hub":
            import uvicorn

            from .hub_web import create_app

            print(f"Serapis Hub — read-only — http://{args.host}:{args.port}")
            print("No Blackboard/Drive/model call is made by loading any Hub page.")
            uvicorn.run(create_app(), host=args.host, port=args.port)
    except StateError as exc:
        print(f"serapis: {exc}", file=sys.stderr)
        usage = getattr(exc, "usage", None)
        if usage is not None:
            print(
                "serapis: response usage: "
                f"input_tokens={usage.input_tokens}, "
                f"output_tokens={usage.output_tokens}, "
                f"total_tokens={usage.total_tokens}",
                file=sys.stderr,
            )
        return 2
    return 0
