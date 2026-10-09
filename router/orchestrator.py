"""The router: plan -> scope-filter -> dispatch -> guard -> synthesize -> escalate.

``run`` is the single production entry point. Evals call it directly so that
concurrency, the scope filter and escalation are all covered by the same code
path real traffic takes.
"""

from __future__ import annotations

import asyncio
import time

from router.guards import GuardLevel, flatten_strings, screen_public
from router.models import AgentResult, Message, Plan, PlanStep, Response, ToolSpec
from router.planner import Planner, PlannerError
from router.registry import Registry
from router.synth import GENERIC_SAFE_REPLY, RuleSynthesizer, Synthesizer
from router.trace import DispatchRecord, RunTrace

LOW_CONFIDENCE_THRESHOLD = 0.5
SUPPORT_SAFE_REPLY = "safe_reply"
AGENT_TIMEOUT_SECONDS = 10.0


def apply_scope_filter(steps: list[PlanStep], allowed: set[str]) -> list[PlanStep]:
    """Drop every planner-proposed step whose capability is not in ``allowed``.

    This is the central safety property of the router. It is a module-level
    function (rather than inlined) so the mutation test can disable it and
    confirm the golden scenarios notice.
    """
    return [s for s in steps if s.capability in allowed]


def needs_escalation(results: list[AgentResult]) -> bool:
    for r in results:
        if r.escalate or r.status == "error":
            return True
        if r.status == "ok" and r.confidence < LOW_CONFIDENCE_THRESHOLD:
            return True
    return False


async def _dispatch(
    registry: Registry, step: PlanStep, msg: Message, trace: RunTrace, *, is_escalation: bool = False
) -> AgentResult:
    agent = registry.agent_for(step.capability)
    if agent is None:  # the registry shrank between expand and dispatch
        return AgentResult.failure(f"no agent for {step.capability!r}")

    record = DispatchRecord(
        capability=step.capability,
        agent_id=agent.agent_id,
        request_payload=dict(step.arguments),
        is_escalation=is_escalation,
    )
    trace.dispatches.append(record)
    record.started_at = time.monotonic()
    try:
        result = await asyncio.wait_for(
            agent.invoke(step.capability, step.arguments, msg.channel), AGENT_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 - an agent crash must not take the run down
        # The exception text is kept for the trace only; it is never shown to the user.
        result = AgentResult.failure(f"{type(exc).__name__}: {exc}")
    record.finished_at = time.monotonic()
    record.result = result
    return result


def _apply_guards(
    steps: list[PlanStep], results: list[AgentResult], trace: RunTrace, level: GuardLevel
) -> list[AgentResult]:
    """Screen each agent's public output before any LLM reads it.

    A result that looks like a prompt injection has its public payload blanked
    (so no LLM ever sees it), is flagged for escalation, and its claimed
    confidence is ignored. Otherwise the (possibly sanitised) payload is forwarded.
    """
    guarded: list[AgentResult] = []
    for step, res in zip(steps, results, strict=True):
        if res.status == "ok":
            public, hostile = screen_public(res.public, level)
            if hostile:
                trace.guard_events.append(f"injection_suspected:{step.capability}")
                res = res.model_copy(update={"public": {}, "escalate": True, "confidence": 0.0})
            elif public != res.public:
                trace.guard_events.append(f"sanitized:{step.capability}")
                res = res.model_copy(update={"public": public})
        guarded.append(res)
    return guarded


def _internal_secrets(results: list[AgentResult]) -> list[str]:
    return [s for r in results for s in flatten_strings(r.internal) if len(s) >= 6]


async def _escalate(
    registry: Registry, qualified: list[str], msg: Message, trace: RunTrace, fallback: Response
) -> Response:
    """Replace the reply with a safe one and mark the response escalated."""
    reply: str | None = None
    if SUPPORT_SAFE_REPLY in qualified:
        step = PlanStep(
            capability=SUPPORT_SAFE_REPLY,
            arguments={"situation": "An agent flagged this conversation for human follow-up."},
        )
        support = await _dispatch(registry, step, msg, trace, is_escalation=True)
        if support.status == "ok" and support.public.get("summary"):
            reply = str(support.public["summary"])
    return fallback.model_copy(
        update={"reply": reply or GENERIC_SAFE_REPLY, "escalate": True, "confidence": 0.0}
    )


async def run(
    msg: Message,
    reachable_caps: list[str],
    *,
    registry: Registry,
    planner: Planner,
    synthesizer: Synthesizer | None = None,
    guard_level: GuardLevel = "v2",
) -> tuple[Response, RunTrace]:
    """Route one message. Returns the response and the full trace."""
    synthesizer = synthesizer or RuleSynthesizer()
    trace = RunTrace(
        query=msg.text, application_id=msg.application_id, reachable_caps=list(reachable_caps)
    )

    def finish(resp: Response) -> tuple[Response, RunTrace]:
        trace.final = resp
        return resp, trace

    if not msg.application_id:
        return finish(Response.rejected("application_required", "application_id is required."))

    qualified = registry.expand_reachable(reachable_caps, msg.application_id)
    if not qualified:
        return finish(
            Response.rejected("no_reachable_capability", "No capability is reachable for this request.")
        )

    # The planner only sees capabilities meant for it. Router-internal ones (the
    # escalation reply) remain in ``qualified`` so escalation can still call them.
    tools: list[ToolSpec] = []
    for name in qualified:
        cap = registry.capability(name)
        if cap is not None and cap.planner_visible:
            tools.append(cap.tool_spec())
    trace.tools_offered = tools

    trace.planner_called = True
    try:
        plan: Plan = await planner.plan(msg.text, tools)
    except PlannerError as exc:
        # Keep "the model is down" distinct from "nothing matched": the first is an
        # incident, the second is a normal answer.
        trace.notes.append(str(exc))
        return finish(Response(status="error", error_code="classifier_unavailable",
                               error_message="The routing model is unavailable."))
    trace.proposed = list(plan.steps)

    # A plan step is only runnable if it was actually offered to the planner.
    allowed = {t.name for t in tools}
    safe_steps = apply_scope_filter(plan.steps, allowed)
    trace.dropped_out_of_scope = [s.capability for s in plan.steps if s.capability not in allowed]
    if not safe_steps:
        return finish(
            Response.rejected("no_reachable_capability", "No in-scope capability matched the request.")
        )

    # Independent steps run concurrently, as in the real orchestrator.
    results = list(
        await asyncio.gather(*(_dispatch(registry, s, msg, trace) for s in safe_steps))
    )
    results = _apply_guards(safe_steps, results, trace, guard_level)

    public = [r.public for r in results if r.status == "ok"]
    # With nothing safe to summarise there is nothing for a model to say.
    reply = await synthesizer.synthesize(msg.text, public) if any(public) else None

    # Last line of defence: a reply that repeats anything from an agent's
    # internal data is thrown away in favour of the rule-based one.
    secrets = _internal_secrets(results)
    if reply and any(s in reply for s in secrets):
        trace.guard_events.append("internal_data_in_reply")
        reply = await RuleSynthesizer().synthesize(msg.text, public)

    ok_conf = [r.confidence for r in results if r.status == "ok"]
    final = Response(
        status="ok",
        reply=reply or GENERIC_SAFE_REPLY,
        confidence=min(ok_conf) if ok_conf else 0.0,
        capabilities_called=[s.capability for s in safe_steps],
    )

    if needs_escalation(results):
        trace.escalated = True
        final = await _escalate(registry, qualified, msg, trace, final)
    return finish(final)


__all__ = ["apply_scope_filter", "needs_escalation", "run"]
