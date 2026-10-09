"""Wire types shared by the router, the agents and the eval harness."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Channel(StrEnum):
    CHAT = "chat"
    SLACK = "slack"
    ADMIN = "admin"


class Message(BaseModel):
    """An inbound user message, already normalised by whatever sits in front."""

    session_id: str = "s-1"
    channel: Channel = Channel.CHAT
    application_id: str | None = None
    text: str


class AgentResult(BaseModel):
    """What an agent hands back to the router.

    ``public`` is the only part that may be shown to the planner/synthesizer
    LLM or to the customer. ``internal`` is for the router's own bookkeeping
    and must never cross that boundary (raw snapshots, ids, debug output).
    """

    status: Literal["ok", "error"] = "ok"
    confidence: float = 1.0
    escalate: bool = False
    public: dict[str, Any] = Field(default_factory=dict)
    internal: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @classmethod
    def failure(cls, message: str) -> AgentResult:
        return cls(status="error", confidence=0.0, error=message)


class Response(BaseModel):
    """The router's final answer for one message."""

    status: Literal["ok", "rejected", "error"]
    reply: str | None = None
    escalate: bool = False
    confidence: float = 0.0
    capabilities_called: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def rejected(cls, code: str, message: str) -> Response:
        return cls(status="rejected", error_code=code, error_message=message)


class ToolSpec(BaseModel):
    """A capability as it is presented to the planner LLM."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class PlanStep(BaseModel):
    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    """The planner's *raw* proposal. Nothing here is trusted until it has
    passed the scope filter in ``orchestrator.run``."""

    steps: list[PlanStep] = Field(default_factory=list)
