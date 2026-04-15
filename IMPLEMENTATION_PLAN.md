# PawPal+ Agentic AI Implementation Plan

## Goal

Upgrade PawPal+ from a deterministic heuristic scheduler into a hybrid AI system that:

- uses the Google Gemini API to propose schedules and explanations
- validates every generated schedule against hard business rules
- falls back safely when AI output is invalid or unavailable
- logs important actions and errors for debugging and reproducibility
- includes clear setup and testing instructions so another person can run it reliably

This plan is designed specifically for the current codebase, which already has:

- domain models and rule-based scheduling in `pawpal_system.py`
- a Streamlit interface in `app.py`
- automated tests in `tests/test_pawpal.py`

## Guiding Approach

Do not replace the current scheduler all at once.

Instead, keep the existing `Scheduler` as the safe baseline and add a new AI planning layer around it. The LLM should be responsible for proposing and explaining plans, while Python code remains responsible for:

- enforcing constraints
- catching malformed output
- scoring schedule quality
- deciding whether to retry or fall back

This creates an agentic workflow without trusting the model blindly.

## Current-State Assessment

The project already has a strong foundation:

- `Owner`, `Pet`, `Task`, and `Scheduler` form a clean domain model.
- The current scheduler already respects fixed-time tasks, time budgets, and priority ordering.
- The test suite already covers many core scheduling behaviors.
- The Streamlit app already captures the user inputs needed to build an AI planning payload.

The main gap is not scheduling logic itself. The main gap is the orchestration layer needed to safely integrate an LLM.

## Target Architecture

Refactor the project into these responsibilities:

### 1. Domain Layer

Keep the existing classes in `pawpal_system.py` or gradually split them into a dedicated module.

Responsibilities:

- represent owners, pets, tasks, and priorities
- preserve backward compatibility with current UI and tests
- provide serialization helpers for AI planning

Recommended additions:

- a helper to convert the current owner/task state into a plain JSON-safe dictionary
- optional dataclasses for schedule result objects

### 2. AI Planner Layer

Create a new module such as `gemini_planner.py`.

Responsibilities:

- call the Gemini API
- send owner/task constraints and PawPal-specific planning instructions
- request structured JSON output
- return a parsed schedule proposal

Recommended classes and methods:

- `GeminiPlannerConfig`
- `GeminiSchedulePlanner`
- `generate_schedule_proposal(owner: Owner) -> dict`
- `generate_schedule_explanation(owner: Owner, validated_plan: dict) -> str`

Important design choice:

- ask Gemini for structured schedule JSON first
- ask for natural-language explanation only after a schedule passes validation

### 3. Validation Layer

Create a new module such as `schedule_validator.py`.

Responsibilities:

- verify that AI output matches required schema and domain rules
- reject unsafe or low-quality schedules
- produce actionable errors for retries

Recommended functions:

- `validate_schedule_structure(plan, owner)`
- `validate_task_identity(plan, owner)`
- `validate_fixed_time_constraints(plan, owner)`
- `validate_total_time_budget(plan, owner)`
- `validate_overlap_rules(plan)`
- `validate_duration_integrity(plan, owner)`
- `score_schedule_quality(plan, owner)`

Expected output:

```python
{
    "is_valid": True,
    "errors": [],
    "warnings": ["Low-priority task scheduled before a medium-priority task."],
    "quality_score": 0.88,
}
```

### 4. Orchestration Layer

Create a small orchestration module such as `planning_service.py`.

Responsibilities:

- prepare input for the planner
- call Gemini
- validate the returned plan
- retry once or twice using validation feedback
- fall back to the deterministic scheduler if needed
- return a single schedule result shape to the UI

Recommended flow:

1. Build planning payload from the current `Owner`.
2. Ask Gemini for a structured plan.
3. Validate the plan.
4. If invalid, retry with validation errors.
5. If still invalid, call `Scheduler.generate_schedule()`.
6. Ask Gemini to explain the final accepted plan.
7. Return the plan, explanation, validation details, and metadata.

### 5. UI Layer

Update `app.py` to use the orchestration layer instead of calling the rule scheduler directly.

Responsibilities:

- collect user inputs
- display AI planning status
- show accepted schedule and explanation
- show fallback messages when AI planning fails
- expose validation warnings in a helpful way

## Recommended File Changes

### New Files

