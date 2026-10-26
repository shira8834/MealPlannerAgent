"""Entry point for the SDK version.

Chat (Hebrew) - new session / continue the last one / continue a given session id:
    uv run python -m SDK.main
    uv run python -m SDK.main --last
    uv run python -m SDK.main --resume <session_id>

Run a scenario file and save the results (used in the measurement step):
    uv run python -m SDK.main --scenario scenario.json --out results/sdk.json

Authentication: the SDK uses your Claude Code login (claude.ai / Pro subscription).
If ANTHROPIC_API_KEY is set, the SDK would use it instead and bill the API,
so this program stops unless you pass --allow-api-key.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as "python SDK/main.py": make the project folder importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from SDK.agent import DATA_DIR, SDKMealPlannerAgent
from shared.memory_store import MemoryStore
from shared.scenario import (build_results, load_scenario, print_checks, reset_data_dir,
                             save_results)

LAST_SESSION_FILE = DATA_DIR / "last_session.txt"
DEFAULT_STDERR_LOG = DATA_DIR / "logs" / "sdk_stderr.log"  # data/ is in .gitignore
BILLED_CREDENTIALS = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                      "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"]


def save_last_session(session_id):
    LAST_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_SESSION_FILE.write_text(session_id, encoding="utf-8")


async def chat(resume=None, stderr_log=None):
    async with SDKMealPlannerAgent(resume=resume, stderr_log=stderr_log) as agent:
        print("שלום! אני MealPlanner. כתבי הודעה (או 'יציאה' כדי לסיים).")
        while True:
            user_text = input("את> ").strip()
            if user_text in ("יציאה", "exit", "quit"):
                break
            if not user_text:
                continue
            result = await agent.ask(user_text)
            save_last_session(result["session_id"])
            print("סוכן>", result["text"])
        if agent.session_id:
            print(f"מזהה הסשן: {agent.session_id}  (להמשך: --resume {agent.session_id} או --last)")


async def run_scenario(scenario_path, out_path, data_dir=DATA_DIR, client_class=None,
                       stderr_log=None):
    """Every session starts with a NEW agent instance (as after restarting the program).
    The data folder is cleaned first, so every run starts from a clean state."""
    scenario = load_scenario(scenario_path)
    reset_data_dir(data_dir)
    memory_at_start = MemoryStore(data_dir / "memory.json").snapshot()
    extra = {"client_class": client_class} if client_class else {}
    if stderr_log:
        extra["stderr_log"] = stderr_log

    sessions = []
    for session in scenario["sessions"]:
        agent = SDKMealPlannerAgent(data_dir=data_dir, **extra)  # new instance, no resume
        turns = []
        async with agent:
            for user_text in session["turns"]:
                result = await agent.ask(user_text)
                turns.append({"user": user_text, "answer": result["text"],
                              "tools": result["tools_used"], "usage": result["usage"]})
        sessions.append({"name": session["name"], "session_id": agent.session_id,
                         "memory_after": agent.memory.snapshot(), "turns": turns})

    results = build_results("sdk", sessions, memory_at_start)
    save_results(results, out_path)
    print_checks(results)
    return results


def main():
    parser = argparse.ArgumentParser(description="MealPlanner agent (Claude Agent SDK)")
    parser.add_argument("--resume", help="continue the session with this id")
    parser.add_argument("--last", action="store_true", help="continue the last session")
    parser.add_argument("--scenario", help="run this scenario file instead of a chat")
    parser.add_argument("--out", default="results/sdk.json", help="where to save scenario results")
    parser.add_argument("--stderr-log", nargs="?", const=str(DEFAULT_STDERR_LOG),
                        help=f"save Claude Code's stderr to a log file (default: {DEFAULT_STDERR_LOG})")
    parser.add_argument("--allow-api-key", action="store_true",
                        help="allow ANTHROPIC_API_KEY (this bills the API, not the subscription)")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Hebrew output on Windows

    # Any of these comes BEFORE the subscription login, and would bill an API account instead
    billed = [name for name in BILLED_CREDENTIALS if os.environ.get(name)]
    if billed and not args.allow_api_key:
        print(f"מוגדר: {', '.join(billed)}. ה-SDK יחייב חשבון API ולא את המנוי. עוצרת.")
        print("כדי להשתמש במנוי: הסירי את המשתנה. כדי להשתמש בו בכל זאת: --allow-api-key")
        return

    if args.stderr_log:
        print(f"[SDK/main.py] stderr of Claude Code -> {args.stderr_log} (secrets are hidden)")

    if args.scenario:
        asyncio.run(run_scenario(args.scenario, args.out, stderr_log=args.stderr_log))
        return

    resume = args.resume
    if args.last:
        if not LAST_SESSION_FILE.exists():
            print("אין סשן קודם שמור.")
            return
        resume = LAST_SESSION_FILE.read_text(encoding="utf-8").strip()
    asyncio.run(chat(resume, stderr_log=args.stderr_log))


if __name__ == "__main__":
    main()
