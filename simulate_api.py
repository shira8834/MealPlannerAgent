"""SIMULATED run of the API version: scenario.json with a FakeClient, no real model.

    python simulate_api.py            -> results/api_simulated.json

What this shows: the API harness (loop, tools, history, memory, context,
compaction, caching, tokens) runs the 8 turns end to end, and the 9 checks
pass on the state it saves.
What it does NOT show: real model behavior, tokens, cache hits, cost or time.
Those numbers come from the fake client and are marked as simulated.
It never overwrites results/api.json (the real run).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from API.main import run_scenario  # noqa: E402
from shared.scenario import SCENARIO_PATH, save_results  # noqa: E402
from tests.fake_client import FakeClient  # noqa: E402
from tests.scripted_model import api_responses  # noqa: E402

OUT_PATH = ROOT / "results" / "api_simulated.json"
DATA_DIR = ROOT / "data" / "api_simulated"  # never the real run's data/api

NOTE = ("SIMULATED: FakeClient with a scripted model, no API call. The tool calls, saved state "
        "and checks are real harness behavior on scripted model answers. Tokens, cache, cost and "
        "time are fake numbers, NOT measurements, and must not be compared with real runs.")


def mark_simulated(results):
    results["simulated"] = True
    results["data_source"] = NOTE
    results["totals"] = {"simulated": True, **results["totals"]}
    for session in results["sessions"]:
        session["simulated"] = True
        for turn in session["turns"]:
            turn["usage"] = {"simulated": True, **turn["usage"]}
    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # The runner saves its own copy inside the simulation data folder; only the
    # marked copy goes to results/, so an unmarked file never appears there
    results = run_scenario(SCENARIO_PATH, DATA_DIR / "unmarked_results.json",
                           FakeClient(api_responses()), data_dir=DATA_DIR)
    save_results(mark_simulated(results), OUT_PATH)
    print(f"[simulate_api.py] {NOTE}")


if __name__ == "__main__":
    main()
