"""Offline tests for the SDK version (FakeSDKClient - no Claude Code process, no cost)."""
import asyncio
import json

import pytest

from API.harness.tools import TOOL_SCHEMAS
from SDK.agent import AGENT_HOME, SDKMealPlannerAgent, make_memory_hook, memory_text
from SDK.tools import ALLOWED_TOOLS, build_tools
from shared.config import EFFORT, MAX_STEPS, MODEL
from shared.memory_store import MemoryStore
from shared.tool_schemas import INPUT_SCHEMAS
from tests.fake_sdk_client import FakeSDKClient, assistant, result, text, tool_call


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json")


@pytest.fixture(autouse=True)
def clear_fake_instances():
    FakeSDKClient.instances.clear()


def call_tool(tools, name, args):
    """Run one SDK tool handler directly, the way the SDK would."""
    handler = {t.name: t for t in tools}[name].handler
    return asyncio.run(handler(args))


# ---------- SDK/tools.py ----------

def test_sdk_has_the_same_four_tools_and_schemas_as_api(store):
    tools = build_tools(store)
    assert [t.name for t in tools] == [s["name"] for s in TOOL_SCHEMAS]
    for t in tools:
        assert t.input_schema == INPUT_SCHEMAS[t.name]
    assert ALLOWED_TOOLS == [f"mcp__meals__{t.name}" for t in tools]


def test_sdk_tool_returns_short_json(store):
    out = call_tool(build_tools(store), "search_recipes", {"query": "lentils"})
    data = json.loads(out["content"][0]["text"])
    assert data["recipes"][0]["id"] == "r06"
    assert "is_error" not in out


def test_sdk_tool_error_is_reported(store):
    tools = build_tools(store)
    out = call_tool(tools, "plan_meals", {"days": 10})
    assert out["is_error"] is True and "days" in out["content"][0]["text"]
    out = call_tool(tools, "create_shopping_list", {})  # no plan yet
    assert out["is_error"] is True


def test_sdk_tool_saves_preference_to_disk(store):
    call_tool(build_tools(store), "save_preference", {"key": "diet", "value": "vegan"})
    assert MemoryStore(store.path).get_preferences()["diet"] == "vegan"


# ---------- SDK/agent.py: options ----------

def test_options_match_the_requirements(tmp_path):
    agent = SDKMealPlannerAgent(data_dir=tmp_path, client_class=FakeSDKClient)
    o = agent.options
    assert o.model == MODEL and o.effort == EFFORT          # same as the API version
    assert o.strict_mcp_config is True
    assert o.tools == []                                      # no built-in tools
    assert o.allowed_tools == ALLOWED_TOOLS                  # only our 4 tools
    assert o.permission_mode == "dontAsk"
    assert o.max_turns == MAX_STEPS
    assert o.setting_sources == ["project"]
    assert o.cwd == str(AGENT_HOME) and (AGENT_HOME / "CLAUDE.md").exists()
    assert o.resume is None
    assert "meals" in o.mcp_servers


# ---------- memory hook ----------

def test_memory_hook_adds_saved_preferences(store):
    hook = make_memory_hook(store)
    assert asyncio.run(hook({}, None, {})) == {}  # nothing saved yet
    store.set_preference("avoid", ["peanut"])
    out = asyncio.run(hook({}, None, {}))
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "avoid=['peanut']" in out["hookSpecificOutput"]["additionalContext"]


def test_memory_text_includes_plan(store):
    store.save_last_plan({"days": [{"day": 1, "dinner": "r11"}]})
    assert "day 1: dinner r11" in memory_text(store)


# ---------- ask(), usage, sessions ----------

def run_turns(agent, turns, prompts):
    async def go():
        agent.client.turns = turns
        async with agent:
            return [await agent.ask(p) for p in prompts]
    return asyncio.run(go())


def test_ask_collects_answer_tools_and_usage(tmp_path):
    agent = SDKMealPlannerAgent(data_dir=tmp_path, client_class=FakeSDKClient)
    turn1 = [
        # two parallel tool calls in one model response share one message_id
        assistant("m1", tool_call("t1", "save_preference", {"key": "diet", "value": "vegan"})),
        assistant("m1", tool_call("t2", "search_recipes", {"query": "soup"})),
        assistant("m2", text("Saved. Try lentil soup.")),
        result("Saved. Try lentil soup.", total_cost=0.05, input_tokens=300,
               cache_write=1500, output_tokens=80),
    ]
    turn2 = [assistant("m3", text("Sure.")), result("Sure.", total_cost=0.07, cache_read=1500)]
    r1, r2 = run_turns(agent, [turn1, turn2], ["I'm vegan, soup?", "thanks"])

    assert r1["text"] == "Saved. Try lentil soup."
    assert r1["tools_used"] == ["save_preference", "search_recipes"]
    assert r1["model_calls"] == 2
    u = r1["usage"]
    assert (u["input_tokens"], u["cache_write_tokens"], u["output_tokens"]) == (300, 1500, 80)
    assert u["cost_usd"] == pytest.approx(0.05)
    # total_cost_usd is a running total -> turn 2 cost is the difference
    assert r2["usage"]["cost_usd"] == pytest.approx(0.02)
    assert r2["usage"]["cache_read_tokens"] == 1500
    assert r2["session_id"] == "sess-1"


def test_resume_passes_session_id_to_sdk(tmp_path):
    agent = SDKMealPlannerAgent(data_dir=tmp_path, resume="sess-1", client_class=FakeSDKClient)
    assert agent.options.resume == "sess-1"
    [r] = run_turns(agent, [[assistant("m1", text("Hi again")), result("Hi again", 0.30)]], ["hi"])
    assert r["usage"]["cost_usd"] is None             # includes old spend -> unknown
    assert r["usage"]["session_cost_usd"] == pytest.approx(0.30)


def test_new_session_sees_memory_saved_in_old_session(tmp_path):
    # Session 1: the tool saves a preference (as the SDK would run it)
    agent1 = SDKMealPlannerAgent(data_dir=tmp_path, client_class=FakeSDKClient)
    call_tool(build_tools(agent1.memory), "save_preference", {"key": "diet", "value": "vegetarian"})

    # Session 2: a brand new agent object; the hook gives the model the memory
    agent2 = SDKMealPlannerAgent(data_dir=tmp_path, client_class=FakeSDKClient)
    run_turns(agent2, [[assistant("m1", text("You are vegetarian.")), result("ok", 0.01)]],
              ["מה את זוכרת עליי?"])
    context = agent2.client.hook_outputs[0]["hookSpecificOutput"]["additionalContext"]
    assert "diet=vegetarian" in context
    assert agent2.options.resume is None  # a new session, not a resumed one


def test_error_result_does_not_crash(tmp_path):
    agent = SDKMealPlannerAgent(data_dir=tmp_path, client_class=FakeSDKClient)
    bad = result("", 0.01)
    bad.is_error, bad.subtype = True, "error_max_turns"
    [r] = run_turns(agent, [[bad]], ["loop forever"])
    assert r["text"] == ""
    assert r["usage"]["cost_usd"] == pytest.approx(0.01)

