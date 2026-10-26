"""Long-term memory: saves the user's food preferences in a JSON file on disk.

Memory is separate from the chat history:
- history = everything that was said in the conversation
- memory  = a few facts we keep between sessions (diet, foods to avoid, last plan)
"""
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = PROJECT_ROOT / "data" / "memory.json"


class MemoryStore:
    def __init__(self, path=DEFAULT_MEMORY_PATH):
        self.path = Path(path)

    def _read(self):
        """Read the whole memory file. A missing file means empty memory."""
        if not self.path.exists():
            return {"preferences": {}, "last_plan": None}
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data):
        """Write to a temp file first, then rename it.
        This way a crash in the middle never leaves a broken memory file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.path)

    def get_preferences(self):
        return self._read()["preferences"]

    def set_preference(self, key, value):
        """Save one preference. Returns the old value (None if it is new)."""
        data = self._read()
        old_value = data["preferences"].get(key)
        data["preferences"][key] = value
        self._write(data)
        return old_value

    def get_last_plan(self):
        return self._read()["last_plan"]

    def save_last_plan(self, plan):
        data = self._read()
        data["last_plan"] = plan
        self._write(data)

    def snapshot(self):
        """A copy of everything in memory (used to record the state after each session)."""
        return self._read()

    def reset(self):
        """Delete the memory file, so a run can start from a clean state."""
        if self.path.exists():
            self.path.unlink()
