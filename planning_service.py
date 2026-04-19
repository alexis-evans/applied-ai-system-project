from __future__ import annotations

from dataclasses import dataclass
import logging
import time
import uuid
from typing import Any, Dict, Optional

from gemini_planner import (
    GeminiPlannerConfig,
    GeminiSchedulePlanner,
    PlannerConfigurationError,
    PlannerExecutionError,
)
from logging_config import configure_logging
from pawpal_system import Owner, Scheduler, Task
from schedule_validator import validate_schedule_plan


@dataclass
class PlanningServiceConfig:
    max_retries: int = 1

    @classmethod
    def from_env(cls) -> "PlanningServiceConfig":
        planner_config = GeminiPlannerConfig.from_env()
        return cls(max_retries=planner_config.max_retries)


class PlanningService:
    """Orchestrates AI planning, validation, retries, and deterministic fallback."""

    def __init__(
        self,
        planner: Optional[GeminiSchedulePlanner] = None,
        logger: Optional[logging.Logger] = None,
        config: Optional[PlanningServiceConfig] = None,
    ):
        self.planner = planner or GeminiSchedulePlanner()
        self.logger = logger or configure_logging()
        self.config = config or PlanningServiceConfig.from_env()

    def generate_schedule(self, owner: Owner) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        planning_payload = owner.to_planning_payload()
        self.logger.info("planner_started run_id=%s", run_id)
        trace = [
            {
                "step": "serialize_owner_state",
                "status": "completed",
                "detail": f"Prepared {len(planning_payload.get('tasks', []))} task(s) for planning.",
            }
        ]

        if not owner.get_all_tasks():
            schedule = Scheduler(owner=owner).generate_schedule()
            schedule["metadata"] = {
                "source": "fallback",
                "status": "No tasks were available for AI planning",
                "run_id": run_id,
                "attempts": 0,
                "confidence": 1.0,
            }
            schedule["validation"] = {
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "quality_score": 1.0,
            }
            schedule["trace"] = trace + [
                {
                    "step": "short_circuit_no_tasks",
                    "status": "completed",
                    "detail": "Returned deterministic scheduler output because there were no tasks to plan.",
                }
            ]
            return schedule

        last_validation = None
        last_error = None

        if self.planner.is_configured():
            trace.append(
                {
                    "step": "ai_planner_available",
                    "status": "completed",
                    "detail": "Gemini planner is configured; attempting AI schedule generation.",
                }
            )
            validation_errors = None
            for attempt in range(self.config.max_retries + 1):
                started_at = time.perf_counter()
                try:
                    trace.append(
                        {
                            "step": "generate_ai_plan",
                            "status": "in_progress",
                            "detail": f"Attempt {attempt + 1} started.",
                        }
                    )
                    proposed_plan = self.planner.generate_schedule_proposal(
                        planning_payload,
                        validation_errors=validation_errors,
                    )
                    validation = validate_schedule_plan(proposed_plan, owner)
                    last_validation = validation.to_dict()
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    self.logger.info(
                        "planner_response_received run_id=%s attempt=%s latency_ms=%s valid=%s",
                        run_id,
                        attempt,
                        duration_ms,
                        validation.is_valid,
                    )
                    if validation.is_valid:
                        accepted_schedule = self._accept_plan(owner, proposed_plan)
                        accepted_schedule["validation"] = last_validation
                        accepted_schedule["metadata"] = {
                            "source": "ai",
                            "status": "AI-generated schedule accepted",
                            "run_id": run_id,
                            "attempts": attempt + 1,
                            "confidence": last_validation["quality_score"],
                        }
                        trace[-1] = {
                            "step": "generate_ai_plan",
                            "status": "completed",
                            "detail": (
                                f"Attempt {attempt + 1} produced a valid plan "
                                f"(quality score {last_validation['quality_score']})."
                            ),
                        }
                        accepted_schedule["trace"] = trace + [
                            {
                                "step": "human_review_ready",
                                "status": "completed",
                                "detail": "Plan, confidence score, and validation warnings are available in the UI for review.",
                            }
                        ]
                        accepted_schedule["explanation"] = self._safe_explanation(
                            planning_payload,
                            accepted_schedule,
                            accepted_schedule["explanation"],
                            run_id,
                        )
                        return accepted_schedule

                    validation_errors = validation.errors
                    trace[-1] = {
                        "step": "generate_ai_plan",
                        "status": "completed",
                        "detail": (
                            f"Attempt {attempt + 1} failed validation with "
                            f"{len(validation.errors)} error(s); retrying with validator feedback."
                        ),
                    }
                    self.logger.warning(
                        "planner_validation_failed run_id=%s attempt=%s errors=%s",
                        run_id,
                        attempt,
                        validation.errors,
                    )
                except (PlannerConfigurationError, PlannerExecutionError) as exc:
                    last_error = str(exc)
                    trace[-1] = {
                        "step": "generate_ai_plan",
                        "status": "failed",
                        "detail": f"Attempt {attempt + 1} failed: {exc}",
                    }
                    self.logger.warning(
                        "planner_retry_failed run_id=%s attempt=%s error=%s",
                        run_id,
                        attempt,
                        exc,
                    )
                    break
                except Exception as exc:
                    last_error = str(exc)
                    trace[-1] = {
                        "step": "generate_ai_plan",
                        "status": "failed",
                        "detail": f"Attempt {attempt + 1} raised an unexpected error: {exc}",
                    }
                    self.logger.exception(
                        "planner_unexpected_failure run_id=%s attempt=%s", run_id, attempt
                    )
                    break
        else:
            last_error = "Gemini is not configured."
            trace.append(
                {
                    "step": "ai_planner_available",
                    "status": "failed",
                    "detail": last_error,
                }
            )

        fallback_schedule = Scheduler(owner=owner).generate_schedule()
        fallback_schedule["validation"] = last_validation or {
            "is_valid": False,
            "errors": [last_error] if last_error else [],
            "warnings": [],
            "quality_score": 0.0,
        }
        fallback_schedule["metadata"] = {
            "source": "fallback",
            "status": "AI planning failed, safe fallback scheduler used",
            "run_id": run_id,
            "attempts": 0 if not self.planner.is_configured() else self.config.max_retries + 1,
            "confidence": fallback_schedule["validation"]["quality_score"],
        }
        self.logger.info("planner_fallback_used run_id=%s reason=%s", run_id, last_error)
        fallback_schedule["trace"] = trace + [
            {
                "step": "fallback_scheduler",
                "status": "completed",
                "detail": "Deterministic scheduler generated the final schedule after AI planning was unavailable or invalid.",
            },
            {
                "step": "human_review_ready",
                "status": "completed",
                "detail": "Fallback result, validator feedback, and logs are available for review.",
            },
        ]
        fallback_schedule["explanation"] = self._safe_explanation(
            planning_payload,
            fallback_schedule,
            fallback_schedule["explanation"],
            run_id,
        )
        return fallback_schedule

    def _accept_plan(self, owner: Owner, plan: Dict[str, Any]) -> Dict[str, Any]:
        lookup = {task.task_id: task for task in owner.get_all_tasks()}

        for task in lookup.values():
            if task.status in {"scheduled", "skipped"}:
                task.change_status("pending")

        scheduled_tasks = []
        occupied_intervals = []
        for entry in plan.get("scheduled_tasks", []):
            task = lookup[entry["task_id"]]
            start_minutes = Scheduler(owner=owner)._time_to_minutes(entry["start_time"])
            end_minutes = Scheduler(owner=owner)._time_to_minutes(entry["end_time"])
            task.change_status("scheduled")
            scheduled_tasks.append(
                {
                    "task": task,
                    "pet_name": task.pet.name if task.pet else "unknown pet",
                    "start_time_minutes": start_minutes,
                    "end_time_minutes": end_minutes,
                    "time_range": f"{entry['start_time']} - {entry['end_time']}",
                    "reason": entry["reason"],
                }
            )
            occupied_intervals.append((start_minutes, end_minutes, task))

        skipped_tasks = []
        for entry in plan.get("skipped_tasks", []):
            task = lookup[entry["task_id"]]
            task.change_status("skipped")
            skipped_tasks.append(
                {
                    "task": task,
                    "reason": entry["reason"],
                }
            )

        scheduled_tasks.sort(key=lambda item: item["start_time_minutes"])
        return {
            "scheduled_tasks": scheduled_tasks,
            "skipped_tasks": skipped_tasks,
            "total_time_used": Scheduler(owner=owner)._calculate_occupied_time(occupied_intervals),
            "explanation": plan.get("summary", "AI-generated schedule."),
        }

    def _safe_explanation(
        self,
        planning_payload: Dict[str, Any],
        accepted_schedule: Dict[str, Any],
        fallback_text: str,
        run_id: str,
    ) -> str:
        if not self.planner.is_configured():
            return fallback_text
        try:
            explanation = self.planner.generate_schedule_explanation(
                planning_payload,
                self._explanation_payload(accepted_schedule),
            )
            self.logger.info("explanation_generated run_id=%s", run_id)
            return explanation or fallback_text
        except Exception as exc:
            self.logger.warning("explanation_failed run_id=%s error=%s", run_id, exc)
            return fallback_text

    def _explanation_payload(self, accepted_schedule: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "scheduled_tasks": [
                {
                    "task_id": item["task"].task_id,
                    "description": item["task"].description,
                    "pet_name": item["pet_name"],
                    "time_range": item["time_range"],
                    "reason": item["reason"],
                }
                for item in accepted_schedule.get("scheduled_tasks", [])
            ],
            "skipped_tasks": [
                {
                    "task_id": item["task"].task_id,
                    "description": item["task"].description,
                    "reason": item["reason"],
                }
                for item in accepted_schedule.get("skipped_tasks", [])
            ],
            "total_time_used": accepted_schedule.get("total_time_used", 0),
        }
