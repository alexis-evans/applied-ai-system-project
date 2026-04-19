"""Comprehensive tests for PawPal+ domain and scheduler logic."""

from datetime import datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pawpal_system import Owner, Pet, Priority, Scheduler, Task


def test_owner_add_remove_pet_and_get_all_tasks_filters_correctly():
    owner = Owner(name="Alex")
    dog = Pet(name="Buddy", age=3, type="Dog")
    cat = Pet(name="Milo", age=2, type="Cat")

    walk = Task(description="Walk", duration=30, priority=Priority.HIGH)
    feed = Task(description="Feed", duration=10, priority=Priority.MEDIUM)
    groom = Task(description="Groom", duration=20, priority=Priority.LOW)
    dog.add_task(walk)
    dog.add_task(feed)
    cat.add_task(groom)

    owner.add_pet(dog)
    owner.add_pet(cat)
    owner.add_pet(dog)  # no duplicate add

    assert dog.owner is owner
    assert len(owner.pets) == 2
    assert owner.get_all_tasks() == [walk, feed, groom]
    assert owner.get_all_tasks(dog) == [walk, feed]

    outsider = Pet(name="Outside", age=1, type="Bird")
    assert owner.get_all_tasks(outsider) == []

    owner.remove_pet(cat)
    assert cat.owner is None
    assert owner.pets == [dog]


def test_pet_add_remove_and_get_pending_tasks():
    pet = Pet(name="Buddy", age=3, type="Dog")
    pending = Task(description="Pending", duration=15, priority=Priority.HIGH)
    completed = Task(
        description="Completed",
        duration=5,
        priority=Priority.LOW,
        status="completed",
    )

    pet.add_task(pending)
    pet.add_task(completed)
    pet.add_task(pending)  # duplicate ignored

    assert len(pet.tasks) == 2
    assert pending.pet is pet
    assert completed.pet is pet
    assert pet.get_pending_tasks() == [pending]

    pet.remove_task(completed)
    assert completed.pet is None
    assert pet.tasks == [pending]


def test_task_change_status_allows_valid_transitions_and_rejects_invalid():
    task = Task(description="Walk", duration=30, priority=Priority.HIGH)

    for status in ["scheduled", "completed", "skipped", "pending"]:
        task.change_status(status)
        assert task.status == status

    with pytest.raises(ValueError):
        task.change_status("done")


def test_task_update_task_updates_only_fields_provided():
    due = datetime(2026, 1, 1, 8, 0)
    task = Task(
        description="Original",
        duration=30,
        priority=Priority.MEDIUM,
        frequency="once",
        time="08:00",
        due_date=due,
    )

    task.update_task(description="Updated", duration=45, priority=Priority.HIGH)

    assert task.description == "Updated"
    assert task.duration == 45
    assert task.priority == Priority.HIGH
    assert task.frequency == "once"
    assert task.time == "08:00"
    assert task.allow_overlap is False
    assert task.due_date == due

    task.update_task(frequency="daily", allow_overlap=True, time=None, due_date=None)
    assert task.frequency == "daily"
    assert task.allow_overlap is True
    assert task.time is None
    assert task.due_date is None


def test_recurrence_logic_daily_mark_complete_creates_next_day_task():
    pet = Pet(name="Buddy", age=4, type="Dog")
    due = datetime(2026, 2, 10, 9, 0)
    task = Task(
        description="Morning walk",
        duration=30,
        priority=Priority.HIGH,
        frequency="daily",
        allow_overlap=True,
        due_date=due,
    )
    pet.add_task(task)

    new_task = task.mark_complete()

    assert task.status == "completed"
    assert new_task is not None
    assert new_task in pet.tasks
    assert new_task is not task
    assert new_task.status == "pending"
    assert new_task.frequency == "daily"
    assert new_task.allow_overlap is True
    assert new_task.due_date == datetime(2026, 2, 11, 9, 0)


def test_mark_complete_weekly_creates_next_week_and_non_recurring_returns_none():
    weekly = Task(
        description="Weekly meds",
        duration=10,
        priority=Priority.HIGH,
        frequency="weekly",
        due_date=datetime(2026, 2, 1, 12, 0),
    )
    weekly_next = weekly.mark_complete()
    assert weekly_next is not None
    assert weekly_next.due_date == datetime(2026, 2, 8, 12, 0)

    once = Task(description="One-off", duration=10, priority=Priority.LOW, frequency="once")
    assert once.mark_complete() is None
    assert once.status == "completed"