- `gemini_planner.py`
- `schedule_validator.py`
- `planning_service.py`
- `logging_config.py`
- `.env.example`
- `tests/test_schedule_validator.py`
- `tests/test_planning_service.py`

### Existing Files To Update

- `app.py`
- `pawpal_system.py`
- `requirements.txt`
- `README.md`

## Phase-by-Phase Implementation

## Phase 1: Prepare the Codebase for AI Integration

Objective:
Create a clean seam between the current scheduler and the future AI planner.

Tasks:

- keep the current `Scheduler.generate_schedule()` unchanged as a fallback path
- add serialization helpers for owner, pets, and tasks
- standardize the schedule result format so both planners return the same shape
- add a configuration object for runtime settings such as model name and retry count

Definition of done:

- the deterministic scheduler still works exactly as before
- the app can consume a shared schedule result format

## Phase 2: Add Gemini Explanation Generation First

Objective:
Use AI in the lowest-risk part of the system before handing it planning responsibilities.

Tasks:

- add a Gemini client wrapper
- generate a short explanation for the existing deterministic schedule
- handle API errors safely
- log request success, failure, and latency

Why this phase matters:

- it validates your Gemini integration
- it proves environment setup works
- it gives you a visible AI feature quickly without risking schedule correctness

Definition of done:

- schedule creation still uses the deterministic algorithm
- explanation comes from Gemini when the API is configured
- explanation falls back to the current text if the API fails

## Phase 3: Add Structured AI Schedule Proposal

Objective:
Let Gemini propose schedules in a strict machine-readable format.

Tasks:

- define a schedule schema
- request structured JSON from Gemini
- parse the response into Python data
- reject malformed or incomplete outputs immediately

Suggested schedule schema:

```json
{
  "scheduled_tasks": [
    {
      "task_description": "Morning walk",
      "pet_name": "Buddy",
      "start_time": "08:00",
      "end_time": "08:30",
      "reason": "High-priority exercise task in the preferred morning window."
    }
  ],
  "skipped_tasks": [
    {
      "task_description": "Grooming",
      "pet_name": "Buddy",
      "reason": "Insufficient time after higher-priority tasks."
    }
  ],
  "summary": "Morning essentials were prioritized first."
}
```

Prompt requirements:

- explicitly state all hard constraints
- tell the model not to invent tasks
- tell the model to preserve fixed times exactly
- tell the model to keep total time within the owner budget
- instruct the model to return only schema-compliant JSON

Definition of done:

- Gemini returns a parseable plan for straightforward cases
- invalid JSON is caught and handled without crashing the app

## Phase 4: Build Deterministic Validation and Quality Scoring

Objective:
Make correctness depend on code, not on the LLM.

Hard validation checks:

- every scheduled task maps to a real task in the input
- no required fields are missing
- every time value is valid `HH:MM`
- scheduled duration matches the original task duration
- fixed-time tasks keep their required start time
- total scheduled minutes do not exceed available time
- tasks do not overlap unless your rules explicitly allow it
- skipped tasks must include reasons

Quality checks:

- high-priority tasks are generally scheduled before low-priority tasks
- preferred time windows are respected when feasible
- avoid leaving large unnecessary idle gaps
- medication and feeding should be treated as especially important if your PawPal rules say so

Validation output should be detailed enough to feed back into a retry prompt.

Definition of done:

- the validator can accept, reject, and score schedules deterministically
- test cases exist for both valid and invalid plans

## Phase 5: Add Retry and Fallback Logic

Objective:
Make the system robust in real use.

Tasks:

- if validation fails, retry Gemini with the exact error list
- cap retries at a small number such as 1 or 2
- if retries fail, call the deterministic scheduler
- record whether the final result came from AI or fallback logic

Recommended user-facing statuses:

- `AI-generated schedule accepted`
- `AI schedule repaired after validation feedback`
- `AI planning failed, safe fallback scheduler used`

Definition of done:

- the app always returns a usable schedule
- AI failures no longer block the user

## Phase 6: Add Logging and Guardrails

Objective:
Make the system observable and safe to demo.

Tasks:

- configure Python logging for both console and optional file output
- assign a run id to each planning attempt
- log model name, retry count, validation outcome, and fallback reason
- avoid logging secrets such as API keys
- catch and log:
  - missing API key
  - timeout
  - malformed JSON
  - schema mismatch
  - unexpected exceptions

