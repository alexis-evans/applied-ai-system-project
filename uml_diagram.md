```mermaid
flowchart TD
    UI[Streamlit UI]
    STATE[Owner / Pet / Task State]
    SERVICE[PlanningService]
    AI[GeminiSchedulePlanner]
    VALIDATOR[Schedule Validator]
    FALLBACK[Deterministic Scheduler]
    RESULT[Final Schedule + Explanation]
    REVIEW[Human Review]
    TESTS[Pytest + evaluate_pawpal.py]
    LOGS[Console + File Logs]

    UI --> STATE
    STATE --> SERVICE
    SERVICE --> AI
    AI --> VALIDATOR
    VALIDATOR -->|Valid| RESULT
    VALIDATOR -->|Invalid + retry| AI
    VALIDATOR -->|Invalid or unavailable| FALLBACK
    FALLBACK --> RESULT
    RESULT --> REVIEW
    SERVICE --> LOGS
    TESTS --> SERVICE
```

Short explanation:

- The user enters pets, tasks, time budget, and preferences in the Streamlit UI.
- `PlanningService` coordinates AI planning, validation, retry, fallback, and explanation generation.
- The validator acts as a guardrail before any AI proposal becomes the final schedule.
- Humans remain in the loop by reviewing the source, confidence, warnings, and final schedule in the UI.
