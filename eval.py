"""Evaluation harness: runs sample inputs through the agent and prints PASS/FAIL.

Usage:
    python eval.py            # real Gemini model (needs GEMINI_API_KEY)
    python eval.py --offline  # no network: guardrail cases only

Cases marked KNOWN are documented limitations; a failure there is reported but
does not make the script exit non-zero.
"""

import sys

from ai_agent import api_key_available, run_agent
from pawpal_system import Owner, Pet


def make_owner() -> Owner:
    owner = Owner("Jordan")
    owner.add_pet(Pet("Buddy", "dog", 3))
    owner.add_pet(Pet("Whiskers", "cat", 2))
    return owner


def no_llm(system: str, user: str) -> str:
    raise AssertionError("guardrail should have stopped the request before the LLM")


# (name, input, needs_model, known_limitation, check(result) -> (ok, expected))
CASES = [
    ("empty input is rejected", "   ", False, False,
     lambda r: (r["added"] == [], "0 tasks added")),
    ("over-long input is rejected", "walk " * 200, False, False,
     lambda r: (r["added"] == [], "0 tasks added")),
    ("simple request", "Whiskers has meds at noon", True, False,
     lambda r: (len(r["added"]) == 1 and r["added"][0].pet.name == "Whiskers"
                and r["added"][0].time == "12:00", "1 task, Whiskers, 12:00")),
    ("conflict is detected and fixed",
     "Buddy needs a walk at 8:00 and Whiskers needs breakfast at 8:00 today", True, False,
     lambda r: (len(r["added"]) == 2 and r["conflicts"] == [], "2 tasks, no conflicts left")),
    ("unknown pet is rejected", "Rex needs a bath at 9:00", True, True,
     lambda r: (r["added"] == [], "0 tasks (Rex is not a pet)")),
]


def main() -> int:
    offline = "--offline" in sys.argv
    if not offline and not api_key_available():
        print("No GEMINI_API_KEY found. Set it in .env or run with --offline.")
        return 2

    failures = 0
    for name, text, needs_model, known, check in CASES:
        if offline and needs_model:
            print(f"SKIP  {name}")
            continue
        owner = make_owner()
        kwargs = {} if needs_model else {"llm": no_llm}
        result = run_agent(owner, text, **kwargs)
        ok, expected = check(result)
        got = "; ".join(f"{t.pet.name} {t.time} {t.description}" for t in result["added"]) or "no tasks"
        if ok:
            print(f"PASS  {name}\n      input: {text[:60]!r}\n      expected: {expected}\n      got: {got}")
        elif known:
            print(f"KNOWN {name} (documented limitation)\n      input: {text!r}\n      expected: {expected}\n      got: {got}")
        else:
            failures += 1
            print(f"FAIL  {name}\n      input: {text[:60]!r}\n      expected: {expected}\n      got: {got}")
    print(f"\n{failures} unexpected failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
