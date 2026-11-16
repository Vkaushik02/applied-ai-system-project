"""Agentic workflow: plan (LLM parses text) -> act (add tasks) -> check (resolve conflicts)."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from typing import Callable

from dotenv import load_dotenv

from pawpal_system import Frequency, Owner, Scheduler, Task

load_dotenv()  # read GEMINI_API_KEY from .env if present

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_INPUT_CHARS = 500
MAX_TASKS = 10
MAX_ROUNDS = 3

logging.basicConfig(
    filename="pawpal.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("pawpal.agent")

# An LLM is just a function (system_prompt, user_prompt) -> text, so tests can fake it.
LLM = Callable[[str, str], str]


def gemini_llm(system: str, user: str) -> str:
    """Call Gemini. Requires GEMINI_API_KEY in the environment."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=8000,  # thinking models spend tokens on reasoning first
            response_mime_type="application/json",
            http_options=types.HttpOptions(timeout=30000),  # fail fast instead of hanging
        ),
    )
    return resp.text or ""


def _extract_json(text: str):
    """Pull the first JSON array/object out of an LLM reply (it may add prose or fences)."""
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if not match:
        log.error("model reply had no JSON: %r", text[:500])
        raise ValueError("no JSON found in model reply")
    return json.loads(match.group(1))


def _valid_time(value: str) -> bool:
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except (ValueError, TypeError):
        return False


def validate_task(raw: dict, owner: Owner) -> tuple[Task | None, str | None]:
    """Guardrail: check one LLM-proposed task. Returns (Task, None) or (None, reason)."""
    pet = next(
        (p for p in owner.pets if p.name.lower() == str(raw.get("pet", "")).lower()), None
    )
    if pet is None:
        return None, f"unknown pet {raw.get('pet')!r}"
    if not _valid_time(raw.get("time")):
        return None, f"bad time {raw.get('time')!r} (need HH:MM)"
    try:
        freq = Frequency(str(raw.get("frequency", "once")).lower())
    except ValueError:
        return None, f"bad frequency {raw.get('frequency')!r}"
    try:
        due = date.fromisoformat(raw.get("due_date") or date.today().isoformat())
    except ValueError:
        return None, f"bad date {raw.get('due_date')!r}"
    desc = str(raw.get("description", "")).strip()
    if not desc:
        return None, "empty description"
    task = Task(description=desc, time=raw["time"], frequency=freq, due_date=due)
    task._target_pet = pet  # applied only when the task is committed
    return task, None


def propose_tasks(owner: Owner, text: str, llm: LLM = gemini_llm) -> dict:
    """PLAN + validate. Returns {'tasks': [...], 'trace': [...]}. Does NOT change the owner's pets."""
    trace: list[str] = []

    def note(msg: str) -> None:
        log.info(msg)
        trace.append(msg)

    text = text.strip()
    if not text:
        return {"tasks": [], "trace": ["Nothing to do: empty request."]}
    if len(text) > MAX_INPUT_CHARS:
        return {"tasks": [], "trace": [f"Request too long (max {MAX_INPUT_CHARS} chars)."]}
    if not owner.pets:
        return {"tasks": [], "trace": ["Add a pet first."]}

    # ---- PLAN: LLM turns free text into structured tasks
    pets = ", ".join(p.name for p in owner.pets)
    system = (
        "You convert pet-care requests into tasks. Reply with ONLY a JSON array of objects with keys: "
        'pet (one of: ' + pets + '), description, time ("HH:MM" 24-hour), '
        'frequency ("once"|"daily"|"weekly"), due_date ("YYYY-MM-DD"). '
        f"Today is {date.today().isoformat()}."
    )
    note(f"PLAN: asking model to parse: {text!r}")
    try:
        proposals = _extract_json(llm(system, text))
        if not isinstance(proposals, list):
            raise ValueError("expected a JSON array")
    except Exception as exc:  # network, auth, parse errors all end safely here
        log.exception("plan step failed")
        return {"tasks": [], "trace": trace + [f"PLAN failed: {exc}. No changes made."]}

    # ---- VALIDATE: guardrail check on every proposal (nothing is committed yet)
    tasks: list[Task] = []
    for raw in proposals[:MAX_TASKS]:
        task, err = validate_task(raw, owner) if isinstance(raw, dict) else (None, "not an object")
        if err:
            note(f"VALIDATE: rejected {raw!r}: {err}")
        else:
            tasks.append(task)
            note(f"VALIDATE: ok '{task.description}' for {task._target_pet.name} at {task.time}")
    return {"tasks": tasks, "trace": trace}


def apply_tasks(owner: Owner, tasks: list[Task], llm: LLM = gemini_llm, trace: list[str] | None = None) -> dict:
    """ACT + CHECK. Call only after the human approved `tasks`.
    Returns {'added': [...], 'conflicts': [...], 'trace': [...]}."""
    trace = list(trace or [])

    def note(msg: str) -> None:
        log.info(msg)
        trace.append(msg)

    if not tasks:
        return {"added": [], "conflicts": [], "trace": trace}

    added: list[Task] = []
    for task in tasks:
        task._target_pet.add_task(task)
        added.append(task)
        note(f"ACT: added '{task.description}' for {task.pet.name} at {task.time} ({task.frequency.value})")

    # ---- CHECK: resolve conflicts involving the new tasks, up to MAX_ROUNDS
    scheduler = Scheduler(owner)
    conflicts: list[list[Task]] = []
    for round_no in range(1, MAX_ROUNDS + 1):
        conflicts = scheduler.detect_conflicts(owner.get_all_tasks())
        conflicts = [g for g in conflicts if any(t in added for t in g)]
        if not conflicts:
            note(f"CHECK: no conflicts (round {round_no}).")
            break
        note(f"CHECK: {len(conflicts)} conflict(s) found (round {round_no}); asking model to reschedule.")
        movable = [t for g in conflicts for t in g if t in added][: MAX_TASKS]
        prompt = json.dumps(
            [{"id": i, "description": t.description, "pet": t.pet.name, "time": t.time,
              "date": t.due_date.isoformat()} for i, t in enumerate(movable)]
        )
        sys2 = (
            "These tasks clash with others at the same time. Pick a new nearby free time for each. "
            'Reply with ONLY a JSON array of {"id": int, "time": "HH:MM"}.'
        )
        try:
            for fix in _extract_json(llm(sys2, prompt)):
                idx, new_time = fix.get("id"), fix.get("time")
                if isinstance(idx, int) and 0 <= idx < len(movable) and _valid_time(new_time):
                    task = movable[idx]
                    note(f"CHECK: moved '{task.description}' ({task.pet.name}) {task.time} -> {new_time}")
                    task.reschedule(new_time)
                else:
                    note(f"CHECK: ignored invalid fix {fix!r}")
        except Exception as exc:
            log.exception("check step failed")
            note(f"CHECK failed: {exc}. Leaving conflicts for the user.")
            break
    else:
        note("CHECK: gave up after max rounds; conflicts remain.")

    conflicts = [g for g in scheduler.detect_conflicts(owner.get_all_tasks()) if any(t in added for t in g)]
    return {"added": added, "conflicts": conflicts, "trace": trace}


def run_agent(owner: Owner, text: str, llm: LLM = gemini_llm) -> dict:
    """Full pipeline with no human step (used by tests/scripts). The app uses propose_tasks,
    asks the user to confirm, then calls apply_tasks."""
    proposal = propose_tasks(owner, text, llm)
    return apply_tasks(owner, proposal["tasks"], llm, proposal["trace"])


def api_key_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))
