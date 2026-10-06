"""Load and narrowly retrieve transparent academic state."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any


class StateError(ValueError):
    """Raised when academic state is missing or inconsistent."""


TRUST_STATUSES = {"CONFIRMED", "NEEDS_VERIFICATION", "UNKNOWN"}
SOURCE_CLASSES = {
    "UNIVERSITY_MATERIAL",
    "STUDENT_ENTERED",
    "MACHINE_OBSERVED_LMS",
    "DERIVED_STUDY_AID",
    "OTHER",
}
ACADEMIC_TRUTH_SCHEMA_VERSION = 1

_MODULE_FACTS = ("code", "title", "semester", "academic_year")
_ASSESSMENT_FACTS = (
    "title", "deadline", "deadline_status", "weight_percent", "requirements"
)


def _fact_has_value(value: Any, field: str) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() != "unknown"
    if field == "requirements" and isinstance(value, list):
        return bool(value)
    return True


def normalize_academic_truth(state: dict[str, Any]) -> dict[str, Any]:
    """Return an in-memory truth-aware copy; legacy values are never confirmed."""
    normalized = deepcopy(state)
    marker = normalized.get("academic_truth_schema_version")
    if marker not in (None, ACADEMIC_TRUTH_SCHEMA_VERSION):
        raise StateError(f"Unsupported academic_truth_schema_version: {marker!r}")
    normalized["academic_truth_schema_version"] = ACADEMIC_TRUTH_SCHEMA_VERSION

    for source in normalized.get("sources", []):
        source.setdefault("source_class", "OTHER")

    def annotate(owner: dict[str, Any], fact_names: tuple[str, ...]) -> None:
        provenance = owner.setdefault("fact_provenance", {})
        for field in fact_names:
            existing = provenance.get(field)
            if existing is not None:
                continue
            value_present = _fact_has_value(owner.get(field), field)
            provenance[field] = {
                "status": "NEEDS_VERIFICATION" if value_present else "UNKNOWN",
                "evidence": [],
            }

    for module in normalized.get("modules", []):
        annotate(module, _MODULE_FACTS)
        for assessment in module.get("assessments", []):
            annotate(assessment, _ASSESSMENT_FACTS)
    return normalized


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

    state = normalize_academic_truth(state)
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
    sources_by_id = {source["id"]: source for source in state["sources"]}
    for source in state["sources"]:
        if source.get("source_class") not in SOURCE_CLASSES:
            raise StateError(f"Invalid source_class for source {source.get('id')}")
        if source.get("availability") == "content_available" and not source.get("locator"):
            raise StateError(
                f"Content-available source has no locator: {source.get('id')}"
            )

    def validate_fact(owner: dict[str, Any], field: str, module_code: str) -> None:
        metadata = owner.get("fact_provenance", {}).get(field)
        if not isinstance(metadata, dict) or set(metadata) != {"status", "evidence"}:
            raise StateError(f"Invalid fact_provenance for {module_code}.{field}")
        status = metadata.get("status")
        evidence = metadata.get("evidence")
        if status not in TRUST_STATUSES:
            raise StateError(f"Invalid trust status for {module_code}.{field}")
        has_value = _fact_has_value(owner.get(field), field)
        if status == "UNKNOWN" and has_value:
            raise StateError(f"Unverified value {module_code}.{field} must use NEEDS_VERIFICATION")
        if status == "NEEDS_VERIFICATION" and not has_value:
            raise StateError(f"Empty fact {module_code}.{field} must use UNKNOWN")
        if not isinstance(evidence, list):
            raise StateError(f"Evidence must be a list for {module_code}.{field}")
        for ref in evidence:
            if not isinstance(ref, dict) or set(ref) - {"source_id", "location"} or "source_id" not in ref:
                raise StateError(f"Invalid evidence reference for {module_code}.{field}")
            source_id = ref["source_id"]
            if not isinstance(source_id, str) or source_id not in known_sources:
                raise StateError(f"Unknown evidence source {source_id!r} for {module_code}.{field}")
            if "location" in ref and not isinstance(ref["location"], str):
                raise StateError(f"Evidence location must be text for {module_code}.{field}")
            source = sources_by_id[source_id]
            source_module = source.get("module_code")
            if source_module is not None and str(source_module).upper() != module_code.upper():
                raise StateError(f"Evidence source {source_id} belongs to another module")
        if status == "CONFIRMED":
            confirming_classes = {
                sources_by_id[ref["source_id"]].get("source_class")
                for ref in evidence
            }
            if not confirming_classes.intersection({"UNIVERSITY_MATERIAL", "MACHINE_OBSERVED_LMS"}):
                raise StateError(
                    f"Confirmed fact {module_code}.{field} requires university or explicitly reconciled LMS evidence"
                )
            if not has_value:
                raise StateError(f"Confirmed fact {module_code}.{field} has no value")

    for module in state["modules"]:
        module_code = str(module.get("code", ""))
        for field in _MODULE_FACTS:
            validate_fact(module, field, module_code)
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
            for source_id in week.get("source_ids", []):
                source = sources_by_id[source_id]
                source_module = source.get("module_code")
                source_week = source.get("week")
                if source_module is not None and str(source_module).upper() != module_code.upper():
                    raise StateError(f"Source {source_id} belongs to another module")
                if source_week is not None and source_week != number:
                    raise StateError(f"Source {source_id} belongs to another week")
        assessment_ids: set[str] = set()
        for assessment in module.get("assessments", []):
            assessment_id = assessment.get("id")
            if not isinstance(assessment_id, str) or not assessment_id or assessment_id in assessment_ids:
                raise StateError(f"Assessment IDs must be unique in {module_code}")
            assessment_ids.add(assessment_id)
            for field in _ASSESSMENT_FACTS:
                validate_fact(assessment, field, module_code)
            weight = assessment.get("weight_percent")
            if weight is not None and (not isinstance(weight, (int, float)) or isinstance(weight, bool) or not 0 <= weight <= 100):
                raise StateError(f"Invalid assessment weight for {module_code}.{assessment_id}")
            requirements = assessment.get("requirements")
            if requirements is not None and (
                not isinstance(requirements, list)
                or not all(isinstance(item, str) and item.strip() for item in requirements)
            ):
                raise StateError(f"Invalid assessment requirements for {module_code}.{assessment_id}")
    for source in state["sources"]:
        scoped_module = source.get("module_code")
        if scoped_module is not None and str(scoped_module).upper() not in module_codes:
            raise StateError(f"Source {source['id']} references unknown module {scoped_module}")
        scoped_week = source.get("week")
        if scoped_week is not None:
            if isinstance(scoped_week, bool) or not isinstance(scoped_week, int) or scoped_week < 1:
                raise StateError(f"Invalid week scope for source {source['id']}")
            if scoped_module is None:
                raise StateError(f"Week-scoped source {source['id']} must also have module_code")
            scoped_module_data = next(
                module for module in state["modules"]
                if str(module.get("code", "")).upper() == str(scoped_module).upper()
            )
            if scoped_week not in {week.get("week") for week in scoped_module_data.get("weeks", [])}:
                raise StateError(f"Source {source['id']} references an unknown module/week")


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
