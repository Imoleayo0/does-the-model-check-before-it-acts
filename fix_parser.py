"""Re-parse Call 1 records with the fixed answer parser.

BUG (found 2026-11-14): the original parse_answer used
    re.search(r"answer\\s*:\\s*(.+)", raw, re.IGNORECASE)
which returns the FIRST "Answer:" occurrence. The model's working often
contains "**Final Answer:**" (boxed number on the next line) before the
final "Answer: <number>" line, so the parser captured "**" or "\\[" and
marked the record wrong even when the model's final answer was correct.
This understated bet accuracy (0.769 instead of 0.991) and therefore every
downstream number (EV, EV gaps, calibration, tier accuracy, B/C accuracy).

The fix: strip markdown bold, find ALL "Answer:" lines, take the LAST one
containing a digit (the final answer), and compare that to the key.
For verify, take the LAST "Verdict:" line containing TRUE/FALSE.
Hand-verified on a random sample (2026-11-14): all 100 flipped bet records
in the A run genuinely had the correct final answer; the 4 still-wrong
records genuinely had digit slips.

This script re-parses results_call1_a.json, results_call1_abc_v2.json,
results_call1_reasoner.json and results_call1_v4pro.json in place (keeping
a .pre_fix backup), and rewrites the sweep CSVs' `correct` column from the
corrected Call 1 (keyed by item_id + epoch).
Usage: python3 fix_parser.py
"""
import json
import re
import shutil
import unicodedata

import pandas as pd


def _norm(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def fixed_parse(item, raw):
    """Return (answer_text, correct) using the last Answer/Verdict line."""
    if item["family"] == "bet":
        text = raw.replace("*", "")
        cands = re.findall(r"answer\s*:\s*([^\n]*)", text, re.IGNORECASE)
        for cand in reversed(cands):
            nums = re.findall(r"-?\d+", cand.replace(",", ""))
            if nums:
                ans = nums[-1]
                return ans, _norm(ans) == _norm(str(item["answer"]))
        return "", False
    text = raw.replace("*", "")
    cands = re.findall(r"verdict\s*:\s*([^\n]*)", text, re.IGNORECASE)
    for cand in reversed(cands):
        m = re.search(r"\b(true|false)\b", cand, re.IGNORECASE)
        if m:
            v = m.group(1).upper()
            return v, (v == "TRUE") == bool(item["truth"])
    return "", False


def main():
    items = {}
    for path in ("items_hard_bet.jsonl", "items_hard_verify.jsonl"):
        for line in open(path):
            it = json.loads(line)
            items[it["id"]] = it

    corrected = {}  # (item_id, epoch) -> correct
    for fname in ("results_call1_a.json", "results_call1_abc_v2.json",
                  "results_call1_reasoner.json", "results_call1_v4pro.json"):
        try:
            rows = json.load(open(fname))
        except FileNotFoundError:
            print(f"{fname}: missing, skipped")
            continue
        shutil.copy(fname, fname + ".pre_fix")
        n_flip = 0
        for r in rows:
            it = items.get(r["id"])
            if it is None:
                continue
            ans, corr = fixed_parse(it, r.get("raw", ""))
            if corr != r["initial_correct"]:
                n_flip += 1
            r["answer_text"] = ans
            r["initial_correct"] = bool(corr)
            # only keep the primary (condition A) record for the sweep join
            if r.get("condition", "A") == "A":
                corrected[(r["id"], r["epoch"])] = bool(corr)
        json.dump(rows, open(fname, "w"), indent=2)
        print(f"{fname}: n={len(rows)} correctness flips={n_flip} "
              f"new acc={sum(r['initial_correct'] for r in rows)/len(rows):.3f}")

    # Fix the sweep CSVs' correct column from corrected Call 1.
    for fname in ("results_sweep.csv", "results_sweep_nothr.csv"):
        try:
            df = pd.read_csv(fname)
        except FileNotFoundError:
            print(f"{fname}: missing, skipped")
            continue
        shutil.copy(fname, fname + ".pre_fix")
        n_fixed = 0
        new_correct = []
        for _, row in df.iterrows():
            key = (row["item_id"], int(row["epoch"]))
            c = corrected.get(key)
            if c is None:
                new_correct.append(int(row["correct"]))
            else:
                new_correct.append(1 if c else 0)
                if (1 if c else 0) != int(row["correct"]):
                    n_fixed += 1
        df["correct"] = new_correct
        df.to_csv(fname, index=False)
        print(f"{fname}: n={len(df)} correct-column fixes={n_fixed}")


if __name__ == "__main__":
    main()
