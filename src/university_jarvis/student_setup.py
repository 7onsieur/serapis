"""Small local operations for student setup and academic edits."""
from __future__ import annotations

import os
import json
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from .sources import PROJECT_ROOT
from .state import StateError, _validate_state, normalize_academic_truth, personal_data_dir, save_state


def personal_state_path() -> Path:
    override = os.environ.get("JARVIS_STATE_FILE")
    if override:
        target = Path(override).expanduser()
        if target.is_file():
            try:
                if json.loads(target.read_text(encoding="utf-8")).get("dataset_kind") == "fictional_example":
                    raise StateError("JARVIS_STATE_FILE points to the read-only fictional sample. Unset that override before creating personal setup data.")
            except json.JSONDecodeError:
                pass
        return target
    return personal_data_dir() / "academic-state.json"


def existing_user_state_path() -> Path | None:
    """Locate a customized legacy checkout state without treating sample data as personal."""
    target = personal_state_path()
    if target.exists():
        return None
    for candidate in (Path.cwd() / "data" / "academic-state.json", PROJECT_ROOT / "data" / "academic-state.json"):
        if candidate.is_file():
            try:
                if json.loads(candidate.read_text(encoding="utf-8")).get("dataset_kind") != "fictional_example":
                    return candidate
            except (OSError, json.JSONDecodeError):
                continue
    return None


def initialize_personal_state(*, copy_existing: bool = False) -> Path:
    """Create a clean personal state, seeded only with product mission/schema."""
    target = personal_state_path()
    if target.exists():
        return target
    sample_path = PROJECT_ROOT / "data" / "academic-state.json"
    legacy_candidate = existing_user_state_path()
    legacy_path = legacy_candidate or (Path.cwd() / "data" / "academic-state.json" if (Path.cwd() / "data" / "academic-state.json").is_file() else sample_path)
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    if legacy.get("dataset_kind") != "fictional_example":
        seed = legacy if copy_existing else json.loads(sample_path.read_text(encoding="utf-8"))
    else:
        seed = legacy
    if legacy.get("dataset_kind") == "fictional_example":
        seed.update({"dataset_kind": "personal"})
        seed["student"] = {"name": "", "university": "", "programme": "", "year_of_study": None, "level": None, "academic_year": ""}
        seed["modules"] = []
        seed["sources"] = []
        seed["progress"] = {"overall_status": "unknown", "last_updated": None}
    save_state(seed, target)
    return target


def _load(path: Path | None = None) -> tuple[dict[str, Any], Path]:
    from .state import load_state
    target = path or personal_state_path()
    if not target.exists():
        initialize_personal_state()
    return load_state(target), target


def _save(state: dict[str, Any], path: Path) -> dict[str, Any]:
    normalized = normalize_academic_truth(state)
    _validate_state(normalized)
    save_state(normalized, path)
    return normalized


def _fact(value: Any, *, field: str) -> dict[str, Any]:
    has_value = value is not None and value != "" and value != []
    return {"status": "NEEDS_VERIFICATION" if has_value else "UNKNOWN", "evidence": []}


def _facts(owner: dict[str, Any], fields: tuple[str, ...]) -> None:
    owner["fact_provenance"] = {field: _fact(owner.get(field), field=field) for field in fields}


