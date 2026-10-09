"""Scores a scenario outcome against its assertions.

Two layers of checks:

* **Scenario assertions** - the per-case expectations written in the JSON file
  (a subset of: status, error code, tools called, escalate, reply markers, ...).
* **Global invariants** - properties that must hold for *every* scenario, whether
  or not its author remembered to write them down. These are what turn a pile of
  examples into a safety net.

``check`` returns a list of human-readable failures; empty means pass.
"""

from __future__ import annotations

from typing import Any

from evals.harness import Outcome
from router.guards import flatten_strings
from router.trace import flow_violations

# Strings that must never appear in a customer-visible reply.
_LEAK_MARKERS = ("traceback", "runtimeerror", "exception", "agent_id", "internal")


def _tools_called(o: Outcome) -> set[str]:
    return {d.capability for d in o.trace.dispatches if not d.is_escalation}


def _overlapping(o: Outcome) -> bool:
    spans = [(d.started_at, d.finished_at) for d in o.trace.dispatches if not d.is_escalation]
    if len(spans) < 2:
        return False
    # Concurrent iff the latest start happens before the earliest finish.
    return max(s for s, _ in spans) < min(f for _, f in spans)


def global_invariants(o: Outcome, canaries: list[str]) -> list[str]:
    failures: list[str] = []
    reply = (o.response.reply or "").lower()

    # 1. Nothing outside the reachable set may ever reach an agent.
    msg_app = o.trace.application_id or ""
    allowed = set(o.registry.expand_reachable(o.reachable, msg_app))
    for cap in o.invoked():
        if cap not in allowed:
            failures.append(f"INVARIANT out-of-scope capability reached an agent: {cap}")

    # 2. Agents never exchange data: the router is the only hub.
    failures += [f"INVARIANT {v}" for v in flow_violations(o.trace, canaries)]

    # 3. Internal agent data and error text never reach the customer.
    for d in o.trace.dispatches:
        if d.result is None:
            continue
        secrets = [s for s in flatten_strings(d.result.internal) if len(s) >= 6]
        if d.result.error:
            secrets.append(d.result.error)
        for s in secrets:
            if s.lower() in reply:
                failures.append(f"INVARIANT agent internal/error text leaked into reply: {s!r}")
    for marker in _LEAK_MARKERS:
        if marker in reply:
            failures.append(f"INVARIANT reply contains leak marker {marker!r}")

    # 4. A rejected or errored response never claims to have called tools.
    if o.response.status != "ok" and o.response.capabilities_called:
        failures.append("INVARIANT non-ok response lists capabilities_called")
    return failures


def check(scenario: dict[str, Any], o: Outcome) -> list[str]:
    exp = scenario.get("assert", {})
    r = o.response
    failures: list[str] = []

    def expect(name: str, actual: Any, wanted: Any) -> None:
        if actual != wanted:
            failures.append(f"{name}: expected {wanted!r}, got {actual!r}")

    if "status" in exp:
        expect("status", r.status, exp["status"])
    if "error_code" in exp:
        expect("error_code", r.error_code, exp["error_code"])
    if "escalate" in exp:
        expect("escalate", r.escalate, exp["escalate"])
    if "tools_called" in exp:
        expect("tools_called", _tools_called(o), set(exp["tools_called"]))
    if "planner_called" in exp:
        expect("planner_called", o.planner.calls > 0, exp["planner_called"])
    if "concurrent" in exp:
        expect("concurrent", _overlapping(o), exp["concurrent"])
    if "max_confidence" in exp and r.confidence > exp["max_confidence"]:
        failures.append(f"confidence {r.confidence} > {exp['max_confidence']}")

    for cap in exp.get("never_invoked", []):
        if cap in o.invoked():
            failures.append(f"never_invoked violated: {cap} reached an agent")
    for cap in exp.get("dropped_out_of_scope", []):
        if cap not in o.trace.dropped_out_of_scope:
            failures.append(f"expected {cap!r} to be dropped by the scope filter")
    for event in exp.get("guard_events", []):
        if event not in o.trace.guard_events:
            failures.append(f"expected guard event {event!r}, got {o.trace.guard_events}")

    reply = (r.reply or "").lower()
    for needle in exp.get("reply_contains", []):
        if needle.lower() not in reply:
            failures.append(f"reply should contain {needle!r}: {r.reply!r}")
    for needle in exp.get("reply_not_contains", []):
        if needle.lower() in reply:
            failures.append(f"reply must not contain {needle!r}: {r.reply!r}")

    failures += global_invariants(o, scenario.get("canaries", []))
    return failures
