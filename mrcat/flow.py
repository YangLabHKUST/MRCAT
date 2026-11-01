"""Checkpointed session and control state shared by all role subgraphs."""
from typing import TypedDict

class Flow(TypedDict, total=False):
    session: dict
    coding_stop: bool
    coding_call: dict
    coding_action_id: str
    sid: str
    request: str
    role: str
    decision: dict
    plan: dict
    action: dict
    handoff: dict
    rounds: int
    manager_attempts: int
    manager_error: str
    next_node: str
    ending: str
    review_reason: str
    review: dict
    recovering: bool
    recoveries: int
    evaluations: int
    failures: int
    format_errors: int
    unchanged: int
    fingerprints: list[str]
    item_round_start: int
