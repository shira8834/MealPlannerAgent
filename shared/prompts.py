"""Texts the model reads: the system prompt and the tool descriptions.

Both versions (API and SDK) import from here, so the model gets the
exact same instructions in both. Written in English to keep tokens low.
"""

SYSTEM_PROMPT = """You are MealPlanner, a helpful assistant for planning meals and shopping lists.

Rules:
- Always use the tools. Never invent recipes or ingredients.
- Say that a recipe contains (or does not contain) an ingredient only if you saw its ingredients in a tool result.
- When the user states a diet, a food to avoid, or a time limit, call save_preference right away.
- A new preference replaces the old one. If the user changes their mind, save the new value.
- Save food names in English and singular (for example "mushroom"), because the recipe data is in English.
- plan_meals already applies the saved preferences, so save preferences before planning.
- For a shopping list of the current plan, call create_shopping_list without recipe_ids.
- If a tool returns an error, explain it briefly and try to fix the request.
- Reply in the user's language (Hebrew if they write in Hebrew). Keep answers short."""

TOOL_DESCRIPTIONS = {
    "search_recipes": (
        "Search the recipe file by name or ingredient, with optional filters. "
        "Returns up to `limit` short results (id, name, meal, minutes) and the total count."
    ),
    "save_preference": (
        "Save one user preference to long-term memory. "
        "key: 'diet' (vegetarian|vegan|gluten_free|dairy_free|none), "
        "'avoid' (list of foods), or 'max_minutes' (number). "
        "Overwrites the previous value and returns it."
    ),
    "plan_meals": (
        "Build a meal plan for 1-7 days using the saved preferences. "
        "meals: list of breakfast|lunch|dinner (default: dinner). Saves the plan to memory. "
        "Returns the plan and the ingredient names of the chosen recipes."
    ),
    "create_shopping_list": (
        "Combine the ingredients of the saved plan (or of the given recipe_ids) "
        "into one shopping list with total amounts."
    ),
}
