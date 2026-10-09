"""Planners turn a user message into a *proposed* list of tool calls.

The router never trusts a planner. ``OllamaPlanner`` is the real thing;
``ScriptedPlanner`` replays a fixed plan so the golden scenarios can exercise
everything downstream of the model deterministically.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from router.models import Plan, PlanStep, ToolSpec

CLASSIFY_SYSTEM_PROMPT = (
    "You route customer support requests to tools. "
    "Call only tools from the provided list, and fill in their arguments from the "
    "user's message. If the request is outside what the tools can do, or asks for "
    "a change that none of the tools performs, reply briefly without calling any tool. "
    "Never invent tool names."
)


class PlannerError(RuntimeError):
    """The planner could not produce a plan (model down, timeout, bad reply)."""


class Planner(Protocol):
    async def plan(self, text: str, tools: list[ToolSpec]) -> Plan: ...


class ScriptedPlanner:
    """Returns a canned plan, or raises, regardless of input. Counts calls."""

    def __init__(self, steps: list[PlanStep] | None = None, *, fail: bool = False) -> None:
        self._steps = steps or []
        self._fail = fail
        self.calls = 0

    async def plan(self, text: str, tools: list[ToolSpec]) -> Plan:
        self.calls += 1
        if self._fail:
            raise PlannerError("scripted planner outage")
        return Plan(steps=list(self._steps))


class OllamaPlanner:
    """Tool-calling planner backed by a local Ollama model."""

    def __init__(
        self,
        model: str = "llama3.2",
        host: str = "http://localhost:11434",
        *,
        temperature: float = 0.0,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    async def plan(self, text: str, tools: list[ToolSpec]) -> Plan:
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": self.temperature},
            "messages": [
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.host}/api/chat", json=body)
                resp.raise_for_status()
                message = resp.json().get("message", {})
        except (httpx.HTTPError, ValueError) as exc:
            raise PlannerError(f"{type(exc).__name__}: {exc}") from exc

        steps: list[PlanStep] = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            name = fn.get("name")
            if not isinstance(name, str):
                continue
            args = fn.get("arguments")
            steps.append(PlanStep(capability=name, arguments=args if isinstance(args, dict) else {}))
        return Plan(steps=steps)
