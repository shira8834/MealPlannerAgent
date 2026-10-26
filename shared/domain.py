"""The four meal-planning tools, written as plain Python functions.

There is no AI here. Both the API version and the SDK version call these
same functions, so the comparison between them is fair.

Rules for every tool:
- Return a short dict (short output = fewer tokens for the model).
- On bad input, raise ValueError with a clear message.
  The harness turns that into an error result (is_error) for the model.
"""
import json
from pathlib import Path

RECIPES_PATH = Path(__file__).resolve().parent / "recipes.json"

MEAL_TYPES = ["breakfast", "lunch", "dinner"]
DIETS = ["vegetarian", "vegan", "gluten_free", "dairy_free"]
PREFERENCE_KEYS = ["diet", "avoid", "max_minutes"]
MAX_DAYS = 7


def load_recipes(path=RECIPES_PATH):
    """Read the recipes file (this is the tool's external source)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _uses_avoided_food(recipe, avoid):
    """True if any ingredient contains an avoided word ("peanut" -> "peanut butter")."""
    for ingredient in recipe["ingredients"]:
        for food in avoid:
            if food.lower() in ingredient["item"].lower():
                return True
    return False


def _matches(recipe, meal=None, diet=None, avoid=None, max_minutes=None):
    """Check one recipe against all filters. A filter that is None is skipped."""
    if meal and recipe["meal"] != meal:
        return False
    if diet and diet not in recipe["tags"]:
        return False
    if avoid and _uses_avoided_food(recipe, avoid):
        return False
    if max_minutes and recipe["minutes"] > max_minutes:
        return False
    return True


def search_recipes(query="", meal=None, diet=None, avoid=None, max_minutes=None,
                   limit=5, recipes=None):
    """Tool 1: find recipes by name/ingredient and filters."""
    if recipes is None:
        recipes = load_recipes()
    if meal and meal not in MEAL_TYPES:
        raise ValueError(f"meal must be one of {MEAL_TYPES}")
    if diet and diet not in DIETS:
        raise ValueError(f"diet must be one of {DIETS}")

    query = query.lower().strip()
    found = []
    for recipe in recipes:
        ingredient_names = " ".join(i["item"] for i in recipe["ingredients"])
        text = (recipe["name"] + " " + ingredient_names).lower()
        if query and query not in text:
            continue
        if _matches(recipe, meal, diet, avoid, max_minutes):
            found.append(recipe)

    # Only the short fields, not the full ingredient list
    short = [
        {"id": r["id"], "name": r["name"], "meal": r["meal"], "minutes": r["minutes"]}
        for r in found[:limit]
    ]
    return {"count": len(found), "recipes": short}


def save_preference(store, key, value):
    """Tool 2: save one preference to memory. A new value replaces the old one."""
    if key not in PREFERENCE_KEYS:
        raise ValueError(f"key must be one of {PREFERENCE_KEYS}")

    if key == "diet":
        value = str(value).lower().strip()
        if value == "none":
            value = None  # the user no longer follows a diet
        elif value not in DIETS:
            raise ValueError(f"diet must be one of {DIETS} or 'none'")
    elif key == "avoid":
        if isinstance(value, str):
            value = value.split(",")  # allow "peanuts, fish"
        value = [str(food).lower().strip() for food in value if str(food).strip()]
    elif key == "max_minutes":
        value = int(value)
        if value <= 0:
            raise ValueError("max_minutes must be a positive number")

    previous = store.set_preference(key, value)
    return {"saved": key, "value": value, "previous": previous}


def plan_meals(store, days=3, meals=None, recipes=None):
    """Tool 3: build a meal plan using the preferences saved in memory."""
    if recipes is None:
        recipes = load_recipes()
    if meals is None:
        meals = ["dinner"]
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}")
    for meal in meals:
        if meal not in MEAL_TYPES:
            raise ValueError(f"meal must be one of {MEAL_TYPES}")

    prefs = store.get_preferences()
    names = {r["id"]: r["name"] for r in recipes}

    # For each meal type, collect the recipes that fit the preferences
    options = {}
    for meal in meals:
        options[meal] = [
            r["id"] for r in recipes
            if _matches(r, meal, prefs.get("diet"), prefs.get("avoid"), prefs.get("max_minutes"))
        ]
        if not options[meal]:
            raise ValueError(f"No {meal} recipes match the saved preferences {prefs}")

    # Go over the options in order; start again if there are more days than recipes
    plan_days = []
    for day in range(1, days + 1):
        day_plan = {"day": day}
        for meal in meals:
            ids = options[meal]
            day_plan[meal] = ids[(day - 1) % len(ids)]
        plan_days.append(day_plan)

    store.save_last_plan({"days": plan_days})

    # Show the model "r11 Pasta with Tomato Sauce" instead of only "r11"
    readable = [
        {k: (f"{v} {names[v]}" if k != "day" else v) for k, v in d.items()}
        for d in plan_days
    ]
    # Ingredient names of the chosen recipes only (not the whole recipe file),
    # so the model never has to guess what a planned recipe contains
    by_id = {r["id"]: r for r in recipes}
    chosen = sorted({rid for d in plan_days for k, rid in d.items() if k != "day"})
    ingredients = {rid: ", ".join(i["item"] for i in by_id[rid]["ingredients"]) for rid in chosen}
    return {"days": readable, "ingredients": ingredients, "applied_preferences": prefs}


def _format_amount(amount):
    """4.0 -> "4", 2.5 -> "2.5" """
    return str(int(amount)) if amount == int(amount) else str(amount)


def create_shopping_list(store, recipe_ids=None, recipes=None):
    """Tool 4: add up all ingredients of a plan into one shopping list.
    Without recipe_ids, it uses the last plan saved in memory."""
    if recipes is None:
        recipes = load_recipes()
    by_id = {r["id"]: r for r in recipes}

    if recipe_ids is None:
        plan = store.get_last_plan()
        if plan is None:
            raise ValueError("No saved meal plan. Call plan_meals first.")
        recipe_ids = []
        for day in plan["days"]:
            for meal, recipe_id in day.items():
                if meal != "day":
                    recipe_ids.append(recipe_id)

    unknown = [rid for rid in recipe_ids if rid not in by_id]
    if unknown:
        raise ValueError(f"Unknown recipe ids: {unknown}")

    # Same item + same unit -> add the amounts together
    totals = {}
    for rid in recipe_ids:
        for ingredient in by_id[rid]["ingredients"]:
            key = (ingredient["item"], ingredient["unit"])
            totals[key] = totals.get(key, 0) + ingredient["amount"]

    items = [
        f"{item}: {_format_amount(amount)} {unit}"
        for (item, unit), amount in sorted(totals.items())
    ]
    return {"count": len(items), "items": items}
