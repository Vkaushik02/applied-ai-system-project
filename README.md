# PawPal+ AI Planner

## Original Project

This project extends **PawPal+** (Modules 2), a Streamlit app that helps a pet owner stay consistent with pet care. The original app let an owner add pets and schedule care tasks (walks, feeding, meds) through forms. Its scheduler sorted tasks chronologically, handled daily and weekly recurring tasks, and warned about tasks that shared the same time slot. It had no AI: every task was entered by hand and every conflict was fixed by hand.

## Summary

**PawPal+ AI Planner** adds an AI assistant on top of that scheduler. Instead of filling in a form per task, the owner types a sentence such as *"Buddy needs a walk at 7:30 and Whiskers has meds at noon"*. An AI agent (Google Gemini) turns it into structured tasks, the owner reviews and confirms them, and the agent then checks for time conflicts and moves clashing tasks itself.

It matters because describing a routine in plain language is faster than filling in a form for each task. Because the AI's output is validated and approved by a person before it changes anything, it saves typing without being trusted blindly.

## Architecture Overview

The AI feature is an **agentic workflow** (plan, act, check) with a human approval step. The full diagram is in [diagrams/system_diagram.mmd](diagrams/system_diagram.mmd).


Data flows in three stages:

1. **Plan** (`propose_tasks` in [ai_agent.py](ai_agent.py)): Input guardrails reject empty, over-long, or pet-less requests. Gemini converts the text to JSON tasks. A validator then checks each one (pet exists, `HH:MM` time, valid frequency and date) and drops invalid tasks. Nothing is changed yet.
2. **Human review** ([app.py](app.py)): The user sees the proposed tasks and clicks **Confirm** or **Cancel**. Only confirmed tasks continue.
3. **Act and check** (`apply_tasks`): Confirmed tasks are added through the existing `Owner`/`Pet`/`Task` classes. The existing `Scheduler.detect_conflicts` runs. If new tasks clash, Gemini suggests new times, which are validated and applied, and the check repeats (at most 3 rounds). Any remaining conflicts are shown to the user as warnings.

Every step is logged to `pawpal.log`, and the Streamlit UI shows an expandable **agent trace** of what happened.

The original scheduling logic is unchanged and lives in [pawpal_system.py](pawpal_system.py):

| Feature | Method(s) | Notes |
|---------|-----------|-------|
| Task sorting | `Scheduler.sort_by_time` | Orders tasks by their `HH:MM` time. Zero-padded 24-hour strings sort chronologically. |
| Filtering | `Scheduler.get_daily_schedule`, `Scheduler.filter_by_status` | Today's schedule shows only incomplete tasks due today. |
| Conflict handling | `Scheduler.detect_conflicts` | Groups tasks by exact `(due_date, time)` and returns groups with more than one task. It does not detect partial overlaps because tasks have no duration. |
| Recurring tasks | `Task.mark_complete`, `Frequency` | Completing a daily or weekly task creates the next occurrence (+1 or +7 days). |

## Setup Instructions

