from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Dict, List, Optional


class PlannerConfigurationError(RuntimeError):
    """Raised when Gemini planning is not configured correctly."""


class PlannerExecutionError(RuntimeError):
    """Raised when Gemini planning fails during execution."""


@dataclass
class GeminiPlannerConfig:
    """Runtime configuration for Gemini-powered planning."""

    api_key: Optional[str]
    model: str = "gemini-2.5-flash"
    max_retries: int = 1

    @classmethod
    def from_env(cls) -> "GeminiPlannerConfig":
        return cls(
            api_key=os.getenv("GEMINI_API_KEY"),
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            max_retries=int(os.getenv("PAWPAL_MAX_RETRIES", "1")),
        )


class GeminiSchedulePlanner:
    """Wrapper around the Gemini API for schedule proposals and explanations."""

    def __init__(self, config: Optional[GeminiPlannerConfig] = None):
        self.config = config or GeminiPlannerConfig.from_env()

    def is_configured(self) -> bool:
        return bool(self.config.api_key)

    def generate_schedule_proposal(
        self,
        planning_payload: Dict[str, Any],
        validation_errors: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Ask Gemini for a structured schedule proposal."""
        if not self.is_configured():
            raise PlannerConfigurationError("GEMINI_API_KEY is not configured.")

        prompt = self._build_schedule_prompt(planning_payload, validation_errors)
        raw_text = self._generate_text(prompt, response_mime_type="application/json")

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise PlannerExecutionError("Gemini returned invalid JSON for schedule planning.") from exc

    def generate_schedule_explanation(
        self,
        planning_payload: Dict[str, Any],
        accepted_plan: Dict[str, Any],
    ) -> str:
        """Ask Gemini to explain an already-validated schedule."""
        if not self.is_configured():
            raise PlannerConfigurationError("GEMINI_API_KEY is not configured.")

        prompt = self._build_explanation_prompt(planning_payload, accepted_plan)
        return self._generate_text(prompt).strip()

    def _generate_text(self, prompt: str, response_mime_type: Optional[str] = None) -> str:
        """Generate text using the Gemini SDK."""
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise PlannerConfigurationError(
                "google-genai is not installed. Install dependencies from requirements.txt."
            ) from exc

        try:
            client = genai.Client(api_key=self.config.api_key)
            config = None
            if response_mime_type:
                config = types.GenerateContentConfig(response_mime_type=response_mime_type)

            response = client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            raise PlannerExecutionError(f"Gemini request failed: {exc}") from exc

        text = getattr(response, "text", None)
        if text:
            return text

        raise PlannerExecutionError("Gemini returned an empty response.")

    def _build_schedule_prompt(
        self,
        planning_payload: Dict[str, Any],
        validation_errors: Optional[List[str]] = None,
    ) -> str:
        repair_block = ""
        if validation_errors:
            repair_block = (
                "\nThe previous plan failed validation. Fix every issue below and return a corrected plan only:\n"
                + "\n".join(f"- {error}" for error in validation_errors)
                + "\n"
            )

        return f"""
You are PawPal+, a pet care scheduling planner.

Create a schedule that satisfies all hard constraints.

Hard constraints:
- Use only tasks from the provided task list.
- Reference tasks only by task_id.
- Keep fixed-time tasks at their exact provided time.
- Do not change task durations.
- Keep total scheduled minutes within available_time_minutes.
- Do not overlap scheduled tasks.
- Return JSON only.

Return exactly this JSON shape:
{{
  "scheduled_tasks": [
    {{
      "task_id": "string",
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "reason": "short explanation"
    }}
  ],
  "skipped_tasks": [
    {{
      "task_id": "string",
      "reason": "short explanation"
    }}
  ],
  "summary": "one short summary"
}}
{repair_block}
Planning payload:
{json.dumps(planning_payload, indent=2)}
""".strip()

    def _build_explanation_prompt(
        self,
        planning_payload: Dict[str, Any],
        accepted_plan: Dict[str, Any],
    ) -> str:
        return f"""
You are explaining a validated PawPal+ schedule to a pet owner.

Write a concise explanation in 3 to 5 sentences.
- Mention the most important priorities first.
- Mention skipped tasks only if any were skipped.
- Avoid inventing details that are not in the data.

Owner and task context:
{json.dumps(planning_payload, indent=2)}

Accepted schedule:
{json.dumps(accepted_plan, indent=2)}
""".strip()
