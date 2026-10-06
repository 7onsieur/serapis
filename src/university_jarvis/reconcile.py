"""Milestone 5A: persisted, content-identity-based change detection/reconciliation.

Reuses Intake V1's proven traversal/classification (``discover_week_content``)
unchanged, and adds a durable ledger (``intake_ledger``) so repeated runs can
answer "what is new or changed" instead of blindly re-downloading and
re-syncing every attachment every time. ``intake.intake_week`` (Intake V1) is
untouched by this module.

Evidence limitation: Blackboard metadata may help avoid unnecessary downloads,
but downloaded bytes and their content hash remain the authority for detecting
content changes. The integration does not modify Blackboard content.

Identity: Blackboard's public API exposes content identity only at the
document/container level (``content_id``) -- there is no separate,
API-exposed identifier for an individual attachment (see ``blackboard.py``'s
``extract_attachments`` docstring: the file is only reachable by parsing an
anchor href inside the document's HTML body). Ledger entries are therefore
keyed by (content_id, file_name): content_id identifies the container,
file_name disambiguates multiple attachments discovered under the same
document. A week containing two discovered attachments that collide on
file_name is routed to AMBIGUOUS before reconciliation ever keys anything by
name (mirrors Intake V1's own duplicate-name handling in ``intake.py``), so
that identity assumption is never silently violated by a same-named
collision within a document, or across documents in the same week.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .blackboard import (
    AMBIGUOUS_WEEK_STRUCTURE,
    BlackboardClient,
    BlackboardError,
    ContentRef,
    DiscoveredAttachment,
    WEEK_AMBIGUOUS_DUPLICATE,
    WEEK_NOT_YET_PUBLISHED,
    discover_week_content,
    sources_destination,
)
from .drive import DriveClient, DriveError, sync_file
from .intake import (
    AMBIGUOUS,
    DUPLICATE_FILE_NAME_IN_WEEK,
    FAILED,
    SKIPPED,
    WEEK_NOT_FOUND,
)
from .intake_ledger import all_document_entries, get_document_entry, set_document_entry

NEW = "NEW"
UNCHANGED = "UNCHANGED"
CHANGED = "CHANGED"
METADATA_CHANGED = "METADATA_CHANGED_CONTENT_IDENTICAL"
MISSING_SINCE_LAST_CHECK = "MISSING_SINCE_LAST_CHECK"

DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
DRIVE_SYNC_FAILED = "DRIVE_SYNC_FAILED"


@dataclass(frozen=True)
class ReconcileItemResult:
    """Outcome for one discovered document/attachment, or one skipped node."""

    status: str
    source_path: tuple[ContentRef, ...]
    file_name: str | None = None
    local_path: Path | None = None
    drive_file_id: str | None = None
    reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class WeekReconcileResult:
    """Reconciliation outcome for one module/week. ``success`` never masks a failure."""

    module_code: str
    week: int
    status: str
    items: list[ReconcileItemResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        if self.status in (WEEK_NOT_FOUND, WEEK_AMBIGUOUS_DUPLICATE):
            return False
        return not any(item.status in (FAILED, AMBIGUOUS) for item in self.items)


def _now(now: str | None) -> str:
    return now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _duplicate_file_names(attachments: list[DiscoveredAttachment]) -> set[str]:
    # Same rule as Intake V1 (intake.py): a shared file name is not proof of
    # a unique underlying resource, so a collision must be surfaced, never
    # silently ledgered onto one entry.
    seen: set[str] = set()
    dupes: set[str] = set()
    for discovered in attachments:
        name = discovered.attachment.file_name
        if name in seen:
            dupes.add(name)
        seen.add(name)
    return dupes


def _document_ref(source_path: tuple[ContentRef, ...]) -> ContentRef:
    return source_path[-1]


def _source_path_dicts(source_path: tuple[ContentRef, ...]) -> list[dict[str, Any]]:
    return [
        {"content_id": ref.content_id, "title": ref.title, "content_handler": ref.content_handler}
        for ref in source_path
    ]


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _download_to_temp(
    blackboard_client: BlackboardClient, url: str, dest: Path
) -> tuple[Path, bytes]:
    """Download the attachment into a sibling temp file; caller promotes it atomically.

    ``dest`` (the canonical local path) is never touched on failure -- only a
    successful download produces a temp file, and only the caller's
    subsequent ``os.replace`` ever changes what ``dest`` points to.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest.with_name(dest.name + ".part")
    blackboard_client.download_attachment(url, temp_path)
    data = temp_path.read_bytes()
    return temp_path, data


