"""Offline tests for scenario.json, the clean start and the pass/fail checks.

The two end-to-end tests run the REAL scenario.json through the API and SDK
runners with fake clients. The fake model asks for real tools, so the memory
file really changes, and the checks judge that saved state.
"""
import asyncio
import copy
import json

import pytest

from API.main import run_scenario as run_api_scenario
from SDK.main import run_scenario as run_sdk_scenario
from SDK.tools import build_tools
from shared import domain
from shared.checks import run_checks
from shared.memory_store import MemoryStore
from shared.scenario import SCENARIO_PATH, load_scenario, reset_data_dir
from tests.fake_client import FakeClient
from tests.fake_sdk_client import FakeSDKClient, assistant, result, text, tool_call
from tests.scripted_model import SCRIPT, answer_for, api_responses


# ---------- scenario.json ----------

def test_scenario_file_has_8_hebrew_turns_in_2_sessions():
    scenario = load_scenario()
    assert [s["name"] for s in scenario["sessions"]] == ["session1", "session2"]
    assert [len(s["turns"]) for s in scenario["sessions"]] == [4, 4]
    for session in scenario["sessions"]:
        for turn in session["turns"]:
            assert any("֐" <= ch <= "׿" for ch in turn), f"not Hebrew: {turn}"
    all_text = " ".join(t for s in scenario["sessions"] for t in s["turns"])
    assert all_text.count("פטריות") >= 2  # the preference, and the change of mind


@pytest.mark.parametrize("bad", [
    {"sessions": []},
    {"sessions": [{"name": "a", "turns": ["x"] * 4}]},
    {"sessions": [{"name": "a", "turns": ["x"] * 2}, {"name": "b", "turns": ["y"] * 2}]},
    {"sessions": [{"name": "a", "turns": ["x"] * 4}, {"name": "b", "turns": ["", "y", "y", "y"]}]},
])
def test_bad_scenario_is_rejected(tmp_path, bad):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        load_scenario(path)


def test_reset_removes_only_run_state(tmp_path):
    MemoryStore(tmp_path / "memory.json").set_preference("diet", "vegan")
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "s1.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "keep_me.txt").write_text("hi", encoding="utf-8")
    reset_data_dir(tmp_path)
    assert not (tmp_path / "memory.json").exists()
    assert not (tmp_path / "history").exists()
    assert (tmp_path / "keep_me.txt").exists()


# ---------- the data makes the mushroom checks meaningful ----------

