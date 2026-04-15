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

        if not owner.get_all_tasks():
            return Scheduler(owner=owner).generate_schedule()

        last_validation = None
        last_error = None

        if self.planner.is_configured():
            validation_errors = None
            for attempt in range(self.config.max_retries + 1):
                started_at = time.perf_counter()
                try:
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
                        }
                        accepted_schedule["explanation"] = self._safe_explanation(
                            planning_payload,
                            accepted_schedule,
                            accepted_schedule["explanation"],
                            run_id,
                        )
                        return accepted_schedule

                    validation_errors = validation.errors
                    self.logger.warning(
                        "planner_validation_failed run_id=%s attempt=%s errors=%s",
                        run_id,
                        attempt,
                        validation.errors,
                    )
                except (PlannerConfigurationError, PlannerExecutionError) as exc:
                    last_error = str(exc)
                    self.logger.warning(
                        "planner_retry_failed run_id=%s attempt=%s error=%s",
                        run_id,
                        attempt,
                        exc,
                    )
                    break
                except Exception as exc:
                    last_error = str(exc)
                    self.logger.exception(
                        "planner_unexpected_failure run_id=%s attempt=%s", run_id, attempt
                    )
                    break
        else:
            last_error = "Gemini is not configured."

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
        }
        self.logger.info("planner_fallback_used run_id=%s reason=%s", run_id, last_error)
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
        total_time_used = 0
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
            total_time_used += task.duration or 0

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
            "total_time_used": total_time_used,
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
