import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ai_agent import run_agent
from pawpal_system import Owner, Pet


def make_owner():
    owner = Owner("Jordan")
    owner.add_pet(Pet("Buddy", "dog", 3))
    owner.add_pet(Pet("Whiskers", "cat", 2))
    return owner


def fake_llm(*replies):
    it = iter(replies)
    return lambda system, user: next(it)


def task(pet, time, desc="x"):
    return {"pet": pet, "description": desc, "time": time, "frequency": "daily",
            "due_date": date.today().isoformat()}


def test_adds_valid_tasks():
    owner = make_owner()
    res = run_agent(owner, "walk buddy", fake_llm(json.dumps([task("Buddy", "07:30", "Walk")])))
    assert len(res["added"]) == 1
    assert owner.pets[0].tasks[0].time == "07:30"


def test_rejects_bad_output_without_changing_state():
    owner = make_owner()
    bad = json.dumps([task("Ghost", "07:30"), task("Buddy", "25:99")])
    res = run_agent(owner, "x", fake_llm(bad))
    assert res["added"] == []
    assert owner.get_all_tasks() == []


def test_garbage_reply_is_handled():
    owner = make_owner()
    res = run_agent(owner, "x", fake_llm("sorry, I can't help"))
    assert res["added"] == [] and "failed" in res["trace"][-1]


def test_llm_exception_is_handled():
    def boom(s, u):
        raise RuntimeError("no network")

    assert run_agent(make_owner(), "x", boom)["added"] == []


def test_conflict_is_resolved_by_agent():
    owner = make_owner()
    plan = json.dumps([task("Buddy", "08:00", "Walk"), task("Whiskers", "08:00", "Feed")])
    fix = json.dumps([{"id": 0, "time": "08:30"}, {"id": 1, "time": "09:00"}])
    res = run_agent(owner, "two tasks", fake_llm(plan, fix))
    assert res["conflicts"] == []
    assert sorted(t.time for t in res["added"]) == ["08:30", "09:00"]


def test_input_guardrails():
    owner = make_owner()
    assert run_agent(owner, "   ", fake_llm())["added"] == []
    assert run_agent(owner, "a" * 1000, fake_llm())["added"] == []


def test_propose_does_not_change_pets_until_applied():
    from ai_agent import apply_tasks, propose_tasks

    owner = make_owner()
    prop = propose_tasks(owner, "walk", fake_llm(json.dumps([task("Buddy", "07:30", "Walk")])))
    assert len(prop["tasks"]) == 1
    assert owner.get_all_tasks() == []  # human has not confirmed yet
    apply_tasks(owner, prop["tasks"], fake_llm(), prop["trace"])
    assert len(owner.get_all_tasks()) == 1
