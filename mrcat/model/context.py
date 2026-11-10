"""Whole-request token estimates and model-specific context budgets.

Estimates deliberately allow more space for multilingual text than the default
four-characters-per-token heuristic. Provider usage remains the measured count.
"""
from dataclasses import dataclass
import json
import os

from langchain_core.messages.utils import count_tokens_approximately


class ContextBudgetExceeded(RuntimeError):
    """Pause without discarding unsummarized work or sending an oversized request."""


def tokens(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    # UTF-8 bytes account for CJK and symbols that a character-only heuristic misses.
    return max(int(count_tokens_approximately([("user", text)], chars_per_token=3.0)),
               (len(text.encode("utf-8")) + 2) // 3) + 16


@dataclass(frozen=True)
class ContextBudget:
    window: int
    output: int
    margin: int

    @classmethod
    def configured(cls, model):
        overrides = json.loads(os.environ.get("MRCAT_MODEL_CONTEXT_TOKENS", "{}"))
        window = int(overrides.get(model, os.environ.get("MRCAT_CONTEXT_TOKENS", "131072")))
        output = int(os.environ.get("MRCAT_MAX_OUTPUT_TOKENS", "32768"))
        margin = max(256, window // 32)
        if window <= 0 or output <= 0 or window - output - margin < 1024:
            raise ValueError("Context capacity must leave at least 1024 input tokens after output and safety reserves.")
        return cls(window, output, margin)

    @property
    def input_limit(self):
        return self.window - self.output - self.margin

    @property
    def summary_trigger(self):
        return int(self.input_limit * .85)

    @property
    def summary_target(self):
        return int(self.input_limit * .60)

    def measure(self, system, context, tool=None):
        return tokens(system) + tokens(context) + (tokens(tool) if tool else 0)

    def check(self, system, context, tool=None):
        estimated = self.measure(system, context, tool)
        if estimated > self.input_limit:
            raise ContextBudgetExceeded(
                f"Estimated input {estimated} exceeds the {self.input_limit}-token input budget. "
                "History and evidence are preserved; reduce the requested evidence or configure "
                "the served model's actual context capacity before continuing.")
        return estimated
