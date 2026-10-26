"""Compare the API run and the SDK run of scenario.json, and count lines of code.

    python compare.py                       (print the tables)
    python compare.py --out results/comparison.md

Only numbers from results/api.json and results/sdk.json are used. If a file is
missing, its column says so - no value is invented. If there is no real API run
but results/api_simulated.json exists, the API column shows the simulation:
only its functional results (checks, tools), never its fake tokens, cache, cost or time.
"""
import argparse
import ast
import io
import json
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = {"api": ROOT / "results" / "api.json", "sdk": ROOT / "results" / "sdk.json",
           "api_simulated": ROOT / "results" / "api_simulated.json"}
PENDING = "waiting for the API run"
NOT_MEASURED = "simulated - not a measurement"
# Rows that only mean something in a real run; a simulation never shows a number for them
MEASURED_ONLY = {"input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens",
                 "cache_read_pct", "cache_write_pct", "seconds", "cost_usd"}

HARNESS_FILES = ["loop.py", "tools.py", "history.py", "memory.py",
                 "context.py", "compaction.py", "caching.py", "tokens.py"]

# What does the same job in the SDK version: (file, function or None for the whole file),
# or None when the SDK does it by itself (built in, no code of ours)
SDK_EQUIVALENT = {
    "loop.py": ("SDK/agent.py", "SDKMealPlannerAgent.ask"),
    "tools.py": ("SDK/tools.py", None),
    "history.py": None,      # resume=session_id
    "memory.py": ("SDK/agent.py", "memory_text"),
    "context.py": ("SDK/agent.py", "make_memory_hook"),
    "compaction.py": None,   # automatic compaction
    "caching.py": None,      # automatic cache_control
    "tokens.py": ("SDK/agent.py", "turn_usage"),
}

TOKEN_KEYS = ["input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens"]


# ---------- lines of code ----------

def _docstring_lines(tree):
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                lines.update(range(body[0].lineno, body[0].end_lineno + 1))
    return lines


def code_lines(source):
    """Line numbers that hold code: no blank lines, comments or docstrings."""
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
            tokenize.DEDENT, tokenize.ENDMARKER, tokenize.ENCODING}
    lines = set()
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type not in skip:
            lines.update(range(tok.start[0], tok.end[0] + 1))
    return lines - _docstring_lines(ast.parse(source))


def count_loc(path, function=None):
    """Code lines of a file, or of one function ("name" or "Class.method") in it."""
    source = Path(path).read_text(encoding="utf-8")
    lines = code_lines(source)
    if function is None:
        return len(lines)
    tree = ast.parse(source)
    *class_name, func_name = function.split(".")
    scope = tree.body
    if class_name:
        scope = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name[0]).body
    node = next(n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == func_name)
    return len({n for n in lines if node.lineno <= n <= node.end_lineno})


def loc_table(root=ROOT):
    rows = []
    for name in HARNESS_FILES:
        api_loc = count_loc(root / "API" / "harness" / name)
        equivalent = SDK_EQUIVALENT[name]
        if equivalent is None:
            rows.append((name, api_loc, 0, "built into the SDK"))
        else:
            file, function = equivalent
            where = f"{file}::{function}" if function else file
            rows.append((name, api_loc, count_loc(root / file, function), where))
    totals = {
        "api_harness": sum(r[1] for r in rows),
        "api_all": sum(count_loc(p) for p in [*(root / "API" / "harness").glob("*.py"),
                                             root / "API" / "agent.py", root / "API" / "main.py"]),
        "sdk_all": sum(count_loc(root / "SDK" / f) for f in ("agent.py", "tools.py", "main.py")),
    }
    return rows, totals


# ---------- run results ----------

