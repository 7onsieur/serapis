"""Milestone 6A: read-only academic-picture aggregation over existing state.

Aggregates three already-authoritative, independently-owned files into one
queryable, in-memory snapshot without merging or mutating any of them:

- ``data/academic-state.json``      -- STUDENT_ENTERED curriculum facts.
- ``data/intake-ledger.json``       -- MACHINE_OBSERVED Blackboard facts.
- ``workspace/<MODULE>/week-NN/academic-record.json`` -- DERIVED_WORKSPACE
  study-workflow state.

Every fact keeps an explicit provenance tag. Presence in one source is never
treated as evidence of absence from another: a module known only to the
ledger, or only to academic-state, is represented as such, not merged away.

Deliberately does not link intake-ledger material to academic-state sources.
No field shared between the two schemas today identifies the same document
(the ledger keys on Blackboard ``content_id``/file name; academic-state keys
on a hand-assigned ``source.id`` with a local ``locator`` path). Any linkage
built from title or path similarity would be a guess, not evidence, so every
observed attachment is reported ``UNLINKED`` in this milestone. See the
module docstring history / Milestone 6 report for the reasoning.

Also deliberately excludes ``module.progress``, ``week.progress``, and
``item.status`` from academic-state: grep across the codebase shows no
writer ever sets these to anything but their initial placeholder, so
surfacing them as fact would misrepresent unimplemented tracking as real
completion state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .intake_ledger import default_ledger_path, load_ledger
from .state import default_state_path, load_state
from .workspace import default_workspace_root

MACHINE_OBSERVED = "MACHINE_OBSERVED"
STUDENT_ENTERED = "STUDENT_ENTERED"
DERIVED_WORKSPACE = "DERIVED_WORKSPACE"

UNLINKED = "UNLINKED"

_WEEK_DIR_RE = re.compile(r"^week-(\d+)$")

_WORKFLOW_NAMES = ("prepare_me", "after_lecture", "teach", "quiz", "revise")


@dataclass(frozen=True)
class MaterialObservation:
    """One machine-observed Blackboard attachment for one module/week."""

    module_code: str
    week: int
    content_id: str
    filename: str
    content_sha256: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    last_changed_at: str | None
    provenance: str = MACHINE_OBSERVED
    linkage_status: str = UNLINKED
    linkage_reason: str = (
        "no deterministic identity field shared between the intake ledger "
        "and academic-state sources"
    )


@dataclass(frozen=True)
class AssessmentView:
    """One assessment exactly as recorded in academic-state.json."""

    module_code: str
    assessment_id: str | None
    title: str | None
    category: str | None
    deadline: str | None
    deadline_status: str | None
    weight_percent: float | None
    provenance: str = STUDENT_ENTERED


@dataclass(frozen=True)
class StudyState:
    """Existing per-week workspace study state, if any record has been written."""

    module_code: str
    week: int
    record_found: bool
    record_path: str | None = None
    workflow_statuses: dict[str, str] = field(default_factory=dict)
    unresolved_items_status: str | None = None
    unresolved_items: list[Any] = field(default_factory=list)
    provenance: str = DERIVED_WORKSPACE


@dataclass(frozen=True)
class WeekPicture:
    module_code: str
    week: int
    in_academic_state: bool
    in_intake_ledger: bool
    topic: str | None = None
    materials: list[MaterialObservation] = field(default_factory=list)
    study_state: StudyState | None = None


@dataclass(frozen=True)
class ModulePicture:
    module_code: str
    in_academic_state: bool
    in_intake_ledger: bool
    title: str | None = None
    assessments: list[AssessmentView] = field(default_factory=list)
    weeks: list[WeekPicture] = field(default_factory=list)


@dataclass(frozen=True)
class AcademicPicture:
    modules: list[ModulePicture] = field(default_factory=list)


def _state_modules_by_code(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {module["code"].upper(): module for module in state.get("modules", [])}


def _ledger_modules_by_code(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {code.upper(): entry for code, entry in ledger.get("modules", {}).items()}


def _assessment_view(module_code: str, assessment: dict[str, Any]) -> AssessmentView:
    return AssessmentView(
        module_code=module_code,
        assessment_id=assessment.get("id"),
        title=assessment.get("title"),
        category=assessment.get("category"),
        deadline=assessment.get("deadline"),
        deadline_status=assessment.get("deadline_status"),
        weight_percent=assessment.get("weight_percent"),
    )


def _materials_for_week(
    module_code: str, week: int, ledger_week_entry: dict[str, Any]
) -> list[MaterialObservation]:
    materials: list[MaterialObservation] = []
    for content_id, document in sorted(ledger_week_entry.get("documents", {}).items()):
        attachments = document.get("attachments", {})
        if not attachments:
            materials.append(
                MaterialObservation(
                    module_code=module_code,
                    week=week,
                    content_id=content_id,
                    filename=document.get("title") or content_id,
                    content_sha256=None,
                    first_seen_at=None,
                    last_seen_at=document.get("last_seen_at"),
                    last_changed_at=None,
                )
            )
            continue
        for filename, attachment in sorted(attachments.items()):
            materials.append(
                MaterialObservation(
                    module_code=module_code,
                    week=week,
                    content_id=content_id,
                    filename=filename,
                    content_sha256=attachment.get("content_sha256"),
                    first_seen_at=attachment.get("first_seen_at"),
                    last_seen_at=attachment.get("last_seen_at"),
                    last_changed_at=attachment.get("last_changed_at"),
                )
            )
    return materials


def _discover_academic_records(workspace_root: Path) -> dict[tuple[str, int], Path]:
    """Deterministically find every existing academic-record.json by its expected path."""
    records: dict[tuple[str, int], Path] = {}
    if not workspace_root.is_dir():
        return records
    for module_dir in sorted(p for p in workspace_root.iterdir() if p.is_dir()):
        for week_dir in sorted(p for p in module_dir.iterdir() if p.is_dir()):
            match = _WEEK_DIR_RE.match(week_dir.name)
            if not match:
                continue
            record_path = week_dir / "academic-record.json"
            if record_path.is_file():
                records[(module_dir.name.upper(), int(match.group(1)))] = record_path
    return records


def _load_study_state(
    module_code: str, week: int, record_path: Path | None
) -> StudyState:
    if record_path is None:
        return StudyState(module_code=module_code, week=week, record_found=False)

    with record_path.open(encoding="utf-8") as handle:
        record = json.load(handle)

    workflows = record.get("workflows", {})
    workflow_statuses = {
        name: workflows[name]["status"]
        for name in _WORKFLOW_NAMES
        if name in workflows and "status" in workflows[name]
    }

    unresolved = record.get("learning", {}).get("unresolved_items", {})

    return StudyState(
        module_code=module_code,
        week=week,
        record_found=True,
        record_path=str(record_path),
        workflow_statuses=workflow_statuses,
        unresolved_items_status=unresolved.get("status"),
        unresolved_items=list(unresolved.get("items", [])),
    )


def build_academic_picture(
    state: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
) -> AcademicPicture:
    """Build the read-only academic picture. Never mutates any input source."""
    if state is None:
        state = load_state(default_state_path())
    if ledger is None:
        ledger = load_ledger(default_ledger_path())
    root = workspace_root if workspace_root is not None else default_workspace_root()

    state_modules = _state_modules_by_code(state)
    ledger_modules = _ledger_modules_by_code(ledger)
    records = _discover_academic_records(root)

    module_codes = sorted(set(state_modules) | set(ledger_modules))
    modules: list[ModulePicture] = []

    for module_code in module_codes:
        state_module = state_modules.get(module_code)
        ledger_module = ledger_modules.get(module_code)

        state_weeks = {
            week["week"]: week for week in (state_module or {}).get("weeks", [])
        }
        ledger_weeks = {
            int(week_number): week_entry
            for week_number, week_entry in (ledger_module or {}).get("weeks", {}).items()
        }

        week_numbers = sorted(set(state_weeks) | set(ledger_weeks))
        weeks: list[WeekPicture] = []
        for week_number in week_numbers:
            state_week = state_weeks.get(week_number)
            ledger_week_entry = ledger_weeks.get(week_number, {})
            materials = _materials_for_week(module_code, week_number, ledger_week_entry)
            study_state = _load_study_state(
                module_code, week_number, records.get((module_code, week_number))
            )
            weeks.append(
                WeekPicture(
                    module_code=module_code,
                    week=week_number,
                    in_academic_state=state_week is not None,
                    in_intake_ledger=week_number in ledger_weeks,
                    topic=(state_week or {}).get("topic"),
                    materials=materials,
                    study_state=study_state,
                )
            )

        assessments = [
            _assessment_view(module_code, assessment)
            for assessment in (state_module or {}).get("assessments", [])
        ]

        modules.append(
            ModulePicture(
                module_code=module_code,
                in_academic_state=state_module is not None,
                in_intake_ledger=ledger_module is not None,
                title=(state_module or {}).get("title"),
                assessments=assessments,
                weeks=weeks,
            )
        )

    return AcademicPicture(modules=modules)


def render_picture_text(picture: AcademicPicture) -> str:
    """Deterministic, human-readable text report grouped by module/week."""
    lines: list[str] = ["Serapis — academic picture (read-only)"]

    if not picture.modules:
        lines.append("No modules known from academic-state.json or intake-ledger.json.")
        return "\n".join(lines)

    for module in picture.modules:
        presence = []
        if module.in_academic_state:
            presence.append("academic-state")
        if module.in_intake_ledger:
            presence.append("intake-ledger")
        title = f" — {module.title}" if module.title else ""
        lines.append("")
        lines.append(f"{module.module_code}{title} [known to: {', '.join(presence)}]")

        if module.assessments:
            lines.append("  Assessments (STUDENT_ENTERED, exactly as recorded):")
            for assessment in module.assessments:
                deadline = assessment.deadline if assessment.deadline is not None else "UNKNOWN"
                if assessment.deadline_status:
                    deadline += f" [{assessment.deadline_status}]"
                weight = (
                    f"; {assessment.weight_percent}%"
                    if assessment.weight_percent is not None
                    else ""
                )
                lines.append(f"    - {assessment.title}: {deadline}{weight}")
        elif module.in_academic_state:
            lines.append("  Assessments: none recorded.")

        if not module.weeks:
            lines.append("  Weeks: none known from either source.")
            continue

        for week in module.weeks:
            week_presence = []
            if week.in_academic_state:
                week_presence.append("academic-state")
            if week.in_intake_ledger:
                week_presence.append("intake-ledger")
            topic = f" — {week.topic}" if week.topic else ""
            lines.append(f"  Week {week.week}{topic} [known to: {', '.join(week_presence)}]")

            if week.materials:
                lines.append("    Observed material (MACHINE_OBSERVED):")
                for material in week.materials:
                    lines.append(
                        f"      - {material.filename} "
                        f"(last seen {material.last_seen_at or 'UNKNOWN'}; "
                        f"linkage: {material.linkage_status})"
                    )
            else:
                lines.append("    Observed material: none recorded in intake-ledger.")

            study_state = week.study_state
            if study_state and study_state.record_found:
                lines.append("    Study/workflow state (DERIVED_WORKSPACE):")
                if study_state.workflow_statuses:
                    for name, status in study_state.workflow_statuses.items():
                        lines.append(f"      - {name}: {status}")
                if study_state.unresolved_items:
                    lines.append(
                        f"      unresolved_items ({study_state.unresolved_items_status}):"
                    )
                    for item in study_state.unresolved_items:
                        lines.append(f"        - {item}")
            else:
                lines.append(
                    "    Study/workflow state: no academic-record.json found "
                    "(unknown whether studied, not \"not studied\")."
                )

    return "\n".join(lines)
