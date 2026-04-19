from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pawpal_system import Owner, Pet, Priority, Task
from schedule_validator import validate_schedule_plan


def test_validate_schedule_plan_accepts_valid_plan():
    owner = Owner(name="Alex", available_time_minutes=60, preferences={"preferred_time_window": "morning"})
    pet = Pet(name="Buddy", age=3, type="Dog")
    owner.add_pet(pet)

    walk = Task(description="Walk", duration=30, priority=Priority.HIGH, time="08:00")
    brush = Task(description="Brush", duration=10, priority=Priority.MEDIUM)
    pet.add_task(walk)
    pet.add_task(brush)

    plan = {
        "scheduled_tasks": [
            {
                "task_id": walk.task_id,
                "start_time": "08:00",
                "end_time": "08:30",
                "reason": "Fixed-time walk.",
            },
            {
                "task_id": brush.task_id,
                "start_time": "08:30",
                "end_time": "08:40",
                "reason": "Fits after the walk.",
            },
        ],
        "skipped_tasks": [],
        "summary": "Morning essentials first.",
    }

    result = validate_schedule_plan(plan, owner)

    assert result.is_valid is True
    assert result.errors == []
    assert 0 <= result.quality_score <= 1


def test_validate_schedule_plan_rejects_fixed_time_changes_and_missing_tasks():
    owner = Owner(name="Alex", available_time_minutes=30)
    pet = Pet(name="Buddy", age=3, type="Dog")
    owner.add_pet(pet)

    walk = Task(description="Walk", duration=30, priority=Priority.HIGH, time="08:00")
    feed = Task(description="Feed", duration=10, priority=Priority.HIGH)
    pet.add_task(walk)
    pet.add_task(feed)

    plan = {
        "scheduled_tasks": [
            {
                "task_id": walk.task_id,
                "start_time": "08:30",
                "end_time": "09:00",
                "reason": "Moved later.",
            }
        ],
        "skipped_tasks": [],
        "summary": "Bad plan.",
    }

    result = validate_schedule_plan(plan, owner)

    assert result.is_valid is False
    assert any("must stay fixed" in error for error in result.errors)
    assert any("did not account for every pending task" in error for error in result.errors)


def test_validate_schedule_plan_rejects_overlaps():
    owner = Owner(name="Alex", available_time_minutes=30)
    pet = Pet(name="Milo", age=2, type="Cat")
    owner.add_pet(pet)

    t1 = Task(description="Medication", duration=20, priority=Priority.HIGH)
    t2 = Task(description="Play", duration=20, priority=Priority.LOW)
    pet.add_task(t1)
    pet.add_task(t2)

    plan = {
        "scheduled_tasks": [
            {
                "task_id": t1.task_id,
                "start_time": "09:00",
                "end_time": "09:20",
                "reason": "First.",
            },
            {
                "task_id": t2.task_id,
                "start_time": "09:10",
                "end_time": "09:30",
                "reason": "Overlaps.",
            },
        ],
        "skipped_tasks": [],
        "summary": "Too much overlap.",
    }

    result = validate_schedule_plan(plan, owner)

    assert result.is_valid is False
    assert any("overlaps" in error for error in result.errors)


def test_validate_schedule_plan_allows_overlap_when_both_tasks_opt_in():
    owner = Owner(name="Alex", available_time_minutes=40)
    pet = Pet(name="Milo", age=2, type="Cat")
    owner.add_pet(pet)

    t1 = Task(description="Feed Cat 1", duration=20, priority=Priority.MEDIUM, allow_overlap=True)
    t2 = Task(description="Feed Cat 2", duration=20, priority=Priority.MEDIUM, allow_overlap=True)
    pet.add_task(t1)
    pet.add_task(t2)

    plan = {
        "scheduled_tasks": [
            {
                "task_id": t1.task_id,
                "start_time": "09:00",
                "end_time": "09:20",
                "reason": "Can happen alongside the other feeding task.",
            },
            {
                "task_id": t2.task_id,
                "start_time": "09:00",
                "end_time": "09:20",
                "reason": "Can happen alongside the other feeding task.",
            },
        ],
        "skipped_tasks": [],
        "summary": "Feed both cats together.",
    }

    result = validate_schedule_plan(plan, owner)

    assert result.is_valid is True
    assert not any("overlaps" in error for error in result.errors)


def test_validate_schedule_plan_uses_elapsed_time_for_available_time_budget():
    owner = Owner(name="Alex", available_time_minutes=30)
    pet = Pet(name="Milo", age=2, type="Cat")
    owner.add_pet(pet)

    t1 = Task(description="Feed Cat 1", duration=20, priority=Priority.MEDIUM, allow_overlap=True)
    t2 = Task(description="Feed Cat 2", duration=20, priority=Priority.MEDIUM, allow_overlap=True)
    pet.add_task(t1)
    pet.add_task(t2)

    plan = {
        "scheduled_tasks": [
            {
                "task_id": t1.task_id,
                "start_time": "09:00",
                "end_time": "09:20",
                "reason": "Can happen alongside the other feeding task.",
            },
            {
                "task_id": t2.task_id,
                "start_time": "09:10",
                "end_time": "09:30",
                "reason": "Partially overlaps but only uses 30 minutes of real time.",
            },
        ],
        "skipped_tasks": [],
        "summary": "Both feedings fit in the same half hour block.",
    }

    result = validate_schedule_plan(plan, owner)

    assert result.is_valid is True
    assert not any("exceeds available time" in error for error in result.errors)
