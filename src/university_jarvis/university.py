"""Milestone 5C: automatic university-wide teaching-module/week discovery + reconciliation.

Orchestration only, same spirit as Intake V1 (``intake.py``): composes the
already-proven pieces rather than reimplementing them --
``discover_teaching_scope`` for module/week scope discovery and
``reconcile_week`` (Milestone 5A) for the actual per-week reconciliation
against the persisted ledger. No new reconciliation logic, no model/AI
classification, no Drive writes by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .blackboard import (
    BlackboardClient,
    ScopeIssue,
    WEEK_AMBIGUOUS_DUPLICATE,
    discover_teaching_scope,
)
from .drive import DriveClient
from .intake_ledger import save_ledger
from .reconcile import WeekReconcileResult, reconcile_week


@dataclass(frozen=True)
class ModuleCheckResult:
    """Reconciliation outcome for every discovered week of one teaching module."""

    module_code: str
    weeks: list[WeekReconcileResult] = field(default_factory=list)


@dataclass(frozen=True)
class UniversityCheckResult:
    """Aggregate outcome of one ``check-university`` run."""

    modules: list[ModuleCheckResult] = field(default_factory=list)
    scope_issues: list[ScopeIssue] = field(default_factory=list)


def check_university(
    blackboard_client: BlackboardClient,
    drive_client: DriveClient | None,
    ledger: dict[str, Any],
    *,
    sync_to_drive: bool = False,
    now: str | None = None,
) -> UniversityCheckResult:
    """Discover this account's teaching modules/weeks and reconcile each against the ledger.

    Scope is re-derived fresh every call (see ``discover_teaching_scope``) --
    nothing about "is a teaching module" is ever cached. Each successfully
    reconciled week's ledger update is persisted immediately after that
    week, not batched to the end of the run: a later module/week failing
    can never roll back an earlier module/week's already-successful,
    already-saved observation, and an earlier failure never stops later,
    independent module/weeks from being checked.
    """
    scope = discover_teaching_scope(blackboard_client)

    module_results: list[ModuleCheckResult] = []
    for module in scope.modules:
        week_results: list[WeekReconcileResult] = []
        for week_content in module.weeks:
            if week_content.status == WEEK_AMBIGUOUS_DUPLICATE:
                week_results.append(
                    WeekReconcileResult(
                        module.module_code, week_content.week_number, WEEK_AMBIGUOUS_DUPLICATE
                    )
                )
                continue

            result = reconcile_week(
                blackboard_client,
                drive_client,
                module.course_system_id,
                module.module_code,
                week_content.week_number,
                ledger,
                sync_to_drive=sync_to_drive,
                now=now,
            )
            week_results.append(result)
            if result.success:
                save_ledger(ledger)

        module_results.append(ModuleCheckResult(module.module_code, week_results))

    return UniversityCheckResult(module_results, scope.issues)
