"""Agent registry and per-application capability mapping.

Two independent gates decide whether a capability can run:

1. the *channel scope* (``scope.py``) - what the front door lets a channel ask for
2. the *application mapping* here - what an application has switched on

``expand_reachable`` intersects both with what is actually registered, so a
misconfiguration in one layer does not by itself make a tool reachable.
"""

from __future__ import annotations

from router.agents import Agent, Capability, default_agents


class Registry:
    def __init__(self, agents: list[Agent], applications: dict[str, set[str]]) -> None:
        self._agents = {a.agent_id: a for a in agents}
        self._by_cap: dict[str, Agent] = {}
        for agent in agents:
            for name in agent.capabilities:
                self._by_cap[name] = agent
        self._applications = applications

    @property
    def agents(self) -> list[Agent]:
        return list(self._agents.values())

    def agent_for(self, capability: str) -> Agent | None:
        return self._by_cap.get(capability)

    def capability(self, name: str) -> Capability | None:
        agent = self._by_cap.get(name)
        return agent.capabilities[name] if agent else None

    def all_capabilities(self) -> list[str]:
        return sorted(self._by_cap)

    def expand_reachable(self, reachable_caps: list[str], application_id: str) -> list[str]:
        """Return the capabilities this application may actually run, in the
        caller's order. Unknown applications get nothing."""
        enabled = self._applications.get(application_id, set())
        out: list[str] = []
        for cap in reachable_caps:
            if cap in enabled and cap in self._by_cap and cap not in out:
                out.append(cap)
        return out


# The customer-facing app has no access to the mutating capability; the ops
# console does. Both are registered with the same four agents.
_CUSTOMER_CAPS = {"diagnose_voicemail", "check_service_status", "answer_question", "safe_reply"}
_OPS_CAPS = _CUSTOMER_CAPS | {"apply_voicemail_fix"}


def default_applications() -> dict[str, set[str]]:
    return {"help-chat": set(_CUSTOMER_CAPS), "ops-console": set(_OPS_CAPS)}


def default_registry() -> Registry:
    return Registry(default_agents(), default_applications())
