from dataclasses import dataclass, field
import uuid
from typing import Dict, List, Optional
from enum import IntEnum
from datetime import datetime, timedelta


class Priority(IntEnum):
    """Priority levels for tasks"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class Owner:
    """Manages multiple pets and provides access to all their tasks"""
    name: Optional[str] = None
    preferences: Dict = field(default_factory=dict)
    pets: List['Pet'] = field(default_factory=list)
    available_time_minutes: int = 480  # Default 8 hours per day

    def add_pet(self, pet: 'Pet') -> None:
        """Add a pet to this owner's list of pets"""
        if pet not in self.pets:
            self.pets.append(pet)
            pet.owner = self

    def remove_pet(self, pet: 'Pet') -> None:
        """Remove a pet from this owner's list of pets"""
        if pet in self.pets:
            self.pets.remove(pet)
            pet.owner = None

    def get_all_tasks(self, pet: Optional['Pet'] = None) -> List['Task']:
        """Get all tasks across all pets, or tasks for a specific pet if provided"""
        if pet is not None:
            # Return tasks for the specified pet only
            if pet in self.pets:
                return pet.tasks
            else:
                return []  # Pet not owned by this owner
        else:
            # Return all tasks from all pets
            all_tasks = []
            for pet in self.pets:
                all_tasks.extend(pet.tasks)
            return all_tasks

    def to_planning_payload(self) -> Dict:
        """Serialize the owner's current state into a JSON-safe payload for AI planning."""
        return {
            "owner_name": self.name or "",
            "available_time_minutes": self.available_time_minutes,
            "preferences": dict(self.preferences),
            "pets": [pet.to_dict() for pet in self.pets],
            "tasks": [task.to_planning_dict() for task in self.get_all_tasks()],
        }


@dataclass
class Pet:
    """Stores pet details and a list of tasks"""
    name: Optional[str] = None
    age: Optional[int] = None
    type: Optional[str] = None
    owner: Optional['Owner'] = None
    tasks: List['Task'] = field(default_factory=list)

    def add_task(self, task: 'Task') -> None:
        """Add a task to this pet's task list"""
        if task not in self.tasks:
            self.tasks.append(task)
            task.pet = self

    def remove_task(self, task: 'Task') -> None:
        """Remove a task from this pet's task list"""
        if task in self.tasks:
            self.tasks.remove(task)
            task.pet = None

    def get_pending_tasks(self) -> List['Task']:
        """Get all pending tasks for this pet"""
        return [task for task in self.tasks if task.status == "pending"]

    def to_dict(self) -> Dict:
        """Serialize this pet into a JSON-safe structure."""
        return {
            "name": self.name,
            "age": self.age,
            "type": self.type,
            "tasks": [task.to_planning_dict() for task in self.tasks],
        }


