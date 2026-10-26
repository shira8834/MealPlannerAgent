"""Offline tests for compare.py."""
import json

import pytest

import compare


def make_results(turn_usages, checks="9/9"):
    turns = [{"user": "q", "answer": "a", "tools": tools, "usage": usage} for usage, tools in turn_usages]
    return {"model": "claude-opus-5-5", "effort": "medium", "checks_passed": checks,
            "sessions": [{"name": "s1", "turns": turns[:1]}, {"name": "s2", "turns": turns[1:]}]}


def usage(inp, cr, cw, out, calls=2, cost=0.01, sec=1.0, session_cost=None):
    u = {"input_tokens": inp, "cache_read_tokens": cr, "cache_write_tokens": cw,
         "output_tokens": out, "model_calls": calls, "cost_usd": cost, "seconds": sec}
    if session_cost is not None:
        u["session_cost_usd"] = session_cost  # a running total that must NOT be added
    return u


# ---------- lines of code ----------

def test_code_lines_skip_blank_comments_and_docstrings():
    source = '"""Module doc."""\n\n# a comment\nx = 1  # inline\n\ndef f():\n    """Doc\n    more."""\n    return (x +\n            2)\n'
    assert sorted(compare.code_lines(source)) == [4, 6, 9, 10]


def test_count_loc_of_one_function(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("def a():\n    return 1\n\n\nclass C:\n    def b(self):\n        # c\n"
                    "        y = 2\n        return y\n", encoding="utf-8")
    assert compare.count_loc(path, "a") == 2
    assert compare.count_loc(path, "C.b") == 3
    assert compare.count_loc(path) == 6


def test_loc_table_covers_all_eight_harness_files():
    rows, totals = compare.loc_table()
    assert [r[0] for r in rows] == compare.HARNESS_FILES
    assert all(r[1] > 0 for r in rows)  # every API harness file has code
    built_in = {r[0] for r in rows if r[3] == "built into the SDK"}
    assert built_in == {"history.py", "compaction.py", "caching.py"}
    assert totals["api_harness"] == sum(r[1] for r in rows)
    assert totals["sdk_all"] > 0


# ---------- summaries and cache % ----------

def test_summary_adds_each_turn_once_and_ignores_running_totals():
    results = make_results([
        (usage(10, 900, 100, 50, session_cost=0.01), ["search_recipes"]),
        (usage(20, 1800, 200, 70, cost=0.02, session_cost=0.03), ["save_preference", "plan_meals"]),
    ])
    s = compare.summarize(results)
    assert s["input_tokens"] == 30 and s["cache_read_tokens"] == 2700
    assert s["cost_usd"] == pytest.approx(0.03)  # 0.01 + 0.02, not + 0.03 running total
    assert s["tool_calls"] == 3 and s["model_calls"] == 4
    # 2700 / (30 + 2700 + 300) = 89.1%
    assert s["cache_read_pct"] == 89.1
    assert s["cache_write_pct"] == 9.9


def test_cache_pct_with_no_tokens_does_not_crash():
    s = compare.summarize(make_results([(usage(0, 0, 0, 0), []), (usage(0, 0, 0, 0), [])]))
    assert s["cache_read_pct"] == 0.0


def test_unknown_turn_cost_is_marked_partial():
    s = compare.summarize(make_results([(usage(1, 1, 1, 1, cost=None), []), (usage(1, 1, 1, 1), [])]))
    assert s["cost_complete"] is False
    assert "(partial)" in compare.results_table({"api": None, "sdk": s})


# ---------- missing results: nothing is invented ----------

def test_missing_api_results_show_pending(tmp_path):
    sdk_path = tmp_path / "sdk.json"
    sdk_path.write_text(json.dumps(make_results([(usage(4, 100, 50, 10), []),
                                                 (usage(4, 200, 0, 10), [])])), encoding="utf-8")
    report, summaries = compare.build_report({"api": tmp_path / "api.json", "sdk": sdk_path})
    assert summaries["api"] is None
    assert compare.PENDING in report
    api_cells = [line.split("|")[2].strip() for line in report.splitlines()
                 if line.startswith("| ") and "Metric" not in line and "---" not in line
                 and "harness" not in line and ".py" not in line]
    assert set(api_cells) == {compare.PENDING}  # no API number anywhere


def test_both_results_fill_both_columns(tmp_path):
    paths = {}
    for version, out in (("api", 30), ("sdk", 40)):
        paths[version] = tmp_path / f"{version}.json"
        paths[version].write_text(json.dumps(make_results([(usage(5, 100, 20, out), []),
                                                           (usage(5, 100, 0, out), [])])),
                                  encoding="utf-8")
    report, summaries = compare.build_report(paths)
    assert compare.PENDING not in report
    assert "| Output tokens | 60 | 80 |" in report
    assert "(SDK estimate)" in report


# ---------- simulated API results ----------

def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def api_and_sdk(tmp_path, simulated_api):
    api = make_results([(usage(5, 100, 20, 30, cost=0.5, sec=9.0), ["search_recipes"]),
                        (usage(5, 100, 0, 30), [])])
    api["simulated"] = simulated_api
    sdk = make_results([(usage(4, 300, 50, 40), ["search_recipes"]), (usage(4, 300, 0, 40), [])])
    return api, sdk


def table_rows(report):
    return {line.split("|")[1].strip(): [c.strip() for c in line.split("|")[2:4]]
            for line in report.splitlines() if line.startswith("| ") and ".py" not in line}


def test_simulated_api_never_shows_measured_numbers(tmp_path):
    api, sdk = api_and_sdk(tmp_path, simulated_api=True)
    paths = {"api": tmp_path / "api.json", "sdk": write(tmp_path / "sdk.json", sdk),
             "api_simulated": write(tmp_path / "api_simulated.json", api)}
    report, summaries = compare.build_report(paths)
    rows = table_rows(report)
    assert rows["Metric"][0] == "API (SIMULATED)" and rows["Metric"][1] == "SDK"
    for key, label in compare.ROWS:
        api_cell = rows[label][0]
        if key in compare.MEASURED_ONLY:
            assert api_cell == compare.NOT_MEASURED, label   # no fake number at all
        else:
            assert api_cell.endswith("(simulated)"), label
    assert "$0.5" not in report and "9.0" not in report     # the fake cost and time are hidden
    assert rows["Output tokens"][1] == "80"                  # the real SDK column is unchanged
    assert "SIMULATION" in report and "no API vs SDK number should be concluded" in report


def test_real_api_results_win_over_simulated(tmp_path):
    api, sdk = api_and_sdk(tmp_path, simulated_api=False)
    simulated, _ = api_and_sdk(tmp_path, simulated_api=True)
    paths = {"api": write(tmp_path / "api.json", api), "sdk": write(tmp_path / "sdk.json", sdk),
             "api_simulated": write(tmp_path / "api_simulated.json", simulated)}
    report, summaries = compare.build_report(paths)
    assert summaries["api"]["simulated"] is False
    assert "SIMULATED" not in report and table_rows(report)["Output tokens"][0] == "60"


def test_simulation_file_is_marked_everywhere(tmp_path, monkeypatch):
    import simulate_api
    monkeypatch.setattr(simulate_api, "OUT_PATH", tmp_path / "results" / "api_simulated.json")
    monkeypatch.setattr(simulate_api, "DATA_DIR", tmp_path / "data")
    simulate_api.main()
    data = json.loads(simulate_api.OUT_PATH.read_text(encoding="utf-8"))
    assert data["simulated"] is True and "NOT measurements" in data["data_source"]
    assert data["totals"]["simulated"] is True
    for session in data["sessions"]:
        assert session["simulated"] is True
        assert all(turn["usage"]["simulated"] is True for turn in session["turns"])
    assert data["checks_passed"] == "9/9"
    assert not (tmp_path / "results" / "api.json").exists()  # never pretends to be the real run


def test_real_sdk_results_can_be_summarized():
    data = compare.load_results(compare.RESULTS["sdk"])
    if data is None:
        pytest.skip("results/sdk.json not created yet")
    s = compare.summarize(data)
    assert s["turns"] == 8
    assert s["model_calls"] == data["totals"]["model_calls"]
