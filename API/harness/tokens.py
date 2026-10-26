"""Token and cost measurement for every turn.

For each user turn we save: input tokens, cache read/write tokens, output tokens,
number of model calls, tools used, cost in USD and time in seconds.
All numbers come from response.usage - nothing is guessed.
"""
import json
import time

LOG = "[harness/tokens.py]"

# USD per 1 million tokens (Anthropic price table, checked 2026-10).
# cache_write = 5-minute cache write (1.25 x input); cache_read is per model.
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
}


def estimate_tokens(messages):
    """Rough size when we have no measurement yet (about 4 characters per token)."""
    return len(json.dumps(messages, ensure_ascii=False)) // 4


def cost_usd(model, input_tokens, cache_read, cache_write, output_tokens):
    price = PRICES[model]
    total = (input_tokens * price["input"]
             + cache_read * price["cache_read"]
             + cache_write * price["cache_write"]
             + output_tokens * price["output"])
    return total / 1_000_000


class TokenTracker:
    def __init__(self, model):
        self.model = model
        self.turns = []
        self.last_context_tokens = 0  # size of the last chat request + its answer
        self._turn = None
        self._start_time = None

    def start_turn(self):
        self._turn = {
            "input_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
            "output_tokens": 0, "model_calls": 0, "compaction_calls": 0,
        }
        self._start_time = time.perf_counter()

    def record(self, response, purpose="chat"):
        """Called after every model call (chat or compaction)."""
        usage = response.usage
        cache_read = usage.cache_read_input_tokens or 0
        cache_write = usage.cache_creation_input_tokens or 0
        t = self._turn
        t["input_tokens"] += usage.input_tokens
        t["cache_read_tokens"] += cache_read
        t["cache_write_tokens"] += cache_write
        t["output_tokens"] += usage.output_tokens
        t["model_calls"] += 1
        if purpose == "compaction":
            t["compaction_calls"] += 1
        else:
            self.last_context_tokens = usage.input_tokens + cache_read + cache_write + usage.output_tokens
        print(LOG, f"{purpose} call: in={usage.input_tokens} cache_read={cache_read} "
                   f"cache_write={cache_write} out={usage.output_tokens}")

    def end_turn(self, tools_used):
        t = self._turn
        t["tools"] = list(tools_used)
        t["cost_usd"] = round(cost_usd(self.model, t["input_tokens"], t["cache_read_tokens"],
                                       t["cache_write_tokens"], t["output_tokens"]), 6)
        t["seconds"] = round(time.perf_counter() - self._start_time, 2)
        self.turns.append(t)
        print(LOG, f"turn {len(self.turns)}: {t['model_calls']} calls, "
                   f"${t['cost_usd']:.6f}, {t['seconds']}s")
        return t

    def totals(self):
        keys = ["input_tokens", "cache_read_tokens", "cache_write_tokens",
                "output_tokens", "model_calls", "compaction_calls", "cost_usd", "seconds"]
        return {k: round(sum(turn[k] for turn in self.turns), 6) for k in keys}
