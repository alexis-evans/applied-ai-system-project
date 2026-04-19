import streamlit as st
from datetime import datetime
from pawpal_system import Owner, Pet, Task, Scheduler, Priority
from planning_service import PlanningService

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency at runtime
    load_dotenv = None

if load_dotenv:
    load_dotenv()

st.set_page_config(
    page_title="PawPal+",
    page_icon="🐾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# Step 2: Initialize Session State (Application "Memory")
# ============================================================================
# st.session_state acts as a persistent dictionary that survives between reruns
# Check if owner exists, if not create a new one

if "owner" not in st.session_state:
    st.session_state.owner = Owner(
        name="",
        available_time_minutes=480,
        preferences={}
    )

if "current_pet" not in st.session_state:
    st.session_state.current_pet = None

if "schedule" not in st.session_state:
    st.session_state.schedule = None

if "edit_task_id" not in st.session_state:
    st.session_state.edit_task_id = None


def apply_app_theme():
    """Apply lightweight styling to improve readability and visual hierarchy."""
    st.markdown(
        """
        <style>
            .block-container {
                padding-top: 1.2rem;
                padding-bottom: 2rem;
            }
            .pawpal-hero {
                background: linear-gradient(120deg, #f0f9ff 0%, #fef9c3 100%);
                border: 1px solid #e2e8f0;
                border-radius: 14px;
                padding: 1.1rem 1.2rem;
                margin-bottom: 1rem;
            }
            .pawpal-hero h1 {
                margin: 0;
                font-size: 1.6rem;
                color: #0f172a;
            }
            .pawpal-hero p {
                margin: 0.4rem 0 0 0;
                color: #334155;
            }
            .pawpal-section {
                margin-top: 0.6rem;
                margin-bottom: 0.35rem;
                color: #0f172a;
                font-weight: 700;
                font-size: 1.1rem;
            }
            .pawpal-chip {
                display: inline-block;
                padding: 0.15rem 0.45rem;
                border-radius: 999px;
                background: #e0f2fe;
                color: #075985;
                font-size: 0.8rem;
                font-weight: 600;
                margin-right: 0.3rem;
            }
        </style>
        """,
        unsafe_allow_html=True
    )


def pet_label(pet: Pet) -> str:
    """Build a user-friendly label for pet selectors."""
    return f"{pet.name} ({pet.type}, age {pet.age})"


def priority_chip(priority_value: int) -> str:
    """Return a compact color-tagged priority label."""
    name = Priority(priority_value).name
    color_map = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#16a34a"}
    color = color_map[name]
    return (
        f'<span style="display:inline-block;padding:0.15rem 0.45rem;border-radius:999px;'
        f'background:{color}22;color:{color};font-size:0.8rem;font-weight:700;">{name}</span>'
    )


def status_chip(status: str) -> str:
    """Return a compact color-tagged status label."""
    color_map = {
        "pending": "#ca8a04",
        "scheduled": "#0284c7",
        "completed": "#16a34a",
        "skipped": "#64748b"
    }
    color = color_map.get(status, "#334155")
    return (
        f'<span style="display:inline-block;padding:0.15rem 0.45rem;border-radius:999px;'
        f'background:{color}22;color:{color};font-size:0.8rem;font-weight:700;text-transform:capitalize;">'
        f"{status}</span>"
    )


def parse_task_time(value: str):
    """Parse HH:MM input and return normalized time string or None if blank."""
    cleaned = value.strip()
    if not cleaned:
        return "", None

    if len(cleaned) == 5 and cleaned[2] == ":":
        try:
            hours, mins = map(int, cleaned.split(":"))
            if 0 <= hours < 24 and 0 <= mins < 60:
                return "", f"{hours:02d}:{mins:02d}"
        except ValueError:
            pass

    return "Invalid time format! Use HH:MM (e.g., 08:00)", None

# ============================================================================
# App Header
# ============================================================================
apply_app_theme()
st.markdown(
    """
    <div class="pawpal-hero">
      <h1>🐾 PawPal+ Pet Care Planner</h1>
      <p>Plan care tasks for your pets based on available time, priority, and your preferred routine.</p>
    </div>
    """,
    unsafe_allow_html=True
)

total_pets = len(st.session_state.owner.pets)
total_tasks = len(st.session_state.owner.get_all_tasks())
pending_tasks = len([t for t in st.session_state.owner.get_all_tasks() if t.status == "pending"])
quick_col1, quick_col2, quick_col3, quick_col4 = st.columns(4)
quick_col1.metric("Pets", total_pets)
quick_col2.metric("Total Tasks", total_tasks)
quick_col3.metric("Pending", pending_tasks)
quick_col4.metric("Available Time", f"{st.session_state.owner.available_time_minutes} min")

with st.sidebar:
    st.header("PawPal+ Guide")
    st.caption("1. Add pets\n2. Add tasks\n3. Generate schedule\n4. Complete recurring care")
    st.divider()
    st.caption("Tip: Fixed times (HH:MM) are always honored first.")
    st.caption("Tip: Flexible tasks are prioritized by priority, then by shorter duration.")


# ============================================================================
# Owner Information Section
# ============================================================================
st.markdown('<p class="pawpal-section">👤 Owner Information</p>', unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    owner_name = st.text_input(
        "Your Name",
        value=st.session_state.owner.name or "",
        help="Enter your name"
    )
    if owner_name != st.session_state.owner.name:
        st.session_state.owner.name = owner_name

with col2:
    available_hour_options = [x / 2 for x in range(1, 17)]  # 0.5 -> 8.0
    current_hours = max(0.5, min(8.0, st.session_state.owner.available_time_minutes / 60))
    default_idx = min(
        range(len(available_hour_options)),
        key=lambda i: abs(available_hour_options[i] - current_hours)
    )
    selected_hours = st.selectbox(
        "Available Time (hours)",
        available_hour_options,
        index=default_idx,
        format_func=lambda h: f"{h:g} hrs",
        help="How much time do you have available today?"
    )
    selected_minutes = int(selected_hours * 60)
    if selected_minutes != st.session_state.owner.available_time_minutes:
        st.session_state.owner.available_time_minutes = selected_minutes

# Time preferences
time_preference = st.selectbox(
    "Preferred Time Window",
    ["None", "morning", "afternoon", "evening"],
    help="When do you prefer to do tasks?"
)

if time_preference != "None":
    st.session_state.owner.preferences["preferred_time_window"] = time_preference
elif "preferred_time_window" in st.session_state.owner.preferences:
    del st.session_state.owner.preferences["preferred_time_window"]

st.divider()

# ============================================================================
# Pet Management Section
# ============================================================================
st.markdown('<p class="pawpal-section">🐕 Manage Pets</p>', unsafe_allow_html=True)

# Add new pet
with st.expander("➕ Add New Pet", expanded=len(st.session_state.owner.pets) == 0):
    selected_pet_type = st.selectbox(
        "Type",
        ["Dog", "Cat", "Bird", "Other"],
        key="new_pet_type"
    )

    with st.form("add_pet_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            new_pet_name = st.text_input("Pet Name", key="new_pet_name")
        with col2:
            new_pet_age = st.number_input("Age", min_value=0, max_value=30, value=1, key="new_pet_age")

        other_type = ""
        if selected_pet_type == "Other":
            other_type = st.text_input("Animal Type", key="new_pet_type_other", placeholder="e.g., Rabbit")

        add_pet_clicked = st.form_submit_button("Add Pet", type="primary")

    if add_pet_clicked:
        pet_name_clean = new_pet_name.strip()
        pet_type_value = other_type.strip() if selected_pet_type == "Other" else selected_pet_type

        if not pet_name_clean:
            st.error("Please enter a pet name")
        elif selected_pet_type == "Other" and not pet_type_value:
            st.error("Please enter the animal type")
        else:
            duplicate = any(
                pet.name
                and pet.type
                and pet.name.strip().lower() == pet_name_clean.lower()
                and pet.type.strip().lower() == pet_type_value.lower()
                for pet in st.session_state.owner.pets
            )
            if duplicate:
                st.warning(f"You already have a {pet_type_value.lower()} with the same name")
            else:
                new_pet = Pet(name=pet_name_clean, age=new_pet_age, type=pet_type_value)
                st.session_state.owner.add_pet(new_pet)
                st.success(f"✅ Added {pet_name_clean} to your pets!")
                st.rerun()

# Display existing pets
if st.session_state.owner.pets:
    st.subheader("Your Pets")
    for idx, pet in enumerate(st.session_state.owner.pets):
        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(
                f"**{pet.name}**  \n"
                f"`{pet.type}` · age `{pet.age}` · `{len(pet.tasks)}` task(s)"
            )
        with col2:
            if st.button("Remove", key=f"remove_pet_{idx}", help=f"Remove {pet.name}", use_container_width=True):
                st.session_state.owner.remove_pet(pet)
                st.rerun()
else:
    st.info("No pets added yet. Add your first pet above!")

st.divider()

# ============================================================================
# Task Management Section
# ============================================================================
st.markdown('<p class="pawpal-section">📋 Manage Tasks</p>', unsafe_allow_html=True)

# Select pet for task
if st.session_state.owner.pets:
    pet_options = {pet_label(p): p for p in st.session_state.owner.pets}
    selected_pet_key = st.selectbox(
        "Select Pet for Task",
        list(pet_options.keys()),
        help="Choose which pet this task is for"
    )
    selected_pet = pet_options[selected_pet_key]

    # Add new task
    with st.expander("➕ Add New Task", expanded=True):
        with st.form("add_task_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                task_desc = st.text_input(
                    "Task Description",
                    key="task_desc_input",
                    placeholder="e.g., Morning walk"
                )
                task_duration = st.number_input(
                    "Duration (minutes)",
                    min_value=1,
                    max_value=300,
                    value=30,
                    key="task_duration_input"
                )
                task_time = st.text_input(
                    "Scheduled Time (HH:MM)",
                    key="task_time_input",
                    placeholder="e.g., 08:00",
                    help="Optional - leave blank for unscheduled"
                )
                task_allow_overlap = st.checkbox(
                    "Allow simultaneous scheduling",
                    key="task_allow_overlap_input",
                    help="Use this when this task can happen at the same time as another task, like feeding two pets together."
                )
            with col2:
                task_priority = st.selectbox(
                    "Priority",
                    ["LOW", "MEDIUM", "HIGH"],
                    index=1,
                    key="task_priority_input"
                )
                task_frequency = st.selectbox(
                    "Frequency",
                    ["once", "daily", "weekly"],
                    key="task_frequency_input"
                )

            add_task_clicked = st.form_submit_button("Add Task", type="primary")

        if add_task_clicked:
            if task_desc:
                # Map priority string to Priority enum
                priority_map = {"LOW": Priority.LOW, "MEDIUM": Priority.MEDIUM, "HIGH": Priority.HIGH}

                # Validate time format if provided
                time_error, parsed_time = parse_task_time(task_time)
                if time_error:
                    st.error(time_error)
                elif task_time.strip() and parsed_time is None:
                    # Don't create task if time format is invalid
                    pass
                else:
                    new_task = Task(
                        description=task_desc.strip(),
                        duration=task_duration,
                        priority=priority_map[task_priority],
                        frequency=task_frequency,
                        time=parsed_time if parsed_time else None,
                        allow_overlap=task_allow_overlap,
                        due_date=datetime.now() if task_frequency in ["daily", "weekly"] else None
                    )
                    selected_pet.add_task(new_task)
                    st.success(f"✅ Added task '{task_desc.strip()}' for {selected_pet.name}!")
                    st.rerun()
            else:
                st.error("Please enter a task description")

    # Display tasks with filtering and sorting
    st.subheader("Current Tasks")

    # Create scheduler for filtering/sorting
    scheduler = Scheduler(owner=st.session_state.owner)
    all_tasks = st.session_state.owner.get_all_tasks()

    # Filter and Sort Controls
    col1, col2, col3 = st.columns(3)
    with col1:
        filter_pet_options = {"All Pets": None}
        for pet in st.session_state.owner.pets:
            filter_pet_options[pet_label(pet)] = pet
        filter_pet = st.selectbox(
            "Filter by Pet",
            list(filter_pet_options.keys()),
            key="filter_pet"
        )
    with col2:
        filter_status = st.selectbox(
            "Filter by Status",
            ["All Status", "pending", "scheduled", "completed", "skipped"],
            key="filter_status"
        )
    with col3:
        sort_by_time = st.checkbox("Sort by Time", value=False, key="sort_time")

    # Apply filters
    filtered_tasks = all_tasks
    if filter_pet != "All Pets":
        selected_filter_pet = filter_pet_options[filter_pet]
        filtered_tasks = scheduler.filter_tasks(filtered_tasks, pet_name=selected_filter_pet.name)
    if filter_status != "All Status":
        filtered_tasks = scheduler.filter_tasks(filtered_tasks, status=filter_status)

    # Apply sorting
    if sort_by_time:
        filtered_tasks = scheduler.sort_by_time(filtered_tasks)

    # Conflict Detection
    if all_tasks:
        conflicts = scheduler.detect_conflicts(all_tasks)
        if conflicts:
            st.warning(f"⚠️ **{len(conflicts)} Scheduling Conflict(s) Detected!**")
            st.caption("Only overlaps between tasks that have not both enabled simultaneous scheduling are flagged here.")
            with st.expander("View Conflicts", expanded=False):
                for conflict in conflicts:
                    st.error(conflict['message'])

    # Display filtered tasks
    if filtered_tasks:
        for idx, task in enumerate(filtered_tasks):
            pet_name = task.pet.name if task.pet else "No pet"
            time_str = f" 🕐 {task.time}" if task.time else ""
            overlap_str = " · simultaneous OK" if task.allow_overlap else ""
            task_id = id(task)

            with st.container():
                col1, col2, col3, col4, col5, col6, col7 = st.columns([3.3, 1.2, 1.2, 1.4, 1, 1, 1])
                with col1:
                    st.markdown(f"**{task.description}**  \n{pet_name}{time_str}{overlap_str}")
                with col2:
                    st.markdown(f"`{task.duration} min`")
                with col3:
                    st.markdown(priority_chip(task.priority), unsafe_allow_html=True)
                with col4:
                    st.markdown(status_chip(task.status), unsafe_allow_html=True)
                with col5:
                    # Mark complete button for recurring tasks
                    if task.frequency in ["daily", "weekly"] and task.status != "completed":
                        if st.button(
                            "Done",
                            key=f"complete_{pet_name}_{idx}",
                            help="Mark complete (auto-creates next)",
                            use_container_width=True
                        ):
                            new_task = task.mark_complete()
                            if new_task:
                                st.success(f"✅ Task completed! Created new task for next occurrence.")
                            st.rerun()
                with col6:
                    if st.button("Edit", key=f"edit_task_{pet_name}_{idx}", help="Edit task", use_container_width=True):
                        st.session_state.edit_task_id = task_id
                        st.rerun()
                with col7:
                    if st.button("Delete", key=f"remove_task_{pet_name}_{idx}", help="Remove task", use_container_width=True):
                        if task.pet:
                            task.pet.remove_task(task)
                        st.rerun()

                if st.session_state.edit_task_id == task_id:
                    st.caption("Edit task")
                    edit_pet_options = {
                        f"{pet.name} ({pet.type})": pet for pet in st.session_state.owner.pets
                    }
                    current_pet_label = next(
                        (
                            label
                            for label, pet_obj in edit_pet_options.items()
                            if pet_obj is task.pet
                        ),
                        next(iter(edit_pet_options.keys()))
                    )
                    edit_col1, edit_col2 = st.columns(2)
                    with edit_col1:
                        edit_desc = st.text_input(
                            "Description",
                            value=task.description or "",
                            key=f"edit_desc_{task_id}"
                        )
                        edit_duration = st.number_input(
                            "Duration (minutes)",
                            min_value=1,
                            max_value=300,
                            value=int(task.duration) if task.duration else 30,
                            key=f"edit_duration_{task_id}"
                        )
                        edit_time = st.text_input(
                            "Scheduled Time (HH:MM)",
                            value=task.time or "",
                            key=f"edit_time_{task_id}",
                            help="Optional - leave blank for unscheduled"
                        )
                        edit_allow_overlap = st.checkbox(
                            "Allow simultaneous scheduling",
                            value=task.allow_overlap,
                            key=f"edit_allow_overlap_{task_id}",
                            help="Use this when this task can happen at the same time as another task, like feeding two pets together."
                        )
                    with edit_col2:
                        edit_pet_label = st.selectbox(
                            "Pet",
                            list(edit_pet_options.keys()),
                            index=list(edit_pet_options.keys()).index(current_pet_label),
                            key=f"edit_pet_{task_id}"
                        )
                        edit_priority = st.selectbox(
                            "Priority",
                            ["LOW", "MEDIUM", "HIGH"],
                            index={Priority.LOW: 0, Priority.MEDIUM: 1, Priority.HIGH: 2}[Priority(task.priority)],
                            key=f"edit_priority_{task_id}"
                        )
                        edit_frequency = st.selectbox(
                            "Frequency",
                            ["once", "daily", "weekly"],
                            index=["once", "daily", "weekly"].index(task.frequency if task.frequency in ["once", "daily", "weekly"] else "once"),
                            key=f"edit_frequency_{task_id}"
                        )

                    save_col, cancel_col = st.columns(2)
                    with save_col:
                        if st.button("Save Changes", key=f"save_task_{task_id}", use_container_width=True):
                            time_error, parsed_time = parse_task_time(edit_time)
                            if time_error:
                                st.error(time_error)
                            elif not edit_desc.strip():
                                st.error("Please enter a task description")
                            else:
                                priority_map = {"LOW": Priority.LOW, "MEDIUM": Priority.MEDIUM, "HIGH": Priority.HIGH}
                                new_due_date = datetime.now() if edit_frequency in ["daily", "weekly"] else None
                                new_pet = edit_pet_options[edit_pet_label]
                                task.update_task(
                                    description=edit_desc.strip(),
                                    duration=edit_duration,
                                    priority=priority_map[edit_priority],
                                    frequency=edit_frequency,
                                    allow_overlap=edit_allow_overlap,
                                    time=parsed_time if parsed_time else None,
                                    due_date=new_due_date
                                )
                                if task.pet is not new_pet:
                                    if task.pet:
                                        task.pet.remove_task(task)
                                    new_pet.add_task(task)
                                st.session_state.edit_task_id = None
                                st.success("✅ Task updated")
                                st.rerun()
                    with cancel_col:
                        if st.button("Cancel", key=f"cancel_task_{task_id}", use_container_width=True):
                            st.session_state.edit_task_id = None
                            st.rerun()
                st.divider()
    else:
        st.info("No tasks match the current filters. Add tasks above!")

else:
    st.warning("⚠️ Please add at least one pet before adding tasks.")

st.divider()

# ============================================================================
# Schedule Generation Section
# ============================================================================
st.markdown('<p class="pawpal-section">📅 Generate Schedule</p>', unsafe_allow_html=True)
scheduler_for_schedule = Scheduler(owner=st.session_state.owner)
planning_service = PlanningService()

col1, col2 = st.columns([1, 3])
with col1:
    if st.button("Generate Schedule", type="primary", use_container_width=True):
        st.session_state.schedule = planning_service.generate_schedule(st.session_state.owner)

with col2:
    if st.button("Clear Schedule", use_container_width=True):
        st.session_state.schedule = None
        # Reset all task statuses to pending
        for pet in st.session_state.owner.pets:
            for task in pet.tasks:
                task.change_status("pending")
        st.rerun()

# Display schedule
if st.session_state.schedule:
    schedule = st.session_state.schedule
    metadata = schedule.get("metadata", {})
    validation = schedule.get("validation", {})
    trace = schedule.get("trace", [])

    if metadata.get("status"):
        if metadata.get("source") == "ai":
            st.success(metadata["status"])
        else:
            st.warning(metadata["status"])

    review_col1, review_col2, review_col3, review_col4 = st.columns(4)
    review_col1.metric("Plan Source", (metadata.get("source") or "unknown").upper())
    review_col2.metric("Attempts", metadata.get("attempts", 0))
    review_col3.metric("Confidence", f"{validation.get('quality_score', metadata.get('confidence', 0.0)):.2f}")
    review_col4.metric("Validation", "Pass" if validation.get("is_valid") else "Fallback")

    if metadata.get("run_id"):
        st.caption(f"Run ID: `{metadata['run_id']}`")

    if validation.get("errors"):
        with st.expander("Validation Errors", expanded=False):
            for error in validation["errors"]:
                st.caption(f"• {error}")

    if validation.get("warnings"):
        with st.expander("Validation Warnings", expanded=False):
            for warning in validation["warnings"]:
                st.caption(f"• {warning}")

    if trace:
        with st.expander("Agent Workflow Trace", expanded=False):
            for item in trace:
                st.markdown(
                    f"**{item.get('step', 'step')}** · `{item.get('status', 'unknown')}`  \n"
                    f"{item.get('detail', '')}"
                )

    st.caption(
        "Human review checkpoint: inspect the source, confidence, validator output, and workflow trace before trusting the plan."
    )

    # Explanation
    st.info(schedule["explanation"])

    # Scheduled tasks
    if schedule["scheduled_tasks"]:
        st.subheader("✅ Scheduled Tasks")
        st.caption(f"Total time: {schedule['total_time_used']} minutes")

        scheduled_task_objects = [entry["task"] for entry in schedule["scheduled_tasks"]]
        schedule_conflicts = scheduler_for_schedule.detect_conflicts(scheduled_task_objects)
        conflict_task_ids = {
            id(conflict["task1"]) for conflict in schedule_conflicts
        } | {
            id(conflict["task2"]) for conflict in schedule_conflicts
        }

        for i, scheduled_task in enumerate(schedule["scheduled_tasks"], 1):
            task = scheduled_task["task"]
            pet_name = scheduled_task.get("pet_name") or (task.pet.name if task.pet else "Unknown")
            is_completed = task.status == "completed"
            has_conflict = id(task) in conflict_task_ids

            with st.container():
                row_title = f"{i}. {task.description} ({pet_name})"
                if has_conflict:
                    row_title = f"{row_title} ⚠️"
                if is_completed:
                    row_title = f"~~{row_title}~~"
                st.markdown(row_title)

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    time_text = f"⏰ {scheduled_task['time_range']}"
                    st.markdown(f"~~{time_text}~~" if is_completed else time_text)
                with col2:
                    duration_text = f"⏱️ {task.duration} minutes"
                    st.markdown(f"~~{duration_text}~~" if is_completed else duration_text)
                with col3:
                    priority_text = f"🎯 {Priority(task.priority).name} priority"
                    st.markdown(f"~~{priority_text}~~" if is_completed else priority_text)
                with col4:
                    if not is_completed:
                        if st.button("✅ Complete", key=f"schedule_complete_{id(task)}", use_container_width=True):
                            if task.frequency in ["daily", "weekly"]:
                                task.mark_complete()
                            else:
                                task.change_status("completed")

                            if task.pet:
                                task.pet.remove_task(task)
                            st.rerun()

                reason_text = f"📝 {scheduled_task['reason']}"
                st.caption(f"~~{reason_text}~~" if is_completed else reason_text)
                st.divider()

    # Skipped tasks
    if schedule["skipped_tasks"]:
        st.subheader("⏭️ Skipped Tasks")
        for i, skipped in enumerate(schedule["skipped_tasks"], 1):
            task = skipped["task"]
            pet_name = task.pet.name if task.pet else "Unknown"
            st.markdown(f"**{i}. {task.description}** ({pet_name})")
            st.caption(f"❌ Reason: {skipped['reason']}")

    # Summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Scheduled", f"{len(schedule['scheduled_tasks'])} tasks")
    with col2:
        st.metric("Skipped", f"{len(schedule['skipped_tasks'])} tasks")
    with col3:
        st.metric("Time Used", f"{schedule['total_time_used']} / {st.session_state.owner.available_time_minutes} min")

else:
    st.info("👆 Click 'Generate Schedule' to create your daily pet care plan!")

# ============================================================================
# Footer
# ============================================================================
st.divider()
st.caption("🐾 PawPal+ - Built with Streamlit and Python")
