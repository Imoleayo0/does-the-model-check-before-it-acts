# Does the Model Check Before It Acts?

A confidence-to-action coherence benchmark. Two decision families, tool-call
actions, separate turns for confidence and action, generated arithmetic items
with computed keys, and a payoff sweep scored against a calibrated-policy
expected-value baseline. Built for the Apart Research AI x Epistemics
Research Sprint, Track 1 (Model Epistemics & Decision-Making Evals).

## What is in this repo

- `gen_hard_items.py` — generates the 240 frozen items (150 bet, 90 verify)
  with computed keys; self-checks every key by recomputing it.
- `items_hard_bet.jsonl`, `items_hard_verify.jsonl` — the frozen items.
- `sweep_config.py` — payoff math and the λ/c grid (thresholds, optimal
  action, regret).
- `task_v3.py`, `task_v3_nothr.py` — the two-stage Inspect tasks (Call 1:
  answer + confidence, cached and reused; Call 2: the action). The
  `_nothr` variant withholds the break-even threshold.
- `run_call1_a.py`, `run_call1_abc_v2.py` — the standalone Call 1 runners
  (condition A; conditions A/B/C).
- `run_deepseek_eval.py` — runs an Inspect task against DeepSeek.
- `analyze_sweep.py` — the analysis (model/cell/tier tables, EV gaps with
  item-level bootstrap CIs, the calibrated-policy baseline, the
  check-iff-no-working baseline).
- `fix_parser.py` — the parser fix (see the measurement note below) and
  the script that re-parsed every record.
- `make_figure.py` — regenerates `figure_ev.png`.
- `results_call1_a.json` — the 720 Call 1 records (240 items × 3 epochs,
  deepseek-chat, T=0).
- `results_sweep.csv`, `results_sweep_nothr.csv` — the 3,960 + 1,320 Call 2
  samples.
- `out/`, `out_nothr/` — the analysis tables (model/cell/tier/EV-gap).
- `corrected_tables.md` — the frozen corrected numbers the paper is
  drafted from.

## Headline numbers (deepseek-chat, condition A, T=0)

- Bet-or-pass: 99.1% accuracy at 98.9% mean confidence (ECE 0.002). The
  model is calibrated here and the items do not create the uncertainty the
  decision needs — the family is at ceiling.
- Verify-first: 88.5% accuracy at 100.0% confidence. An audit shows the
  errors are a shortcut mode, not arithmetic slips: on 28% of records the
  model gave a bare `Verdict: FALSE` with no working, at 100% confidence,
  right on every false claim and wrong on all 31 true ones, while every
  verdict preceded by working was correct (194/194).
- No-threshold ablation: the model under-bets as the penalty rises, losing
  0.23 points per item at λ=9 against a calibrated policy (95% CI
  [0.06, 0.35], one epoch).

## Reproducing

The runners fetch the DeepSeek key from a local secure credential store
(`dynamic_credential_entry("custom.deepseek")`, which returns a short-lived
surrogate, not the raw key). To reproduce outside that environment, set
`DEEPSEEK_API_KEY` in the environment and replace the credential-fetch
lines in `run_call1_a.py`, `run_call1_abc_v2.py` and `run_deepseek_eval.py`
with a plain read of that variable. The analysis (`analyze_sweep.py`) and
the figure (`make_figure.py`) run on the shipped CSVs with no key.

```bash
python3 analyze_sweep.py results_sweep.csv --call1 results_call1_a.json --outdir out
python3 analyze_sweep.py results_sweep_nothr.csv --call1 results_call1_a.json --outdir out_nothr
python3 make_figure.py
```

## Measurement note (read this before trusting the numbers)

An early version of the answer parser used `re.search` for the first
`Answer:` in the raw text. The model's working usually contains a
`**Final Answer:**` line (with the number boxed on the next line) before
the final `Answer: <number>` line, so the parser grabbed `**` or `\[` and
marked the record wrong even when the model's final answer was correct.
That turned a calibrated model into one that looked about 20 points
overconfident on bet-or-pass (0.769 vs 0.991) and it survived design, a
pilot and a full sweep. `fix_parser.py` re-parses every record with the
last `Answer:`/`Verdict:` line; an independent line-based second parser
agrees on all 720 A-run records and all 266 A/B records (0 disagreements),
and every flipped record was hand-checked. The corrected numbers are in
`corrected_tables.md`. The pre-fix files are kept alongside the corrected
ones as `*.pre_fix` backups, so the effect of the bug can be reproduced
exactly.

A second, smaller error in the same fix script then corrupted the sweep's
correctness column: it rebuilt that column by joining four Call 1 files
(the A run, a re-pilot, and two slices from different models) and let the
later files overwrite the A run's values on 14 (item, epoch) keys,
understating the sweep's bet accuracy to 0.969 and making the bet EV
numbers inconsistent with Table 1's 0.991 accuracy. That was caught because
the corrected EV numbers contradicted the accuracy arithmetic, and fixed by
`fix_sweep_correct.py`, which rebuilds the column from the A run alone
(0 mismatches on re-check). The files as corrupted by the first fix are
kept as `*.pre_fix2` backups.

## AI assistance

The code in this repository was written with AI assistance (Claude and
Muse), including the item generator, the sweep configuration, the analysis
script and the Inspect task. The author conceived the project, chose the
research direction and design decisions, directed the experiments and
verified the results. The parser bug described above was in AI-written
evaluation code, and it was caught by an audit the author directed; see
the measurement note.
