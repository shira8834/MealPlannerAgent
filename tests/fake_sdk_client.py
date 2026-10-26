"""A fake ClaudeSDKClient for offline tests: no Claude Code process, no login, no cost.

For every query() it runs the UserPromptSubmit hooks (like the real SDK does),
then receive_response() returns the messages we prepared for that turn.
"""
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock


def assistant(message_id, *blocks):
    return AssistantMessage(content=list(blocks), model="fake-model", parent_tool_use_id=None,
                            message_id=message_id, session_id="sess-1")


def tool_call(tool_id, name, tool_input):
    return ToolUseBlock(id=tool_id, name=f"mcp__meals__{name}", input=tool_input)


def text(value):
    return TextBlock(text=value)


def result(answer, total_cost, session_id="sess-1", api_ms=900, **usage):
    """api_ms is the RUNNING total of API time, like the real SDK reports it."""
    return ResultMessage(
        subtype="success", duration_ms=1200, duration_api_ms=api_ms, is_error=False,
        num_turns=2, session_id=session_id, total_cost_usd=total_cost, result=answer,
        usage={"input_tokens": usage.get("input_tokens", 100),
               "cache_read_input_tokens": usage.get("cache_read", 0),
               "cache_creation_input_tokens": usage.get("cache_write", 0),
               "output_tokens": usage.get("output_tokens", 20)},
    )


class FakeSDKClient:
    instances = []  # every fake client that was created, so tests can look at it

    def __init__(self, options):
        self.options = options
        self.prompts = []
        self.hook_outputs = []
        self.turns = []  # list of message lists, one per query()
        self.connected = False
        FakeSDKClient.instances.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def query(self, prompt):
        self.prompts.append(prompt)
        for matcher in self.options.hooks.get("UserPromptSubmit", []):
            for hook in matcher.hooks:
                self.hook_outputs.append(await hook({"prompt": prompt}, None, {}))

    async def receive_response(self):
        for message in self.turns.pop(0):
            yield message
