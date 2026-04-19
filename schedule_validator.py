from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from pawpal_system import Owner, Priority, Task


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    quality_score: float

    def to_dict(self) -> Dict:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "quality_score": self.quality_score,
        }


def _time_to_minutes(time_str: str) -> int:
    hours, minutes = map(int, time_str.split(":"))
    return hours * 60 + minutes


def _valid_hhmm(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    try:
        hours, minutes = map(int, value.split(":"))
    except ValueError:
        return False
    return 0 <= hours < 24 and 0 <= minutes < 60


def _task_lookup(owner: Owner) -> Dict[str, Task]:
    return {task.task_id: task for task in owner.get_all_tasks()}


def _tasks_can_overlap(task1: Task, task2: Task) -> bool:
    return bool(task1.allow_overlap and task2.allow_overlap)


def _occupied_minutes(intervals: List[Tuple[int, int]]) -> int:
    if not intervals:
        return 0

    merged: List[List[int]] = []
    for start, end in sorted(intervals, key=lambda interval: interval[0]):
        if not merged or start >= merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def validate_schedule_plan(plan: Dict, owner: Owner) -> ValidationResult:
    """Validate an AI-generated schedule proposal against hard business rules."""
    errors: List[str] = []
    warnings: List[str] = []
    lookup = _task_lookup(owner)

    scheduled_tasks = plan.get("scheduled_tasks")
    skipped_tasks = plan.get("skipped_tasks")

    if not isinstance(scheduled_tasks, list):
        errors.append("scheduled_tasks must be a list.")
        scheduled_tasks = []
    if not isinstance(skipped_tasks, list):
        errors.append("skipped_tasks must be a list.")
        skipped_tasks = []

    seen_ids = set()
    occupied: List[Tuple[int, int, str]] = []
    occupied_ranges: List[Tuple[int, int]] = []

    for entry in scheduled_tasks:
        if not isinstance(entry, dict):
            errors.append("Each scheduled task entry must be an object.")
            continue

        task_id = entry.get("task_id")
        start_time = entry.get("start_time")
        end_time = entry.get("end_time")
        reason = entry.get("reason")

        if task_id not in lookup:
            errors.append(f"Unknown scheduled task_id: {task_id}")
            continue

        if task_id in seen_ids:
            errors.append(f"Task {task_id} appears more than once in the plan.")
            continue
        seen_ids.add(task_id)

        if not reason:
            errors.append(f"Scheduled task {task_id} is missing a reason.")

        if not _valid_hhmm(start_time or "") or not _valid_hhmm(end_time or ""):
            errors.append(f"Task {task_id} has an invalid time format.")
            continue

        task = lookup[task_id]
        start_minutes = _time_to_minutes(start_time)
        end_minutes = _time_to_minutes(end_time)
        duration = (task.duration or 0)

        if end_minutes <= start_minutes:
            errors.append(f"Task {task_id} must end after it starts.")
            continue

        if end_minutes - start_minutes != duration:
            errors.append(
                f"Task {task_id} duration mismatch: expected {duration} minutes."
            )

        if task.time and start_time != task.time:
            errors.append(f"Task {task_id} must stay fixed at {task.time}.")

        for other_start, other_end, other_task_id in occupied:
            other_task = lookup[other_task_id]
            if start_minutes < other_end and end_minutes > other_start and not _tasks_can_overlap(task, other_task):
                errors.append(f"Task {task_id} overlaps with task {other_task_id}.")

        occupied.append((start_minutes, end_minutes, task_id))
        occupied_ranges.append((start_minutes, end_minutes))

    for entry in skipped_tasks:
        if not isinstance(entry, dict):
            errors.append("Each skipped task entry must be an object.")
            continue
        task_id = entry.get("task_id")
        if task_id not in lookup:
            errors.append(f"Unknown skipped task_id: {task_id}")
            continue
        if task_id in seen_ids:
            errors.append(f"Task {task_id} appears in both scheduled and skipped tasks.")
            continue
        seen_ids.add(task_id)
        if not entry.get("reason"):
            errors.append(f"Skipped task {task_id} is missing a reason.")

    pending_task_ids = {task.task_id for task in owner.get_all_tasks() if task.status == "pending"}
    missing_pending = pending_task_ids - seen_ids
    if missing_pending:
        errors.append(
            "The plan did not account for every pending task: " + ", ".join(sorted(missing_pending))
        )

    total_scheduled = _occupied_minutes(occupied_ranges)
    if total_scheduled > owner.available_time_minutes:
        errors.append(
            f"Scheduled time {total_scheduled} exceeds available time {owner.available_time_minutes}."
        )

    warnings.extend(_priority_warnings(plan, lookup))
    warnings.extend(_preferred_window_warnings(plan, owner))

    quality_score = _quality_score(errors, warnings)
    return ValidationResult(
        is_valid=not errors,
        errors=errors,
        warnings=warnings,
        quality_score=quality_score,
    )


def _priority_warnings(plan: Dict, lookup: Dict[str, Task]) -> List[str]:
    warnings: List[str] = []
    ordered_entries = sorted(
        [
            entry for entry in plan.get("scheduled_tasks", [])
            if isinstance(entry, dict) and _valid_hhmm(entry.get("start_time", ""))
        ],
        key=lambda entry: _time_to_minutes(entry["start_time"]),
    )

    priorities = []
    for entry in ordered_entries:
        task = lookup.get(entry.get("task_id"))
        if task and task.time is None:
            priorities.append((entry["task_id"], int(task.priority)))

    for idx in range(1, len(priorities)):
        previous_id, previous_priority = priorities[idx - 1]
        current_id, current_priority = priorities[idx]
        if current_priority > previous_priority:
            warnings.append(
                f"Flexible task {current_id} is scheduled before lower-priority task {previous_id}."
            )
            break
    return warnings


def _preferred_window_warnings(plan: Dict, owner: Owner) -> List[str]:
    time_window = owner.preferences.get("preferred_time_window") if owner.preferences else None
    if not time_window:
        return []

    windows = {
        "morning": (360, 720),
        "afternoon": (720, 1080),
        "evening": (1080, 1320),
    }
    window = windows.get(time_window.lower())
    if not window:
        return []

    start, end = window
    warnings: List[str] = []
    for entry in plan.get("scheduled_tasks", []):
        if not isinstance(entry, dict) or not _valid_hhmm(entry.get("start_time", "")):
            continue
        task_start = _time_to_minutes(entry["start_time"])
        if not (start <= task_start < end):
            warnings.append(
                f"Some tasks fall outside the preferred {time_window} window."
            )
            break
    return warnings


def _quality_score(errors: List[str], warnings: List[str]) -> float:
    score = 1.0
    score -= min(0.7, len(errors) * 0.2)
    score -= min(0.3, len(warnings) * 0.05)
    return max(0.0, round(score, 2))