def _promote(temp_path: Path, dest: Path) -> None:
    os.replace(temp_path, dest)


def reconcile_week(
    blackboard_client: BlackboardClient,
    drive_client: DriveClient | None,
    course_system_id: str,
    module_code: str,
    week: int,
    ledger: dict[str, Any],
    *,
    sync_to_drive: bool = True,
    now: str | None = None,
) -> WeekReconcileResult:
    """Discover this week's content and reconcile it against the persisted ledger.

    Mutates ``ledger`` in place -- but only for items whose required work
    (download + hash, and Drive sync when enabled) fully succeeds. A failed
    item leaves its prior ledger entry (if any) exactly as it was, so a
    crash or a Drive failure never makes failed work look complete; it will
    simply be reconsidered on the next run. The caller persists ``ledger``
    (see ``intake_ledger.save_ledger``) only after this returns.
    """
    weeks = discover_week_content(blackboard_client, course_system_id)
    week_content = next((w for w in weeks if w.week_number == week), None)
    if week_content is None:
        return WeekReconcileResult(module_code, week, WEEK_NOT_FOUND)

    if week_content.status == WEEK_NOT_YET_PUBLISHED:
        return WeekReconcileResult(module_code, week, WEEK_NOT_YET_PUBLISHED)

    items: list[ReconcileItemResult] = []
    timestamp = _now(now)

    for skipped in week_content.skipped:
        status = AMBIGUOUS if skipped.reason == AMBIGUOUS_WEEK_STRUCTURE else SKIPPED
        items.append(
            ReconcileItemResult(status=status, source_path=skipped.source_path, reason=skipped.reason)
        )

    duplicate_names = _duplicate_file_names(week_content.attachments)
    seen_keys: set[tuple[str, str]] = set()

    for discovered in week_content.attachments:
        attachment = discovered.attachment
        document_ref = _document_ref(discovered.source_path)
        content_id = document_ref.content_id

        if content_id is None or attachment.file_name in duplicate_names:
            items.append(
                ReconcileItemResult(
                    status=AMBIGUOUS,
                    source_path=discovered.source_path,
                    file_name=attachment.file_name,
                    reason=DUPLICATE_FILE_NAME_IN_WEEK
                    if content_id is not None
                    else AMBIGUOUS_WEEK_STRUCTURE,
                )
            )
            continue

        seen_keys.add((content_id, attachment.file_name))

        document_entry = get_document_entry(ledger, module_code, week, content_id)
        attachment_entry = (
            (document_entry or {}).get("attachments", {}).get(attachment.file_name)
        )

        modified_matches = (
            document_entry is not None and document_entry.get("modified") == document_ref.modified
        )

        if modified_matches and attachment_entry is not None:
            item, updated_attachment_entry = _reconcile_unchanged(
                discovered, attachment_entry, timestamp
            )
            items.append(item)
            attachments = dict(document_entry.get("attachments", {}))
            attachments[attachment.file_name] = updated_attachment_entry
            set_document_entry(
                ledger,
                module_code,
                week,
                content_id,
                {**document_entry, "attachments": attachments, "last_seen_at": timestamp},
            )
            continue

        item, new_document_entry = _reconcile_download(
            blackboard_client,
            drive_client,
            discovered,
            document_entry,
            attachment_entry,
            module_code,
            week,
            timestamp,
            sync_to_drive=sync_to_drive,
        )
        items.append(item)
        if new_document_entry is not None:
            set_document_entry(ledger, module_code, week, content_id, new_document_entry)

    for (content_id, file_name), entry in _missing_entries(
        ledger, module_code, week, seen_keys
    ):
        items.append(
            ReconcileItemResult(
                status=MISSING_SINCE_LAST_CHECK,
                source_path=(
                    ContentRef(
                        content_id=content_id,
                        title=entry.get("title"),
                        content_handler=entry.get("content_handler"),
                        modified=entry.get("modified"),
                        created=entry.get("created"),
                    ),
                ),
                file_name=file_name,
            )
        )

    return WeekReconcileResult(module_code, week, week_content.status, items)