def edit_profile(*, university: str | None = None, programme: str | None = None, path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    if university is not None: state["student"]["university"] = university.strip()
    if programme is not None: state["student"]["programme"] = programme.strip()
    _save(state, target)
    return state


def add_module(code: str, title: str, *, path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,31}", code):
        raise StateError("Use a module code with letters, numbers, hyphens or underscores.")
    if any(m["code"].upper() == code for m in state["modules"]):
        raise StateError(f"{code} already exists. Edit that module instead.")
    module = {"code": code, "title": title.strip(), "semester": None, "academic_year": "", "assessments": [], "weeks": [], "progress": {"status": "unknown", "completed_week_numbers": [], "last_consolidated_week": None}}
    _facts(module, ("code", "title", "semester", "academic_year"))
    state["modules"].append(module)
    return _save(state, target)


def update_module(code: str, title: str, *, new_code: str | None = None, path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    module = next((m for m in state["modules"] if m["code"].upper() == code.upper()), None)
    if module is None: raise StateError(f"Module {code} was not found.")
    updated_code = (new_code or code).strip().upper()
    if any(m is not module and m["code"].upper() == updated_code for m in state["modules"]):
        raise StateError(f"{updated_code} is already used by another module.")
    if updated_code != module["code"]:
        old = module["code"]
        module["code"] = updated_code
        for source in state["sources"]:
            if source.get("module_code", "").upper() == old.upper(): source["module_code"] = updated_code
    module["title"] = title.strip()
    provenance = module.setdefault("fact_provenance", {})
    for field in ("code", "title"):
        provenance[field] = _fact(module.get(field), field=field)
    return _save(state, target)


def remove_module(code: str, *, path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    if not any(m["code"].upper() == code.upper() for m in state["modules"]): raise StateError(f"Module {code} was not found.")
    removed_sources = [s for s in state["sources"] if s.get("module_code", "").upper() == code.upper()]
    removed_source_ids = {s["id"] for s in removed_sources}
    state["modules"] = [m for m in state["modules"] if m["code"].upper() != code.upper()]
    state["sources"] = [s for s in state["sources"] if s["id"] not in removed_source_ids]
    result = _save(state, target)
    managed_root = (personal_data_dir() / "materials").resolve()
    for source in removed_sources:
        try:
            material = Path(source.get("locator", "")).resolve()
            material.relative_to(managed_root)
        except (ValueError, OSError):
            continue
        material.unlink(missing_ok=True)
    return result


def save_assessment(module_code: str, *, assessment_id: str | None = None, title: str, deadline: str = "", weight_percent: str = "", requirements: str = "", path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    module = next((m for m in state["modules"] if m["code"].upper() == module_code.upper()), None)
    if module is None: raise StateError(f"Module {module_code} was not found.")
    existing = next((a for a in module.setdefault("assessments", []) if a["id"] == assessment_id), None) if assessment_id else None
    if assessment_id and existing is None:
        raise StateError("That assessment could not be found. Refresh the module and try again.")
    if not title.strip(): raise StateError("Enter an assessment title.")
    deadline = deadline.strip()
    weight: float | None = None
    if weight_percent.strip():
        try: weight = float(weight_percent)
        except ValueError as exc: raise StateError("Weight must be a number from 0 to 100.") from exc
        if not 0 <= weight <= 100: raise StateError("Weight must be from 0 to 100.")
    import datetime
    if deadline:
        try: datetime.date.fromisoformat(deadline)
        except ValueError as exc: raise StateError("Enter a date as YYYY-MM-DD, or leave it blank.") from exc
    record = existing or {"id": "assessment-" + uuid.uuid4().hex[:12], "category": "ASSESSMENT"}
    record.update({"title": title.strip(), "deadline": deadline or None, "deadline_status": "unverified" if deadline else None, "weight_percent": weight, "requirements": [x.strip() for x in requirements.splitlines() if x.strip()] or None})
    _facts(record, ("title", "deadline", "deadline_status", "weight_percent", "requirements"))
    if existing is None: module["assessments"].append(record)
    return _save(state, target)


def remove_assessment(module_code: str, assessment_id: str, *, path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    module = next((m for m in state["modules"] if m["code"].upper() == module_code.upper()), None)
    if module is None: raise StateError(f"Module {module_code} was not found.")
    module["assessments"] = [a for a in module.get("assessments", []) if a["id"] != assessment_id]
    return _save(state, target)


def material_capability(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pptx": return "Text extraction available on this platform."
    if suffix == ".pdf": return "Text extraction available on macOS." if sys.platform == "darwin" else "File can be stored, but text extraction is currently available only on macOS."
    raise StateError("Serapis can currently import PDF and PowerPoint (.pptx) files only.")


def import_material(module_code: str, source_path: Path, *, week: int | None = None, source_id: str | None = None, path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    module = next((m for m in state["modules"] if m["code"].upper() == module_code.upper()), None)
    if module is None: raise StateError(f"Module {module_code} was not found.")
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file(): raise StateError(f"Could not find the selected file: {source_path.name}")
    capability = material_capability(source_path)
    if week is not None and (isinstance(week, bool) or week < 1): raise StateError("Week must be a number greater than zero.")
    materials_dir = (target.parent / "materials" / module["code"]) if path is not None else (personal_data_dir() / "materials" / module["code"])
    materials_dir.mkdir(parents=True, exist_ok=True)
    name = source_path.name
    destination = materials_dir / name
    if destination.exists():
        if destination.read_bytes() == source_path.read_bytes():
            existing = next((s for s in state["sources"] if Path(s.get("locator", "")).resolve() == destination.resolve()), None)
            if existing:
                if week is not None and (existing.get("module_code") != module["code"] or existing.get("week") != week):
                    reassigned = reassign_material(existing["id"], module["code"], week, path=target)
                    state = reassigned
                    existing["week"] = week
                return {"state": state, "source": existing, "capability": capability, "duplicate": True}
        destination = materials_dir / f"{source_path.stem}-{uuid.uuid4().hex[:8]}{source_path.suffix.lower()}"
    temp = destination.with_name(destination.name + ".importing")
    try:
        shutil.copyfile(source_path, temp)
        os.replace(temp, destination)
        sid = source_id or "src-" + uuid.uuid4().hex
        if any(s["id"] == sid for s in state["sources"]): raise StateError("A generated source identifier collided; retry the import.")
        source = {"id": sid, "module_code": module["code"], "type": "course_material", "source_class": "UNIVERSITY_MATERIAL", "title": source_path.name, "availability": "content_available", "locator": str(destination), "original_filename": source_path.name}
        if week is not None:
            existing_week = next((w for w in module["weeks"] if w["week"] == week), None)
            if existing_week is None:
                existing_week = {"week": week, "date": None, "topic": "", "progress": "unknown", "source_ids": [], "items": []}
                module["weeks"].append(existing_week)
            existing_week.setdefault("source_ids", []).append(sid)
            source["week"] = week
        state["sources"].append(source)
        try: _save(state, target)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    except Exception:
        temp.unlink(missing_ok=True)
        if destination.exists() and not any(s.get("locator") == str(destination) for s in state.get("sources", [])):
            destination.unlink(missing_ok=True)
        raise
    return {"state": state, "source": source, "capability": capability, "duplicate": False}


def reassign_material(source_id: str, module_code: str, week: int | None, *, path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    source = next((s for s in state["sources"] if s["id"] == source_id), None)
    module = next((m for m in state["modules"] if m["code"].upper() == module_code.upper()), None)
    if source is None or module is None: raise StateError("Material or module could not be found.")
    old_module = next((m for m in state["modules"] if m["code"].upper() == str(source.get("module_code", "")).upper()), None)
    if old_module:
        for old_week in old_module.get("weeks", []): old_week["source_ids"] = [sid for sid in old_week.get("source_ids", []) if sid != source_id]
    source["module_code"] = module["code"]
    source.pop("week", None)
    if week is not None:
        week_obj = next((w for w in module["weeks"] if w["week"] == week), None)
        if week_obj is None:
            week_obj = {"week": week, "date": None, "topic": "", "progress": "unknown", "source_ids": [], "items": []}
            module["weeks"].append(week_obj)
        week_obj.setdefault("source_ids", []).append(source_id)
        source["week"] = week
    return _save(state, target)


def replace_material(source_id: str, source_path: Path, *, path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    source = next((s for s in state["sources"] if s["id"] == source_id), None)
    if source is None: raise StateError("Material could not be found.")
    incoming = source_path.expanduser().resolve()
    if not incoming.is_file(): raise StateError(f"Could not find the selected file: {incoming.name}")
    capability = material_capability(incoming)
    old_path = Path(source["locator"])
    try:
        old_path.resolve().relative_to((personal_data_dir() / "materials").resolve())
    except (ValueError, OSError) as exc:
        raise StateError("This material is linked from outside Serapis. Remove it and import a managed copy before replacing it.") from exc
    destination = old_path.with_name(incoming.name)
    if destination.exists() and destination != old_path:
        destination = destination.with_name(f"{destination.stem}-{uuid.uuid4().hex[:8]}{destination.suffix.lower()}")
    temp = destination.with_name(destination.name + ".replacing")
    backup = old_path.read_bytes() if old_path.exists() else None
    try:
        shutil.copyfile(incoming, temp)
        os.replace(temp, destination)
        source["locator"] = str(destination)
        source["title"] = incoming.name
        source["original_filename"] = incoming.name
        _save(state, target)
        if old_path != destination: old_path.unlink(missing_ok=True)
    except Exception:
        temp.unlink(missing_ok=True)
        if destination.exists() and destination != old_path: destination.unlink(missing_ok=True)
        if backup is not None and old_path.exists(): old_path.write_bytes(backup)
        raise
    return {"state": state, "source": source, "capability": capability}


def remove_material(source_id: str, *, path: Path | None = None) -> dict[str, Any]:
    state, target = _load(path)
    source = next((s for s in state["sources"] if s["id"] == source_id), None)
    if source is None: raise StateError("Material could not be found.")
    if any(ref.get("source_id") == source_id for module in state["modules"] for assessment in module.get("assessments", []) for fact in assessment.get("fact_provenance", {}).values() for ref in fact.get("evidence", [])):
        raise StateError("This material supports a confirmed fact, so it cannot be removed until that fact is corrected.")
    for module in state["modules"]:
        for week in module.get("weeks", []): week["source_ids"] = [sid for sid in week.get("source_ids", []) if sid != source_id]
    state["sources"].remove(source)
    _save(state, target)
    try:
        material = Path(source.get("locator", "")).resolve()
        material.relative_to((personal_data_dir() / "materials").resolve())
    except (ValueError, OSError):
        return state
    material.unlink(missing_ok=True)
    return state
