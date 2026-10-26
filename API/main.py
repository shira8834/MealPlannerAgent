"""Entry point for the API version.

Chat in the terminal:
    uv run python -m API.main --session s1

Run the scenario and save the results:
    uv run python -m API.main --scenario scenario.json --out results/api.json

This makes REAL (paid) API calls, and needs ANTHROPIC_API_KEY in the .env file.
"""
import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as "python API/main.py": make the project folder importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
from dotenv import load_dotenv

from API.agent import DATA_DIR, MealPlannerAgent
from shared.memory_store import MemoryStore
from shared.scenario import (build_results, load_scenario, print_checks, reset_data_dir,
                             save_results)


def run_scenario(scenario_path, out_path, client, data_dir=DATA_DIR):
    """Every session starts with a NEW agent instance; memory stays on disk between them."""
    scenario = load_scenario(scenario_path)
    reset_data_dir(data_dir)
    memory_at_start = MemoryStore(data_dir / "memory.json").snapshot()

    sessions = []
    for session in scenario["sessions"]:
        agent = MealPlannerAgent(client, session_id=session["name"], data_dir=data_dir)
        turns = []
        for user_text in session["turns"]:
            result = agent.ask(user_text)
            turns.append({"user": user_text, "answer": result["text"],
                          "tools": result["tools_used"], "usage": result["usage"]})
        sessions.append({"name": session["name"], "session_id": session["name"],
                         "memory_after": agent.memory.store.snapshot(), "turns": turns})

    results = build_results("api", sessions, memory_at_start)
    save_results(results, out_path)
    print_checks(results)
    return results


def chat(client, session_id):
    agent = MealPlannerAgent(client, session_id=session_id)
    print("Type a message (or 'exit' to quit).")
    while True:
        user_text = input("you> ").strip()
        if user_text.lower() in ("exit", "quit", "יציאה"):
            break
        if user_text:
            print("agent>", agent.ask(user_text)["text"])


def main():
    parser = argparse.ArgumentParser(description="MealPlanner agent (Messages API)")
    parser.add_argument("--session", default="s1", help="session id (one history file per session)")
    parser.add_argument("--scenario", help="run this scenario file instead of a chat")
    parser.add_argument("--out", default="results/api.json", help="where to save scenario results")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Hebrew output on Windows

    load_dotenv()  # reads .env into environment variables; the key is never printed
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is missing. Copy .env.example to .env and add your key.")
        return

    client = anthropic.Anthropic()
    if args.scenario:
        run_scenario(args.scenario, args.out, client)
    else:
        chat(client, args.session)


if __name__ == "__main__":
    main()