You need Python 3.10+ and a free Gemini API key from [Google AI Studio](https://aistudio.google.com/).

1. **Clone the repo and open the project folder.**

   ```bash
   cd applied-ai-system-project
   ```

2. **Create and activate a virtual environment.**

   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   source .venv/bin/activate     # macOS / Linux
   ```

3. **Install dependencies.**

   ```bash
   python -m pip install -r requirements.txt
   ```

   (Using `python -m pip` avoids the "pip.exe blocked" error some Windows machines show.)

4. **Add your API key.** Copy `.env.example` to `.env` and replace the placeholder:

   ```
   GEMINI_API_KEY=your-key-here
   ```

   Optionally set `GEMINI_MODEL` to use a different Gemini model (default: `gemini-3.5-flash-lite`). `.env` is gitignored, so your key is not committed.

5. **Run the app.**

   ```bash
   streamlit run app.py
   ```

6. **Run the tests** (no API key or network needed):

   ```bash
   python -m pytest
   ```

The manual forms (add a pet, schedule a task) work without a key. Only the "Describe your tasks (AI)" box needs one.

## Sample Interactions
### Example 1: Simple request, no conflicts

**Input:**
```
Whiskers has meds at noon
```
**Proposed tasks (before confirming):**
```
12:00 Whiskers: Give medication (daily) 
```
**Agent trace:**
```
PLAN: asking model to parse: 'Whiskers has meds at noon'

VALIDATE: ok 'Give medication' for Whiskers at 12:00

ACT: added 'Give medication' for Whiskers at 12:00 (daily)

CHECK: no conflicts (round 1).
```

### Example 2: Request that creates a time conflict

**Input:**
```
Buddy needs a walk at 8:00 and Whiskers needs breakfast at 8:00 today
```

**Proposed tasks (before confirming):**
```
08:00 Buddy: Walk (once, 2026-11-15)
08:00 Whiskers: Breakfast (once, 2026-11-15)
```

**Agent trace (showing the conflict being found and fixed):**
```
PLAN: asking model to parse: 'Buddy needs a walk at 8:00 and Whiskers needs breakfast at 8:00 today'
VALIDATE: ok 'Walk' for Buddy at 08:00
VALIDATE: ok 'Breakfast' for Whiskers at 08:00
ACT: added 'Walk' for Buddy at 08:00 (once)
ACT: added 'Breakfast' for Whiskers at 08:00 (once)
CHECK: 1 conflict(s) found (round 1); asking model to reschedule.
CHECK: moved 'Walk' (Buddy) 08:00 -> 08:00
CHECK: moved 'Breakfast' (Whiskers) 08:00 -> 08:30
CHECK: no conflicts (round 2).

```

### Example 3: Unknown pet (a guardrail limitation)

**Input** (Rex is not one of the owner's pets):
```
Rex needs a bath at 9:00
```

**Proposed tasks (before confirming):**
```
09:00 Buddy: Give Rex a bath (once, 2026-11-15)
```

**What happened:** the prompt tells the model to choose from the existing pet names, so it mapped "Rex" onto Buddy. The validator saw a valid pet and let it through. The Confirm/Cancel step is where a person catches it. See [Evaluation script](#evaluation-script).

## Design Decisions

- **Agentic workflow, kept small.** A plan, act, check loop was the simplest AI feature that genuinely changes how the system behaves: the model's output decides what lands in the schedule and where clashing tasks move. It reuses the existing scheduler instead of replacing it.
- **The AI feeds the scheduler; it doesn't replace it.** Sorting, recurrence and conflict detection stay as deterministic, tested code. The LLM only handles language understanding and picking new times. This keeps the reliable parts reliable.
- **Validate before trusting.** LLM output is untrusted. Every proposed task is validated before it can touch app state, and a bad or garbled reply leaves the data unchanged.
- **Human in the loop.** The user confirms the proposed tasks before they are added. The trade-off is one extra click per request, in exchange for catching misreadings (wrong time, wrong pet).
- **Bounded loop.** The conflict-fixing loop runs at most 3 rounds, and requests are capped at 500 characters and 10 tasks. This protects the free API quota and prevents runaway behavior.
- **The LLM is a plain function.** `llm(system, user) -> text` means tests can swap in a fake, and the provider can change in one place (`gemini_llm`). I chose Gemini because it has a free tier.
- **Trade-offs.** Conflict detection is exact-time only (tasks have no duration), so a 30-minute walk at 08:00 and a feeding at 08:15 are not flagged. The model picks new times without knowing the owner's real availability. There is no automated measurement of real Gemini accuracy.

## Testing Summary

Run `python -m pytest`. There are **19 tests**:

- **12 scheduler tests** ([tests/test_pawpal.py](tests/test_pawpal.py)): task completion, chronological sorting (including out-of-order input and zero-padded times), daily and weekly recurrence, and conflict detection across pets and dates.
- **7 AI workflow tests** ([tests/test_agent.py](tests/test_agent.py)) using a fake LLM: valid tasks are added, invalid pets and times are rejected, garbled replies and exceptions are handled safely, a conflict is resolved by the agent, input guardrails work, and nothing is added until the human-approved step runs.

### Evaluation script

[eval.py](eval.py) runs five sample inputs through the agent and prints PASS / FAIL / KNOWN (a documented limitation that doesn't fail the run).

```bash
python eval.py            # real Gemini model (needs GEMINI_API_KEY)
python eval.py --offline  # no network: runs the guardrail cases only
```

Sample output from a real run:

```
PASS  empty input is rejected
      input: '   '
      expected: 0 tasks added
      got: no tasks
PASS  over-long input is rejected
      expected: 0 tasks added
      got: no tasks
PASS  simple request
      input: 'Whiskers has meds at noon'
      expected: 1 task, Whiskers, 12:00
      got: Whiskers 12:00 Give medication
PASS  conflict is detected and fixed
      expected: 2 tasks, no conflicts left
      got: Buddy 07:30 Walk; Whiskers 08:30 Breakfast
KNOWN unknown pet is rejected (documented limitation)
      input: 'Rex needs a bath at 9:00'
      expected: 0 tasks (Rex is not a pet)
      got: Buddy 09:00 Give Rex a bath

0 unexpected failure(s).
```

The model picks its own times, so the conflict case can produce different (but still conflict-free) times on each run.

### Manual checks against the real model

The automated tests use a fake LLM, so I also ran three prompts against the real Gemini model (`gemini-3.5-flash-lite`) to see how it actually behaves:

| Prompt | Expected | Actual | Result |
|---|---|---|---|
| `Whiskers has meds at noon` | One task for Whiskers at 12:00 | Added "Give medication" at 12:00. The model assumed `daily`, though I never gave a frequency. | Pass, with an assumption |
| `Buddy needs a walk at 8:00 and Whiskers needs breakfast at 8:00 today` | Clash detected and fixed | Conflict found in round 1. Breakfast moved to 08:30 and no conflicts remained. (The model also "moved" the walk from 08:00 to 08:00, a harmless no-op.) | Pass |
| `Rex needs a bath at 9:00` (Rex is not one of my pets) | Rejected as an unknown pet | Assigned to **Buddy** as "Give Rex a bath". The prompt tells the model to pick from the existing pet names, so it forced a match and the validator saw a valid pet. | **Fail (known limitation)** |

**Takeaways:** the conflict-fixing loop works on a real model, but the model can fill in details I didn't give it (the frequency) or map an unknown name onto a real pet. The validator can't catch those, because the result looks valid. This is why the **Confirm/Cancel review step** matters: a person can see "Buddy: Give Rex a bath" in the preview and cancel it. I left this limitation in place instead of hiding it. A possible fix is to let the model answer `UNKNOWN` for pets not in the list.

**What worked:** swapping the model for a fake function made the AI flow fully testable offline, with no API key and no quota use. Testing the validator caught the cases that matter most (hallucinated pet names, impossible times).

**Limits:** the tests prove my code handles AI output correctly, not that Gemini's output is *good*. Real-model behavior was only checked by hand with a few prompts. One bug found while building the approval step: a failed plan still ran the conflict check and logged a misleading "no conflicts" line. A test caught it, and it was fixed.

**What I learned:** treat model output as untrusted input, put the checks in code rather than in the prompt, and design so the AI can be replaced by a fake for testing.

## Reflection
Building this project taught me that adding AI to an app is mostly about the code around the model, not the model itself. At first I assumed that once Gemini returned an answer, the hard part was done. Instead, I had to treat every reply as untrusted: validate it, cap it, log it, and put a human confirmation step between the AI and my schedule. The biggest surprise was that a guardrail can pass and the result can still be wrong. When I typed a pet name that didn't exist, the model assigned the task to a different pet, and my validator saw a valid name and let it through. I also learned that unit tests with a dummy model can't tell me how the real model behaves, so I had to run it by hand to find the slow model and the empty replies. Next time I'd test the real model earlier and let it say "I don't know" instead of forcing an answer.


