"""The four tools for the Claude Agent SDK, as an in-process MCP server.

# replaces: tools.py - the SDK sends the schemas to the model, dispatches each
# call to the right function and reports errors (isError) for us. We only wrap
# the shared domain functions; no domain logic is copied here.
"""
import json

from claude_agent_sdk import create_sdk_mcp_server, tool

from shared import domain
from shared.prompts import TOOL_DESCRIPTIONS
from shared.tool_schemas import INPUT_SCHEMAS

LOG = "[SDK/tools.py]"
SERVER_NAME = "meals"
# The SDK names MCP tools "mcp__<server>__<tool>"
ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{name}" for name in INPUT_SCHEMAS]


def _run(name, call):
    """Run one domain function and turn the result (or the error) into an MCP result."""
    try:
        result = call()
    except (ValueError, TypeError) as error:
        print(LOG, f"{name} failed: {error}")
        return {"content": [{"type": "text", "text": f"Error: {error}"}], "is_error": True}
    # Same compact JSON as the API version, so the tool outputs cost the same tokens
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    print(LOG, f"{name} ok ({len(text)} chars)")
    return {"content": [{"type": "text", "text": text}]}


def build_tools(store):
    """The four tools. `store` is the MemoryStore the tools read and write."""

    @tool("search_recipes", TOOL_DESCRIPTIONS["search_recipes"], INPUT_SCHEMAS["search_recipes"])
    async def search_recipes(args):
        return _run("search_recipes", lambda: domain.search_recipes(**args))

    @tool("save_preference", TOOL_DESCRIPTIONS["save_preference"], INPUT_SCHEMAS["save_preference"])
    async def save_preference(args):
        return _run("save_preference", lambda: domain.save_preference(store, **args))

    @tool("plan_meals", TOOL_DESCRIPTIONS["plan_meals"], INPUT_SCHEMAS["plan_meals"])
    async def plan_meals(args):
        return _run("plan_meals", lambda: domain.plan_meals(store, **args))

    @tool("create_shopping_list", TOOL_DESCRIPTIONS["create_shopping_list"],
          INPUT_SCHEMAS["create_shopping_list"])
    async def create_shopping_list(args):
        return _run("create_shopping_list", lambda: domain.create_shopping_list(store, **args))

    return [search_recipes, save_preference, plan_meals, create_shopping_list]


def build_server(store):
    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=build_tools(store))
