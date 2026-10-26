"""A scripted "model" for scenario.json: what a good model would do in each of the 8 turns.

Used by the offline tests and by simulate_api.py. It is NOT a real model:
the answers are fixed texts and the token numbers are the fake client's defaults.
"""
from tests.fake_client import text_response, tool_response

# (tool, input) for each turn, or None when the turn is answered with text only
SCRIPT = [
    ("search_recipes", {"meal": "dinner"}),
    ("save_preference", {"key": "avoid", "value": ["mushroom"]}),
    ("plan_meals", {"days": 3, "meals": ["dinner"]}),
    ("create_shopping_list", {}),
    None,
    ("save_preference", {"key": "avoid", "value": []}),
    ("plan_meals", {"days": 3, "meals": ["dinner"]}),
    None,
]
RECALL_ANSWER = "שמרתי שאת לא אוכלת פטריות, והתוכנית היא r11, r12, r13."


def answer_for(turn_index):
    return RECALL_ANSWER if turn_index == 4 else f"done {turn_index + 1}"


def api_responses():
    """FakeClient responses for the API runner, in order."""
    responses = []
    for i, step in enumerate(SCRIPT):
        if step:
            responses.append(tool_response((f"t{i}", step[0], step[1])))
        responses.append(text_response(answer_for(i)))
    return responses
