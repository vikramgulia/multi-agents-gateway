"""Golden scenario pack: every JSON file in evals/scenarios runs through router.run().

Run alone with:  pytest -m eval_golden
No LLM, no network: the planner is scripted and agents are in-process.
"""

from __future__ import annotations

import pytest

from evals.harness import load_scenarios, run_scenario
from evals.runner import check

SCENARIOS = load_scenarios()

pytestmark = pytest.mark.eval_golden


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
async def test_scenario(scenario: dict) -> None:
    outcome = await run_scenario(scenario)
    failures = check(scenario, outcome)
    # On failure, show the trace: it is the fastest way to see where routing went wrong.
    assert not failures, "\n".join(failures) + "\n\n" + outcome.trace.model_dump_json(indent=2)
