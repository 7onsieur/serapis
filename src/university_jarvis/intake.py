"""Intake V1: automatic module+week Blackboard material intake.

Orchestration only -- composes the already-proven pieces rather than
reimplementing them: ``discover_week_content`` for traversal/classification,
``BlackboardClient.download_attachment`` for retrieval, and
``drive.sync_file`` for idempotent Drive upload. Input is module + week; no
Blackboard content title is ever supplied by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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

RETRIEVED = "RETRIEVED"
SYNCED = "SYNCED"
SKIPPED = "SKIPPED"
AMBIGUOUS = "AMBIGUOUS"
FAILED = "FAILED"

WEEK_NOT_FOUND = "WEEK_NOT_FOUND"

DUPLICATE_FILE_NAME_IN_WEEK = "DUPLICATE_FILE_NAME_IN_WEEK"


@dataclass(frozen=True)
class IntakeItemResult:
    """Outcome for one discovered attachment, or one node discovery already skipped."""

    status: str
    source_path: tuple[ContentRef, ...]
    file_name: str | None = None
    local_path: Path | None = None
    drive_file_id: str | None = None
    reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class WeekIntakeResult:
    """Intake outcome for one module/week. ``success`` never masks a failure."""

    module_code: str
    week: int
    status: str
    items: list[IntakeItemResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        if self.status in (WEEK_NOT_FOUND, WEEK_AMBIGUOUS_DUPLICATE):
            return False
        return not any(item.status in (FAILED, AMBIGUOUS) for item in self.items)


def _find_week(weeks, week_number: int):
    for week_content in weeks:
        if week_content.week_number == week_number:
            return week_content
    return None


def _duplicate_file_names(attachments: list[DiscoveredAttachment]) -> set[str]:
    # A file name is not proof of a unique underlying Blackboard resource --
    # two distinct discovered attachments landing on the same destination
    # path must be surfaced, never silently overwritten onto one another.
    seen: set[str] = set()
    dupes: set[str] = set()
    for discovered in attachments:
        name = discovered.attachment.file_name
        if name in seen:
            dupes.add(name)
        seen.add(name)
    return dupes


def intake_week(
    blackboard_client: BlackboardClient,
    drive_client: DriveClient | None,
    course_system_id: str,
    module_code: str,
    week: int,
    *,
    sync_to_drive: bool = True,
) -> WeekIntakeResult:
    """Discover, retrieve, and (optionally) Drive-sync one module/week.

    ``course_system_id`` is Blackboard's internal course id (already resolved
    via ``resolve_course`` by the caller). Retrieval/sync failures on one
    attachment do not stop the others, and never flip ``success`` to true.
    """
    weeks = discover_week_content(blackboard_client, course_system_id)
    week_content = _find_week(weeks, week)
    if week_content is None:
        return WeekIntakeResult(module_code, week, WEEK_NOT_FOUND)

    if week_content.status == WEEK_NOT_YET_PUBLISHED:
        return WeekIntakeResult(module_code, week, WEEK_NOT_YET_PUBLISHED)

    items: list[IntakeItemResult] = []

    for skipped in week_content.skipped:
        status = AMBIGUOUS if skipped.reason == AMBIGUOUS_WEEK_STRUCTURE else SKIPPED
        items.append(IntakeItemResult(status=status, source_path=skipped.source_path, reason=skipped.reason))

    duplicate_names = _duplicate_file_names(week_content.attachments)

    for discovered in week_content.attachments:
        attachment = discovered.attachment
        if attachment.file_name in duplicate_names:
            items.append(
                IntakeItemResult(
                    status=AMBIGUOUS,
                    source_path=discovered.source_path,
                    file_name=attachment.file_name,
                    reason=DUPLICATE_FILE_NAME_IN_WEEK,
                )
            )
            continue

        dest = sources_destination(module_code, week, attachment.file_name)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            blackboard_client.download_attachment(attachment.url, dest)
        except BlackboardError as exc:
            items.append(
                IntakeItemResult(
                    status=FAILED,
                    source_path=discovered.source_path,
                    file_name=attachment.file_name,
                    error=str(exc),
                )
            )
            continue

        if not sync_to_drive or drive_client is None:
            items.append(
                IntakeItemResult(
                    status=RETRIEVED,
                    source_path=discovered.source_path,
                    file_name=attachment.file_name,
                    local_path=dest,
                )
            )
            continue

        try:
            drive_file_id = sync_file(drive_client, dest, module_code, week)
        except DriveError as exc:
            items.append(
                IntakeItemResult(
                    status=FAILED,
                    source_path=discovered.source_path,
                    file_name=attachment.file_name,
                    local_path=dest,
                    error=str(exc),
                )
            )
            continue

        items.append(
            IntakeItemResult(
                status=SYNCED,
                source_path=discovered.source_path,
                file_name=attachment.file_name,
                local_path=dest,
                drive_file_id=drive_file_id,
            )
        )

    return WeekIntakeResult(module_code, week, week_content.status, items)
