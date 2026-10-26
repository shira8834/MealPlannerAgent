"""Tools: JSON schemas for the model, dispatch to shared/domain.py, and error handling.

The domain functions are NOT copied here. This file only:
1. describes each tool to the model (TOOL_SCHEMAS)
2. calls the right domain function when the model asks for a tool
3. turns any error into a tool_result with is_error=True
"""
import json

from shared import domain
from shared.prompts import TOOL_DESCRIPTIONS
from shared.tool_schemas import INPUT_SCHEMAS

LOG = "[harness/tools.py]"

# The Messages API format: name + description + input_schema (schemas are shared with the SDK)
TOOL_SCHEMAS = [
    {"name": name, "description": TOOL_DESCRIPTIONS[name], "input_schema": schema}
    for name, schema in INPUT_SCHEMAS.items()
]

# Tool name -> function that runs it. Each one gets the memory store and the model's arguments.
TOOL_FUNCTIONS = {
    "search_recipes": lambda store, args: domain.search_recipes(**args),
    "save_preference": lambda store, args: domain.save_preference(store, **args),
    "plan_meals": lambda store, args: domain.plan_meals(store, **args),
    "create_shopping_list": lambda store, args: domain.create_shopping_list(store, **args),
}


def run_tool(name, args, store):
    """Run one tool. Returns (result_text, is_error)."""
    if name not in TOOL_FUNCTIONS:
        print(LOG, f"unknown tool: {name}")
        return f"Error: unknown tool '{name}'", True
    try:
        result = TOOL_FUNCTIONS[name](store, args)
    except (ValueError, TypeError) as error:
        # ValueError = bad value, TypeError = wrong/missing argument name
        print(LOG, f"{name} failed: {error}")
        return f"Error: {error}", True
    except Exception as error:
        print(LOG, f"{name} crashed: {error!r}")
        return f"Error: {name} failed unexpectedly ({type(error).__name__})", True

    # Compact JSON (no spaces) = fewer tokens
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    print(LOG, f"{name} ok ({len(text)} chars)")
    return text, False


def run_tool_calls(tool_use_blocks, store):
    """Run every tool_use block from one model response.
    Returns ALL results as one list, so the loop sends them in ONE user message."""
    results = []
    for block in tool_use_blocks:
        print(LOG, f"dispatch {block.name} {json.dumps(block.input, ensure_ascii=False)}")
        text, is_error = run_tool(block.name, block.input, store)
        result = {"type": "tool_result", "tool_use_id": block.id, "content": text}
        if is_error:
            result["is_error"] = True
        results.append(result)
    return results
