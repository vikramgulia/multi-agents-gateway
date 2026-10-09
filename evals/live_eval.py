"""Live intent eval: does a real model pick the right tools?

Unlike the golden pack this needs a model server (Ollama). It calls the real
planner on a fixed utterance dataset, with a fixed set of reachable tools per
case, and measures:

* accuracy            - did the model propose exactly an acceptable tool set?
* post-filter accuracy- the same, after the router's scope filter (what a user would see)
* out-of-scope leakage- the model proposed a tool that exists but was NOT offered. This is
                        the dangerous kind: the scope filter should stop it, and this
                        number says how often it has to.
* hallucination rate  - the model proposed a tool name that exists nowhere
* argument accuracy   - required arguments extracted correctly
* consistency         - same proposal on every repeat of the same utterance
* latency             - p50 / p95 of the planner call

Exit code is non-zero if a gate fails, so a nightly job can fail on a regression.

    python -m evals.live_eval --model llama3.2 --repeats 3
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from router import scope
from router.models import Channel, ToolSpec
from router.planner import CLASSIFY_SYSTEM_PROMPT, OllamaPlanner, PlannerError
from router.registry import default_registry

ROOT = Path(__file__).parent
DATASET = ROOT / "intent" / "dataset.jsonl"
BASELINE = ROOT / "baseline.json"
REPORTS = ROOT.parent / "reports"

_REGISTRY = default_registry()

# Named tool sets referenced by the dataset's "reachable" field.
REACHABLE_SETS: dict[str, list[str]] = {
    "chat": scope.reachable_for(Channel.CHAT),
    "ops": scope.reachable_for(Channel.ADMIN),
    "diag_only": ["diagnose_voicemail"],
}


def _tools(names: list[str]) -> list[ToolSpec]:
    specs = []
    for n in names:
        cap = _REGISTRY.capability(n)
        if cap is not None and cap.planner_visible:
            specs.append(cap.tool_spec())
    return specs


def load_dataset(path: Path = DATASET) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
    return ordered[idx]


def _args_ok(case: dict[str, Any], proposals: list[Any]) -> bool | None:
    """None if the case has no argument expectations; otherwise True/False."""
    wanted: dict[str, dict[str, str]] = case.get("args", {})
    if not wanted:
        return None
    by_tool = {p.capability: p.arguments for p in proposals}
    for tool, expected in wanted.items():
        got = by_tool.get(tool)
        if got is None:
            return False
        for key, value in expected.items():
            if str(got.get(key, "")).strip() != value:
                return False
    return True


async def evaluate(model: str, host: str, repeats: int, temperature: float = 0.0) -> dict[str, Any]:
    planner = OllamaPlanner(model=model, host=host, temperature=temperature)
    known = set(_REGISTRY.all_capabilities())
    cases = load_dataset()

    latencies: list[float] = []
    per_cat: dict[str, list[bool]] = defaultdict(list)
    exact: list[bool] = []
    post_filter: list[bool] = []
    arg_results: list[bool] = []
    consistency: list[bool] = []
    leaked: list[dict[str, Any]] = []
    hallucinated = 0
    total_calls = 0
    planner_errors = 0
    failures: list[dict[str, Any]] = []

    for case in cases:
        offered = REACHABLE_SETS[case["reachable"]]
        offered_set = {t.name for t in _tools(offered)}
        acceptable = [set(case["expected"]), *[set(a) for a in case.get("also_ok", [])]]
        tools = _tools(offered)
        seen_proposals: list[frozenset[str]] = []

        for rep in range(repeats):
            started = time.perf_counter()
            try:
                plan = await planner.plan(case["text"], tools)
            except PlannerError:
                planner_errors += 1
                continue
            latencies.append(time.perf_counter() - started)
            total_calls += 1

            proposed = [s.capability for s in plan.steps]
            proposed_set = set(proposed)
            seen_proposals.append(frozenset(proposed_set))

            out_of_scope = proposed_set - offered_set
            for name in out_of_scope:
                if name in known:
                    leaked.append({"case": case["id"], "tool": name, "repeat": rep})
                else:
                    hallucinated += 1

            ok = proposed_set in acceptable
            survivors = proposed_set & offered_set  # what the scope filter lets through
            ok_filtered = survivors in acceptable
            exact.append(ok)
            post_filter.append(ok_filtered)
            per_cat[case["category"]].append(ok)

            args = _args_ok(case, [s for s in plan.steps if s.capability in offered_set])
            if args is not None and ok:
                arg_results.append(args)

            if not ok:
                failures.append({
                    "case": case["id"], "category": case["category"], "text": case["text"],
                    "expected": case["expected"], "proposed": sorted(proposed_set), "repeat": rep,
                })

        if len(seen_proposals) == repeats:
            consistency.append(len(set(seen_proposals)) == 1)

    def rate(xs: list[bool]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    return {
        "meta": {
            "model": model,
            "host": host,
            "temperature": temperature,
            "repeats": repeats,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "cases": len(cases),
            "calls": total_calls,
            "dataset_sha": hashlib.sha256(DATASET.read_bytes()).hexdigest()[:12],
            "prompt_sha": hashlib.sha256(CLASSIFY_SYSTEM_PROMPT.encode()).hexdigest()[:12],
        },
        "metrics": {
            "accuracy": rate(exact),
            "post_filter_accuracy": rate(post_filter),
            "out_of_scope_leakage_rate": round(len(leaked) / total_calls, 4) if total_calls else 0.0,
            "out_of_scope_leakage_count": len(leaked),
            "hallucinated_tool_rate": round(hallucinated / total_calls, 4) if total_calls else 0.0,
            "argument_accuracy": rate(arg_results),
            "consistency": rate(consistency),
            "planner_errors": planner_errors,
            "latency_p50_s": round(statistics.median(latencies), 3) if latencies else 0.0,
            "latency_p95_s": round(_percentile(latencies, 95), 3),
        },
        "by_category": {c: {"accuracy": rate(v), "n": len(v)} for c, v in sorted(per_cat.items())},
        "leaks": leaked,
        "failures": failures,
    }


def gate(report: dict[str, Any], baseline: dict[str, float]) -> list[str]:
    """Return reasons the run should fail. Empty means it passes."""
    m = report["metrics"]
    problems = []
    if m["out_of_scope_leakage_count"] > 0:
        problems.append(
            f"HARD: model proposed an out-of-scope tool {m['out_of_scope_leakage_count']} time(s)"
        )
    if m["planner_errors"] > 0:
        problems.append(f"{m['planner_errors']} planner call(s) failed; the run is not trustworthy")
    if m["accuracy"] < baseline["min_accuracy"]:
        problems.append(f"accuracy {m['accuracy']:.3f} < baseline {baseline['min_accuracy']:.3f}")
    if m["hallucinated_tool_rate"] > baseline["max_hallucinated_tool_rate"]:
        problems.append(
            f"hallucinated-tool rate {m['hallucinated_tool_rate']:.3f} > {baseline['max_hallucinated_tool_rate']:.3f}"
        )
    if m["latency_p95_s"] > baseline["max_latency_p95_s"]:
        problems.append(f"p95 latency {m['latency_p95_s']}s > {baseline['max_latency_p95_s']}s")
    return problems


def _previous_report(reports_dir: Path, model: str, current: Path) -> dict[str, Any] | None:
    candidates = sorted(p for p in reports_dir.glob("*.json") if p != current)
    for path in reversed(candidates):
        data = json.loads(path.read_text())
        if data.get("meta", {}).get("model") == model:
            return data
    return None


def render_markdown(report: dict[str, Any], problems: list[str], previous: dict[str, Any] | None) -> str:
    m, meta = report["metrics"], report["meta"]
    lines = [
        f"# Live intent eval: `{meta['model']}`",
        "",
        f"{meta['timestamp']} · {meta['cases']} cases x {meta['repeats']} repeats = {meta['calls']} calls · "
        f"dataset `{meta['dataset_sha']}` · prompt `{meta['prompt_sha']}`",
        "",
        "| metric | value |", "|---|---|",
    ]
    for key, value in m.items():
        lines.append(f"| {key} | {value} |")
    lines += ["", "## Accuracy by category", "", "| category | n | accuracy |", "|---|---|---|"]
    for cat, v in report["by_category"].items():
        lines.append(f"| {cat} | {v['n']} | {v['accuracy']} |")

    if previous:
        lines += ["", f"## Change vs previous run ({previous['meta']['timestamp']})", ""]
        for key in ("accuracy", "out_of_scope_leakage_rate", "hallucinated_tool_rate", "latency_p95_s"):
            lines.append(f"- {key}: {previous['metrics'][key]} -> {m[key]}")
        prev_bad = {(f["case"]) for f in previous["failures"]}
        now_bad = {(f["case"]) for f in report["failures"]}
        lines.append(f"- newly failing cases: {sorted(now_bad - prev_bad) or 'none'}")
        lines.append(f"- newly passing cases: {sorted(prev_bad - now_bad) or 'none'}")

    lines += ["", "## Gate", ""]
    lines += [f"- FAIL: {p}" for p in problems] if problems else ["- PASS"]
    if report["leaks"]:
        lines += ["", "## Out-of-scope proposals", ""]
        lines += [f"- `{x['case']}` proposed `{x['tool']}`" for x in report["leaks"]]
    if report["failures"]:
        lines += ["", "## Misrouted cases (first 25)", ""]
        for f in report["failures"][:25]:
            lines.append(
                f"- `{f['case']}` ({f['category']}): \"{f['text']}\" expected {f['expected']}, got {f['proposed']}"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="llama3.2")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--reports-dir", type=Path, default=REPORTS)
    ap.add_argument("--keep", type=int, default=30, help="how many JSON reports to retain")
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    ap.add_argument("--no-gate", action="store_true", help="report only; always exit 0")
    args = ap.parse_args()

    report = asyncio.run(evaluate(args.model, args.host, args.repeats))
    baseline = json.loads(args.baseline.read_text())
    problems = gate(report, baseline)

    args.reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_model = args.model.replace(":", "-").replace("/", "-")
    out = args.reports_dir / f"{stamp}_{safe_model}.json"
    previous = _previous_report(args.reports_dir, args.model, out)
    out.write_text(json.dumps(report, indent=2) + "\n")
    (args.reports_dir / "latest.md").write_text(render_markdown(report, problems, previous))

    # Keep only the newest N machine-readable reports.
    for old in sorted(args.reports_dir.glob("*.json"))[: -args.keep]:
        old.unlink()

    print(render_markdown(report, problems, previous))
    return 0 if (args.no_gate or not problems) else 1


if __name__ == "__main__":
    sys.exit(main())
