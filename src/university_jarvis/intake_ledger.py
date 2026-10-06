"""Machine-observed intake ledger: schema-versioned, separate from data/academic-state.json.

Records what Serapis has actually retrieved from Blackboard, keyed by document
identity, purely so repeated intake runs can tell NEW/UNCHANGED/CHANGED
material apart. Never hand-authored -- only ever written by reconciliation
(see ``reconcile.py``). Deliberately kept as its own file rather than folded
into ``academic-state.json``: one is curriculum state a person edits, the
other is an observation log Serapis edits.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .sources import PROJECT_ROOT
from .state import StateError, personal_data_dir

LEDGER_SCHEMA_VERSION = 1


class LedgerError(StateError):
    """Raised for intake ledger load/save failures."""


def default_ledger_path() -> Path:
    configured = os.environ.get("JARVIS_LEDGER_FILE")
    if configured:
        return Path(configured)
    legacy = PROJECT_ROOT / "data" / "intake-ledger.json"
    return legacy if legacy.exists() else personal_data_dir() / "intake-ledger.json"


def new_ledger() -> dict[str, Any]:
    return {"schema_version": LEDGER_SCHEMA_VERSION, "modules": {}}


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    """Load the ledger, or start a fresh one if none has ever been written yet."""
    ledger_path = path or default_ledger_path()
    try:
        with ledger_path.open(encoding="utf-8") as handle:
            ledger = json.load(handle)
    except FileNotFoundError:
        return new_ledger()
    except json.JSONDecodeError as exc:
        raise LedgerError(f"Invalid JSON in intake ledger: {ledger_path}") from exc

    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise LedgerError(
            f"Unsupported intake ledger schema_version: {ledger.get('schema_version')!r}"
        )
    ledger.setdefault("modules", {})
    return ledger


def save_ledger(ledger: dict[str, Any], path: Path | None = None) -> None:
    """Atomically replace the ledger file (temp file + rename)."""
    ledger_path = path or default_ledger_path()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temp_path = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    temp_path.write_bytes(payload)
    os.replace(temp_path, ledger_path)


def _documents_for_week(ledger: dict[str, Any], module_code: str, week: int) -> dict[str, Any]:
    modules = ledger.setdefault("modules", {})
    module_entry = modules.setdefault(module_code.upper(), {"weeks": {}})
    weeks = module_entry.setdefault("weeks", {})
    week_entry = weeks.setdefault(str(week), {"documents": {}})
    return week_entry.setdefault("documents", {})


def get_document_entry(
    ledger: dict[str, Any], module_code: str, week: int, content_id: str
) -> dict[str, Any] | None:
    documents = (
        ledger.get("modules", {})
        .get(module_code.upper(), {})
        .get("weeks", {})
        .get(str(week), {})
        .get("documents", {})
    )
    return documents.get(content_id)

def all_document_entries(ledger: dict[str, Any], module_code: str, week: int) -> dict[str, Any]:
    """Read-only view of every document entry currently ledgered for this module/week."""
    return dict(
        ledger.get("modules", {})
        .get(module_code.upper(), {})
        .get("weeks", {})
        .get(str(week), {})
        .get("documents", {})
    )


def set_document_entry(
    ledger: dict[str, Any], module_code: str, week: int, content_id: str, entry: dict[str, Any]
) -> None:
    documents = _documents_for_week(ledger, module_code, week)
    documents[content_id] = entry
