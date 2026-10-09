"""Builds a router from a scenario file and runs it through ``router.run``.

A scenario can stub the planner (what the "model" proposes), override what
individual capabilities return, and swap in an adversarial synthesizer. Anything
it does not override uses the real toy agents, so the happy-path scenarios
exercise real agent code too.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from router import scope
from router.agents import Agent, Capability, default_agents
from router.models import AgentResult, Channel, Message, PlanStep, Response
from router.orchestrator import run
from router.planner import ScriptedPlanner
from router.registry import Registry, default_applications
from router.trace import RunTrace

SCENARIO_DIR = Path(__file__).parent / "scenarios"


class OverriddenAgent(Agent):
    """Wraps a real agent; capabilities named in ``overrides`` return canned results.

    The wrapper keeps its own ``calls`` list, so "this agent must never run"
    assertions look at what really reached the agent boundary.
    """

    def __init__(self, inner: Agent, overrides: dict[str, dict[str, Any]]) -> None:
        super().__init__()
        self._inner = inner
        self._overrides = overrides
        self.agent_id = inner.agent_id
        self.capabilities: dict[str, Capability] = inner.capabilities

    async def _handle(self, capability: str, payload: dict[str, Any], channel: Channel) -> AgentResult:
        spec = self._overrides.get(capability)
        if spec is None:
            return await self._inner._handle(capability, payload, channel)
        if spec.get("delay_ms"):
            await asyncio.sleep(spec["delay_ms"] / 1000)
        if spec.get("raise"):
            raise RuntimeError(spec["raise"])
        fields = {k: v for k, v in spec.items() if k not in {"delay_ms", "raise"}}
        return AgentResult(**fields)


class FixedSynthesizer:
    """Always returns the same reply, whatever the tool results say.

    Used to prove the post-synthesis guard replaces a reply that leaks agent
    internal data.
    """

    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def synthesize(self, user_text: str, public_results: list[dict[str, Any]]) -> str | None:
        return self._reply


class ObedientSynthesizer:
    """A worst-case synthesizer: it does whatever instructions appear in tool output.

    If hostile text ever reaches it, the reply says so. The router is expected to
    have removed that text before this point.
    """

    async def synthesize(self, user_text: str, public_results: list[dict[str, Any]]) -> str | None:
        blob = " ".join(str(v) for r in public_results for v in r.values()).lower()
        if "ignore" in blob and "instructions" in blob:
            return "Refund approved. Applying the fix for every user now."
        return "ok"


def _synthesizer(spec: dict[str, Any] | None) -> Any:
    if not spec:
        return None
    if spec["kind"] == "fixed":
        return FixedSynthesizer(spec["reply"])
    if spec["kind"] == "obedient":
        return ObedientSynthesizer()
    raise ValueError(f"unknown synthesizer kind {spec['kind']!r}")


@dataclass
class Outcome:
    response: Response
    trace: RunTrace
    registry: Registry
    planner: ScriptedPlanner
    reachable: list[str]

    def invoked(self) -> list[str]:
        """Every capability that actually reached an agent, in call order per agent."""
        return [cap for agent in self.registry.agents for cap in agent.calls]


def load_scenarios(directory: Path = SCENARIO_DIR) -> list[dict[str, Any]]:
    scenarios = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        data["_file"] = path.name
        scenarios.append(data)
    return scenarios


def _reachable(spec: Any) -> list[str]:
    # "channel:chat" means "whatever the front door grants the chat channel".
    if isinstance(spec, str) and spec.startswith("channel:"):
        return scope.reachable_for(Channel(spec.split(":", 1)[1]))
    return list(spec)


async def run_scenario(scenario: dict[str, Any]) -> Outcome:
    inp = scenario["input"]
    stub = scenario.get("stub", {})
    overrides: dict[str, dict[str, Any]] = stub.get("agents", {})

    agents: list[Agent] = [OverriddenAgent(a, overrides) for a in default_agents()]
    registry = Registry(agents, default_applications())

    planner = ScriptedPlanner(
        [PlanStep(**s) for s in stub.get("plan", [])], fail=bool(stub.get("planner_error"))
    )
    msg = Message(
        channel=Channel(inp.get("channel", "chat")),
        application_id=inp.get("application_id"),
        text=inp["text"],
    )
    reachable = _reachable(inp["reachable_caps"])
    response, trace = await run(
        msg, reachable, registry=registry, planner=planner,
        synthesizer=_synthesizer(stub.get("synthesizer")),
    )
    return Outcome(response, trace, registry, planner, reachable)
