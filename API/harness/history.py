"""Conversation history: append-only, saved to a JSONL file (one message per line).

Append-only means we only ever ADD messages - never edit or delete old ones.
The model's content blocks (text, thinking, tool_use) are saved exactly as they
came back, because the API needs them unchanged to continue tool use.
"""
import json
from pathlib import Path

LOG = "[harness/history.py]"


def to_jsonable(content):
    """Turn SDK block objects into plain dicts that json can save."""
    if isinstance(content, str):
        return content
    blocks = []
    for block in content:
        if hasattr(block, "model_dump"):  # an SDK object such as TextBlock or ToolUseBlock
            blocks.append(block.model_dump(mode="json", exclude_none=True))
        else:  # already a dict (for example our tool_result dicts)
            blocks.append(block)
    return blocks


class History:
    def __init__(self, path):
        self.path = Path(path)
        self._messages = []
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        self._messages.append(json.loads(line))
            print(LOG, f"loaded {len(self._messages)} messages from {self.path.name}")

    def append(self, role, content):
        """Add one message to memory and to the end of the file."""
        message = {"role": role, "content": to_jsonable(content)}
        self._messages.append(message)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:  # "a" = append, never overwrite
            f.write(json.dumps(message, ensure_ascii=False) + "\n")
        print(LOG, f"append {role} (total {len(self._messages)})")

    def messages(self):
        """A copy of all messages, so nobody can change the history from outside."""
        return list(self._messages)

    def __len__(self):
        return len(self._messages)
