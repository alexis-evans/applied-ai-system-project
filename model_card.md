# Model Card: PawPal+ AI Planning Component

## 1. Model Overview

**System name:** PawPal+ AI Pet Care Planner  
**Component documented here:** the AI planning component used by `PlanningService`  
**Primary model provider:** Google Gemini via the `google-genai` SDK  
**Default model name in this repo:** `gemini-2.5-flash`  
**Configuration source:** environment variables loaded from `.env`

PawPal+ is a hybrid scheduling system for pet care. It is not a standalone trained model hosted in this repository. Instead, the application uses an external Gemini model to propose a structured daily schedule, then validates that proposal against hard rules before accepting it. If the AI output is invalid or unavailable, the system falls back to a deterministic scheduler implemented in code.

Because of that architecture, this model card describes the role of the model inside the full system rather than claiming the repository contains or trains a custom model artifact.

## 2. Intended Use

The AI planner is intended to help generate a realistic daily pet-care schedule from owner preferences and task information such as:

- pet names and types
- task descriptions
- task durations
- task priorities
- fixed times for tasks like medication or meals
- overlap permissions
- owner time budget
- preferred time window such as morning, afternoon, or evening

The model is meant to support low-stakes planning assistance inside the PawPal+ app. It is most appropriate for:

- proposing an initial task ordering
- fitting flexible tasks around fixed-time obligations
- generating a short natural-language explanation of the final accepted plan

The model is **not** intended to:

- provide veterinary, medical, or emergency advice
- replace human judgment for safety-critical pet care decisions
- make unsupervised decisions without validation
- guarantee correctness on its own

## 3. Users and Stakeholders

Primary users include:

- pet owners using the Streamlit app
- the project author and reviewers evaluating the system
- developers testing orchestration, validation, and fallback behavior

Stakeholders affected by output quality include:

- pets receiving care
- pet owners relying on the schedule
- developers maintaining the system

## 4. Model Inputs and Outputs

### Inputs

The planner receives a serialized planning payload produced from the local application state. That payload includes:

- owner name
- available time in minutes
- owner preferences
- pets
- all current tasks

Each task may include:

- `task_id`
- description
- duration
- priority and priority name
- status
- frequency
- pet information
- fixed time
- overlap permission
- due date

If a previous AI attempt fails validation, the planner also receives validator error messages so it can attempt a repair on retry.

### Outputs

The planner is prompted to return strict JSON with this shape:

- `scheduled_tasks`
- `skipped_tasks`
- `summary`

Each scheduled task must include:

- `task_id`
- `start_time`
- `end_time`
- `reason`

Each skipped task must include:

- `task_id`
- `reason`

The accepted final system output shown to the user may also include:

- explanation text
- validation status
- validation errors and warnings
- confidence score
- plan source (`ai` or `fallback`)
- attempt count
- workflow trace

## 5. Decision Role in the System

The Gemini model is used as a **proposal generator**, not a final authority.

The full decision workflow is:

1. Serialize owner, pets, and tasks into a planning payload.
2. Ask Gemini for a structured schedule proposal.
3. Validate the proposal against hard rules.
4. Retry once with validation feedback if the first proposal is invalid.
5. Accept the plan only if validation passes.
6. Otherwise use the deterministic fallback scheduler.

This design reduces the risk of plausible-looking but incorrect schedules becoming final outputs.

## 6. Safety and Guardrails

Several safeguards are built around the model:

- Hard-rule validation checks every AI schedule before acceptance.
- Fixed-time tasks must remain at their exact specified time.
- Task durations cannot be changed by the model.
- Every pending task must be accounted for as either scheduled or skipped.
- Total scheduled time must stay within the owner's available-time budget.
- Overlaps are only allowed when all overlapping tasks explicitly allow overlap.
- If the AI output is invalid, the system retries with validator feedback.
- If AI planning still fails, the app uses a deterministic fallback scheduler.
- The UI exposes confidence, warnings, errors, and workflow trace for human review.

These guardrails mean the user never receives raw AI output as trusted final output without system checks.

## 7. Limitations

Important limitations of the current AI planning component include:

- The repository does not train or fine-tune a custom model.
- Output quality depends on the external Gemini model and API availability.
- The model may still produce invalid JSON, missing tasks, wrong fixed times, or bad task ordering.
- Validation enforces structural and scheduling constraints, but it does not understand all real-world pet-care nuance.
- The system does not infer veterinary urgency, medication interactions, or health risk from task text.
- The confidence score is rule-based and derived from validation results, not a calibrated probability of correctness.
- Preferred time windows are treated as soft preferences for warnings, not universal hard constraints.
- The app is designed for daily scheduling assistance, not long-term care management or clinical use.

## 8. Performance Characteristics

The planner is expected to do best when:

- tasks are clearly described
- durations are realistic
- fixed-time tasks are explicitly specified
- the daily task set is modest in size

The planner may perform worse when:

- task descriptions are vague
- many tasks compete for a small time budget
- there are many overlap edge cases
- user intent is underspecified
- the model returns malformed or incomplete JSON

## 9. Evaluation

This repository includes both automated tests and a small evaluation harness.

### Automated tests

The `tests/` directory covers domain logic, scheduling behavior, validation behavior, and planning-service orchestration.

### Evaluation harness

`evaluate_pawpal.py` defines three reproducible end-to-end style scenarios:

- valid AI plan accepted immediately
- invalid first draft repaired on retry
- invalid AI proposal rejected in favor of deterministic fallback

### Reported project results

According to the current project documentation in `README.md`, the reported local results are:

- `27/27` pytest tests passed
- `3/3` evaluation scenarios passed
- average confidence score: `0.93`

Those numbers describe this project snapshot and its local evaluation setup, not a broad benchmark across real-world users.

## 10. Ethical and Reliability Considerations

This system touches pet care, which can become safety-sensitive. For that reason:

- the model should be treated as assistive, not authoritative
- humans should review outputs before acting on them
- fixed obligations such as medication should be checked carefully
- suspicious or incomplete schedules should be rejected
- veterinary or emergency concerns should be handled by professionals, not by the app

The hybrid design reflects this stance by prioritizing validation and fallback over blind trust in the model.

## 11. Data and Privacy Considerations

The planner sends serialized task and pet-care context to an external model provider when Gemini is configured. That can include user-entered information such as:

- owner name
- pet names
- task descriptions
- due dates
- routine preferences

This repository does not implement a separate privacy layer beyond environment-based API configuration and normal application behavior. Users should avoid entering sensitive information they would not want sent to the configured model provider.

## 12. Operational Dependencies

The AI component depends on:

- `GEMINI_API_KEY`
- optional `GEMINI_MODEL`
- `google-genai`

Relevant environment variables in this project include:

- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `PAWPAL_MAX_RETRIES`
- `PAWPAL_LOG_LEVEL`
- `PAWPAL_LOG_FILE`

If `GEMINI_API_KEY` is missing, the application still functions by using the deterministic scheduler fallback instead of AI planning.

## 13. Maintenance Notes

This model card should be updated if any of the following change:

- the default model name or provider
- the validation rules
- retry behavior
- confidence calculation
- evaluation results
- privacy or logging behavior
- the system's intended use

## 14. Summary

PawPal+ uses Gemini as a constrained schedule-proposal model inside a larger reliability-focused system. The model helps generate structured pet-care plans and natural-language explanations, but validation, retry logic, human review, and deterministic fallback are the primary mechanisms that make the overall application safe and usable.
