"""Prompt caching: mark stable content with cache_control.

The API reads a request in this order: tools -> system -> messages.
A cache_control mark means "cache everything up to here". We put two marks:
1. on the system prompt  -> tools + system are cached (they never change in a session)
2. on the last message   -> the conversation so far is cached for the next call

Moving marks does not count as editing the history, so this is always safe.
Note: Claude Opus 5.5 caches only prefixes of 512 tokens or more.
"""
import copy

LOG = "[harness/caching.py]"
CACHE = {"type": "ephemeral"}  # default 5-minute cache


def apply_caching(request):
    """Return a copy of the request with cache_control marks.
    The original (and the saved history) is not changed."""
    request = dict(request)
    request["system"] = copy.deepcopy(request["system"])
    request["system"][-1]["cache_control"] = CACHE

    messages = copy.deepcopy(request["messages"])
    last = messages[-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"][-1]["cache_control"] = CACHE
    request["messages"] = messages

    print(LOG, f"cache_control on system and on message {len(messages) - 1}")
    return request
