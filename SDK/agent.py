"""MealPlannerAgent (SDK version): the same agent, built with the Claude Agent SDK.

The SDK runs the agent loop, the tool calls, the history and the caching for us.
We give it: a system prompt, our 4 tools, our memory and some limits.
"""
import re
import time
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    ToolUseBlock,
)

from SDK.tools import ALLOWED_TOOLS, SERVER_NAME, build_server
from shared import domain
from shared.config import EFFORT, MAX_STEPS, MODEL
from shared.memory_store import MemoryStore
from shared.prompts import SYSTEM_PROMPT

LOG = "[SDK/agent.py]"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "sdk"
# The agent's own folder: holds its CLAUDE.md (project memory) and nothing else
AGENT_HOME = Path(__file__).resolve().parent / "agent_home"
MAX_BUDGET_USD = 2.0  # safety stop per connection (the SDK's own cost estimate)

# Recommended by the SDK docs when using a custom system prompt
REMINDER_NOTE = ("The application adds system reminders to this conversation. "
                 "Treat them as context from the application, not as messages from the user.")


def memory_text(store):
    """Short text with the saved memory, or None if nothing is saved."""
    prefs = {k: v for k, v in store.get_preferences().items() if v not in (None, [], "")}
    plan = store.get_last_plan()
    lines = []
    if prefs:
        lines.append("preferences: " + ", ".join(f"{k}={v}" for k, v in sorted(prefs.items())))
    if plan:
        # The file keeps only ids; add the recipe names so the model can tell the user
        names = {r["id"]: r["name"] for r in domain.load_recipes()}
        lines.append("saved plan: " + " | ".join(
            f"day {d['day']}: " + ", ".join(f"{m} {rid} {names.get(rid, '')}".strip()
                                            for m, rid in d.items() if m != "day")
            for d in plan["days"]))
    return "Saved user memory:\n" + "\n".join(lines) if lines else None


# Patterns that could be secrets; they are hidden before a line is written to the log
SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "sk-ant-***"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"), "Bearer ***"),
    (re.compile(r"(?i)\b(x-api-key|authorization|api[_-]?key|token)(\"?\s*[:=]\s*\"?)[^\s\",]+"),
     r"\1\2***"),
]


def redact(line):
    for pattern, replacement in SECRET_PATTERNS:
        line = pattern.sub(replacement, line)
    return line