Recommended events:

- `planner_started`
- `planner_response_received`
- `planner_validation_failed`
- `planner_retry_started`
- `planner_fallback_used`
- `explanation_generated`

Definition of done:

- a reviewer can trace what the app attempted and why it accepted or rejected a plan

## Phase 7: Expand Testing

Objective:
Prove the AI path is reliable, not just the heuristic path.

Add these test categories:

### Unit Tests for Validation

- reject overlapping tasks
- reject impossible total durations
- reject moved fixed-time tasks
- reject unknown task references
- accept a valid structured plan

### Planner Contract Tests

- valid Gemini JSON parses correctly
- malformed responses are handled safely
- missing fields trigger validator errors

### Orchestration Tests

- valid AI plan is accepted
- invalid AI plan triggers retry
- repeated invalid output triggers fallback
- explanation generation failure does not break scheduling

### Regression Tests for Existing Behavior

Keep the current tests in `tests/test_pawpal.py` so the deterministic scheduler remains trustworthy as the fallback path.

Definition of done:

- `pytest` covers both deterministic and AI-assisted flows

## Phase 8: Improve Reproducibility and Setup

Objective:
Make the project easy for another person to run without guessing.

Tasks:

- add `google-genai` to `requirements.txt`
- add `python-dotenv` if you use `.env` loading
- create `.env.example`
- document exact setup in `README.md`
- state the supported Python version
- document fallback mode when no API key is configured
- provide commands for:
  - installing dependencies
  - running the Streamlit app
  - running tests

Recommended environment variables:

```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
PAWPAL_MAX_RETRIES=1
PAWPAL_LOG_LEVEL=INFO
```

Definition of done:

- another student or instructor can clone the repo, install dependencies, set an API key, and run the app successfully

## Fine-Tuning Strategy

For this project, treat fine-tuning as a later-stage option, not the first step.

Recommended order:

1. prompt engineering with hard constraints
2. structured output schema
3. few-shot examples using high-quality PawPal schedules
4. retrieval of similar examples
5. Vertex AI tuning only if the earlier steps are not enough

Important note:

Direct Gemini API fine-tuning is not the path to build around for this project. Current Google guidance points model tuning work toward Vertex AI rather than a straightforward public Gemini API fine-tuning workflow. For this reason, the practical way to make PawPal-specific behavior stronger is:

- create a small bank of approved schedule examples
- include them in prompts as few-shot demonstrations
- add deterministic validation so quality does not depend purely on the model

## PawPal-Specific Data Strategy

Create a small dataset of good schedules in JSON for future experimentation.

Suggested fields:

- owner available time
- preferred time window
- pet species and age
- task list with duration, priority, fixed time, and frequency
- accepted schedule
- skipped tasks with reasons
- explanation

Use this dataset for:

- few-shot prompting
- offline evaluation
- future tuning experiments if you later move to Vertex AI

## Acceptance Criteria

The AI-enhanced PawPal project is complete when:

- the app can generate a schedule through Gemini
- every AI-generated schedule is validated before display
- invalid schedules trigger retry or fallback
- explanations are clear and user-friendly
- logging captures planner actions and failures
- the README provides complete setup and run steps
- tests cover validation, orchestration, and fallback behavior
- the app still works even when Gemini is unavailable

## Suggested Implementation Order for This Repo

If you want the smoothest path, implement in this exact order:

1. add config and logging
2. add owner/task serialization helpers
3. integrate Gemini for explanation only
4. add structured schedule schema and parser
5. build deterministic validator
6. add retry and fallback orchestration
7. wire the new service into `app.py`
8. expand tests
9. update README and setup instructions

## Suggested Milestone Deliverables

### Milestone 1

- Gemini API connected
- explanation generation working
- setup documented

### Milestone 2

- AI schedule proposal working
- schema parsing implemented
- initial validator implemented

### Milestone 3

- retry and fallback flow implemented
- logging added
- tests expanded

### Milestone 4

- README finalized
- reproducibility verified from a fresh environment
- project ready for demo

## Notes for Demo and Writeup

When you present this project, emphasize that it is not "LLM replaces all logic."

The stronger systems story is:

- AI handles flexible reasoning and explanation
- code enforces safety and correctness
- tests verify reliability
- fallback behavior keeps the app usable

That framing makes the project sound much more mature and engineering-focused.
