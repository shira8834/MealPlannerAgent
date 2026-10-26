"""Offline tests for context.py, compaction.py, caching.py and tokens.py (FakeClient only)."""
import copy

import pytest

from API.agent import MealPlannerAgent
from API.harness.caching import apply_caching
from API.harness.compaction import SUMMARY_PROMPT
from API.harness.context import build_user_content, check_sequence
from API.harness.history import History
from API.harness.memory import Memory
from API.harness.tokens import TokenTracker, cost_usd
from shared import domain
from tests.fake_client import FakeClient, text_response, tool_response


def make_agent(tmp_path, responses, session_id="s1", **kwargs):
    client = FakeClient(responses)
    return MealPlannerAgent(client, session_id=session_id, data_dir=tmp_path, **kwargs), client


def without_cache_marks(messages):
    """Remove cache_control so we can compare two requests' messages."""
    messages = copy.deepcopy(messages)
    for message in messages:
        if isinstance(message["content"], list):
            for block in message["content"]:
                block.pop("cache_control", None)
    return messages


@pytest.fixture
def memory(tmp_path):
    memory = Memory(tmp_path / "memory.json")
    domain.save_preference(memory.store, "diet", "vegan")
    domain.plan_meals(memory.store, days=2)
    return memory


# ---------- context.py ----------

def test_irrelevant_question_gets_no_memory(memory):
    assert build_user_content("Hi, how are you?", memory) == [
        {"type": "text", "text": "Hi, how are you?"},
    ]


def test_plan_question_gets_preferences(memory):
    content = build_user_content("Plan 3 dinners for me", memory)
    assert "diet=vegan" in content[0]["text"]
    assert content[1]["text"] == "Plan 3 dinners for me"


def test_shopping_question_gets_plan_but_not_preferences(memory):
    content = build_user_content("מה לקנות בסופר?", memory)  # Hebrew works too
    assert "Saved meal plan" in content[0]["text"]
    assert "r11 Pasta with Tomato Sauce" in content[0]["text"]
    assert "diet=vegan" not in content[0]["text"]


def test_check_sequence_finds_missing_tool_result():
    good = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    ]
    check_sequence(good)  # no error
    with pytest.raises(ValueError):
        check_sequence(good[:2])  # tool_use with no result
    with pytest.raises(ValueError):
        check_sequence(good[1:])  # starts with assistant


def test_system_and_old_messages_never_change_in_a_session(tmp_path):
    # Changing a preference in the middle must NOT change the system prompt
    agent, client = make_agent(tmp_path, [
        tool_response(("t1", "save_preference", {"key": "diet", "value": "vegan"})),
        text_response("Saved."),
        text_response("Here is a plan."),
    ])
    agent.ask("I'm vegan")
    agent.ask("Plan dinners")
    first, *rest = client.requests
    for later in rest:
        assert later["system"] == first["system"]
    # Each request starts with exactly the messages of the one before (append-only)
    for before, after in zip(client.requests, client.requests[1:]):
        old = without_cache_marks(before["messages"])
        assert without_cache_marks(after["messages"])[:len(old)] == old


# ---------- compaction.py ----------

def test_compaction_summarizes_but_keeps_original_history(tmp_path):
    agent, client = make_agent(tmp_path, [
        text_response("Pasta is great."),           # turn 1
        text_response("User likes pasta."),         # compaction call
        text_response("Yes, pasta again."),         # turn 2
    ], compact_at=10)
    agent.ask("Tell me about pasta")
    history_before = agent.history.path.read_text(encoding="utf-8")
    agent.ask("More pasta?")

    summary_request = client.requests[1]
    assert summary_request["tool_choice"] == {"type": "none"}
    assert summary_request["messages"][-1]["content"] == SUMMARY_PROMPT

    # The next request = summary + the new user message only
    turn2 = client.requests[2]["messages"]
    assert len(turn2) == 2
    assert "User likes pasta." in turn2[0]["content"][0]["text"]
    assert turn2[1]["content"][-1]["text"] == "More pasta?"

    # The original history file only grew; the first turn is still there
    history_after = agent.history.path.read_text(encoding="utf-8")
    assert history_after.startswith(history_before)
    assert len(History(agent.history.path)) == 4


def test_compaction_is_reloaded_by_new_instance(tmp_path):
    agent, _ = make_agent(tmp_path, [
        text_response("A"), text_response("SUMMARY"), text_response("B"),
    ], compact_at=10)
    agent.ask("one")
    agent.ask("two")

    # Same session, new program run
    agent2, client2 = make_agent(tmp_path, [text_response("C")], compact_at=100_000)
    agent2.ask("three")
    messages = client2.requests[0]["messages"]
    assert "SUMMARY" in messages[0]["content"][0]["text"]
    assert len(messages) == 4  # summary, "two", "B", "three"


def test_no_compaction_when_context_is_small(tmp_path):
    agent, client = make_agent(tmp_path, [text_response("A"), text_response("B")])
    agent.ask("one")
    agent.ask("two")
    assert len(client.requests) == 2  # no extra summary call


# ---------- caching.py ----------

def test_cache_marks_on_system_and_last_message():
    request = {
        "system": [{"type": "text", "text": "rules"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    original = copy.deepcopy(request)
    cached = apply_caching(request)
    assert cached["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert cached["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert request == original  # the input was not changed


def test_cache_marks_are_not_saved_in_history(tmp_path):
    agent, client = make_agent(tmp_path, [text_response("Hi")])
    agent.ask("Hello")
    assert "cache_control" in str(client.requests[0]["messages"])
    assert "cache_control" not in agent.history.path.read_text(encoding="utf-8")


# ---------- tokens.py ----------

def test_cost_uses_all_four_prices():
    # 1000*4 + 2000*0.20 + 500*5 + 300*20 = 12,900 per million
    assert cost_usd("claude-opus-5-5", 1000, 2000, 500, 300) == pytest.approx(0.0129)


def test_turn_usage_adds_up_all_calls(tmp_path):
    agent, _ = make_agent(tmp_path, [
        tool_response(("t1", "search_recipes", {"query": "soup"}),
                      input_tokens=50, cache_write=1500, output_tokens=40),
        text_response("Lentil soup.", input_tokens=60, cache_read=1500, output_tokens=25),
    ])
    usage = agent.ask("Soup ideas?")["usage"]
    assert usage["input_tokens"] == 110
    assert usage["cache_write_tokens"] == 1500
    assert usage["cache_read_tokens"] == 1500
    assert usage["output_tokens"] == 65
    assert usage["model_calls"] == 2
    assert usage["tools"] == ["search_recipes"]
    assert usage["cost_usd"] == pytest.approx(cost_usd("claude-opus-5-5", 110, 1500, 1500, 65), abs=1e-6)
    assert usage["seconds"] >= 0


def test_compaction_call_is_counted(tmp_path):
    agent, _ = make_agent(tmp_path, [
        text_response("A"), text_response("SUMMARY"), text_response("B"),
    ], compact_at=10)
    agent.ask("one")
    usage = agent.ask("two")["usage"]
    assert usage["model_calls"] == 2
    assert usage["compaction_calls"] == 1
    totals = agent.tokens.totals()
    assert totals["model_calls"] == 3


def test_tracker_totals():
    tracker = TokenTracker("claude-opus-5-5")
    for _ in range(2):
        tracker.start_turn()
        tracker.record(text_response("x", input_tokens=10, output_tokens=5))
        tracker.end_turn([])
    assert tracker.totals()["input_tokens"] == 20
    assert tracker.totals()["model_calls"] == 2
