# Corrected tables (frozen 2026-11-14 ~11:15 WAT)
# All numbers recomputed with the fixed answer parser (fix_parser.py).
# The original parser used re.search for the FIRST "Answer:" occurrence and
# grabbed "**" / "\[" from "**Final Answer:**" lines. The fixed parser takes
# the LAST "Answer:"/"Verdict:" line. Validated by an independent line-based
# parser: 0 disagreements on 720 A-run + 266 A/B records.
# DeepSeek balance is $0.00 — no further API runs are possible.

## A run (deepseek-chat, condition A, T=0, 240 items x 3 epochs = 720)
- Overall: acc 0.951, mean conf 99.3%, SD 1.74, below 90% 0.0%, below 100% 14.3%
- Overall AUROC 0.425, ECE 0.042, Brier 0.049
- Bet (n=450): acc 0.991, conf 98.9%, SD 2.09, ECE 0.002, Brier 0.009, AUROC 0.387
- Verify (n=270): acc 0.885, conf 100.0%, SD 0.09, ECE 0.115, Brier 0.115, AUROC 0.496
- Bet tiers (n=90 each): mod_10_3 1.000, mod_8_3 1.000, mul_10x5 0.978, mul_11x6 1.000, square_7 0.978
- Verify tiers (n=90 each): vmul_10x5 0.811, vmul_6x5 0.922, vmul_8x5 0.922

## Verify working vs no-working (the short-circuit finding)
- Model does working (n=194): 100% correct (104 TRUE on true claims, 90 FALSE on false claims)
- Model skips working (n=76): ALWAYS says FALSE; right on false claims 45/45, wrong on true claims 0/31
- All 31 wrong verify instances are bare "Verdict: FALSE / Confidence: 100%" (31 chars), no working
- Claims all genuinely TRUE (Python-verified); the verdict parser is fine; no claim formatting problem
- The verify "false bias" (100% false / 77% true) is a default-FALSE short-circuit, NOT arithmetic slipping

## EV gaps, main sweep (3,960 samples; calibrated policy per tier, in-sample)
- Bet: lam 0.25 gap 0.002 [0.000, 0.007]; lam 1 gap 0.018 [0.007, 0.029];
  lam 4 gap 0.020 [0.007, 0.036]; lam 9 gap 0.013 [0.004, 0.027]
  (bet EV at lam 9: model 0.676, calibrated 0.689, never 0.000)
- Verify: lam 1 c 0.1 gap 0.059 [-0.021, 0.152]; lam 4 c 0.1 gap 0.282 [0.079, 0.523]
  (verify EV at lam 4 c 0.1: model 0.618, calibrated 0.900)
- Coherence: bet 0.978-0.998, verify 0.881-0.974; n_diag = 0 everywhere
- Verdict-aware policy (in-sample, check iff verdict FALSE):
  lam 1 c 0.1: 0.939 (model 0.841, calibrated 0.900); lam 4 c 0.1: 0.939 (model 0.618, calibrated 0.900)
  Beats the model in 4/8 verify cells, beats the calibrated policy in 3/8.

## EV gaps, no-threshold ablation (1 epoch, 1,320 samples)
- Bet: lam 0.25 gap 0.000; lam 1 gap 0.080 [0.027, 0.133];
  lam 4 gap 0.140 [0.040, 0.267]; lam 9 gap 0.427 [0.187, 0.707]
  (bet EV at lam 9: model 0.107, calibrated 0.533; coherence 0.707 vs 0.987 main)
- Verify: lam 4 c 0.1 gap 0.253 [0.029, 0.532]
- The model UNDER-bets when it must derive the break-even: abstains 29% at lam 9
  while 99% accurate and stating ~100% confidence. Incoherent with its own
  confidence, and it costs EV.

## Check-vs-correctness (verify, main sweep)
- P(check|wrong) = 0.211 (232 instances, 15 distinct items) vs P(check|right) = 0.061
- Ratio 3.48, item-level bootstrap 95% CI [2.59, 4.66]
- All 166 checks at 100% stated confidence; bet side shows no signal

## NEW: P(check | working mode) — verify, main sweep (Analysis 1)
- P(check | no working) = 0.104 (n=608) vs P(check | working) = 0.066 (n=1552)
- On the 21 items with both modes: 0.093 vs 0.062, ratio 1.48,
  item-level bootstrap 95% CI [0.71, 3.13] — INCLUDES 1, NOT significant
- By working x correctness: no-working + wrong 0.211 (n=232); no-working + right 0.037 (n=376);
  working + right 0.066 (n=1552); working + wrong does not exist (working is always correct)
- Conclusion: the check signal tracks CORRECTNESS, not the response mode.
  The "cleaner" version (actions track reasoning) does not hold at item level.

## NEW: skip rate (Analysis 2)
- By tier: vmul_10x5 40.0% skip, vmul_6x5 28.9%, vmul_8x5 15.6% — skipping rises with difficulty
- By epoch: 28.9% / 30.0% / 25.6% — no epoch trend
- Per item (of 3 epochs): 54 never skip, 11 skip once, 10 skip twice, 15 always skip
- Expected if random Bernoulli(p=0.28): always ~2 items, never ~33 items
- Observed always 15 / never 54 — skipping is ITEM-SPECIFIC, not random
- Always-skip items (15): 6 true claims, 9 false claims — skipping is a property of the
  item (its difficulty), not of the truth. When it skips it always says FALSE, which is
  right on false claims and wrong on true ones — that is what produces the "false bias".
