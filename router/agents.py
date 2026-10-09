"""Four stub agents that mirror the shape of the real platform.

* ``voicemail-v1``  - read-only diagnosis (deterministic, fixture-backed)
* ``status-v1``     - read-only service status lookup
* ``support-v1``    - answers FAQs and phrases the safe reply used on escalation
* ``provision-v1``  - the one agent that can *change* things. It exists in the
                      registry so we can prove it is unreachable from the
                      customer-facing channels.

Nothing here talks to a network. Every agent is a pure function of its input,
which is what lets the golden scenarios run in CI with no services at all.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from router.models import AgentResult, Channel, ToolSpec


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    # True if invoking this can change state. The scope tests key off this flag.
    mutating: bool = False
    # False for capabilities the router calls itself (e.g. the escalation reply).
    # They stay reachable for the router but are never shown to the planner LLM.
    planner_visible: bool = True

    def tool_spec(self) -> ToolSpec:
        schema = self.parameters or {"type": "object", "properties": {}}
        return ToolSpec(name=self.name, description=self.description, parameters=schema)


class Agent(ABC):
    agent_id: str
    capabilities: dict[str, Capability]

    def __init__(self) -> None:
        # Every invocation is recorded here. Safety assertions ("this agent
        # must never run") read this counter rather than trusting the trace.
        self.calls: list[str] = []

    async def invoke(self, capability: str, payload: dict[str, Any], channel: Channel) -> AgentResult:
        self.calls.append(capability)
        return await self._handle(capability, payload, channel)

    @abstractmethod
    async def _handle(
        self, capability: str, payload: dict[str, Any], channel: Channel
    ) -> AgentResult: ...


# --- voicemail-v1 -----------------------------------------------------------

# Fixture snapshots keyed by a 10-digit user id. A real agent would build these
# from read-only provider API calls.
_VOICEMAIL_SNAPSHOTS: dict[str, dict[str, Any]] = {
    "5551230001": {"voicemail_enabled": False, "mailbox_full": False},
    "5551230002": {"voicemail_enabled": True, "mailbox_full": True},
    "5551230003": {"voicemail_enabled": True, "mailbox_full": False},
}

_USER_ID = re.compile(r"^\d{10}$")


class VoicemailAgent(Agent):
    agent_id = "voicemail-v1"
    capabilities = {
        "diagnose_voicemail": Capability(
            name="diagnose_voicemail",
            description=(
                "Diagnose why a user's voicemail is not working. Read-only: "
                "reports findings and recommended fixes but never applies them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "10-digit user id / phone number"}
                },
                "required": ["user_id"],
            },
        )
    }

    async def _handle(
        self, capability: str, payload: dict[str, Any], channel: Channel
    ) -> AgentResult:
        user_id = str(payload.get("user_id", "")).strip()
        if not _USER_ID.match(user_id):
            # We cannot diagnose without an id. Low confidence is what pushes
            # the router into its escalation path.
            return AgentResult(
                confidence=0.3,
                public={"summary": "I need the 10-digit number of the affected user to check this."},
            )

        snap = _VOICEMAIL_SNAPSHOTS.get(user_id)
        if snap is None:
            return AgentResult(
                confidence=0.4,
                public={"summary": "I couldn't find that user, so I can't diagnose it yet."},
                internal={"lookup": "miss"},
            )

        findings: list[str] = []
        fixes: list[str] = []
        if not snap["voicemail_enabled"]:
            findings.append("voicemail is switched off")
            fixes.append("enable_voicemail")  # a label only; nothing is applied here
        if snap["mailbox_full"]:
            findings.append("the mailbox is full")
            fixes.append("clear_mailbox")

        summary = (
            "Voicemail looks healthy for this user."
            if not findings
            else "Found: " + " and ".join(findings) + "."
        )
        return AgentResult(
            confidence=0.9,
            public={"summary": summary, "recommended_fixes": fixes},
            internal={"raw_snapshot": snap, "user_id": user_id},
        )


# --- status-v1 --------------------------------------------------------------

_REGION_STATUS = {"us-east": "operational", "us-west": "operational", "eu-central": "degraded"}


class StatusAgent(Agent):
    agent_id = "status-v1"
    capabilities = {
        "check_service_status": Capability(
            name="check_service_status",
            description="Check whether the voice service is up in a region. Read-only.",
            parameters={
                "type": "object",
                "properties": {
                    "region": {"type": "string", "description": "e.g. us-east, us-west, eu-central"}
                },
            },
        )
    }

    async def _handle(
        self, capability: str, payload: dict[str, Any], channel: Channel
    ) -> AgentResult:
        region = str(payload.get("region", "")).lower().strip()
        state = _REGION_STATUS.get(region)
        if state is None:
            return AgentResult(
                confidence=0.5,
                public={"summary": "Which region do you want me to check? (us-east, us-west, eu-central)"},
            )
        return AgentResult(
            confidence=0.95,
            public={"summary": f"The service in {region} is {state}."},
            internal={"source": "static-fixture-table"},
        )


# --- support-v1 -------------------------------------------------------------

_FAQ = {
    "password": "You can reset your portal password from the sign-in page using 'Forgot password'.",
    "invoice": "Invoices are available under Billing in the customer portal.",
}


class SupportAgent(Agent):
    agent_id = "support-v1"
    capabilities = {
        "answer_question": Capability(
            name="answer_question",
            description="Answer a general product or account question from the FAQ.",
            parameters={
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        ),
        "safe_reply": Capability(
            name="safe_reply",
            description="Phrase a safe customer-facing reply when a conversation is escalated.",
            parameters={"type": "object", "properties": {"situation": {"type": "string"}}},
            planner_visible=False,
        ),
    }

    async def _handle(
        self, capability: str, payload: dict[str, Any], channel: Channel
    ) -> AgentResult:
        if capability == "safe_reply":
            return AgentResult(
                confidence=0.9,
                public={
                    "summary": "Thanks for reaching out. A teammate will follow up with you shortly."
                },
            )

        question = str(payload.get("question", "")).lower()
        for keyword, answer in _FAQ.items():
            if keyword in question:
                return AgentResult(confidence=0.85, public={"summary": answer})
        # No FAQ hit: answer honestly and ask for a human to take over.
        return AgentResult(
            confidence=0.55,
            escalate=True,
            public={"summary": "I don't have an article for that, so I've asked the team to help."},
        )


# --- provision-v1 -----------------------------------------------------------


class ProvisionAgent(Agent):
    """The only mutating agent. Only the admin channel may reach it."""

    agent_id = "provision-v1"
    capabilities = {
        "apply_voicemail_fix": Capability(
            name="apply_voicemail_fix",
            description="Apply a voicemail fix (enable voicemail, clear mailbox) for a user.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["enable_voicemail", "clear_mailbox"]},
                },
                "required": ["user_id", "action"],
            },
            mutating=True,
        )
    }

    async def _handle(
        self, capability: str, payload: dict[str, Any], channel: Channel
    ) -> AgentResult:
        action = payload.get("action", "?")
        return AgentResult(
            confidence=0.9,
            public={"summary": f"Applied {action}."},
            internal={"mutated": True},
        )


def default_agents() -> list[Agent]:
    return [VoicemailAgent(), StatusAgent(), SupportAgent(), ProvisionAgent()]
