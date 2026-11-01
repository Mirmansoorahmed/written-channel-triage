# Error analysis (v2)

**pending real run** - run `make eval` (System A) or `TRIAGE_EVAL_REAL=1 ... eval.harness_v2` to populate per-split misclassifications (dev, test, unseen). No numbers are committed until a run produces them.

**Honest note on System C (embeddings + SLM):** my last real run showed C is **worse than System A's regex on the unseen split**, its self-reported confidence is near-constant (so it is not used to route - see ADR 0007), and it **over-predicts `Sonstiges`**. The regenerated tables will show the concrete numbers; the weakness is stated, not hidden.
