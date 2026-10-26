"""Regression tests for the problems found in the review of the first real SDK run."""
import asyncio
import json

from API.harness.tools import TOOL_SCHEMAS, run_tool
from SDK.agent import SDKMealPlannerAgent, build_options, memory_text, redact
from SDK.tools import build_tools
from shared import config, domain
from shared.memory_store import MemoryStore
from shared.prompts import SYSTEM_PROMPT, TOOL_DESCRIPTIONS
from tests.fake_sdk_client import FakeSDKClient, assistant, result, text


def run_turns(agent, turns, prompts):
    async def go():
        agent.client.turns = turns
        async with agent:
            return [await agent.ask(p) for p in prompts]
    return asyncio.run(go())


def turn(answer, total, api_ms):
    return [assistant("m", text(answer)), result(answer, total, api_ms=api_ms)]


# ---------- 1. api_seconds is per turn, not a running total ----------

def test_api_seconds_is_the_difference_between_turns(tmp_path):
    # The real run reported 11.2, 18.51, 23.67 seconds: running totals
    agent = SDKMealPlannerAgent(data_dir=tmp_path, client_class=FakeSDKClient)
    r = run_turns(agent, [turn("a", 0.02, 11200), turn("b", 0.03, 18510), turn("c", 0.04, 23670)],
                  ["1", "2", "3"])
    assert [x["usage"]["api_seconds"] for x in r] == [11.2, 7.31, 5.16]


def test_api_seconds_starts_from_zero_in_a_new_session(tmp_path):
    agent1 = SDKMealPlannerAgent(data_dir=tmp_path, client_class=FakeSDKClient)
    run_turns(agent1, [turn("a", 0.02, 30280)], ["1"])
    agent2 = SDKMealPlannerAgent(data_dir=tmp_path, client_class=FakeSDKClient)
    [r] = run_turns(agent2, [turn("b", 0.01, 8290)], ["2"])
    assert r["usage"]["api_seconds"] == 8.29  # not 8.29 - 30.28


def test_api_seconds_unknown_on_first_resumed_turn(tmp_path):
    agent = SDKMealPlannerAgent(data_dir=tmp_path, resume="old", client_class=FakeSDKClient)
    r = run_turns(agent, [turn("a", 0.5, 40000), turn("b", 0.6, 43000)], ["1", "2"])
    assert r[0]["usage"]["api_seconds"] is None
    assert r[1]["usage"]["api_seconds"] == 3.0


# ---------- 2. the model gets the ingredients of the planned recipes ----------

def test_plan_returns_ingredients_of_chosen_recipes_only(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    out = domain.plan_meals(store, days=3)  # no preferences -> r10, r11, r12
    assert sorted(out["ingredients"]) == ["r10", "r11", "r12"]  # not the whole recipe file
    assert "mushrooms" in out["ingredients"]["r10"]
    assert "mushrooms" not in out["ingredients"]["r11"]


def test_plan_ingredients_reach_the_model_in_both_versions(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    api_text, _ = run_tool("plan_meals", {"days": 1}, store)
    sdk_out = asyncio.run({t.name: t for t in build_tools(store)}["plan_meals"].handler({"days": 1}))
    sdk_text = sdk_out["content"][0]["text"]
    assert api_text == sdk_text  # same tool output in API and SDK
    assert "mushrooms" in json.loads(api_text)["ingredients"]["r10"]
    assert len(api_text) < 400   # still a short output


def test_prompt_forbids_guessing_ingredients():
    assert "only if you saw its ingredients in a tool result" in SYSTEM_PROMPT
    assert "ingredient names" in TOOL_DESCRIPTIONS["plan_meals"]


# ---------- 3. SDK memory shows recipe names, file format unchanged ----------

def test_sdk_memory_has_names_and_file_keeps_ids(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    domain.plan_meals(store, days=2)
    text_out = memory_text(store)
    assert "day 1: dinner r10 Chicken Stir Fry" in text_out
    assert len(text_out) < 200
    saved = json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))
    assert saved["last_plan"] == {"days": [{"day": 1, "dinner": "r10"}, {"day": 2, "dinner": "r11"}]}


# ---------- 4. stderr log, without secrets ----------

def test_stderr_is_off_by_default_and_on_when_asked(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    assert build_options(store).stderr is None
    log = tmp_path / "logs" / "stderr.log"
    options = build_options(store, stderr_log=log)
    options.stderr("Could not parse message into JSON: event: content_block_delta\n")
    assert "content_block_delta" in log.read_text(encoding="utf-8")


def test_secrets_are_hidden_in_the_log(tmp_path):
    # Obviously fake values (so no secret scanner mistakes them for real keys)
    line = ('x-api-key: sk-ant-FAKE-NOT-A-KEY Authorization: Bearer fake.token '
            '{"token": "tok_fake"} ANTHROPIC_API_KEY=sk-ant-FAKE-2')
    clean = redact(line)
    for secret in ("FAKE-NOT-A-KEY", "fake.token", "tok_fake", "FAKE-2"):
        assert secret not in clean
    log = tmp_path / "stderr.log"
    build_options(MemoryStore(tmp_path / "m.json"), stderr_log=log).stderr(line)
    assert "FAKE-NOT-A-KEY" not in log.read_text(encoding="utf-8")


# ---------- 5. fair comparison: same tools, data, model and effort ----------

def test_both_versions_use_the_same_tools_model_and_effort(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    sdk_tools = build_tools(store)
    api_tools = {s["name"]: s for s in TOOL_SCHEMAS}
    for t in sdk_tools:
        assert t.description == api_tools[t.name]["description"]
        assert t.input_schema == api_tools[t.name]["input_schema"]
    options = build_options(store)
    assert (options.model, options.effort) == (config.MODEL, config.EFFORT)
    assert options.system_prompt.startswith(SYSTEM_PROMPT)
    assert domain.RECIPES_PATH.name == "recipes.json"  # one recipe file for both
