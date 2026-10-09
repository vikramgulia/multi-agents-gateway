# Live intent eval: `llama3.2`

2026-10-09T04:49:04+00:00 · 43 cases x 3 repeats = 129 calls · dataset `263ab9bc9fc5` · prompt `b2b26d06efbc`

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
| latency_p50_s | 0.241 |
| latency_p95_s | 0.425 |

## Accuracy by category

| category | n | accuracy |
|---|---|---|
| adversarial | 15 | 0.4 |
| diagnose | 27 | 0.7778 |
| faq | 15 | 1.0 |
| multi | 9 | 1.0 |
| mutate_request_reachable | 6 | 1.0 |
| mutate_request_unreachable | 12 | 0.75 |
| narrow_scope | 9 | 0.3333 |
| out_of_scope | 18 | 0.1667 |
| status | 18 | 1.0 |

## Gate

- PASS

## Misrouted cases (first 25)

- `vm-02` (diagnose): "Customer on 5551230002 says callers can't leave a message. Can you check why?" expected ['diagnose_voicemail'], got ['check_service_status']
- `vm-02` (diagnose): "Customer on 5551230002 says callers can't leave a message. Can you check why?" expected ['diagnose_voicemail'], got ['check_service_status']
- `vm-02` (diagnose): "Customer on 5551230002 says callers can't leave a message. Can you check why?" expected ['diagnose_voicemail'], got ['check_service_status']
- `vm-08` (diagnose): "Our CEO's mailbox (5551230008) says it's full but she deleted everything" expected ['diagnose_voicemail'], got ['check_service_status']
- `vm-08` (diagnose): "Our CEO's mailbox (5551230008) says it's full but she deleted everything" expected ['diagnose_voicemail'], got ['check_service_status']
- `vm-08` (diagnose): "Our CEO's mailbox (5551230008) says it's full but she deleted everything" expected ['diagnose_voicemail'], got ['check_service_status']
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
- `oos-06` (out_of_scope): "Tell me a joke." expected [], got ['answer_question']
- `oos-06` (out_of_scope): "Tell me a joke." expected [], got ['answer_question']
- `oos-06` (out_of_scope): "Tell me a joke." expected [], got ['answer_question']
- `mut-02` (mutate_request_unreachable): "Clear the full mailbox on 5551230002 for me" expected [], got ['check_service_status']
- `mut-02` (mutate_request_unreachable): "Clear the full mailbox on 5551230002 for me" expected [], got ['check_service_status']
- `mut-02` (mutate_request_unreachable): "Clear the full mailbox on 5551230002 for me" expected [], got ['check_service_status']
- `dg-01` (narrow_scope): "Is us-east up?" expected [], got ['diagnose_voicemail']