def load_results(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def summarize(results):
    """Totals from the per-turn usage. Each turn is counted once; running totals such as
    session_cost_usd are NOT added, so nothing is counted twice."""
    turns = [t for s in results["sessions"] for t in s["turns"]]
    usage = [t["usage"] for t in turns]
    s = {k: sum(u.get(k) or 0 for u in usage) for k in TOKEN_KEYS}
    s["model_calls"] = sum(u.get("model_calls") or 0 for u in usage)
    s["tool_calls"] = sum(len(t["tools"]) for t in turns)
    s["seconds"] = round(sum(u.get("seconds") or 0 for u in usage), 2)
    s["cost_usd"] = round(sum(u.get("cost_usd") or 0 for u in usage), 6)
    s["cost_complete"] = all(u.get("cost_usd") is not None for u in usage)
    # All input-side tokens = uncached input + read from cache + written to cache
    all_input = s["input_tokens"] + s["cache_read_tokens"] + s["cache_write_tokens"]
    s["cache_read_pct"] = round(100 * s["cache_read_tokens"] / all_input, 1) if all_input else 0.0
    s["cache_write_pct"] = round(100 * s["cache_write_tokens"] / all_input, 1) if all_input else 0.0
    s["turns"] = len(turns)
    s["checks_passed"] = results.get("checks_passed", "?")
    s["model"], s["effort"] = results.get("model"), results.get("effort")
    s["simulated"] = bool(results.get("simulated"))
    return s


ROWS = [
    ("model", "Model"), ("effort", "Effort"), ("turns", "Turns"),
    ("input_tokens", "Input tokens (not cached)"), ("cache_read_tokens", "Cache read tokens"),
    ("cache_write_tokens", "Cache write tokens"), ("output_tokens", "Output tokens"),
    ("cache_read_pct", "Cache read % of input"), ("cache_write_pct", "Cache write % of input"),
    ("model_calls", "Model calls"), ("tool_calls", "Tool calls"), ("seconds", "Time (s)"),
    ("cost_usd", "Cost (USD)"), ("checks_passed", "Checks passed"),
]


def _header(version, s):
    name = version.upper()
    return f"{name} (SIMULATED)" if s and s["simulated"] else name


def results_table(summaries):
    api, sdk = summaries.get("api"), summaries.get("sdk")
    lines = [f"| Metric | {_header('api', api)} | {_header('sdk', sdk)} |", "|---|---|---|"]
    for key, label in ROWS:
        cells = []
        for version in ("api", "sdk"):
            s = summaries.get(version)
            if s is None:
                cells.append(PENDING)
            elif s["simulated"]:
                cells.append(NOT_MEASURED if key in MEASURED_ONLY else f"{s[key]} (simulated)")
            else:
                value = s[key]
                if key == "cost_usd":
                    value = f"${value:.4f}" + ("" if s["cost_complete"] else " (partial)")
                    if version == "sdk":
                        value += " (SDK estimate)"
                elif key.endswith("_pct"):
                    value = f"{value}%"
                cells.append(str(value))
        lines.append(f"| {label} | {cells[0]} | {cells[1]} |")
    return "\n".join(lines)


def loc_markdown(rows, totals):
    lines = ["| API harness file | API lines | SDK lines | SDK part that does this job |",
             "|---|---|---|---|"]
    lines += [f"| {name} | {api} | {sdk} | {where} |" for name, api, sdk, where in rows]
    lines.append(f"| **harness total** | **{totals['api_harness']}** | "
                 f"**{sum(r[2] for r in rows)}** | |")
    lines.append("")
    lines.append(f"All API code (harness + agent.py + main.py): {totals['api_all']} lines. "
                 f"All SDK code (agent.py + tools.py + main.py): {totals['sdk_all']} lines. "
                 "Counted without blank lines, comments and docstrings; shared/ is used by both and not counted.")
    return "\n".join(lines)


def build_report(results_paths=RESULTS, root=ROOT):
    summaries = {}
    for version in ("api", "sdk"):
        data = load_results(results_paths[version])
        if data is None and version == "api" and results_paths.get("api_simulated"):
            data = load_results(results_paths["api_simulated"])  # real run always wins
        summaries[version] = summarize(data) if data else None
    rows, totals = loc_table(root)
    parts = ["## Run results (scenario.json)", results_table(summaries)]
    if summaries["api"] is None:
        parts.append(f"\nresults/api.json is missing: the comparison is {PENDING}.")
    elif summaries["api"]["simulated"]:
        parts.append("\nThe API column is a SIMULATION (FakeClient with a scripted model, no API call). "
                     "It shows that the API harness runs the scenario and passes the checks on the "
                     "state it saves. It does not show real model behavior, so tokens, cache, cost "
                     "and time are not compared, and no API vs SDK number should be concluded from "
                     "this table. A real comparison needs results/api.json.")
    parts += ["", "## Lines of code", loc_markdown(rows, totals)]
    return "\n".join(parts), summaries


def main():
    parser = argparse.ArgumentParser(description="Compare API and SDK results")
    parser.add_argument("--out", help="also save the tables to this markdown file")
    args = parser.parse_args()
    report, _ = build_report()
    print(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\nsaved to {args.out}")


if __name__ == "__main__":
    main()
