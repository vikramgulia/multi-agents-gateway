"""Lint the eval datasets so a scenario cannot silently stop guarding anything."""

from __future__ import annotations

import json
from pathlib import Path

from evals.harness import load_scenarios
from router.registry import default_registry

INTENT = Path(__file__).parent.parent / "evals" / "intent" / "dataset.jsonl"
REG = default_registry()
KNOWN = set(REG.all_capabilities())
ALLOWED_ASSERT_KEYS = {
    "status", "error_code", "escalate", "tools_called", "planner_called", "concurrent",
    "max_confidence", "never_invoked", "dropped_out_of_scope", "guard_events",
    "reply_contains", "reply_not_contains",
}


def test_scenario_ids_unique_and_match_filenames() -> None:
    scenarios = load_scenarios()
    ids = [s["id"] for s in scenarios]
    assert len(ids) == len(set(ids))
    for s in scenarios:
        assert s["_file"] == f"{s['id']}.json"
        assert s["schema_version"] == 1


def test_assertion_keys_are_known() -> None:
    for s in load_scenarios():
        unknown = set(s["assert"]) - ALLOWED_ASSERT_KEYS
        assert not unknown, f"{s['id']}: unknown assertion keys {unknown}"
        assert s["assert"], f"{s['id']}: a scenario with no assertions guards nothing"


def test_never_invoked_names_exist() -> None:
    # A typo in never_invoked would make the check vacuously true.
    for s in load_scenarios():
        for cap in s["assert"].get("never_invoked", []):
            assert cap in KNOWN, f"{s['id']}: unknown capability {cap!r}"


def test_intent_dataset_is_well_formed() -> None:
    ids = set()
    for line in INTENT.read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        assert case["id"] not in ids
        ids.add(case["id"])
        assert set(case["expected"]) <= KNOWN
        for alt in case.get("also_ok", []):
            assert set(alt) <= KNOWN
    assert len(ids) >= 40
