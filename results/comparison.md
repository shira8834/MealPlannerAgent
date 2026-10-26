## Run results (scenario.json)
| Metric | API (SIMULATED) | SDK |
|---|---|---|
| Model | claude-opus-5-5 (simulated) | claude-opus-5-5 |
| Effort | medium (simulated) | medium |
| Turns | 8 (simulated) | 8 |
| Input tokens (not cached) | simulated - not a measurement | 30 |
| Cache read tokens | simulated - not a measurement | 48618 |
| Cache write tokens | simulated - not a measurement | 7912 |
| Output tokens | simulated - not a measurement | 2456 |
| Cache read % of input | simulated - not a measurement | 86.0% |
| Cache write % of input | simulated - not a measurement | 14.0% |
| Model calls | 14 (simulated) | 15 |
| Tool calls | 6 (simulated) | 7 |
| Time (s) | simulated - not a measurement | 38.68 |
| Cost (USD) | simulated - not a measurement | $0.1226 (SDK estimate) |
| Checks passed | 9/9 (simulated) | 9/9 |

The API column is a SIMULATION (FakeClient with a scripted model, no API call). It shows that the API harness runs the scenario and passes the checks on the state it saves. It does not show real model behavior, so tokens, cache, cost and time are not compared, and no API vs SDK number should be concluded from this table. A real comparison needs results/api.json.

## Lines of code
| API harness file | API lines | SDK lines | SDK part that does this job |
|---|---|---|---|
| loop.py | 29 | 33 | SDK/agent.py::SDKMealPlannerAgent.ask |
| tools.py | 40 | 34 | SDK/tools.py |
| history.py | 34 | 0 | built into the SDK |
| memory.py | 17 | 13 | SDK/agent.py::memory_text |
| context.py | 59 | 8 | SDK/agent.py::make_memory_hook |
| compaction.py | 44 | 0 | built into the SDK |
| caching.py | 15 | 0 | built into the SDK |
| tokens.py | 59 | 19 | SDK/agent.py::turn_usage |
| **harness total** | **297** | **107** | |

All API code (harness + agent.py + main.py): 411 lines. All SDK code (agent.py + tools.py + main.py): 268 lines. Counted without blank lines, comments and docstrings; shared/ is used by both and not counted.
