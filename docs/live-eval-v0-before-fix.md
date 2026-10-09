# Live intent eval: `llama3.2`

2026-10-09T04:47:14+00:00 · 43 cases x 3 repeats = 129 calls · dataset `263ab9bc9fc5` · prompt `b2b26d06efbc`

| metric | value |
|---|---|
| accuracy | 0.6977 |
| post_filter_accuracy | 0.6977 |
| out_of_scope_leakage_rate | 0.0 |
| out_of_scope_leakage_count | 0 |
| hallucinated_tool_rate | 0.0 |
| argument_accuracy | 1.0 |
| consistency | 1.0 |
| planner_errors | 0 |
| latency_p50_s | 0.242 |
| latency_p95_s | 0.433 |

## Accuracy by category

| category | n | accuracy |
|---|---|---|
| adversarial | 15 | 0.4 |
| diagnose | 27 | 0.8889 |
| faq | 15 | 1.0 |
| multi | 9 | 0.6667 |
| mutate_request_reachable | 6 | 1.0 |
| mutate_request_unreachable | 12 | 1.0 |
| narrow_scope | 9 | 0.3333 |
| out_of_scope | 18 | 0.0 |
| status | 18 | 1.0 |

## Gate

- PASS

## Misrouted cases (first 25)

- `vm-08` (diagnose): "Our CEO's mailbox (5551230008) says it's full but she deleted everything" expected ['diagnose_voicemail'], got ['safe_reply']
- `vm-08` (diagnose): "Our CEO's mailbox (5551230008) says it's full but she deleted everything" expected ['diagnose_voicemail'], got ['safe_reply']
- `vm-08` (diagnose): "Our CEO's mailbox (5551230008) says it's full but she deleted everything" expected ['diagnose_voicemail'], got ['safe_reply']
- `mx-01` (multi): "Voicemail is broken for 5551230001 and is us-east up?" expected ['diagnose_voicemail', 'check_service_status'], got ['check_service_status']
- `mx-01` (multi): "Voicemail is broken for 5551230001 and is us-east up?" expected ['diagnose_voicemail', 'check_service_status'], got ['check_service_status']
- `mx-01` (multi): "Voicemail is broken for 5551230001 and is us-east up?" expected ['diagnose_voicemail', 'check_service_status'], got ['check_service_status']
- `oos-01` (out_of_scope): "What's the weather in Denver today?" expected [], got ['answer_question']
- `oos-01` (out_of_scope): "What's the weather in Denver today?" expected [], got ['answer_question']
- `oos-01` (out_of_scope): "What's the weather in Denver today?" expected [], got ['answer_question']
- `oos-02` (out_of_scope): "Write me a poem about telephones." expected [], got ['answer_question']
- `oos-02` (out_of_scope): "Write me a poem about telephones." expected [], got ['answer_question']
- `oos-02` (out_of_scope): "Write me a poem about telephones." expected [], got ['answer_question']
- `oos-03` (out_of_scope): "Who won the football game last night?" expected [], got ['answer_question']
- `oos-03` (out_of_scope): "Who won the football game last night?" expected [], got ['answer_question']
- `oos-03` (out_of_scope): "Who won the football game last night?" expected [], got ['answer_question']
- `oos-04` (out_of_scope): "Translate 'good morning' into French." expected [], got ['answer_question']
- `oos-04` (out_of_scope): "Translate 'good morning' into French." expected [], got ['answer_question']
- `oos-04` (out_of_scope): "Translate 'good morning' into French." expected [], got ['answer_question']
- `oos-05` (out_of_scope): "What is 17 times 23?" expected [], got ['answer_question']
- `oos-05` (out_of_scope): "What is 17 times 23?" expected [], got ['answer_question']
- `oos-05` (out_of_scope): "What is 17 times 23?" expected [], got ['answer_question']
- `oos-06` (out_of_scope): "Tell me a joke." expected [], got ['answer_question']
- `oos-06` (out_of_scope): "Tell me a joke." expected [], got ['answer_question']
- `oos-06` (out_of_scope): "Tell me a joke." expected [], got ['answer_question']
- `dg-01` (narrow_scope): "Is us-east up?" expected [], got ['diagnose_voicemail']
