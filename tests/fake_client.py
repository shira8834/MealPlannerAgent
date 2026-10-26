"""A fake Anthropic client for offline tests: no network, no API key, no cost.

It returns answers we prepared in advance, and saves every request it got,
so a test can check exactly what would have been sent to the model.
"""
import copy

from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage


def text_response(text, **usage):
    return _message([TextBlock(type="text", text=text)], "end_turn", **usage)


def tool_response(*calls, thinking=None, **usage):
    """calls = (tool_id, tool_name, tool_input) tuples. Optional thinking block first."""
    content = []
    if thinking is not None:
        content.append(ThinkingBlock(type="thinking", thinking=thinking, signature="sig-123"))
    for tool_id, name, tool_input in calls:
        content.append(ToolUseBlock(type="tool_use", id=tool_id, name=name, input=tool_input))
    return _message(content, "tool_use", **usage)


def _message(content, stop_reason, input_tokens=100, output_tokens=20, cache_read=0, cache_write=0):
    return Message(
        id="msg_fake",
        type="message",
        role="assistant",
        model="fake-model",
        content=content,
        stop_reason=stop_reason,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self  # so the code can call client.messages.create(...)

    def create(self, **request):
        # deepcopy: save the request as it was at this moment
        self.requests.append(copy.deepcopy(request))
        if not self.responses:
            raise AssertionError("FakeClient got more calls than prepared responses")
        return self.responses.pop(0)
