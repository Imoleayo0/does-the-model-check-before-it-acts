#!/usr/bin/env python3
"""Fix the sweep CSVs' `correct` column from the VALIDATED A-run only.

ROOT CAUSE (found 2026-11-14, user-reported EV inconsistency): fix_parser.py
built its `corrected` dict by iterating over FOUR Call 1 files in order
(results_call1_a.json, results_call1_abc_v2.json, results_call1_reasoner.json,
results_call1_v4pro.json) and letting later files overwrite the same
(item_id, epoch) keys. The B/C re-pilot is a separate deepseek-chat run
(T=0 non-determinism), and the reasoner / v4-pro slices are DIFFERENT MODELS,
so their condition-A records disagree with the A-run on some items. The
sweep was built from the full A run, so its `correct` column must come from
the A run alone. The overwrite corrupted 64 rows in each sweep CSV
(48 bet + 16 verify), understating bet accuracy in the sweep to 0.969
(main) / 0.927 (ablation) instead of 0.991, which made the bet EV and EV
gaps inconsistent with Table 1.

This script rewrites both sweep CSVs' `correct` column from
results_call1_a.json only (the file validated by the independent second
parser: 0 disagreements on 720 records), keeping a .pre_fix2 backup of the
current files.
Usage: python3 fix_sweep_correct.py
"""
import json
import shutil

import pandas as pd

# The validated source: the full A run only.
a = json.load(open("results_call1_a.json"))
a_correct = {(r["id"], r["epoch"]): bool(r["initial_correct"]) for r in a}
print(f"A-run: {len(a_correct)} (item, epoch) keys, "
      f"accuracy {sum(a_correct.values())/len(a_correct):.4f}")

for fname in ("results_sweep.csv", "results_sweep_nothr.csv"):
    df = pd.read_csv(fname)
    shutil.copy(fname, fname + ".pre_fix2")
    n_fixed = 0
    new_correct = []
    for _, row in df.iterrows():
        key = (row["item_id"], int(row["epoch"]))
        c = a_correct.get(key)
        if c is None:
            raise KeyError(f"{fname}: no A-run record for {key}")
        new_correct.append(1 if c else 0)
        if (1 if c else 0) != int(row["correct"]):
            n_fixed += 1
    df["correct"] = new_correct
    df.to_csv(fname, index=False)
    for fam in ("bet", "verify"):
        sub = df[df["family"] == fam]
        acc = sub["correct"].mean()
        print(f"{fname} {fam}: n={len(sub)} accuracy={acc:.4f}")
    print(f"{fname}: n={len(df)} correct-column fixes={n_fixed}")
