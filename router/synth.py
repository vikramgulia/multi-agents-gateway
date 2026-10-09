"""Reply synthesis.

In the real system a second LLM round turns tool results into a customer reply.
Here the default is rule-based. The ``Synthesizer`` protocol lets the eval
harness plug in adversarial synthesizers (one that obeys instructions found in
tool output, one that echoes a secret) to check what the pipeline contains.
"""

from __future__ import annotations

from typing import Any, Protocol

GENERIC_SAFE_REPLY = (
    "Thanks for reaching out. I'm connecting you with someone who can help with this."
)


class Synthesizer(Protocol):
    async def synthesize(self, user_text: str, public_results: list[dict[str, Any]]) -> str | None: ...


class RuleSynthesizer:
    """Concatenate the ``summary`` of each agent's public result."""

    async def synthesize(self, user_text: str, public_results: list[dict[str, Any]]) -> str | None:
        parts = [str(r["summary"]) for r in public_results if r.get("summary")]
        return " ".join(parts) if parts else None

