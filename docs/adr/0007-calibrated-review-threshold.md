# ADR 0007 — Calibrated probability drives the human-review threshold

Status: accepted (Round 3)

## Context
A triage system should hand the uncertain cases to a human and auto-handle the confident
ones. For that to be safe, the "confidence" it routes on must mean what it says: a 0.7
should be right about 70% of the time. A review found that the SLM's self-reported
confidence is near-constant (it clusters around 0.95 regardless of whether it is right),
so routing on it would send almost nothing to review while being wrong a meaningful share
of the time. I need a probability I can trust.

## Decision
Report Expected Calibration Error (ECE, 10 bins) and a reliability table/PNG for every
system that emits a probability (C and D). Do **not** route on System C's confidence —
report its ECE honestly and treat C's output as a label only. Calibrate System D's
LogisticRegression on the **dev** split with `CalibratedClassifierCV` (sigmoid), and use
D's calibrated probability for the human-review threshold. The threshold is chosen on dev
(not test/unseen): pick the operating point whose expected review rate and post-review
accuracy meet the service goal, and record the value, the method, and the expected review
rate alongside the eval results.

Until a real-model run produces the numbers, the threshold value and the expected review
rate are marked **pending real run** in `docs/architecture.md`; this repo never invents a
calibration figure. System E reuses the same idea operationally: it trusts D when D's
calibrated probability is at or above 0.5 and escalates to the SLM only below that, and it
reports the resulting SLM-call rate.

## Consequences
- Routing decisions rest on a probability that has been measured for calibration, not on a
  model's unanchored self-assessment.
- The review rate becomes a dial: raise the threshold to send more to humans (higher
  precision on the auto path), lower it to send fewer (more automation, more risk). The
  expected review rate at the chosen threshold is documented so operators know the load.
- D must be re-calibrated whenever it is retrained; the threshold is re-chosen on dev, so
  test and unseen stay untouched by tuning.
- The honest downside: a small calibrated model can still be confidently wrong on
  genuinely novel phrasings (see the test-vs-unseen gap); the threshold limits but does not
  remove that risk.
