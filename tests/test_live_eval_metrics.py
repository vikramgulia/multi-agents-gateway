"""The live eval's own scoring code, tested with a fake model (no Ollama needed).

If the leakage metric could not fire, a clean nightly run would mean nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import live_eval
from router.models import Plan, PlanStep


class _Leaky:
    """A 'model' that always reaches for the mutating tool and sometimes invents one."""

    def __init__(self, **_: object) -> None:
        self.n = 0

    async def plan(self, text: str, tools: list) -> Plan:  # type: ignore[type-arg]
        self.n += 1
        steps = [PlanStep(capability="apply_voicemail_fix", arguments={})]
        if self.n % 2 == 0:
            steps.append(PlanStep(capability="delete_everything", arguments={}))
        return Plan(steps=steps)


BASELINE = json.loads((Path(live_eval.__file__).parent / "baseline.json").read_text())


async def test_leakage_is_counted_and_fails_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_eval, "OllamaPlanner", _Leaky)
    report = await live_eval.evaluate("fake", "http://unused", repeats=1)
    m = report["metrics"]

    assert m["out_of_scope_leakage_count"] > 0  # known tool, not offered on the chat channel
    assert m["hallucinated_tool_rate"] > 0      # a name that exists nowhere
    problems = live_eval.gate(report, BASELINE)
    assert any(p.startswith("HARD") for p in problems)


async def test_a_perfect_model_scores_one(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = {c["text"]: c for c in live_eval.load_dataset()}

    class Oracle:
        def __init__(self, **_: object) -> None: ...

        async def plan(self, text: str, tools: list) -> Plan:  # type: ignore[type-arg]
            case = cases[text]
            args = case.get("args", {})
            return Plan(steps=[PlanStep(capability=t, arguments=args.get(t, {})) for t in case["expected"]])

    monkeypatch.setattr(live_eval, "OllamaPlanner", Oracle)
    report = await live_eval.evaluate("oracle", "http://unused", repeats=2)
    m = report["metrics"]
    assert m["accuracy"] == 1.0
    assert m["out_of_scope_leakage_count"] == 0
    assert m["argument_accuracy"] == 1.0
    assert live_eval.gate(report, BASELINE) == []
