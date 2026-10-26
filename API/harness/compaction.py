"""Compaction: when the context gets too big, summarize the old part.

The original history file is NEVER changed. The summary is saved in its own
file (data/api/compactions/<session>.json), and only the REQUEST uses it:

    request messages = [summary] + the messages that came after the summary

This is "simple compaction": after a summary we send no old turns at all,
so no old thinking blocks are replayed. We only compact between turns,
never in the middle of a tool round.
"""
import json
from pathlib import Path

LOG = "[harness/compaction.py]"

COMPACT_AT_TOKENS = 6000  # compact when the last request was bigger than this

SUMMARY_PROMPT = (
    "Summarize our conversation so far, so you can continue it from the summary alone. "
    "Keep: the user's current preferences (and which old ones they replaced), "
    "the current meal plan with recipe ids, and any open request. "
    "Write at most 120 words. Do not call tools."
)


class Compactor:
    def __init__(self, path, compact_at=COMPACT_AT_TOKENS):
        self.path = Path(path)
        self.compact_at = compact_at
        self.compactions = []  # every summary ever made, oldest first
        if self.path.exists():
            self.compactions = json.loads(self.path.read_text(encoding="utf-8"))
            print(LOG, f"loaded {len(self.compactions)} compactions")

    def should_compact(self, context_tokens):
        return context_tokens > self.compact_at

    def apply(self, messages):
        """Messages for the request: the latest summary + everything after it.
        `messages` (the original history) is not changed."""
        if not self.compactions:
            return messages
        latest = self.compactions[-1]
        summary_message = {
            "role": "user",
            "content": [{"type": "text", "text": f"<summary_of_earlier_conversation>\n"
                                                 f"{latest['summary']}\n"
                                                 f"</summary_of_earlier_conversation>"}],
        }
        return [summary_message] + messages[latest["start"]:]

    def compact(self, client, request, history_length):
        """Ask the model for a summary of the current context and save it.
        `request` is the normal request, so the cached prefix can be reused."""
        print(LOG, f"compacting {len(request['messages'])} messages (history has {history_length})")
        summary_request = dict(request)
        summary_request["messages"] = request["messages"] + [{"role": "user", "content": SUMMARY_PROMPT}]
        summary_request["tool_choice"] = {"type": "none"}  # text only
        summary_request["max_tokens"] = 2000
        response = client.messages.create(**summary_request)

        summary = "\n".join(b.text for b in response.content if b.type == "text")
        # The next request starts from the summary + messages from this point on
        self.compactions.append({"start": history_length, "summary": summary})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.compactions, ensure_ascii=False, indent=2), encoding="utf-8")
        print(LOG, f"saved summary #{len(self.compactions)} ({len(summary)} chars), starts at message {history_length}")
        return response
