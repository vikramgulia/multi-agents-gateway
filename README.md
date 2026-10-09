# multi-agents-gateway

A small multi-agent gateway, plus an eval suite that checks the agent behavior: routing, scope enforcement, escalation, isolation between agents, and resistance to hostile agent output.

The router is a demo. It is modelled on the production multi-agent support platform I built: a gateway that scopes what each channel may ask for, an orchestrator where an LLM planner picks tools, and independent agents that do the work. The production platform is tested the same way: its orchestrator runs a golden-scenario pack and an untrusted-agent red team against the real `run()` path in CI, alongside its unit and conformance tests. This repo is a standalone reference for that approach: the same shape rebuilt with stub agents, plus a live model eval to run.

**The question:** how do we test this multi-agent system is behaving as expected. Three layers:

| Layer                                   | Proves                                                                     | Model needed | Runs     |
| --------------------------------------- | -------------------------------------------------------------------------- | ------------ | -------- |
| Golden scenarios (`evals/scenarios/`)   | scope, escalation, concurrency and isolation hold on the real `run()` path | no           | every PR |
| Red team (`evals/redteam.py`)           | how much a malicious external agent can achieve, per guard level           | no           | every PR |
| Live intent eval (`evals/live_eval.py`) | a real model routes real phrasings to the right tools                      | Ollama       | nightly  |

```
pip install -e ".[dev]"
pytest                                   # everything model-free, ~1s
python -m evals.redteam                  # -> reports/redteam.md
python -m evals.live_eval --model llama3.2 --repeats 3    # needs `ollama serve`
```

## Architecture

```mermaid
flowchart LR
    U[User message] --> S[Channel scope]
    S -- reachable_caps --> R
    subgraph R[Router: run]
        direction TB
        X[Expand against<br/>application mapping] --> P[Planner LLM<br/>proposes tool calls]
        P --> F{{Scope filter}}
        F --> D[Dispatch<br/>concurrent]
        D --> G{{Output guard}}
        G --> Y[Synthesize reply<br/>public fields only]
        Y --> L{{Leak guard}}
        L --> E{Low confidence,<br/>error or escalate?}
        E -- yes --> H[Safe reply<br/>escalate=true]
    end
    D --> A1[voicemail-v1 · read-only]
    D --> A2[status-v1 · read-only]
    D --> A3[support-v1]
    D -. admin channel only .-> A4[provision-v1 · mutating]
    R --> T[(RunTrace)]
    GP[Golden scenarios<br/>scripted planner] -- calls run --> R
    RT[Red team<br/>rogue agent x guard levels] -- calls run --> R
    LE[Live eval<br/>real planner] --> P
    T -. audited by .-> I[Global invariants]
```

- **The planner is never trusted.** Its proposals are intersected with what was offered to it; anything else is dropped before dispatch.
- **Two gates decide reachability** (channel scope and per-application mapping), so one misconfiguration does not expose a tool.
- **Agents never talk to each other**; the router is the only hub, so information flow is visible in the `RunTrace`.
- **Results carry** `public` **and** `internal` **parts.** Only `public` reaches an LLM or a customer, and agent output can never add tools to a plan.
- **Agent output is screened before any LLM reads it** (`guards.py`): allowlisted shape, normalised text, hostile results withheld and escalated.
- **A dead model is not "out of scope"**: the caller gets `classifier_unavailable`, not `no_reachable_capability`.

## Layer 1: golden scenarios

`evals/scenarios/*.json` holds 21 versioned cases: input, a scripted planner, optional agent overrides, and a subset of assertions (status or error code, exact tools called, tools that must never run, `escalate`, reply markers, guard events, whether dispatches overlapped). The runner calls the same `run()` real traffic uses.

| #     | Covers                                                                                                                                            |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| 01    | diagnose happy path through a real stub agent                                                                                                     |
| 02–05 | out of scope, empty reachable set, missing or unknown application                                                                                 |
| 06–09 | "just fix it" language: mutating tool unreachable from chat, blocked a second way by app mapping, allowed on the admin channel (positive control) |
| 10–11 | low confidence and agent crash: safe reply, no error text leaked                                                                                  |
| 12–14 | concurrent multi-agent dispatch, hallucinated tool dropped, model outage                                                                          |
| 15–19 | injection in tool output, no cross-agent data flow, reply exfiltration, result cannot recruit tools, over-confident rogue agent                   |
| 20–21 | regressions found by the live eval                                                                                                                |

**Global invariants** are checked on every scenario whether or not it asserts them: nothing outside the reachable set reaches an agent; one agent's internal data never reaches another agent's request; agent internals and exception text never reach the reply; a non-ok response never lists tools called.

**Do the scenarios fail?** `tests/test_mutations.py` disables one mechanism at a time (scope filter, escalation, injection guard, concurrency) and requires the matching scenarios to go red. `tests/test_dataset_lint.py` rejects duplicate ids, empty assertions and `never_invoked` names that do not exist (a typo would make the check vacuous).

