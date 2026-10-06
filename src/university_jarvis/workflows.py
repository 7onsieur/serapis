"""Small, deterministic academic workflows."""

from __future__ import annotations

from typing import Any

from .mission import build_objective_context
from .sources import load_source_context
from .state import get_module, get_sources, get_week, normalize_academic_truth


def _load_sources(
    state: dict[str, Any], source_ids: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_contexts = []
    prepared_sources = []
    for source in get_sources(state, source_ids):
        extraction, bounded_context = load_source_context(source)
        prepared_sources.append({**source, "extraction": extraction})
        source_contexts.append(bounded_context)
    return prepared_sources, source_contexts


def build_week_context(
    state: dict[str, Any], module_code: str, week_number: int, workflow: str
) -> dict[str, Any]:
    """Build bounded context for exactly one requested module week."""
    state = normalize_academic_truth(state)
    module = get_module(state, module_code)
    week = get_week(module, week_number)
    prepared_sources, source_contexts = _load_sources(
        state, week.get("source_ids", [])
    )

    return {
        "workflow": workflow,
        "objective_context": build_objective_context(state),
        "module": {
            "code": module["code"],
            "title": module["title"],
            "semester": module["semester"],
            "academic_year": module["academic_year"],
        },
        "week": {
            "number": week["week"],
            "date": week["date"],
            "topic": week["topic"],
            "progress": week["progress"],
        },
        "assessments": module.get("assessments", []),
        "items": week.get("items", []),
        "sources": prepared_sources,
        "source_contexts": source_contexts,
        "truth_sources": state.get("sources", []),
    }


def build_prepare_context(
    state: dict[str, Any], module_code: str, week_number: int
) -> dict[str, Any]:
    """Build only the context needed to prepare one module week."""
    context = build_week_context(state, module_code, week_number, "PREPARE_ME")
    return {
        **context,
        "output_sections": [
            "lecture_overview",
            "core_concepts",
            "assigned_reading_ideas",
            "examples_or_cases",
            "lecture_attention_points",
            "post_lecture_questions",
            "supported_assessment_connections",
        ],
        "generation": {
            "status": "context_ready",
            "brief_generated": False,
            "instruction": (
                "Use only claims supported by the selected sources; preserve source IDs "
                "as provenance; omit unsupported assessment connections."
            ),
        },
    }


def build_assignment_context(
    state: dict[str, Any], module_code: str
) -> dict[str, Any]:
    """Build module assessment context and its currently available sources."""
    state = normalize_academic_truth(state)
    module = get_module(state, module_code)
    source_ids = list(
        dict.fromkeys(
            source_id
            for week in module.get("weeks", [])
            for source_id in week.get("source_ids", [])
        )
    )
    prepared_sources, source_contexts = _load_sources(state, source_ids)
    return {
        "workflow": "ASSIGNMENT_COACH",
        "objective_context": build_objective_context(state),
        "module": {
            "code": module["code"],
            "title": module["title"],
            "semester": module["semester"],
            "academic_year": module["academic_year"],
        },
        "assessments": module.get("assessments", []),
        "weeks": [
            {
                "number": week["week"],
                "topic": week["topic"],
                "items": week.get("items", []),
                "source_ids": week.get("source_ids", []),
            }
            for week in module.get("weeks", [])
        ],
        "sources": prepared_sources,
        "source_contexts": source_contexts,
        "truth_sources": state.get("sources", []),
    }
