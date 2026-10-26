"""Offline tests for the API harness, using FakeClient (no API key, no cost)."""
import json

from API.agent import EFFORT, MODEL, MealPlannerAgent
from API.harness import loop
from API.harness.history import History
from API.harness.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS, run_tool
from shared.memory_store import MemoryStore
from shared.prompts import TOOL_DESCRIPTIONS
from tests.fake_client import FakeClient, text_response, tool_response


def make_agent(tmp_path, responses, session_id="s1"):
    client = FakeClient(responses)
    return MealPlannerAgent(client, session_id=session_id, data_dir=tmp_path), client


# ---------- tools.py ----------

def test_every_schema_has_a_function_and_description():
    names = [schema["name"] for schema in TOOL_SCHEMAS]
    assert sorted(names) == sorted(TOOL_FUNCTIONS) == sorted(TOOL_DESCRIPTIONS)


def test_tool_errors_become_is_error(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    text, is_error = run_tool("plan_meals", {"days": 10}, store)  # ValueError
    assert is_error and "days" in text
    text, is_error = run_tool("plan_meals", {"wrong_arg": 1}, store)  # TypeError
    assert is_error
    text, is_error = run_tool("no_such_tool", {}, store)
    assert is_error and "unknown tool" in text


# ---------- loop.py ----------

def test_two_tools_in_one_response_return_in_one_user_message(tmp_path):
    agent, client = make_agent(tmp_path, [
        tool_response(
            ("t1", "save_preference", {"key": "diet", "value": "vegan"}),
            ("t2", "search_recipes", {"query": "lentils"}),
        ),
        text_response("Saved, and I found lentil soup."),
    ])
    result = agent.ask("I'm vegan. Any lentil recipes?")

    assert result["text"] == "Saved, and I found lentil soup."
    assert result["model_calls"] == 2
    assert result["tools_used"] == ["save_preference", "search_recipes"]

    # The 2nd request ends with ONE user message that holds BOTH results
    last_message = client.requests[1]["messages"][-1]
    assert last_message["role"] == "user"
    assert [r["tool_use_id"] for r in last_message["content"]] == ["t1", "t2"]
    assert all(r["type"] == "tool_result" for r in last_message["content"])
    assert "is_error" not in last_message["content"][0]


def test_error_result_is_sent_back_to_model(tmp_path):
    agent, client = make_agent(tmp_path, [
        tool_response(("t1", "create_shopping_list", {})),  # no plan yet -> error
        text_response("You need a meal plan first."),
    ])
    agent.ask("Make a shopping list")
    result_block = client.requests[1]["messages"][-1]["content"][0]
    assert result_block["is_error"] is True
    assert "plan_meals" in result_block["content"]


def test_loop_stops_after_max_steps(tmp_path):
    # The model asks for a tool every time and never finishes
    endless = [tool_response((f"t{i}", "search_recipes", {})) for i in range(3)]
    agent, client = make_agent(tmp_path, endless)
    agent.history.append("user", "loop forever")
    result = loop.run_loop(client, agent.history, agent.build_request,
                           agent.execute_tools, max_steps=3)
    assert result["model_calls"] == 3
    assert len(client.requests) == 3


def test_request_uses_model_effort_tools_and_system(tmp_path):
    agent, client = make_agent(tmp_path, [text_response("Hi!")])
    agent.ask("Hello")
    request = client.requests[0]
    assert request["model"] == MODEL
    assert request["output_config"] == {"effort": EFFORT}
    assert request["tools"] == TOOL_SCHEMAS
    # "Hello" has no relevant memory, so only the user's text is sent (+ cache mark)
    assert request["messages"] == [{"role": "user", "content": [
        {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}},
    ]}]


# ---------- history.py ----------

def test_thinking_and_tool_use_blocks_are_sent_back_unchanged(tmp_path):
    agent, client = make_agent(tmp_path, [
        tool_response(("t1", "search_recipes", {"query": "pasta"}), thinking="let me search"),
        text_response("Found pasta."),
    ])
    agent.ask("Pasta ideas?")
    assistant_message = client.requests[1]["messages"][1]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"][0] == {
        "type": "thinking", "thinking": "let me search", "signature": "sig-123",
    }
    assert assistant_message["content"][1]["type"] == "tool_use"
    assert assistant_message["content"][1]["id"] == "t1"


def test_history_is_saved_as_jsonl_and_reloaded(tmp_path):
    agent, _ = make_agent(tmp_path, [
        tool_response(("t1", "search_recipes", {"query": "soup"})),
        text_response("Lentil soup."),
    ])
    agent.ask("Soup?")
    # user, assistant(tool_use), user(tool_result), assistant(text)
    lines = agent.history.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert [json.loads(line)["role"] for line in lines] == ["user", "assistant", "user", "assistant"]

    reloaded = History(agent.history.path)
    assert reloaded.messages() == agent.history.messages()


def test_history_only_grows(tmp_path):
    agent, _ = make_agent(tmp_path, [text_response("One"), text_response("Two")])
    agent.ask("first")
    first_two = agent.history.messages()
    agent.ask("second")
    # The old messages are still exactly the same; new ones were only added at the end
    assert agent.history.messages()[:2] == first_two
    assert len(agent.history) == 4


# ---------- memory.py (separate from history) ----------

def test_new_session_gets_memory_but_not_old_history(tmp_path):
    agent1, _ = make_agent(tmp_path, [
        tool_response(("t1", "save_preference", {"key": "avoid", "value": ["peanut"]})),
        text_response("Saved."),
    ], session_id="s1")
    agent1.ask("I'm allergic to peanuts")

    # Session 2: a brand new agent object, as after restarting the program
    agent2, client2 = make_agent(tmp_path, [text_response("Noted.")], session_id="s2")
    agent2.ask("What do you know about me?")

    request = client2.requests[0]
    first_message = request["messages"][0]["content"]
    assert "avoid=['peanut']" in first_message[0]["text"]  # memory is there (via context.py)
    assert len(request["messages"]) == 1                  # old chat is not