## Layer 2: untrusted-agent red team

The registry accepts externally registered agents, so agent output is attacker-controlled. `evals/redteam.py` replays 27 attacks from a rogue agent through `run()` at three guard levels:

- `off`: output goes straight to the reply model
- `v1`: regex tripwire on raw text
- `v2`: allowlisted shape (short `summary` plus fix labels; unknown fields dropped, length capped) and detection on normalised text (unicode folding, zero-width, look-alikes, spaced letters, leetspeak, base64)

Each attack has a goal: marker in the customer reply, mutating tool invoked, or escalation suppressed while another agent has failed. The reply model is a worst-case compliant one, so attack success rate (ASR) is an upper bound on what the router's own defences allow. 14 legitimate results, several chosen to look suspicious, measure false positives.

|                                                  | off     | v1      | v2       |
| ------------------------------------------------ | ------- | ------- | -------- |
| **attack success rate**                          | **93%** | **67%** | **11%**  |
| direct override, role impersonation, obfuscation | 100%    | 50–100% | 0%       |
| side fields, tool recruitment, padding           | 100%    | 33–50%  | 0%       |
| escalation suppression                           | 0%      | 0%      | 0%       |
| **paraphrase (no trigger words)**                | 100%    | 100%    | **100%** |
| **false positives on benign**                    | 0%      | 14%     | 0%       |

- **Structure beat detection.** Dropping unknown fields and capping length removed whole families without recognising any attack.
- **Escalation and dispatch never read agent text**, so suppression and tool recruitment through output fail at every level.
- **Paraphrase is the residual.** Pattern matching cannot close it; that needs a model-based check, or keeping free text from untrusted agents away from a reply model.
- v2 was tuned after its first false positives, so the benign set is no longer held-out, and attacks and guard were written together. The numbers demonstrate the method; they are not a robustness claim.

`tests/test_redteam.py` gates PRs: hardened ASR under its ceiling, structurally blocked families at 0, no benign flagged, mutating tool never invoked. Ceilings live in `evals/redteam/ceiling.json`.

## Layer 3: live intent eval

`evals/intent/dataset.jsonl` has 43 utterances (diagnose, status, FAQ, multi-tool, out of scope, state-changing requests, narrow scope, adversarial), each with the tools offered and the acceptable tool set. The real planner is called `--repeats` times per utterance.

Metrics: accuracy (also after the scope filter), **out-of-scope leakage** (a real tool proposed that was not offered), hallucinated-tool rate, argument accuracy, consistency across repeats, p50/p95 latency.

**Gate** (`evals/baseline.json`): fail on accuracy below baseline, hallucination or p95 above limit, any failed planner call, or **any** out-of-scope proposal (not configurable). Each run writes `reports/<timestamp>_<model>.json` and `reports/latest.md` with a diff against the previous run; the nightly workflow keeps the last 30 as artifacts, with dataset and prompt hashes recorded. `tests/test_live_eval_metrics.py` scores fake models to prove the leakage counter can fire.

**Results**: `llama3.2` (3B), temperature 0, 3 repeats ([report](reports/latest.md)).

| accuracy | out-of-scope leakage | hallucinated tools | argument accuracy | latency p50 / p95 |
| -------- | -------------------- | ------------------ | ----------------- | ----------------- |
| 0.698    | 0 / 129              | 0                  | 1.0               | 0.24 s / 0.43 s   |

By category: FAQ, status, multi-tool and offered mutations 1.0; diagnose 0.78; adversarial 0.40; narrow scope 0.33; out of scope 0.17. With 43 hand-written utterances the 95% interval is roughly ±14 points, and one small model on one machine is a demonstration, not a benchmark.

**What it found**

1. Leakage was zero. The mistakes were in-scope ones a scope filter cannot catch: a model forces the nearest tool onto a request with no good tool.
2. A catch-all tool absorbs off-topic requests (weather, jokes). What makes that safe is the agent escalating (scenario 21).
3. The first run showed the router-internal escalation tool was being offered to the planner, and the model picked it. Fix: such capabilities are `planner_visible=False` and a proposal for one is dropped (scenario 20). The pre-fix run is in `[docs/](docs/live-eval-v0-before-fix.md)`.
4. The fix left overall accuracy unchanged (0.698); the errors moved. Changing the offered tool list shifts model behaviour unpredictably, which is the case for running this on every model, prompt or tool-description change.

## Limitations

- Agents are fixtures: this tests routing and containment, not diagnosis quality. Network failure modes, auth and streaming are not covered.
- The live eval covers only the planner round. The reply round is exercised with a scripted worst-case synthesizer, so red-team ASR is an upper bound, not a measurement of a real model.
- The intent dataset and attack corpus are hand-written and small. Better: utterances mined from scrubbed real tickets, and a public injection corpus.
