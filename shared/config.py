"""Settings that BOTH versions use, so the API vs SDK comparison is fair."""

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_STEPS = 10  # max model calls in one user turn (stops endless tool loops)