- Always-skip items: hv002, hv017, hv021, hv033, hv043, hv045, hv047, hv056, hv059,
  hv062, hv064, hv072, hv077, hv086, hv089. Overlap with the 15 wrong items: only 6.

## NEW: EV baseline "check iff no working" (Analysis 3; replaces verdict-aware)
- Observable from the transcript (the response either has working or it doesn't); in-sample.
- lam=1: c 0.1: 0.972 (model 0.841, calibrated 0.900); c 0.3: 0.916 (0.789, 0.804);
  c 0.5: 0.859 (0.781, 0.785); c 0.7: 0.803 (0.806, 0.785); c 0.9: 0.747 (0.784, 0.785)
- lam=4: c 0.1: 0.972 (model 0.618, calibrated 0.900); c 0.5: 0.859 (0.539, 0.593);
  c 0.9: 0.747 (0.529, 0.463)
- Beats the model in 7/8 cells (loses only lam=1, c=0.9) and beats the calibrated
  policy in 7/8 cells (loses only lam=1, c=0.9); beats the verdict-aware baseline in all 8.
- It works because the no-working responses are always FALSE: checking on them avoids
  the -lam penalty on the 31 wrong true claims, at the cost of 1-c instead of +1 on the
  45 correct false claims. It shows what the model could gain if it tracked its own
  reasoning — but it does not (Analysis 1).
- Stored in out/ev_gap.csv and out_nothr/ev_gap.csv as ev_nowork.

## B/C partial (133 bet items only; 0 verify; DeepSeek balance $0, cannot finish)
- A: acc 0.992, conf 99.0, AUROC 0.396, below-90% 0.0% -> FAIL
- B: acc 0.992, conf 94.7 (SD 4.23), AUROC 0.568, below-90% 13.5% -> FAIL
  (B's stored accuracy 0.301 was the parser bug; the pre-work estimate does not
  improve resolution and B's solving accuracy matches A's)
- C (recomputed with fixed parser on 117 usable records):
  per-sample accuracy 0.945; mean agreement 93.8% (stored 64.9% was the parser bug);
  below-90% 21.4%; AUROC 0.994; ECE 0.043
  -> PASSES the pre-specified rule, but the AUROC rests on only 3 wrong items
  (recomputed confidences 20, 20, 60) and below-90% is barely above 20%.
- No action sweep was run on any B or C confidence.

## Reasoner slice (80 items, 10/tier, condition A, 1 epoch) — COMPLETE
- deepseek-reasoner: acc 1.000, conf 100.0, SD 0.00 (bet 1.000, verify 1.000)
## v4-pro slice (80 items) — INCOMPLETE at 25/80 (DeepSeek balance $0)
- deepseek-v4-pro (partial, 25 records): acc 0.600 — small, incomplete sample; do not report as a finding.

## Calibration, corrected (the tiers were never in the 50-80% band for bet)
- Round 1: mod_8_3 0.70->1.00, mul_7x5 0.90->1.00, square_6 0.90->1.00, vmul_6x5 0.80, vmul_7x4 0.90
- Round 2: mod_10_3 0.50->0.90, mod_9_4 0.80->1.00, mul_10x5 0.80->1.00, square_7 0.60->0.80,
  square_8 0.10->0.90, vmul_8x5 0.80, vmul_9x4 0.90
- Round 3: mul_10x6 0.90->1.00, mul_11x5 0.80->0.90, mul_11x6 0.80->1.00, vmul_10x5 0.70
- Bet tiers were 0.80-1.00 accurate at calibration, not 0.50-0.80.

## V1 pilot (confounded B/C attempt), corrected
- A: 0.908 -> 0.929; B: 0.479 -> 0.537 (still low — B guessed without working; the confound stands)
- C AUROC: 0.318 -> 0.216 (still below chance; the confound stands)
## First pilot (default sampling): CANNOT be recomputed reliably.
- The pilot's item keys are lost (the v1 backup files do not match the pilot's items).
- The "~68% vs ~91%" temperature comparison must be REMOVED from the paper.
- The v2 task also uses the buggy parser, so the v2 accuracy (0.920) is understated too.

## What changed vs the draft v2 numbers
- Bet acc 0.769 -> 0.991; overall acc 0.812 -> 0.951; bet ECE 0.220 -> 0.002
- Bet EV gap at lam 9: 1.302 [0.844, 1.767] -> 0.013 [0.004, 0.027] (headline result gone)
- Ablation bet lam 9 gap: 1.027 -> 0.427; interpretation flips (under-betting, not over-betting)
- B accuracy (v2 re-pilot): 0.301 -> 0.992 (parser bug)
- C mean confidence: 64.9% -> 93.8% (parser bug); C AUROC 0.750 -> 0.994 (on 3 wrong items)
- Verify numbers essentially unchanged (the verdict parser was fine except 2 items)
