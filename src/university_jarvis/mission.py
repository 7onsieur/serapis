"""Shared mission and objective context for academic reasoning workflows."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


OBJECTIVE_CONTEXT_VERSION = 1


def get_mission(state: dict[str, Any]) -> dict[str, Any]:
    """Return the validated persistent mission configuration."""
    return state["mission"]


def has_reliable_cohort_information(state: dict[str, Any]) -> bool:
    """Gate cohort-position reasoning on explicitly reliable, sourced evidence."""
    cohort_information = state.get("cohort_information")
    return bool(
        isinstance(cohort_information, dict)
        and cohort_information.get("reliability") == "reliable"
        and isinstance(cohort_information.get("source"), str)
        and cohort_information["source"].strip()
    )


def build_objective_context(state: dict[str, Any]) -> dict[str, Any]:
    """Build the compact objective context shared by every reasoning workflow."""
    mission = get_mission(state)
    encoded_mission = json.dumps(
        mission, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return {
        "version": OBJECTIVE_CONTEXT_VERSION,
        "mission_fingerprint": sha256(encoded_mission.encode("utf-8")).hexdigest(),
        "primary_objective": mission["primary_objective"]["statement"],
        "stretch_objective": mission["stretch_objective"]["statement"],
        "operating_principles": [
            principle["statement"] for principle in mission["operating_principles"]
        ],
        "hard_constraints": [
            constraint["statement"] for constraint in mission["constraints"]
        ],
        "reliable_cohort_information_available": has_reliable_cohort_information(
            state
        ),
    }
