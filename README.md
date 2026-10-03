# Difficulty routing had nothing to do: a 14-task negative result

**Finding: I built a cheap-first escalate-on-low-confidence router and it never
escalated — because the small tier never failed. `Qwen/Qwen3.8-27B` matched
`Qwen-Ambassador/Qwen3.8-Max` at 14/14, including the four most-cited LLM trap
questions. Worse for the premise, the big model was slightly *more* token-efficient.**

```
python3 run.py      # 14 tasks x 2 models (+ escalations) to the live route
```

## Arms

| arm | model | accuracy | completion tokens | correct / 1k tokens | mean latency |
|-----|-------|----------|-------------------|---------------------|--------------|
| `cheap_only`  | Qwen/Qwen3.8-27B | **1.000** (14/14) | 2563 | 5.46 | 4.19 s |
| `strong_only` | Qwen-Ambassador/Qwen3.8-Max | **1.000** (14/14) | **2394** | 5.85 | 5.39 s |
| `routed`      | 27B → Max on confidence < 70 | **1.000** (14/14) | 2563 | 5.46 | 4.19 s |

**Escalation rate: 0.0%.** No task triggered an escalation, so the routed arm is
bit-identical to `cheap_only`.

## Why this is worth publishing anyway

Three things a reader can use:

1. **The four classic traps no longer discriminate.** Bat-and-ball (`$1.10`, bat `$1.00`
   more → `0.05`), the machines/widgets trap, the lily-pad halving (47), and the
   `2, 6, 12, 20, 30, ?` sequence were all answered correctly **by both tiers**, at
   self-reported confidence 100. If your evaluation still leans on these, it is
   measuring nothing about this generation.
2. **The cost premise did not survive contact.** The assumption behind routing is
   "big model = more tokens". Here the Max used *fewer* completion tokens than the 27B
   (2394 vs 2563), so the routed arm would have been the **more expensive** choice per
   token had it escalated. Token-efficiency and model size are not the same axis.
3. **Self-reported confidence is useless as a routing signal when it is saturated.**
   Every cheap-model answer came back at confidence 100. A threshold of 70 can never
   fire against a signal pinned at the ceiling — which is exactly the failure mode that
   makes the "sentiment-based" routers look better than they are.

## Honest caveats

- **14 tasks is small, and they are short-answer.** This shows the router did not help
  *here*; it does not show routing never helps. The correct reading is "this task class
  is saturated", not "routing is worthless".
- **The task set is the limiting factor, and it is mine.** I wrote the tasks; a set
  tuned to expose the 27B would be a different experiment. I am not claiming the models
  are equal in general — only on these 14 items.
- Escalation used a single signal (self-reported confidence < 70). A verifier-based
  escalation (check the arithmetic deterministically, escalate on check failure) is a
  strictly stronger trigger and was not tested here.
- One run per cell. No variance estimate.
- `Qwen/Qwen3.8-27B` is the *endpoint's* 27B, not a local weight — this is a two-tier
  cloud comparison, not local-vs-cloud.

## What would actually settle it

Long-horizon multi-step tasks (many dependent operations, error compounding), or tasks
with a deterministic verifier so escalation does not depend on the model's own
confidence. Until the small tier fails *something*, routing has no work to do.

## Files

- `run.py` — three arms over 14 graded tasks
- `results/raw.jsonl` — per-task records: both models' answers, confidences, token counts
- `results/summary.json` — per-arm and per-tier rollup
- `receipts.sha256` — hashes of harness, client, README and raw logs
