"""RunTrace: a structured record of one routing run.

The trace is the audit surface. It records what the planner proposed, what the
scope filter dropped, exactly which payload each agent received and what came
back. Anything we want to assert about *information flow* between agents is
derived from here, not from agent internals.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from router.guards import flatten_strings
from router.models import AgentResult, PlanStep, Response, ToolSpec


class DispatchRecord(BaseModel):
    capability: str
    agent_id: str
    request_payload: dict[str, Any]
    result: AgentResult | None = None
    # Monotonic timestamps (seconds). Used to prove dispatches overlapped.
    started_at: float = 0.0
    finished_at: float = 0.0
    is_escalation: bool = False


class RunTrace(BaseModel):
    query: str
    application_id: str | None = None
    reachable_caps: list[str] = Field(default_factory=list)
    tools_offered: list[ToolSpec] = Field(default_factory=list)
    planner_called: bool = False
    proposed: list[PlanStep] = Field(default_factory=list)
    # Capabilities the planner asked for that the scope filter removed.
    dropped_out_of_scope: list[str] = Field(default_factory=list)
    dispatches: list[DispatchRecord] = Field(default_factory=list)
    guard_events: list[str] = Field(default_factory=list)
    escalated: bool = False
    notes: list[str] = Field(default_factory=list)
    final: Response | None = None


def _strings(value: Any, min_len: int) -> list[str]:
    return [t for t in flatten_strings(value) if len(t) >= min_len]


def flow_violations(trace: RunTrace, extra_canaries: list[str] | None = None) -> list[str]:
    """Return cross-agent information-flow violations found in ``trace``.

    Agents in this system never talk to each other; the router is the only hub.
    So one agent's ``internal`` output (or any declared canary string) must not
    show up in the request payload sent to a *different* agent.
    """
    violations: list[str] = []

    for dst in trace.dispatches:
        blob = json.dumps(dst.request_payload, default=str)
        for src in trace.dispatches:
            if src.agent_id == dst.agent_id or src.result is None:
                continue
            for secret in _strings(src.result.internal, 6):
                if secret in blob:
                    violations.append(
                        f"{src.agent_id} internal data reached {dst.agent_id} request: {secret!r}"
                    )
        for canary in extra_canaries or []:
            if canary in blob:
                violations.append(f"canary {canary!r} reached {dst.agent_id} request")
    return violations