def test_generate_schedule_without_owner_returns_empty_schedule_message():
    scheduler = Scheduler(owner=None)
    schedule = scheduler.generate_schedule()

    assert schedule["scheduled_tasks"] == []
    assert schedule["skipped_tasks"] == []
    assert schedule["total_time_used"] == 0
    assert schedule["explanation"] == "No owner specified for scheduling."


def test_generate_schedule_with_owner_but_no_tasks_returns_no_pending_message():
    owner = Owner(name="Alex")
    owner.add_pet(Pet(name="Buddy", age=4, type="Dog"))

    scheduler = Scheduler(owner=owner)
    schedule = scheduler.generate_schedule()

    assert schedule["scheduled_tasks"] == []
    assert schedule["skipped_tasks"] == []
    assert schedule["total_time_used"] == 0
    assert schedule["explanation"] == "No pending tasks to schedule."


def test_generate_schedule_honors_fixed_time_and_orders_chronologically():
    owner = Owner(name="Alex", available_time_minutes=240, preferences={"preferred_time_window": "morning"})
    pet = Pet(name="Buddy", age=4, type="Dog")
    owner.add_pet(pet)

    t1 = Task(description="Noon meal", duration=20, priority=Priority.HIGH, time="12:00")
    t2 = Task(description="Morning walk", duration=30, priority=Priority.HIGH, time="08:00")
    t3 = Task(description="Brush", duration=15, priority=Priority.MEDIUM)
    pet.add_task(t1)
    pet.add_task(t2)
    pet.add_task(t3)

    schedule = Scheduler(owner=owner).generate_schedule()

    starts = [item["start_time_minutes"] for item in schedule["scheduled_tasks"]]
    assert starts == sorted(starts)  # Sorting correctness: chronological output

    fixed_entry = next(item for item in schedule["scheduled_tasks"] if item["task"] is t2)
    assert fixed_entry["start_time_minutes"] == 8 * 60
    assert fixed_entry["time_range"].startswith("08:00")
    assert t1.status == "scheduled"
    assert t2.status == "scheduled"
    assert t3.status == "scheduled"


def test_generate_schedule_fixed_task_outside_preference_is_still_scheduled():
    owner = Owner(
        name="Alex",
        available_time_minutes=120,
        preferences={"preferred_time_window": "morning"},
    )
    pet = Pet(name="Whiskers", age=2, type="Cat")
    owner.add_pet(pet)

    late = Task(description="Late-night feed", duration=15, priority=Priority.HIGH, time="22:00")
    pet.add_task(late)

    schedule = Scheduler(owner=owner).generate_schedule()

    assert late in [item["task"] for item in schedule["scheduled_tasks"]]
    assert late not in [item["task"] for item in schedule["skipped_tasks"]]


def test_generate_schedule_skips_invalid_durations_and_insufficient_total_time():
    owner = Owner(name="Alex", available_time_minutes=20)
    pet = Pet(name="Buddy", age=5, type="Dog")
    owner.add_pet(pet)

    invalid = Task(description="Invalid", duration=0, priority=Priority.HIGH)
    too_long = Task(description="Too long", duration=30, priority=Priority.MEDIUM)
    pet.add_task(invalid)
    pet.add_task(too_long)

    schedule = Scheduler(owner=owner).generate_schedule()

    invalid_reason = next(
        item["reason"] for item in schedule["skipped_tasks"] if item["task"] is invalid
    )
    assert invalid_reason == "Task has no valid duration specified"
    assert invalid.status == "pending"  # current implementation does not set skipped here

    too_long_reason = next(
        item["reason"] for item in schedule["skipped_tasks"] if item["task"] is too_long
    )
    assert "Insufficient time remaining" in too_long_reason
    assert too_long.status == "skipped"


def test_generate_schedule_uses_fallback_window_when_preferred_window_has_no_slot():
    owner = Owner(name="Alex", available_time_minutes=390, preferences={"preferred_time_window": "evening"})
    pet = Pet(name="Buddy", age=5, type="Dog")
    owner.add_pet(pet)

    # Occupies 18:00-24:00 so there is no evening slot left for flexible tasks.
    block_evening = Task(description="Evening meds", duration=360, priority=Priority.HIGH, time="18:00")
    flexible = Task(description="Quick brush", duration=30, priority=Priority.MEDIUM)
    pet.add_task(block_evening)
    pet.add_task(flexible)

    schedule = Scheduler(owner=owner).generate_schedule()

    flexible_entry = next(item for item in schedule["scheduled_tasks"] if item["task"] is flexible)
    assert flexible_entry["start_time_minutes"] == 0


