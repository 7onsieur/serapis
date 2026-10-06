"""Milestone 6B: deterministic university-wide attention view over AcademicPicture.

Answers "what needs my attention?" purely by re-reading facts already present
in an ``AcademicPicture`` (Milestone 6A). This is not a planner: it never
invents a task, never scores or ranks anything, and never turns an absence of
evidence into a claim of non-completion.

Three attention kinds, each traceable back to its source evidence:

- ``STUDY_STATE_UNKNOWN``: a module/week has MACHINE_OBSERVED material but no
  academic-record.json exists at all. This is an evidence gap, not a verdict
  -- it is reported identically whether the student simply hasn't run
  ``workspace`` yet or the source format (e.g. PPTX) blocks it today. The
  attention layer does not know, and does not guess, why the record is
  absent.
- ``OPEN_UNRESOLVED_ITEM``: an item from an existing academic-record.json's
  ``learning.unresolved_items`` block, surfaced only when that block's own
  ``status`` is ``"open"`` -- never reinterpreted.
- ``KNOWN_ASSESSMENT``: an assessment exactly as academic-state.json records
  it, including an unmodified ``TBC`` deadline_status. No urgency, no "due
  soon" language, no date arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .academic_picture import AcademicPicture

STUDY_STATE_UNKNOWN = "STUDY_STATE_UNKNOWN"
OPEN_UNRESOLVED_ITEM = "OPEN_UNRESOLVED_ITEM"
KNOWN_ASSESSMENT = "KNOWN_ASSESSMENT"


@dataclass(frozen=True)
class AttentionItem:
    kind: str
    module_code: str
    description: str
    week: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AttentionPicture:
    study_state_unknown: list[AttentionItem] = field(default_factory=list)
    open_unresolved_items: list[AttentionItem] = field(default_factory=list)
    known_assessments: list[AttentionItem] = field(default_factory=list)


def _study_state_unknown_items(picture: AcademicPicture) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for module in picture.modules:
        for week in module.weeks:
            study_state = week.study_state
            if study_state is not None and study_state.record_found:
                continue
            if not week.materials:
                continue
            filenames = [material.filename for material in week.materials]
            items.append(
                AttentionItem(
                    kind=STUDY_STATE_UNKNOWN,
                    module_code=module.module_code,
                    week=week.week,
                    description=(
                        "University material exists, but Serapis has no evidence "
                        "of study/workflow activity for this week."
                    ),
                    evidence={"observed_material": filenames},
                )
            )
    return items


def _open_unresolved_items(picture: AcademicPicture) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for module in picture.modules:
        for week in module.weeks:
            study_state = week.study_state
            if study_state is None or not study_state.record_found:
                continue
            if study_state.unresolved_items_status != "open":
                continue
            for entry in study_state.unresolved_items:
                items.append(
                    AttentionItem(
                        kind=OPEN_UNRESOLVED_ITEM,
                        module_code=module.module_code,
                        week=week.week,
                        description=str(entry),
                        evidence={
                            "record_path": study_state.record_path,
                            "unresolved_items_status": study_state.unresolved_items_status,
                            "item": entry,
                        },
                    )
                )
    return items


def _known_assessment_items(picture: AcademicPicture) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for module in picture.modules:
        for assessment in module.assessments:
            deadline = assessment.deadline if assessment.deadline is not None else "UNKNOWN"
            description = f"{assessment.title}: {deadline}"
            if assessment.deadline_status:
                description += f" [{assessment.deadline_status}]"
            if assessment.weight_percent is not None:
                description += f"; {assessment.weight_percent}%"
            items.append(
                AttentionItem(
                    kind=KNOWN_ASSESSMENT,
                    module_code=module.module_code,
                    description=description,
                    evidence={
                        "assessment_id": assessment.assessment_id,
                        "deadline": assessment.deadline,
                        "deadline_status": assessment.deadline_status,
                        "weight_percent": assessment.weight_percent,
                    },
                )
            )
    return items


def build_attention_picture(picture: AcademicPicture) -> AttentionPicture:
    """Derive the attention view. Read-only: never mutates ``picture`` or its sources."""
    return AttentionPicture(
        study_state_unknown=_study_state_unknown_items(picture),
        open_unresolved_items=_open_unresolved_items(picture),
        known_assessments=_known_assessment_items(picture),
    )


def render_attention_text(attention: AttentionPicture) -> str:
    """Deterministic, human-readable university-wide attention report."""
    lines: list[str] = ["Serapis — attention"]

    lines.append("")
    lines.append("Study state unknown:")
    if attention.study_state_unknown:
        for item in attention.study_state_unknown:
            lines.append(f"  {item.module_code} Week {item.week}")
            for filename in item.evidence.get("observed_material", []):
                lines.append(f"    material observed: {filename}")
    else:
        lines.append("  None -- every week with observed material has an academic-record.")

    lines.append("")
    lines.append("Open unresolved items:")
    if attention.open_unresolved_items:
        for item in attention.open_unresolved_items:
            lines.append(f"  {item.module_code} Week {item.week}")
            lines.append(f"    {item.description}")
    else:
        lines.append("  None recorded.")

    lines.append("")
    lines.append("Known assessments:")
    if attention.known_assessments:
        by_module: dict[str, list[AttentionItem]] = {}
        for item in attention.known_assessments:
            by_module.setdefault(item.module_code, []).append(item)
        for module_code, module_items in by_module.items():
            lines.append(f"  {module_code}")
            for item in module_items:
                lines.append(f"    {item.description}")
    else:
        lines.append("  None recorded.")

    return "\n".join(lines)
