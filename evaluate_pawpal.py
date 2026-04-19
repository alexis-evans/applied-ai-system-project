#!/usr/bin/env python3
"""Run reproducible evaluation scenarios for PawPal+."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from pawpal_system import Owner, Pet, Priority, Task
from planning_service import PlanningService, PlanningServiceConfig


class StubPlanner:
    """Simple stub planner used to evaluate integration behavior."""

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


@dataclass
class EvaluationCase:
    name: str
    description: str
    expected_source: str

    def build_owner(self) -> Owner:
        raise NotImplementedError

    def build_planner(self, owner: Owner):
        raise NotImplementedError

    def assert_result(self, result: Dict) -> bool:
        raise NotImplementedError


class ValidAIPlanCase(EvaluationCase):
    def build_owner(self) -> Owner:
        owner = Owner(name="Alex", available_time_minutes=60)
        pet = Pet(name="Buddy", age=4, type="Dog")
        owner.add_pet(pet)
        pet.add_task(Task(description="Walk", duration=30, priority=Priority.HIGH, time="08:00"))
        return owner

    def build_planner(self, owner: Owner):
        walk = owner.get_all_tasks()[0]
        return StubPlanner(
            proposals=[
                {
                    "scheduled_tasks": [
                        {
                            "task_id": walk.task_id,
                            "start_time": "08:00",
                            "end_time": "08:30",
                            "reason": "Fixed-time walk kept in place.",
                        }
                    ],
                    "skipped_tasks": [],
                    "summary": "Walk scheduled at the requested time.",
                }
            ],
            explanation="Buddy's fixed walk was preserved first.",
        )

    def assert_result(self, result: Dict) -> bool:
        return (
            result["metadata"]["source"] == "ai"
            and result["validation"]["is_valid"] is True
            and len(result["scheduled_tasks"]) == 1
        )


class RetryThenAcceptCase(EvaluationCase):
    def build_owner(self) -> Owner:
        owner = Owner(name="Jordan", available_time_minutes=90, preferences={"preferred_time_window": "morning"})
        pet = Pet(name="Milo", age=2, type="Cat")
        owner.add_pet(pet)
        pet.add_task(Task(description="Medication", duration=20, priority=Priority.HIGH, time="07:30"))
        pet.add_task(Task(description="Brush", duration=10, priority=Priority.MEDIUM))
        return owner

    def build_planner(self, owner: Owner):
        medication, brush = owner.get_all_tasks()
        return StubPlanner(
            proposals=[
                {
                    "scheduled_tasks": [
                        {
                            "task_id": medication.task_id,
                            "start_time": "08:00",
                            "end_time": "08:20",
                            "reason": "Incorrectly moved later.",
                        }
                    ],
                    "skipped_tasks": [
                        {
                            "task_id": brush.task_id,
                            "reason": "Not enough room.",
                        }
                    ],
                    "summary": "First attempt is invalid.",
                },
                {
                    "scheduled_tasks": [
                        {
                            "task_id": medication.task_id,
                            "start_time": "07:30",
                            "end_time": "07:50",
                            "reason": "Medication is fixed-time.",
                        },
                        {
                            "task_id": brush.task_id,
                            "start_time": "07:50",
                            "end_time": "08:00",
                            "reason": "Short flexible task fits after medication.",
                        },
                    ],
                    "skipped_tasks": [],
                    "summary": "Second attempt repaired with validator feedback.",
                },
            ],
            explanation="The validator corrected the first draft and the second plan passed.",
        )

    def assert_result(self, result: Dict) -> bool:
        return (
            result["metadata"]["source"] == "ai"
            and result["metadata"]["attempts"] == 2
            and result["validation"]["is_valid"] is True
        )


class FallbackCase(EvaluationCase):
    def build_owner(self) -> Owner:
        owner = Owner(name="Sam", available_time_minutes=30, preferences={"preferred_time_window": "morning"})
        pet = Pet(name="Nova", age=1, type="Dog")
        owner.add_pet(pet)
        pet.add_task(Task(description="Breakfast", duration=10, priority=Priority.HIGH, time="08:00"))
        pet.add_task(Task(description="Play", duration=15, priority=Priority.MEDIUM))
        return owner

    def build_planner(self, owner: Owner):
        breakfast, play = owner.get_all_tasks()
        return StubPlanner(
            proposals=[
                {
                    "scheduled_tasks": [
                        {
                            "task_id": breakfast.task_id,
                            "start_time": "09:00",
                            "end_time": "09:10",
                            "reason": "Moved incorrectly.",
                        }
                    ],
                    "skipped_tasks": [
                        {
                            "task_id": play.task_id,
                            "reason": "Skipped arbitrarily.",
                        }
                    ],
                    "summary": "Invalid proposal to force fallback.",
                }
            ],
            explanation="Fallback explanation",
        )

    def assert_result(self, result: Dict) -> bool:
        return (
            result["metadata"]["source"] == "fallback"
            and len(result["scheduled_tasks"]) >= 1
            and len(result.get("trace", [])) >= 2
        )


def run_case(case: EvaluationCase) -> Dict:
    owner = case.build_owner()
    planner = case.build_planner(owner)
    service = PlanningService(planner=planner, config=PlanningServiceConfig(max_retries=1))
    result = service.generate_schedule(owner)
    passed = case.assert_result(result)
    return {
        "name": case.name,
        "description": case.description,
        "passed": passed,
        "source": result["metadata"]["source"],
        "attempts": result["metadata"]["attempts"],
        "confidence": result["metadata"].get("confidence", result["validation"]["quality_score"]),
        "scheduled": len(result["scheduled_tasks"]),
        "skipped": len(result["skipped_tasks"]),
    }


def main() -> None:
    cases: List[EvaluationCase] = [
        ValidAIPlanCase(
            name="valid_ai_plan",
            description="Accept a valid AI schedule without fallback.",
            expected_source="ai",
        ),
        RetryThenAcceptCase(
            name="retry_then_accept",
            description="Use validator feedback to repair an invalid first attempt.",
            expected_source="ai",
        ),
        FallbackCase(
            name="fallback_on_invalid_ai",
            description="Reject invalid AI output and use the deterministic scheduler.",
            expected_source="fallback",
        ),
    ]

    results = [run_case(case) for case in cases]
    passed = sum(1 for result in results if result["passed"])
    average_confidence = sum(result["confidence"] for result in results) / len(results)

    print("PawPal+ Evaluation Harness")
    print("=" * 72)
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        print(
            f"[{status}] {result['name']}: source={result['source']}, attempts={result['attempts']}, "
            f"confidence={result['confidence']:.2f}, scheduled={result['scheduled']}, skipped={result['skipped']}"
        )
        print(f"      {result['description']}")

    print("-" * 72)
    print(
        f"Summary: {passed}/{len(results)} scenarios passed. "
        f"Average confidence score: {average_confidence:.2f}."
    )


if __name__ == "__main__":
    main()