def test_generate_schedule_skips_when_no_contiguous_slot_even_if_total_free_time_exists():
    owner = Owner(name="Alex", available_time_minutes=2000)
    pet = Pet(name="Buddy", age=2, type="Dog")
    owner.add_pet(pet)

    # Four 30-minute gaps remain (120 total), but no 40-minute contiguous slot.
    pet.add_task(Task(description="A", duration=300, priority=Priority.HIGH, time="00:00"))  # 00:00-05:00
    pet.add_task(Task(description="B", duration=300, priority=Priority.HIGH, time="05:30"))  # 05:30-10:30
    pet.add_task(Task(description="C", duration=300, priority=Priority.HIGH, time="11:00"))  # 11:00-16:00
    pet.add_task(Task(description="D", duration=300, priority=Priority.HIGH, time="16:30"))  # 16:30-21:30
    pet.add_task(Task(description="E", duration=120, priority=Priority.HIGH, time="22:00"))  # 22:00-24:00
    target = Task(description="Needs 40", duration=40, priority=Priority.MEDIUM)
    pet.add_task(target)

    schedule = Scheduler(owner=owner).generate_schedule()

    assert target in [item["task"] for item in schedule["skipped_tasks"]]
    reason = next(item["reason"] for item in schedule["skipped_tasks"] if item["task"] is target)
    assert "Insufficient time remaining" in reason
    assert target.status == "skipped"


def test_scheduler_helper_methods_cover_defaults_and_time_conversion():
    scheduler = Scheduler(owner=Owner(name="Alex"))

    assert scheduler._calculate_total_available_time() == 480
    assert scheduler._get_start_time() == 480
    assert scheduler._format_time(65) == "01:05"
    assert scheduler._time_to_minutes("01:05") == 65
    assert scheduler._can_fit_task(Task(description="x", duration=10), 10)
    assert not scheduler._can_fit_task(Task(description="x", duration=None), 10)


def test_scheduler_get_start_time_handles_known_and_unknown_windows():
    owner = Owner(name="Alex", preferences={"preferred_time_window": "afternoon"})
    scheduler = Scheduler(owner=owner)
    assert scheduler._get_start_time() == 720

    owner.preferences["preferred_time_window"] = "unknown"
    assert scheduler._get_start_time() == 480


def test_sort_by_priority_orders_high_first_then_shorter_duration():
    scheduler = Scheduler(owner=Owner(name="Alex"))
    low = Task(description="low", duration=5, priority=Priority.LOW)
    high_long = Task(description="high long", duration=20, priority=Priority.HIGH)
    high_short = Task(description="high short", duration=10, priority=Priority.HIGH)

    ordered = scheduler._sort_tasks_by_priority([low, high_long, high_short])
    assert ordered == [high_short, high_long, low]


def test_sort_by_time_returns_chronological_then_none_times():
    scheduler = Scheduler(owner=Owner(name="Alex"))
    t1 = Task(description="late", duration=10, time="12:30")
    t2 = Task(description="early", duration=10, time="08:00")
    t3 = Task(description="unscheduled", duration=10, time=None)

    ordered = scheduler.sort_by_time([t1, t3, t2])
    assert ordered == [t2, t1, t3]


def test_filter_tasks_by_pet_name_and_status_case_insensitive():
    scheduler = Scheduler(owner=Owner(name="Alex"))
    dog = Pet(name="Buddy", age=2, type="Dog")
    cat = Pet(name="Milo", age=3, type="Cat")

    t1 = Task(description="Walk", duration=20, status="pending", pet=dog)
    t2 = Task(description="Feed", duration=10, status="completed", pet=dog)
    t3 = Task(description="Litter", duration=10, status="pending", pet=cat)

    tasks = [t1, t2, t3]
    assert scheduler.filter_tasks(tasks, pet_name="buddy") == [t1, t2]
    assert scheduler.filter_tasks(tasks, status="PENDING") == [t1, t3]
    assert scheduler.filter_tasks(tasks, pet_name="milo", status="pending") == [t3]


