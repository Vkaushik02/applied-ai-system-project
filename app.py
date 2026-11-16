import streamlit as st
from ai_agent import api_key_available, apply_tasks, propose_tasks
from pawpal_system import Frequency, Owner, Pet, Scheduler, Task

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

if "owner" not in st.session_state:
    st.session_state.owner = Owner(name="Jordan")

owner = st.session_state.owner  # always use this reference afterward


st.title("🐾 PawPal+")

st.caption(
    "Plan daily care for your pets. Describe tasks in plain English and let the AI draft them, "
    "or add them by hand. AI suggestions are drafts: review them before confirming. "
    "Not for medical decisions."
)

st.subheader("📅 Today's Schedule")
scheduler = Scheduler(owner)
schedule = scheduler.get_daily_schedule()

for conflict in scheduler.detect_conflicts(schedule):
    names = ", ".join(f"{t.pet.name}: {t.description}" for t in conflict)
    st.warning(f"⚠️ Conflict at {conflict[0].time}: {names}")

if schedule:
    for i, task in enumerate(schedule):
        col1, col2 = st.columns([4, 1])
        col1.write(f"**{task.time}** — {task.pet.name}: {task.description} ({task.frequency.value})")
        if col2.button("Done", key=f"done_{i}_{id(task)}"):
            task.mark_complete()  # queues the next occurrence for daily/weekly tasks
            st.rerun()
else:
    st.info("Nothing scheduled for today.")

st.divider()

st.subheader("🐶 Your Pets")
if owner.pets:
    st.markdown(" · ".join(f"**{p.name}** ({p.species}, {p.age})" for p in owner.pets))
else:
    st.markdown("**No pets yet.** Add one below to get started.")

st.subheader("Add a Pet")
with st.form("add_pet_form", clear_on_submit=True):
    pet_name = st.text_input("Pet name")
    species = st.selectbox("Species", ["dog", "cat", "other"])
    age = st.number_input("Age", min_value=0, max_value=40, value=1)
    if st.form_submit_button("Add pet"):
        if pet_name.strip():
            owner.add_pet(Pet(name=pet_name.strip(), species=species, age=int(age)))
            st.toast(f"Added {pet_name.strip()}!", icon="✅")
            st.rerun()
        else:
            st.error("Pet name is required.")

st.subheader("✨ Describe your tasks (AI)")
with st.form("ai_form", clear_on_submit=True):
    ai_text = st.text_area("e.g. 'Buddy needs a walk every morning at 7:30 and Whiskers has meds at noon'")
    if st.form_submit_button("Plan with AI"):
        if not api_key_available():
            st.error("Set GEMINI_API_KEY in your .env file to use this feature.")
        else:
            with st.spinner("Asking Gemini..."):
                proposal = propose_tasks(owner, ai_text)
            st.session_state.ai_proposal = proposal["tasks"]
            st.session_state.ai_trace = proposal["trace"]
            st.rerun()

# Human-in-the-loop: nothing is added until the user confirms the AI's proposal.
if st.session_state.get("ai_proposal"):
    st.info("The AI proposes these tasks. Review them, then confirm or cancel:")
    for t in st.session_state.ai_proposal:
        st.write(f"- **{t.time}** {t._target_pet.name}: {t.description} ({t.frequency.value}, {t.due_date})")
    c1, c2 = st.columns(2)
    if c1.button("✅ Confirm and add"):
        with st.spinner("Adding tasks and checking for conflicts..."):
            result = apply_tasks(owner, st.session_state.ai_proposal, trace=st.session_state.get("ai_trace"))
        st.session_state.ai_trace = result["trace"]
        st.session_state.ai_proposal = []
        st.rerun()
    if c2.button("❌ Cancel"):
        st.session_state.ai_trace = st.session_state.get("ai_trace", []) + ["Cancelled by user; nothing added."]
        st.session_state.ai_proposal = []
        st.rerun()

if st.session_state.get("ai_trace"):
    with st.expander("Agent trace (plan / validate / act / check)", expanded=True):
        for line in st.session_state.ai_trace:
            st.write(line)

st.subheader("Schedule a Task")
if not owner.pets:
    st.info("Add a pet first.")
else:
    with st.form("add_task_form"):
        # select by index: st.selectbox returns a copy of object options, not the original
        pet_index = st.selectbox(
            "Pet", range(len(owner.pets)), format_func=lambda i: owner.pets[i].name
        )
        pet_choice = owner.pets[pet_index]
        description = st.text_input("Task description", value="Morning walk")
        task_time = st.time_input("Time")
        frequency = st.selectbox(
            "Frequency", list(Frequency), format_func=lambda f: f.value
        )
        due = st.date_input("Due date")
        if st.form_submit_button("Add task"):
            pet_choice.add_task(
                Task(
                    description=description,
                    time=task_time.strftime("%H:%M"),  # keeps string sorting chronological
                    frequency=frequency,
                    due_date=due,
                )
            )
            st.toast(f"Scheduled '{description}' for {pet_choice.name}.", icon="✅")
            st.rerun()
