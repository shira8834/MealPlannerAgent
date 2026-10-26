"""Long-term memory for the API agent. Uses the MemoryStore from shared/.

Memory is separate from history: history is the chat of one session,
memory is the user's preferences that stay between sessions.
context.py decides which part of the memory the model sees.
"""
from shared.memory_store import MemoryStore

LOG = "[harness/memory.py]"


class Memory:
    def __init__(self, path):
        self.store = MemoryStore(path)  # the tools write to this same store

    def preferences(self):
        """Saved preferences without empty values (for example diet=None after "none")."""
        prefs = self.store.get_preferences()
        saved = {key: value for key, value in prefs.items() if value not in (None, [], "")}
        print(LOG, f"read {len(saved)} preferences")
        return saved

    def last_plan(self):
        plan = self.store.get_last_plan()
        print(LOG, "read last plan" if plan else "no saved plan")
        return plan

    def reset(self):
        print(LOG, "reset memory")
        self.store.reset()
