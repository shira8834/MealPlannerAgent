"""Helpers for running scenario.json. Both API/main.py and SDK/main.py use them."""
import json
import shutil
from pathlib import Path

from shared.checks import run_checks
from shared.config import EFFORT, MODEL

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = PROJECT_ROOT / "scenario.json"

# Files and folders a run creates inside its data folder
RUN_STATE = ["memory.json", "history", "compactions", "last_session.txt"]


def load_scenario(path=SCENARIO_PATH):
    scenario = json.loads(Path(path).read_text(encoding="utf-8"))
    sessions = scenario.get("sessions")
    if not sessions or len(sessions) != 2:
        raise ValueError("scenario must have exactly 2 sessions")
    for session in sessions:
        if not session.get("name") or not session.get("turns"):
            raise ValueError("every session needs a name and turns")
        if not all(isinstance(t, str) and t.strip() for t in session["turns"]):
            raise ValueError(f"empty turn in {session['name']}")
    total = sum(len(s["turns"]) for s in sessions)
    if not 6 <= total <= 8:
        raise ValueError(f"scenario must have 6-8 turns, got {total}")
    return scenario


def reset_data_dir(data_dir):
    """Delete only the state files of a previous run, so the run starts clean."""
    data_dir = Path(data_dir)
    for name in RUN_STATE:
        path = data_dir / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    print(f"[shared/scenario.py] clean start in {data_dir}")


def sum_turns(turns):
    keys = ["input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens",
            "model_calls", "cost_usd", "seconds"]
    return {k: round(sum(t.get(k) or 0 for t in turns), 6) for k in keys}


def build_results(version, sessions, memory_at_start):
    all_usage = [turn["usage"] for s in sessions for turn in s["turns"]]
    results = {
        "version": version,
        "model": MODEL,
        "effort": EFFORT,
        "memory_at_start": memory_at_start,
        "sessions": sessions,
        "totals": sum_turns(all_usage),
    }
    results["checks"] = run_checks(results)
    passed = sum(c["passed"] for c in results["checks"])
    results["checks_passed"] = f"{passed}/{len(results['checks'])}"
    return results


def save_results(results, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[shared/scenario.py] results saved to {out_path}")


def print_checks(results):
    for check in results["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  {mark}  {check['name']}: {check['detail']}")
    print(f"  checks passed: {results['checks_passed']}")
