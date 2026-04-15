from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pawpal_system import Owner, Pet, Priority, Task
from planning_service import PlanningService, PlanningServiceConfig


class StubPlanner:
    def __init__(self, proposals, configured=True, explanation="AI explanation"):
        self.proposals = list(proposals)
        self.configured = configured
        self.explanation = explanation
        self.schedule_calls = 0

    def is_configured(self):
        return self.configured

    def generate_schedule_proposal(self, planning_payload, validation_errors=None):
        proposal = self.proposals[min(self.schedule_calls, len(self.proposals) - 1)]
        self.schedule_calls += 1
        return proposal

    def generate_schedule_explanation(self, planning_payload, accepted_plan):
        return self.explanation


def test_planning_service_accepts_valid_ai_plan():
    owner = Owner(name="Alex", available_time_minutes=60)
    pet = Pet(name="Buddy", age=4, type="Dog")
    owner.add_pet(pet)

    walk = Task(description="Walk", duration=30, priority=Priority.HIGH, time="08:00")
    pet.add_task(walk)

    planner = StubPlanner(
        proposals=[
            {
                "scheduled_tasks": [
                    {
                        "task_id": walk.task_id,
                        "start_time": "08:00",
                        "end_time": "08:30",
                        "reason": "Fixed-time walk.",
                    }
                ],
                "skipped_tasks": [],
                "summary": "Walk scheduled.",
            }
        ]
    )

    service = PlanningService(planner=planner, config=PlanningServiceConfig(max_retries=1))
    result = service.generate_schedule(owner)

    assert result["metadata"]["source"] == "ai"
    assert result["scheduled_tasks"][0]["task"] is walk
    assert result["explanation"] == "AI explanation"
    assert walk.status == "scheduled"


def test_planning_service_falls_back_after_invalid_ai_plan():
    owner = Owner(name="Alex", available_time_minutes=60, preferences={"preferred_time_window": "morning"})
    pet = Pet(name="Buddy", age=4, type="Dog")
    owner.add_pet(pet)

    walk = Task(description="Walk", duration=30, priority=Priority.HIGH, time="08:00")
    brush = Task(description="Brush", duration=10, priority=Priority.MEDIUM)
    pet.add_task(walk)
    pet.add_task(brush)

    invalid_plan = {
        "scheduled_tasks": [
            {
                "task_id": walk.task_id,
                "start_time": "09:00",
                "end_time": "09:30",
                "reason": "Invalid move.",
            }
        ],
        "skipped_tasks": [],
        "summary": "Bad plan.",
    }

    planner = StubPlanner(proposals=[invalid_plan], explanation="Fallback explanation")
    service = PlanningService(planner=planner, config=PlanningServiceConfig(max_retries=0))
    result = service.generate_schedule(owner)

    assert result["metadata"]["source"] == "fallback"
    assert result["scheduled_tasks"]
    assert any(item["task"] is walk for item in result["scheduled_tasks"])
    assert result["validation"]["is_valid"] is False


def test_planning_service_uses_fallback_when_planner_not_configured():
    owner = Owner(name="Alex", available_time_minutes=60)
    pet = Pet(name="Milo", age=2, type="Cat")
    owner.add_pet(pet)

    feed = Task(description="Feed", duration=10, priority=Priority.HIGH)
    pet.add_task(feed)

    planner = StubPlanner(proposals=[], configured=False)
    service = PlanningService(planner=planner, config=PlanningServiceConfig(max_retries=1))
    result = service.generate_schedule(owner)

    assert result["metadata"]["source"] == "fallback"
    assert result["scheduled_tasks"][0]["task"] is feed