def test_conflict_detection_flags_duplicate_times_and_reports_message():
    owner = Owner(name="Alex")
    pet = Pet(name="Buddy", age=4, type="Dog")
    owner.add_pet(pet)

    task1 = Task(description="Walk", duration=30, priority=Priority.HIGH, time="08:00", pet=pet)
    task2 = Task(description="Feed", duration=15, priority=Priority.MEDIUM, time="08:00", pet=pet)

    conflicts = Scheduler(owner=owner).detect_conflicts([task1, task2])

    assert len(conflicts) == 1
    assert conflicts[0]["task1"] is task1
    assert conflicts[0]["task2"] is task2
    assert "CONFLICT" in conflicts[0]["message"]


def test_conflict_detection_allows_overlap_when_both_tasks_opt_in():
    scheduler = Scheduler(owner=Owner(name="Alex"))

    t1 = Task(description="Feed Cat 1", duration=10, time="08:00", allow_overlap=True)
    t2 = Task(description="Feed Cat 2", duration=10, time="08:00", allow_overlap=True)

    conflicts = scheduler.detect_conflicts([t1, t2])
    assert conflicts == []


def test_conflict_detection_still_flags_overlap_when_only_one_task_opts_in():
    scheduler = Scheduler(owner=Owner(name="Alex"))

    t1 = Task(description="Feed Cat 1", duration=10, time="08:00", allow_overlap=True)
    t2 = Task(description="Medication", duration=10, time="08:00", allow_overlap=False)

    conflicts = scheduler.detect_conflicts([t1, t2])
    assert len(conflicts) == 1


def test_conflict_detection_ignores_back_to_back_or_missing_time_duration():
    scheduler = Scheduler(owner=Owner(name="Alex"))

    t1 = Task(description="A", duration=30, time="08:00")
    t2 = Task(description="B", duration=30, time="08:30")  # touches boundary, no overlap
    t3 = Task(description="C", duration=None, time="08:15")
    t4 = Task(description="D", duration=20, time=None)

    conflicts = scheduler.detect_conflicts([t1, t2, t3, t4])
    assert conflicts == []


def test_generate_schedule_explanation_contains_owner_preference_and_summary_sections():
    owner = Owner(name="Alex", available_time_minutes=30, preferences={"preferred_time_window": "morning"})
    pet = Pet(name="Buddy", age=3, type="Dog")
    owner.add_pet(pet)

    pet.add_task(Task(description="Walk", duration=20, priority=Priority.HIGH))
    pet.add_task(Task(description="Big task", duration=50, priority=Priority.MEDIUM))

    schedule = Scheduler(owner=owner).generate_schedule()
    explanation = schedule["explanation"]

    assert "Schedule generated for Alex with 30min available time, starting in the morning." in explanation
    assert "Scheduled 1 task(s) using 20min total." in explanation
    assert "Skipped 1 task(s)" in explanation


def test_generate_schedule_can_place_compatible_flexible_tasks_at_the_same_time():
    owner = Owner(name="Alex", available_time_minutes=60, preferences={"preferred_time_window": "morning"})
    pet = Pet(name="Milo", age=2, type="Cat")
    owner.add_pet(pet)

    t1 = Task(description="Feed Cat 1", duration=30, priority=Priority.HIGH, allow_overlap=True)
    t2 = Task(description="Feed Cat 2", duration=30, priority=Priority.HIGH, allow_overlap=True)
    pet.add_task(t1)
    pet.add_task(t2)

    schedule = Scheduler(owner=owner).generate_schedule()

    scheduled = {item["task"].description: item["start_time_minutes"] for item in schedule["scheduled_tasks"]}
    assert scheduled["Feed Cat 1"] == 360
    assert scheduled["Feed Cat 2"] == 360
    assert schedule["total_time_used"] == 30


def test_generate_schedule_can_use_later_overlap_slot_when_budget_blocks_separate_slot():
    owner = Owner(name="Alex", available_time_minutes=30, preferences={"preferred_time_window": "morning"})
    pet = Pet(name="Milo", age=2, type="Cat")
    owner.add_pet(pet)

    t1 = Task(description="Feed Cat 1", duration=20, priority=Priority.HIGH, allow_overlap=True, time="09:00")
    t2 = Task(description="Feed Cat 2", duration=20, priority=Priority.MEDIUM, allow_overlap=True)
    pet.add_task(t1)
    pet.add_task(t2)

    schedule = Scheduler(owner=owner).generate_schedule()

    t2_entry = next(item for item in schedule["scheduled_tasks"] if item["task"] is t2)
    assert t2_entry["start_time_minutes"] == 9 * 60
    assert schedule["total_time_used"] == 20
