"""JSON schemas of the tool inputs. The API version and the SDK version both use
these exact schemas, so the model sees the same tools in both."""
from shared import domain

INPUT_SCHEMAS = {
    "search_recipes": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Word in the recipe name or ingredients"},
            "meal": {"type": "string", "enum": domain.MEAL_TYPES},
            "diet": {"type": "string", "enum": domain.DIETS},
            "avoid": {"type": "array", "items": {"type": "string"}},
            "max_minutes": {"type": "integer", "minimum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "additionalProperties": False,
    },
    "save_preference": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "enum": domain.PREFERENCE_KEYS},
            "value": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "integer"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
        },
        "required": ["key", "value"],
        "additionalProperties": False,
    },
    "plan_meals": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "minimum": 1, "maximum": domain.MAX_DAYS},
            "meals": {"type": "array", "items": {"type": "string", "enum": domain.MEAL_TYPES}},
        },
        "required": ["days"],
        "additionalProperties": False,
    },
    "create_shopping_list": {
        "type": "object",
        "properties": {
            "recipe_ids": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    },
}