def test_mushroom_preference_changes_the_plan(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    domain.plan_meals(store, days=3)
    assert store.get_last_plan()["days"][0]["dinner"] == "r10"  # r10 has mushrooms
    domain.save_preference(store, "avoid", ["mushroom"])
    domain.plan_meals(store, days=3)
    assert "r10" not in [d["dinner"] for d in store.get_last_plan()["days"]]


# ---------- end to end: API runner ----------

def test_api_scenario_passes_all_checks(tmp_path):
    client = FakeClient(api_responses())
    out = tmp_path / "results" / "api.json"
    MemoryStore(tmp_path / "memory.json").set_preference("diet", "vegan")  # left from an old run

    results = run_api_scenario(SCENARIO_PATH, out, client, data_dir=tmp_path)

    assert results["checks_passed"] == "9/9", [c for c in results["checks"] if not c["passed"]]
    assert json.loads(out.read_text(encoding="utf-8")) == results
    # Separate history files: session 2 started without session 1's chat
    assert (tmp_path / "history" / "session1.jsonl").exists()
    s2_first = json.loads((tmp_path / "history" / "session2.jsonl").read_text(encoding="utf-8")
                          .splitlines()[0])
    assert s2_first["content"][-1]["text"] == load_scenario()["sessions"][1]["turns"][0]
    assert results["totals"]["model_calls"] == len(client.requests)


# ---------- end to end: SDK runner ----------

class ScriptedSDKClient(FakeSDKClient):
    """Plays SCRIPT and, like the real SDK, runs the tool handlers on the agent's memory."""
    data_dir = None
    step = 0

    def __init__(self, options):
        super().__init__(options)
        self.session = f"sdk-session-{len(FakeSDKClient.instances)}"
        self.total = 0.0

    async def receive_response(self):
        i = ScriptedSDKClient.step
        ScriptedSDKClient.step += 1
        tool_step = SCRIPT[i]
        if tool_step:
            yield assistant(f"m{i}a", tool_call(f"t{i}", tool_step[0], tool_step[1]))
            tools = {t.name: t for t in build_tools(MemoryStore(self.data_dir / "memory.json"))}
            await tools[tool_step[0]].handler(tool_step[1])
        yield assistant(f"m{i}b", text(answer_for(i)))
        self.total += 0.01
        yield result(answer_for(i), self.total, session_id=self.session)


def test_sdk_scenario_passes_all_checks(tmp_path):
    FakeSDKClient.instances.clear()
    ScriptedSDKClient.data_dir, ScriptedSDKClient.step = tmp_path, 0
    out = tmp_path / "results" / "sdk.json"

    results = asyncio.run(run_sdk_scenario(SCENARIO_PATH, out, data_dir=tmp_path,
                                           client_class=ScriptedSDKClient))

    assert results["checks_passed"] == "9/9", [c for c in results["checks"] if not c["passed"]]
    assert len(FakeSDKClient.instances) == 2              # one new instance per session
    assert all(c.options.resume is None for c in FakeSDKClient.instances)
    # Session 2's hook got the memory saved in session 1
    first_hook = FakeSDKClient.instances[1].hook_outputs[0]
    assert "mushroom" in first_hook["hookSpecificOutput"]["additionalContext"]


# ---------- the checks catch real failures ----------

@pytest.fixture
def good_results(tmp_path):
    results = run_api_scenario(SCENARIO_PATH, tmp_path / "r.json",
                               FakeClient(api_responses()), data_dir=tmp_path)
    return copy.deepcopy(results)


def failed(results):
    return {c["name"] for c in run_checks(results) if not c["passed"]}


def test_checks_fail_when_preference_was_never_saved(good_results):
    good_results["sessions"][0]["memory_after"]["preferences"]["avoid"] = []
    assert "mushroom_preference_saved" in failed(good_results)


def test_checks_fail_when_old_preference_was_kept(good_results):
    good_results["sessions"][1]["memory_after"]["preferences"]["avoid"] = ["mushroom"]
    assert "contradiction_replaced_old_preference" in failed(good_results)


def test_checks_fail_when_plan_has_mushrooms_in_session1(good_results):
    good_results["sessions"][0]["memory_after"]["last_plan"]["days"][0]["dinner"] = "r10"
    assert "plan_3_days_without_mushrooms" in failed(good_results)


def test_checks_fail_when_session2_reuses_session1(good_results):
    good_results["sessions"][1]["session_id"] = good_results["sessions"][0]["session_id"]
    assert failed(good_results) == {"new_instance_in_session2"}


def test_new_plan_without_mushrooms_still_passes(good_results):
    # Mushrooms are allowed again, but the model chose other dinners - that is fine
    days = good_results["sessions"][1]["memory_after"]["last_plan"]["days"]
    for day, rid in zip(days, ["r11", "r12", "r13"]):
        day["dinner"] = rid
    assert "mushroom_recipes_available_again" not in failed(good_results)


def test_mushrooms_not_available_while_still_avoided(good_results):
    good_results["sessions"][1]["memory_after"]["preferences"]["avoid"] = ["mushroom"]
    assert "mushroom_recipes_available_again" in failed(good_results)


def test_checks_fail_when_no_new_plan_in_session2(good_results):
    for turn in good_results["sessions"][1]["turns"]:
        turn["tools"] = [t for t in turn["tools"] if t != "plan_meals"]
    assert "mushroom_recipes_available_again" in failed(good_results)


def test_every_turn_records_all_measurements(good_results, tmp_path):
    ScriptedSDKClient.data_dir, ScriptedSDKClient.step = tmp_path, 0
    FakeSDKClient.instances.clear()
    sdk = asyncio.run(run_sdk_scenario(SCENARIO_PATH, tmp_path / "s.json", data_dir=tmp_path,
                                       client_class=ScriptedSDKClient))
    needed = {"input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens",
              "model_calls", "tools", "cost_usd", "seconds"}
    for results in (good_results, sdk):
        for session in results["sessions"]:
            for turn in session["turns"]:
                assert needed <= set(turn["usage"]), needed - set(turn["usage"])


def test_checks_fail_on_dirty_start_and_missing_tools(good_results):
    good_results["memory_at_start"]["preferences"] = {"diet": "vegan"}
    good_results["sessions"][0]["turns"][0]["tools"] = []
    good_results["sessions"][1]["turns"][0]["answer"] = "I don't remember anything."
    assert {"clean_start", "search_tool_used", "memory_recalled_in_session2"} <= failed(good_results)
