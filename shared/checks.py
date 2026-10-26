"""Pass/fail checks for a scenario run. Same checks for the API and the SDK version.

Most checks read the SAVED STATE (memory snapshot after each session) and the
tool trace, not the model's text. Only one check reads an answer.
"""
from shared import domain

MUSHROOM = "mushroom"


def _plan_ids(plan):
    if not plan:
        return []
    return [rid for day in plan["days"] for meal, rid in day.items() if meal != "day"]


def _uses_mushroom(recipe_ids):
    by_id = {r["id"]: r for r in domain.load_recipes()}
    return any(MUSHROOM in i["item"] for rid in recipe_ids for i in by_id[rid]["ingredients"])


def _avoids_mushroom(memory):
    return any(MUSHROOM in food for food in memory["preferences"].get("avoid") or [])


def _tools(session):
    return [name for turn in session["turns"] for name in turn["tools"]]


def _mushroom_recipes_allowed(memory):
    """Ids of mushroom recipes that pass the SAVED preferences (diet, avoid, time limit)."""
    prefs = memory["preferences"]
    found = domain.search_recipes(query=MUSHROOM, diet=prefs.get("diet"), avoid=prefs.get("avoid"),
                                  max_minutes=prefs.get("max_minutes"), limit=20)
    return [r["id"] for r in found["recipes"]]


def run_checks(results):
    """Returns a list of {"name", "passed", "detail"}."""
    s1, s2 = results["sessions"]
    mem1, mem2 = s1["memory_after"], s2["memory_after"]
    plan1, plan2 = _plan_ids(mem1["last_plan"]), _plan_ids(mem2["last_plan"])
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    start = results["memory_at_start"]
    add("clean_start", not start["preferences"] and start["last_plan"] is None,
        f"memory at start: {start}")

    add("search_tool_used", "search_recipes" in s1["turns"][0]["tools"],
        f"turn 1 tools: {s1['turns'][0]['tools']}")

    add("mushroom_preference_saved", _avoids_mushroom(mem1),
        f"avoid after session 1: {mem1['preferences'].get('avoid')}")

    add("plan_3_days_without_mushrooms",
        len(plan1) == 3 and not _uses_mushroom(plan1),
        f"plan after session 1: {plan1}")

    shopping_ok = False
    if plan1:
        items = domain.create_shopping_list(None, recipe_ids=plan1)["items"]
        shopping_ok = not any(MUSHROOM in item for item in items)
    add("shopping_list_created",
        "create_shopping_list" in s1["turns"][3]["tools"] and shopping_ok,
        f"turn 4 tools: {s1['turns'][3]['tools']}")

    add("new_instance_in_session2", s1["session_id"] != s2["session_id"],
        f"session ids: {s1['session_id']} / {s2['session_id']}")

    answer = s2["turns"][0]["answer"]
    add("memory_recalled_in_session2", "פטרי" in answer or MUSHROOM in answer.lower(),
        "turn 5 answer mentions mushrooms" if "פטרי" in answer or MUSHROOM in answer.lower()
        else "turn 5 answer does not mention mushrooms")

    add("contradiction_replaced_old_preference",
        not _avoids_mushroom(mem2) and "save_preference" in _tools(s2),
        f"avoid after session 2: {mem2['preferences'].get('avoid')}")

    # The new plan does not HAVE to contain mushrooms - they only have to be allowed again
    allowed = _mushroom_recipes_allowed(mem2)
    add("mushroom_recipes_available_again",
        not _avoids_mushroom(mem2) and len(allowed) > 0
        and len(plan2) == 3 and "plan_meals" in _tools(s2),
        f"mushroom recipes allowed now: {allowed}; plan after session 2: {plan2}")

    return checks