@dataclass
class Task:
    """Represents a single activity (description, time, frequency, completion status)"""
    description: Optional[str] = None
    duration: Optional[int] = None  # Duration in minutes
    priority: int = Priority.MEDIUM  # Use Priority enum
    status: str = "pending"  # pending, scheduled, completed, skipped
    frequency: str = "once"  # once, daily, weekly
    pet: Optional['Pet'] = None
    time: Optional[str] = None  # Scheduled time in "HH:MM" format (e.g., "09:30")
    due_date: Optional[datetime] = None  # Due date for recurring tasks
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def change_status(self, new_status: str) -> None:
        """Change the status of this task"""
        match new_status:
            case "completed":
                self.status = "completed"
            case "scheduled":
                self.status = "scheduled"
            case "skipped":
                self.status = "skipped"
            case "pending":
                self.status = "pending"
            case _:
                raise ValueError(f"Invalid status: {new_status}. Must be 'pending', 'scheduled', 'completed', or 'skipped'.")

    def update_task(self, description: Optional[str] = None,
                    duration: Optional[int] = None,
                    priority: Optional[int] = None,
                    frequency: Optional[str] = None,
                    time=...,
                    due_date=...) -> None:
        """Update task properties"""
        if description is not None:
            self.description = description
        if duration is not None:
            self.duration = duration
        if priority is not None:
            self.priority = priority
        if frequency is not None:
            self.frequency = frequency
        if time is not ...:
            self.time = time
        if due_date is not ...:
            self.due_date = due_date

    def mark_complete(self) -> Optional['Task']:
        """
        Mark this task as completed. If it's a recurring task (daily/weekly),
        automatically create and return a new task instance for the next occurrence.

        Returns:
            New task instance if recurring, None otherwise
        """
        self.change_status("completed")

        # Handle recurring tasks
        if self.frequency in ["daily", "weekly"]:
            # Calculate next due date
            current_due = self.due_date if self.due_date else datetime.now()

            if self.frequency == "daily":
                next_due_date = current_due + timedelta(days=1)
            else:  # weekly
                next_due_date = current_due + timedelta(weeks=1)

            # Create new task instance for next occurrence
            new_task = Task(
                description=self.description,
                duration=self.duration,
                priority=self.priority,
                status="pending",
                frequency=self.frequency,
                pet=self.pet,
                time=self.time,
                due_date=next_due_date
            )

            # Add to pet's task list if pet exists
            if self.pet:
                self.pet.add_task(new_task)

            return new_task

        return None

    def to_planning_dict(self) -> Dict:
        """Serialize this task into a JSON-safe structure for planning and validation."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "duration": self.duration,
            "priority": int(self.priority),
            "priority_name": Priority(self.priority).name,
            "status": self.status,
            "frequency": self.frequency,
            "pet_name": self.pet.name if self.pet else None,
            "pet_type": self.pet.type if self.pet else None,
            "time": self.time,
            "due_date": self.due_date.isoformat() if self.due_date else None,
        }


class Scheduler:
    """The 'Brain' that retrieves, organizes, and manages tasks across pets"""

    def __init__(self, owner: Optional[Owner] = None):
        """Initialize scheduler with an owner (and their pets)"""
        self.owner = owner

    def generate_schedule(self) -> Dict:
        """
        Generate a daily schedule based on owner's pets, tasks, and constraints.

        Returns a dictionary with:
        - scheduled_tasks: List of dicts with task, start_time, end_time, reason
        - skipped_tasks: List of dicts with task and reason
        - total_time_used: Total minutes scheduled
        - explanation: Human-readable explanation of the schedule
        """
        if not self.owner:
            return {
                "scheduled_tasks": [],
                "skipped_tasks": [],
                "total_time_used": 0,
                "explanation": "No owner specified for scheduling."
            }

        # Get all pending tasks from all pets
        all_tasks = []
        for pet in self.owner.pets:
            all_tasks.extend(pet.get_pending_tasks())

        if not all_tasks:
            return {
                "scheduled_tasks": [],
                "skipped_tasks": [],
                "total_time_used": 0,
                "explanation": "No pending tasks to schedule."
            }

        # Schedule tasks with a total-time budget.
        # Preferred time window is used as a starting preference for flexible tasks only.
        scheduled_tasks = []
        skipped_tasks = []
        preferred_start_time = self._get_start_time()
        available_time_minutes = self._calculate_total_available_time()
        remaining_time_minutes = available_time_minutes
        total_time_used = 0
        occupied_intervals = []  # Tuples of (start_minutes, end_minutes)
        day_end_time = 24 * 60

        # Handle fixed-time tasks first, so explicit user times are honored.
        fixed_time_tasks = [task for task in all_tasks if task.time is not None]
        flexible_tasks = [task for task in all_tasks if task.time is None]

        # Stable order: earlier time first, then higher priority.
        fixed_time_tasks = sorted(
            fixed_time_tasks,
            key=lambda t: (self._time_to_minutes(t.time), -t.priority)
        )

        for task in fixed_time_tasks:
            if task.duration is None or task.duration <= 0:
                skipped_tasks.append({
                    "task": task,
                    "reason": "Task has no valid duration specified"
                })
                continue

            if task.duration > remaining_time_minutes:
                skipped_tasks.append({
                    "task": task,
                    "reason": (
                        f"Insufficient total available time ({remaining_time_minutes}min remaining, "
                        f"{task.duration}min needed)"
                    )
                })
                task.change_status("skipped")
                continue

            task_start_time = self._time_to_minutes(task.time)
            task_end_time = task_start_time + task.duration

            priority_label = Priority(task.priority).name
            pet_name = task.pet.name if task.pet else "unknown pet"

            scheduled_tasks.append({
                "task": task,
                "pet_name": pet_name,
                "start_time_minutes": task_start_time,
                "end_time_minutes": task_end_time,
                "time_range": f"{self._format_time(task_start_time)} - {self._format_time(task_end_time)}",
                "reason": f"Fixed time: {task.time}, Priority: {priority_label}, Duration: {task.duration}min, Pet: {pet_name}"
            })

            occupied_intervals.append((task_start_time, task_end_time))
            occupied_intervals.sort(key=lambda interval: interval[0])
            remaining_time_minutes -= task.duration
            total_time_used += task.duration
            task.change_status("scheduled")

        # Schedule flexible tasks by priority in remaining gaps.
        sorted_flexible_tasks = self._sort_tasks_by_priority(flexible_tasks)

        for task in sorted_flexible_tasks:
            if task.duration is None or task.duration <= 0:
                skipped_tasks.append({
                    "task": task,
                    "reason": "Task has no valid duration specified"
                })
                continue

            if task.duration > remaining_time_minutes:
                skipped_tasks.append({
                    "task": task,
                    "reason": (
                        f"Insufficient total available time ({remaining_time_minutes}min remaining, "
                        f"{task.duration}min needed)"
                    )
                })
                task.change_status("skipped")
                continue

            task_start_time = self._find_available_slot(
                task.duration,
                occupied_intervals,
                preferred_start_time,
                day_end_time
            )

            # If no slot exists in preferred window onward, try earlier times too.
            if task_start_time is None and preferred_start_time > 0:
                task_start_time = self._find_available_slot(
                    task.duration,
                    occupied_intervals,
                    0,
                    preferred_start_time
                )

            if task_start_time is not None:
                task_end_time = task_start_time + task.duration

                priority_label = Priority(task.priority).name
                pet_name = task.pet.name if task.pet else "unknown pet"

                scheduled_tasks.append({
                    "task": task,
                    "pet_name": pet_name,
                    "start_time_minutes": task_start_time,
                    "end_time_minutes": task_end_time,
                    "time_range": f"{self._format_time(task_start_time)} - {self._format_time(task_end_time)}",
                    "reason": f"Priority: {priority_label}, Duration: {task.duration}min, Pet: {pet_name}"
                })

                occupied_intervals.append((task_start_time, task_end_time))
                occupied_intervals.sort(key=lambda interval: interval[0])
                remaining_time_minutes -= task.duration
                total_time_used += task.duration
                task.change_status("scheduled")
            else:
                remaining = self._calculate_free_time(
                    occupied_intervals, 0, day_end_time
                )
                skipped_tasks.append({
                    "task": task,
                    "reason": (
                        f"Insufficient time remaining ({remaining}min available, {task.duration}min needed)"
                    )
                })
                task.change_status("skipped")

        # Keep output consistently ordered by actual start time.
        scheduled_tasks.sort(key=lambda item: item["start_time_minutes"])

        # Generate explanation
        explanation = self._generate_explanation(
            scheduled_tasks, skipped_tasks, available_time_minutes, total_time_used
        )

        return {
            "scheduled_tasks": scheduled_tasks,
            "skipped_tasks": skipped_tasks,
            "total_time_used": total_time_used,
            "explanation": explanation
        }

    def _calculate_total_available_time(self) -> int:
        """Calculate total available time from owner"""
        if self.owner:
            return self.owner.available_time_minutes
        return 480  # Default 8 hours

    def _get_start_time(self) -> int:
        """Get start time based on owner preferences (morning/afternoon/evening)"""
        if not self.owner or not self.owner.preferences:
            return 480  # Default to 8:00 AM

        # Check for preferred_time_window preference
        time_window = self.owner.preferences.get("preferred_time_window", "").lower()

        # Define time windows (in minutes from midnight)
        time_windows = {
            "morning": 360,     # 6:00 AM
            "afternoon": 720,   # 12:00 PM (noon)
            "evening": 1080     # 6:00 PM
        }

        # Return the start time for the preferred window, or 8:00 AM if not found
        return time_windows.get(time_window, 480)

    def _sort_tasks_by_priority(self, tasks: List[Task]) -> List[Task]:
        """Sort tasks by priority (HIGH to LOW), then by duration (shorter first)"""
        return sorted(tasks, key=lambda t: (-t.priority, t.duration if t.duration else 0))

    def _can_fit_task(self, task: Task, remaining_time: int) -> bool:
        """Check if a task can fit in the remaining available time"""
        if task.duration is None:
            return False
        return task.duration <= remaining_time

    def _format_time(self, minutes: int) -> str:
        """Convert minutes from start of day to HH:MM format"""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"

    def _time_to_minutes(self, time_str: str) -> int:
        """Convert a time string in HH:MM format to minutes from midnight."""
        hours, minutes = map(int, time_str.split(":"))
        return hours * 60 + minutes

    def _find_available_slot(self, duration: int, intervals: List[tuple],
                             window_start: int, window_end: int) -> Optional[int]:
        """Find earliest available slot of `duration` in [window_start, window_end)."""
        cursor = window_start

        for start, end in sorted(intervals, key=lambda interval: interval[0]):
            if cursor + duration <= start:
                return cursor
            if end > cursor:
                cursor = end

        if cursor + duration <= window_end:
            return cursor

        return None

    def _calculate_free_time(self, intervals: List[tuple], window_start: int, window_end: int) -> int:
        """Calculate total free minutes in the scheduling window."""
        occupied_time = 0
        for start, end in intervals:
            clamped_start = max(start, window_start)
            clamped_end = min(end, window_end)
            if clamped_start < clamped_end:
                occupied_time += (clamped_end - clamped_start)
        return max(0, (window_end - window_start) - occupied_time)

    def _generate_explanation(self, scheduled_tasks: List[Dict],
                            skipped_tasks: List[Dict],
                            available_time: int,
                            time_used: int) -> str:
        """Generate a human-readable explanation of the schedule"""
        explanation_parts = []

        # Base explanation with time preference if set
        base_explanation = f"Schedule generated for {self.owner.name if self.owner.name else 'pet owner'} "
        base_explanation += f"with {available_time}min available time"

        # Add time preference if specified
        if self.owner and self.owner.preferences:
            time_window = self.owner.preferences.get("preferred_time_window")
            if time_window:
                base_explanation += f", starting in the {time_window}"

        base_explanation += "."
        explanation_parts.append(base_explanation)

        if scheduled_tasks:
            explanation_parts.append(
                f"\nScheduled {len(scheduled_tasks)} task(s) using {time_used}min total. "
                f"Tasks were prioritized by importance (HIGH > MEDIUM > LOW) and then by duration."
            )

        if skipped_tasks:
            explanation_parts.append(
                f"\nSkipped {len(skipped_tasks)} task(s) due to time constraints or missing information."
            )

        return " ".join(explanation_parts)

    def sort_by_time(self, tasks: List[Task]) -> List[Task]:
        """
        Sort tasks by their scheduled time in "HH:MM" format.
        Tasks without a time are placed at the end.

        Args:
            tasks: List of Task objects to sort

        Returns:
            Sorted list of tasks by time
        """
        # Separate tasks with and without time
        tasks_with_time = [t for t in tasks if t.time is not None]
        tasks_without_time = [t for t in tasks if t.time is None]

        # Sort tasks with time using lambda to compare time strings
        sorted_with_time = sorted(tasks_with_time, key=lambda t: t.time)

        # Return sorted tasks with time first, then tasks without time
        return sorted_with_time + tasks_without_time

    def filter_tasks(self, tasks: List[Task], pet_name: Optional[str] = None,
                    status: Optional[str] = None) -> List[Task]:
        """
        Filter tasks by pet name and/or completion status.

        Args:
            tasks: List of Task objects to filter
            pet_name: Filter by pet name (case-insensitive). None means no filter.
            status: Filter by status ("pending", "scheduled", "completed", "skipped"). None means no filter.

        Returns:
            Filtered list of tasks
        """
        filtered = tasks

        # Filter by pet name if specified
        if pet_name is not None:
            filtered = [t for t in filtered if t.pet and t.pet.name.lower() == pet_name.lower()]

        # Filter by status if specified
        if status is not None:
            filtered = [t for t in filtered if t.status == status.lower()]

        return filtered

    def detect_conflicts(self, tasks: List[Task]) -> List[Dict]:
        """
        Detect if any tasks have conflicting scheduled times.
        A conflict occurs when two tasks have overlapping time windows.

        Args:
            tasks: List of Task objects to check for conflicts

        Returns:
            List of conflict dictionaries with 'task1', 'task2', and 'message'
        """
        conflicts = []

        # Only check tasks that have both time and duration set
        tasks_with_time = [t for t in tasks if t.time is not None and t.duration is not None]

        # Helper function to convert "HH:MM" to minutes from midnight
        def time_to_minutes(time_str: str) -> int:
            hours, minutes = map(int, time_str.split(':'))
            return hours * 60 + minutes

        # Check each pair of tasks for overlap
        for i in range(len(tasks_with_time)):
            for j in range(i + 1, len(tasks_with_time)):
                task1 = tasks_with_time[i]
                task2 = tasks_with_time[j]

                # Calculate start and end times in minutes
                task1_start = time_to_minutes(task1.time)
                task1_end = task1_start + task1.duration

                task2_start = time_to_minutes(task2.time)
                task2_end = task2_start + task2.duration

                # Check for overlap: tasks overlap if one starts before the other ends
                if task1_start < task2_end and task2_start < task1_end:
                    pet1_name = task1.pet.name if task1.pet else "Unknown"
                    pet2_name = task2.pet.name if task2.pet else "Unknown"

                    conflict_message = (
                        f"⚠️ CONFLICT: '{task1.description}' ({pet1_name}) at {task1.time} "
                        f"overlaps with '{task2.description}' ({pet2_name}) at {task2.time}"
                    )

                    conflicts.append({
                        'task1': task1,
                        'task2': task2,
                        'message': conflict_message
                    })

        return conflicts