def _missing_entries(
    ledger: dict[str, Any], module_code: str, week: int, seen_keys: set[tuple[str, str]]
) -> list[tuple[tuple[str, str], dict[str, Any]]]:
    missing: list[tuple[tuple[str, str], dict[str, Any]]] = []
    for content_id, document_entry in all_document_entries(ledger, module_code, week).items():
        for file_name in document_entry.get("attachments", {}):
            key = (content_id, file_name)
            if key not in seen_keys:
                missing.append((key, document_entry))
    return missing


def _reconcile_unchanged(
    discovered: DiscoveredAttachment, attachment_entry: dict[str, Any], timestamp: str
) -> tuple[ReconcileItemResult, dict[str, Any]]:
    updated = {**attachment_entry, "last_seen_at": timestamp}
    item = ReconcileItemResult(
        status=UNCHANGED,
        source_path=discovered.source_path,
        file_name=discovered.attachment.file_name,
    )
    return item, updated


def _reconcile_download(
    blackboard_client: BlackboardClient,
    drive_client: DriveClient | None,
    discovered: DiscoveredAttachment,
    document_entry: dict[str, Any] | None,
    attachment_entry: dict[str, Any] | None,
    module_code: str,
    week: int,
    timestamp: str,
    *,
    sync_to_drive: bool,
) -> tuple[ReconcileItemResult, dict[str, Any] | None]:
    attachment = discovered.attachment
    document_ref = _document_ref(discovered.source_path)
    dest = sources_destination(module_code, week, attachment.file_name)

    try:
        temp_path, data = _download_to_temp(blackboard_client, attachment.url, dest)
    except BlackboardError as exc:
        return (
            ReconcileItemResult(
                status=FAILED,
                source_path=discovered.source_path,
                file_name=attachment.file_name,
                reason=DOWNLOAD_FAILED,
                error=str(exc),
            ),
            None,
        )

    content_sha256 = _sha256_bytes(data)
    previous_sha256 = (attachment_entry or {}).get("content_sha256")
    is_new = attachment_entry is None
    content_changed = previous_sha256 is not None and previous_sha256 != content_sha256

    _promote(temp_path, dest)

    drive_file_id = (attachment_entry or {}).get("drive_file_id")
    if sync_to_drive and drive_client is not None and (is_new or content_changed):
        try:
            drive_file_id = sync_file(drive_client, dest, module_code, week)
        except DriveError as exc:
            # Local file is already promoted (matches Intake V1's per-item
            # partial-success behaviour), but the ledger is deliberately
            # left untouched here -- next run will see the same stale
            # previous_sha256, treat this as CHANGED again, and retry Drive.
            return (
                ReconcileItemResult(
                    status=FAILED,
                    source_path=discovered.source_path,
                    file_name=attachment.file_name,
                    local_path=dest,
                    reason=DRIVE_SYNC_FAILED,
                    error=str(exc),
                ),
                None,
            )

    first_seen_at = (attachment_entry or {}).get("first_seen_at", timestamp)
    last_changed_at = timestamp if (is_new or content_changed) else (
        (attachment_entry or {}).get("last_changed_at", timestamp)
    )

    new_attachment_entry = {
        "file_name": attachment.file_name,
        "content_sha256": content_sha256,
        "first_seen_at": first_seen_at,
        "last_seen_at": timestamp,
        "last_changed_at": last_changed_at,
    }
    if drive_file_id is not None:
        new_attachment_entry["drive_file_id"] = drive_file_id

    attachments = dict((document_entry or {}).get("attachments", {}))
    attachments[attachment.file_name] = new_attachment_entry

    new_document_entry = {
        "content_id": document_ref.content_id,
        "title": document_ref.title,
        "content_handler": document_ref.content_handler,
        "modified": document_ref.modified,
        "created": document_ref.created,
        "source_path": _source_path_dicts(discovered.source_path),
        "attachments": attachments,
        "last_seen_at": timestamp,
    }

    if is_new:
        status = NEW
    elif content_changed:
        status = CHANGED
    else:
        status = METADATA_CHANGED

    item = ReconcileItemResult(
        status=status,
        source_path=discovered.source_path,
        file_name=attachment.file_name,
        local_path=dest,
        drive_file_id=drive_file_id,
    )
    return item, new_document_entry
