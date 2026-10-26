"""The agent loop: call the model, run tools, repeat while stop_reason == "tool_use".

The loop does not know how the request is built or how tools run.
It gets them as functions, so context.py, caching.py and tokens.py
can be plugged in later without changing this file.
"""
from shared.config import MAX_STEPS  # safety limit, so a confused model can't loop forever

LOG = "[harness/loop.py]"


def final_text(response):
    """Join all text blocks of a response."""
    return "\n".join(block.text for block in response.content if block.type == "text")


def run_loop(client, history, build_request, execute_tools, on_response=None, max_steps=MAX_STEPS):
    """
    client        - anthropic.Anthropic() or a FakeClient in tests
    history       - History object (the user message is already in it)
    build_request - function () -> dict of arguments for client.messages.create
    execute_tools - function (tool_use_blocks) -> list of tool_result dicts
    on_response   - optional function (response) -> None, for example to count tokens
    """
    tools_used = []
    for step in range(1, max_steps + 1):
        request = build_request()
        print(LOG, f"step {step}: calling model with {len(request['messages'])} messages")
        response = client.messages.create(**request)
        print(LOG, f"step {step}: stop_reason={response.stop_reason}")
        if on_response:
            on_response(response)

        # Save the full content (text + thinking + tool_use) - the next request needs it
        history.append("assistant", response.content)

        if response.stop_reason != "tool_use":
            if response.stop_reason in ("max_tokens", "refusal"):
                print(LOG, f"warning: model stopped with {response.stop_reason}")
            return {"text": final_text(response), "model_calls": step, "tools_used": tools_used}

        tool_use_blocks = [block for block in response.content if block.type == "tool_use"]
        tools_used += [block.name for block in tool_use_blocks]
        results = execute_tools(tool_use_blocks)
        # All results together in ONE user message
        history.append("user", results)
        print(LOG, f"step {step}: sent {len(results)} tool results in one message")

    print(LOG, f"stopped after {max_steps} steps")
    return {
        "text": "Sorry, I could not finish this request.",
        "model_calls": max_steps,
        "tools_used": tools_used,
    }
