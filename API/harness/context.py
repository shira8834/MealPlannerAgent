"""Context engineering: put only RELEVANT memory in front of the model.

Important rule (Claude Opus 5.5): inside a session we never remove or edit old
messages, and never change the system prompt - that would break the model's
saved thinking blocks and the prompt cache. So we don't cut messages here.
Instead, for each new user message we pick only the memory facts that relate
to it, and attach them to that message (append-only).
"""
from shared import domain

LOG = "[harness/context.py]"

# Words that show what the user is asking about (English + Hebrew, lowercase)
TOPIC_WORDS = {
    "preferences": [
        "prefer", "diet", "vegan", "vegetarian", "allerg", "avoid", "remember", "about me",
        "העדפ", "טבעונ", "צמחונ", "אלרג", "דיאט", "זוכר", "עליי", "לא אוכל", "רגיש",
    ],
    "plan": [
        "plan", "meal", "breakfast", "lunch", "dinner", "recipe", "cook", "eat", "week", "day",
        "תוכנית", "תכנן", "ארוח", "בוקר", "צהרי", "ערב", "מתכון", "לבשל", "לאכול", "שבוע", "ימים",
    ],
    "shopping": [
        "shopping", "grocer", "buy", "list", "ingredient",
        "קניות", "לקנות", "סופר", "רשימ", "מצרכ", "רכיב",
    ],
}


def find_topics(user_text):
    text = user_text.lower()
    return {topic for topic, words in TOPIC_WORDS.items() if any(w in text for w in words)}


def select_context(user_text, memory):
    """Return a short text with only the relevant memory, or None if nothing is relevant."""
    topics = find_topics(user_text)
    lines = []

    prefs = memory.preferences()
    if prefs and topics & {"preferences", "plan"}:
        lines.append("Saved preferences: " + ", ".join(f"{k}={v}" for k, v in sorted(prefs.items())))

    plan = memory.last_plan()
    if plan and topics & {"plan", "shopping"}:
        names = {r["id"]: r["name"] for r in domain.load_recipes()}
        days = []
        for day in plan["days"]:
            meals = [f"{meal} {rid} {names.get(rid, '')}" for meal, rid in day.items() if meal != "day"]
            days.append(f"day {day['day']}: " + "; ".join(meals))
        lines.append("Saved meal plan: " + " | ".join(days))

    print(LOG, f"topics={sorted(topics)} -> {len(lines)} memory facts selected")
    return "\n".join(lines) if lines else None


def build_user_content(user_text, memory):
    """The content of the new user message: relevant memory (if any) + the user's text.
    Always a list of blocks, so the message looks the same in every later request."""
    context = select_context(user_text, memory)
    blocks = [{"type": "text", "text": user_text}]
    if context is not None:
        blocks.insert(0, {"type": "text", "text": f"<memory>\n{context}\n</memory>"})
    return blocks


def check_sequence(messages):
    """Make sure the messages are a valid conversation before sending:
    starts with user, and every tool_use has its tool_result in the next message."""
    if not messages or messages[0]["role"] != "user":
        raise ValueError("messages must start with a user message")
    for i, message in enumerate(messages):
        if message["role"] != "assistant" or isinstance(message["content"], str):
            continue
        tool_ids = {b["id"] for b in message["content"] if b["type"] == "tool_use"}
        if not tool_ids:
            continue
        if i + 1 == len(messages):
            raise ValueError(f"message {i}: tool_use without tool_result")
        next_content = messages[i + 1]["content"]
        result_ids = set()
        if not isinstance(next_content, str):
            result_ids = {b["tool_use_id"] for b in next_content if b["type"] == "tool_result"}
        if tool_ids != result_ids:
            raise ValueError(f"message {i}: tool_use ids {tool_ids} != tool_result ids {result_ids}")
    print(LOG, f"sequence ok ({len(messages)} messages)")
