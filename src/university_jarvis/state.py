"""Load and narrowly retrieve transparent academic state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class StateError(ValueError):
    """Raised when academic state is missing or inconsistent."""


def default_state_path() -> Path:
    configured = os.environ.get("JARVIS_STATE_FILE")
    if configured:
        return Path(configured)

    cwd_candidate = Path.cwd() / "data" / "academic-state.json"
    if cwd_candidate.exists():
        return cwd_candidate

    return Path(__file__).resolve().parents[2] / "data" / "academic-state.json"


def load_state(path: Path | None = None) -> dict[str, Any]:
    state_path = path or default_state_path()
    try:
        with state_path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError as exc:
        raise StateError(f"State file not found: {state_path}") from exc
    except json.JSONDecodeError as exc:
        raise StateError(f"Invalid JSON in state file: {exc}") from exc

    _validate_state(state)
    return state


def _validate_state(state: dict[str, Any]) -> None:
    for key in ("schema_version", "mission", "student", "modules", "sources"):
        if key not in state:
            raise StateError(f"State is missing required field: {key}")

    _validate_mission(state["mission"])

    module_codes = [module.get("code") for module in state["modules"]]
    if len(module_codes) != len(set(module_codes)):
        raise StateError("Module codes must be unique")

    source_ids = [source.get("id") for source in state["sources"]]
    if len(source_ids) != len(set(source_ids)):
        raise StateError("Source IDs must be unique")

    known_sources = set(source_ids)
    for source in state["sources"]:
        if source.get("availability") == "content_available" and not source.get("locator"):
            raise StateError(
                f"Content-available source has no locator: {source.get('id')}"
            )

    for module in state["modules"]:
        week_numbers: set[int] = set()
        for week in module.get("weeks", []):
            number = week.get("week")
            if number in week_numbers:
                raise StateError(f"Duplicate week {number} in {module.get('code')}")
            week_numbers.add(number)
            unknown = set(week.get("source_ids", [])) - known_sources
            if unknown:
                raise StateError(
                    f"Week {number} in {module.get('code')} references unknown sources: "
                    + ", ".join(sorted(unknown))
                )


def _validate_mission(mission: Any) -> None:
    required = {
        "statement",
        "primary_objective",
        "stretch_objective",
        "operating_principles",
        "constraints",
    }
    if not isinstance(mission, dict) or not required.issubset(mission):
        raise StateError("Mission configuration is missing required fields")
    if not isinstance(mission["statement"], str) or not mission["statement"].strip():
        raise StateError("Mission statement must be a non-empty string")

    for field in ("primary_objective", "stretch_objective"):
        objective = mission[field]
        if not isinstance(objective, dict) or not isinstance(
            objective.get("statement"), str
        ) or not objective["statement"].strip():
            raise StateError(f"Mission {field} must contain a non-empty statement")

    for field in ("operating_principles", "constraints"):
        entries = mission[field]
        if not isinstance(entries, list) or not entries:
            raise StateError(f"Mission {field} must be a non-empty list")
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("id"), str)
                or not entry["id"].strip()
                or not isinstance(entry.get("statement"), str)
                or not entry["statement"].strip()
            ):
                raise StateError(
                    f"Mission {field} entries require non-empty id and statement"
                )


def get_module(state: dict[str, Any], code: str) -> dict[str, Any]:
    normalized = code.upper()
    for module in state["modules"]:
        if module["code"].upper() == normalized:
            return module
    raise StateError(f"Unknown module: {code}")


def get_week(module: dict[str, Any], week_number: int) -> dict[str, Any]:
    for week in module.get("weeks", []):
        if week["week"] == week_number:
            return week
    raise StateError(f"No Week {week_number} state for {module['code']}")


def get_sources(state: dict[str, Any], source_ids: list[str]) -> list[dict[str, Any]]:
    by_id = {source["id"]: source for source in state["sources"]}
    return [by_id[source_id] for source_id in source_ids]