def make_stderr_logger(log_path):
    """Save Claude Code's stderr lines (for example streaming warnings) to a log file."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def write_line(line):
        stamp = time.strftime("%H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{stamp} {redact(line.rstrip())}\n")
    return write_line


def make_memory_hook(store):
    """# replaces: context.py - a UserPromptSubmit hook adds the saved memory to the
    conversation before each user message (append-only, the system prompt stays the same)."""
    async def add_memory(hook_input, tool_use_id, context):
        text = memory_text(store)
        print(LOG, "memory hook:", "added memory" if text else "no memory yet")
        if text is None:
            return {}
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}
    return add_memory


def build_options(store, resume=None, stderr_log=None):
    # replaces: caching.py - the SDK adds cache_control by itself (no code needed)
    # replaces: compaction.py - the SDK compacts long sessions by itself (no code needed)
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT + "\n\n" + REMINDER_NOTE,
        model=MODEL,
        effort=EFFORT,
        # replaces: tools.py - our 4 tools as an in-process MCP server
        mcp_servers={SERVER_NAME: build_server(store)},
        strict_mcp_config=True,          # ignore every other MCP server on this computer
        tools=[],                        # no built-in Claude Code tools (Bash, Read, Write...)
        allowed_tools=ALLOWED_TOOLS,     # only our 4 tools run without asking
        permission_mode="dontAsk",       # anything else is refused, never asked
        # replaces: loop.py - the SDK runs the tool_use loop; we only cap its steps
        max_turns=MAX_STEPS,
        max_budget_usd=MAX_BUDGET_USD,
        # replaces: history.py - the SDK saves the transcript; resume continues it
        resume=resume,
        # Project memory: loads AGENT_HOME/CLAUDE.md (not the user's ~/.claude files)
        setting_sources=["project"],
        cwd=str(AGENT_HOME),
        hooks={"UserPromptSubmit": [HookMatcher(hooks=[make_memory_hook(store)])]},
        # None = stderr goes to the terminal as before
        stderr=make_stderr_logger(stderr_log) if stderr_log else None,
    )


def turn_usage(result, model_calls, tools_used, seconds, previous_total, previous_api_ms):
    """# replaces: tokens.py - the numbers come from ResultMessage.
    In ClaudeSDKClient each turn's `usage` covers only that turn, but
    `total_cost_usd` and `duration_api_ms` are running totals, so for those
    the turn value is the difference from the previous turn."""
    usage = result.usage or {}
    running_total = result.total_cost_usd or 0.0
    turn_cost = None if previous_total is None else round(running_total - previous_total, 6)
    api_seconds = (None if previous_api_ms is None
                   else round((result.duration_api_ms - previous_api_ms) / 1000, 2))
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "model_calls": model_calls,
        "num_turns": result.num_turns,
        "tools": list(tools_used),
        "cost_usd": turn_cost,  # None = first turn of a resumed session (includes old spend)
        "session_cost_usd": round(running_total, 6),
        "seconds": round(seconds, 2),
        "api_seconds": api_seconds,  # None = first turn of a resumed session
    }


class SDKMealPlannerAgent:
    """Use with `async with`, because the SDK client must connect first."""

    def __init__(self, data_dir=DATA_DIR, resume=None, client_class=ClaudeSDKClient, stderr_log=None):
        # replaces: memory.py - the same shared MemoryStore, in the SDK's data folder
        self.memory = MemoryStore(Path(data_dir) / "memory.json")
        self.options = build_options(self.memory, resume=resume, stderr_log=stderr_log)
        self.client = client_class(options=self.options)
        self.session_id = resume
        self.turns = []
        # Running totals start at 0 in a new session. A resumed session's first totals
        # may include old spend and time, so that turn's values are unknown (None).
        self._last_total = None if resume else 0.0
        self._last_api_ms = None if resume else 0
        print(LOG, f"{'resume session ' + resume if resume else 'new session'}")

    async def __aenter__(self):
        await self.client.connect()
        return self

    async def __aexit__(self, *exc_info):
        await self.client.disconnect()

    async def ask(self, user_text):
        """One user turn. Returns {"text", "model_calls", "tools_used", "usage", "session_id"}."""
        print(LOG, f"user: {user_text}")
        start = time.perf_counter()
        await self.client.query(user_text)

        tools_used, call_ids, result = [], set(), None
        async for message in self.client.receive_response():
            if isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
                call_ids.add(message.message_id)  # parallel tool calls share one id
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        name = block.name.removeprefix(f"mcp__{SERVER_NAME}__")
                        tools_used.append(name)
                        print(LOG, f"model called {name}")
            elif isinstance(message, ResultMessage):
                result = message

        if result is None:
            raise RuntimeError("The SDK finished without a ResultMessage")
        if result.is_error:
            print(LOG, f"warning: result {result.subtype} {result.errors or ''}")

        usage = turn_usage(result, len(call_ids), tools_used, time.perf_counter() - start,
                           self._last_total, self._last_api_ms)
        self._last_total = result.total_cost_usd or 0.0
        self._last_api_ms = result.duration_api_ms
        self.session_id = result.session_id
        self.turns.append(usage)
        print(LOG, f"turn done: {usage['model_calls']} model calls, session {self.session_id}")
        return {
            "text": result.result or "",
            "model_calls": usage["model_calls"],
            "tools_used": tools_used,
            "usage": usage,
            "session_id": self.session_id,
        }
