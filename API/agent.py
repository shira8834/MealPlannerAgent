"""MealPlannerAgent (API version): connects the harness parts together.

One user turn:
    compaction (if too big) -> context (relevant memory) -> history
    -> loop [caching -> model -> tools] -> tokens -> answer
"""
from pathlib import Path

from API.harness.caching import apply_caching
from API.harness.compaction import COMPACT_AT_TOKENS, Compactor
from API.harness.context import build_user_content, check_sequence
from API.harness.history import History
from API.harness.loop import run_loop
from API.harness.memory import Memory
from API.harness.tokens import TokenTracker, estimate_tokens
from API.harness.tools import TOOL_SCHEMAS, run_tool_calls
from shared.config import EFFORT, MODEL
from shared.prompts import SYSTEM_PROMPT

LOG = "[API/agent.py]"

MAX_TOKENS = 16000

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "api"


class MealPlannerAgent:
    def __init__(self, client, session_id, data_dir=DATA_DIR, compact_at=COMPACT_AT_TOKENS):
        data_dir = Path(data_dir)
        self.client = client
        self.session_id = session_id
        # Memory is shared by all sessions; history and compactions are per session
        self.memory = Memory(data_dir / "memory.json")
        self.history = History(data_dir / "history" / f"{session_id}.jsonl")
        self.compactor = Compactor(data_dir / "compactions" / f"{session_id}.json", compact_at)
        self.tokens = TokenTracker(MODEL)
        # The system prompt is frozen for the whole session (never rebuilt)
        self.system = [{"type": "text", "text": SYSTEM_PROMPT}]
        print(LOG, f"session {session_id} ready")

    def build_request(self):
        """All arguments for client.messages.create."""
        messages = self.compactor.apply(self.history.messages())
        check_sequence(messages)
        request = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "output_config": {"effort": EFFORT},
            "system": self.system,
            "tools": TOOL_SCHEMAS,
            "messages": messages,
        }
        return apply_caching(request)

    def execute_tools(self, tool_use_blocks):
        return run_tool_calls(tool_use_blocks, self.memory.store)

    def maybe_compact(self):
        """Between turns only: summarize if the last context was too big."""
        if len(self.history) == 0:
            return
        request = self.build_request()
        size = self.tokens.last_context_tokens or estimate_tokens(request["messages"])
        if self.compactor.should_compact(size):
            response = self.compactor.compact(self.client, request, len(self.history))
            self.tokens.record(response, purpose="compaction")

    def ask(self, user_text):
        """One user turn. Returns {"text", "model_calls", "tools_used", "usage"}."""
        print(LOG, f"user: {user_text}")
        self.tokens.start_turn()
        self.maybe_compact()
        self.history.append("user", build_user_content(user_text, self.memory))
        result = run_loop(self.client, self.history, self.build_request,
                          self.execute_tools, on_response=self.tokens.record)
        result["usage"] = self.tokens.end_turn(result["tools_used"])
        return result
