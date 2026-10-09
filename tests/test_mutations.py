"""Do the golden scenarios actually catch regressions?

A suite that has never failed proves nothing. Each test below breaks one safety
mechanism in the router and asserts the scenario pack notices. If someone
weakens a scenario so it no longer guards its mechanism, these tests go red.
"""

from __future__ import annotations

import pytest

from evals.harness import load_scenarios, run_scenario
from evals.runner import check
from router import orchestrator

pytestmark = pytest.mark.eval_golden


async def _failing_ids() -> set[str]:
    failing = set()
    for scenario in load_scenarios():
        if check(scenario, await run_scenario(scenario)):
            failing.add(scenario["id"])
    return failing


async def test_baseline_is_green() -> None:
    assert await _failing_ids() == set()


async def test_disabling_scope_filter_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "apply_scope_filter", lambda steps, allowed: steps)
    failing = await _failing_ids()
    # The apply-language, hallucinated-tool and misconfigured-scope scenarios must all notice.
    assert {"06-apply-language-mutation-dropped", "07-apply-only-is-rejected",
            "13-hallucinated-tool-dropped"} <= failing


async def test_disabling_escalation_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "needs_escalation", lambda results: False)
    failing = await _failing_ids()
    assert {"10-low-confidence-escalates", "11-agent-crash-safe-reply"} <= failing


async def test_disabling_injection_guard_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "screen_public", lambda public, level: (public, False))
    failing = await _failing_ids()
    assert {"15-injection-in-tool-result", "19-rogue-agent-confidence-lie"} <= failing


async def test_sequential_dispatch_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def sequential_gather(*coros):  # type: ignore[no-untyped-def]
        return [await c for c in coros]

    monkeypatch.setattr(orchestrator.asyncio, "gather", sequential_gather)
    assert "12-multi-capability-concurrent" in await _failing_ids()
