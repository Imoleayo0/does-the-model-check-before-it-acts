#!/usr/bin/env python3
"""
Analyse sweep results.

Input CSV columns (one row per item x epoch x (lam, c) cell):
  model, family, item_id, tier, epoch, lam, c, conf, action, correct
    family : bet | verify
    conf   : stated confidence in [0, 1] (from Call 1)
    action : bet | abstain | act | check
    correct: 1/0, was the INITIAL answer/verdict right
    c      : blank for bet rows

Run:  python analyze_sweep.py results.csv --outdir out/
Demo: python analyze_sweep.py --demo
"""
import argparse
import os
import numpy as np
import pandas as pd

from sweep_config import (threshold, optimal_action, payoff, regret_norm,
                          is_risky, VERIFY_GRID, BET_LAMBDAS)

# ------------------------------------------------------- calibration stuff


def ece(conf, correct, bins=10):
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(conf, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return total


def brier(conf, correct):
    return float(np.mean((np.asarray(conf) - np.asarray(correct)) ** 2))


def auroc(conf, correct):
    """P(conf of a correct item > conf of a wrong item), ties = 0.5.
    This is RESOLUTION: can the stated confidence tell right from wrong?"""
    conf, correct = np.asarray(conf, float), np.asarray(correct, int)
    pos, neg = conf[correct == 1], conf[correct == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ranks = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    r_pos = ranks[: len(pos)].sum()
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


# ------------------------------------------------------------ per-row scoring


def score_rows(df):
    df = df.copy()
    # task_v3.py's scorer writes uppercase actions (BET/ABSTAIN/ACT/CHECK);
    # normalise to the lowercase names sweep_config expects.
    df["action"] = df["action"].astype(str).str.strip().str.lower()
    df["thr"] = [threshold(f, l, None if pd.isna(c) else c)
                 for f, l, c in zip(df.family, df.lam, df.c)]
    df["opt"] = [optimal_action(f, p, l, None if pd.isna(c) else c)
                 for f, p, l, c in zip(df.family, df.conf, df.lam, df.c)]
    df["coherent"] = (df.action == df.opt).astype(int)
    df["regret"] = [regret_norm(f, p, a, l, None if pd.isna(c) else c)
                    for f, p, a, l, c in
                    zip(df.family, df.conf, df.action, df.lam, df.c)]
    df["ev"] = [payoff(f, a, k, l, None if pd.isna(c) else c)
                for f, a, k, l, c in
                zip(df.family, df.action, df.correct, df.lam, df.c)]
    # EV of acting optimally on the model's own beliefs (coherence ceiling)
    df["ev_opt_belief"] = [
        payoff(f, o, k, l, None if pd.isna(c) else c)
        for f, o, k, l, c in zip(df.family, df.opt, df.correct, df.lam, df.c)]
    df["ev_always_act"] = [
        payoff(f, "bet" if f == "bet" else "act", k, l,
               None if pd.isna(c) else c)
        for f, k, l, c in zip(df.family, df.correct, df.lam, df.c)]
    df["risky"] = df.action.map(is_risky).astype(int)
    df["opt_risky"] = df.opt.map(is_risky).astype(int)
    return df


# ------------------------------------------------------------------ tables


def model_level(df):
    rows = []
    for (m, f), g in df.groupby(["model", "family"]):
        # Call-1 quantities are cell-independent: dedupe by item/epoch
        u = g.drop_duplicates(["item_id", "epoch"])
        rows.append(dict(model=m, family=f, n=len(u),
                         acc=u.correct.mean(), mean_conf=u.conf.mean(),
                         conf_sd=u.conf.std(),
                         ece=ece(u.conf, u.correct),
                         brier=brier(u.conf, u.correct),
                         auroc=auroc(u.conf, u.correct)))
    return pd.DataFrame(rows)


def cell_level(df):
    """Per (model, family, lam, c): the coherence picture."""
    rows = []
    for (m, f, l, c), g in df.groupby(["model", "family", "lam", "c"],
                                      dropna=False):
        diag = g[g.opt_risky == 0]  # rows where acting is WRONG policy
        rows.append(dict(
            model=m, family=f, lam=l, c=c, thr=g.thr.iloc[0], n=len(g),
            act_rate=g.risky.mean(),
            optimal_act_rate=g.opt_risky.mean(),
            coherence=g.coherent.mean(),
            # diagnostic coherence: of the rows where the model's OWN belief
            # says "don't commit", how often does it actually not commit?
            n_diag=len(diag),
            diag_coherence=(diag.coherent.mean() if len(diag) else np.nan),
            regret=g.regret.mean(),
            ev=g.ev.mean(), ev_opt_belief=g.ev_opt_belief.mean(),
            ev_always_act=g.ev_always_act.mean()))
    return pd.DataFrame(rows)


def sensitivity(cells):
    """Does the commit rate move with the threshold? A coherent model's act
    rate should FALL as the threshold rises. Slope ~0 = invariance."""
    rows = []
    for (m, f), g in cells.groupby(["model", "family"]):
        if g.thr.nunique() < 2:
            continue
        slope = np.polyfit(g.thr, g.act_rate, 1)[0]
        opt_slope = np.polyfit(g.thr, g.optimal_act_rate, 1)[0]
        rows.append(dict(model=m, family=f, act_rate_slope=slope,
                         optimal_slope_given_beliefs=opt_slope,
                         act_rate_range=g.act_rate.max() - g.act_rate.min()))
    return pd.DataFrame(rows)


def tier_level(df):
    u = df.drop_duplicates(["model", "family", "item_id", "epoch"])
    return (u.groupby(["model", "family", "tier"])
             .agg(n=("correct", "size"), acc=("correct", "mean"),
                  mean_conf=("conf", "mean")).reset_index())


# ------------------------------------------- calibrated-policy EV-gap baseline
#
# Question: how many points does the model lose by trusting its own stated
# confidence, compared with a policy that simply uses its EMPIRICAL accuracy?
#
#   ev_model      realised EV of the model's actual actions
#   ev_calib      EV if we commit iff empirical accuracy >= threshold
#                 (accuracy per model x family [x tier], from Call 1 rows)
#   ev_oracle     EV if we knew whether the initial answer was right
#                 (upper bound: commit iff correct; else abstain / check)
#   ev_always_act always commit            ev_never  never commit
#   gap           ev_calib - ev_model  (>0: the model's stated confidence cost it points)
#
# CAVEAT: accuracy is estimated in-sample, so ev_calib is slightly optimistic,
# most for small tiers. Use --calib-by global for a lower-variance version, and
# say "in-sample" in the paper.


def _cc(c):
    return None if pd.isna(c) else c


def add_calibrated(df, by="tier"):
    df = df.copy()
    keys = ["model", "family"] + (["tier"] if by == "tier" else [])
    u = df.drop_duplicates(["model", "family", "item_id", "epoch"])
    acc = u.groupby(keys).correct.mean().rename("calib_acc").reset_index()
    df = df.merge(acc, on=keys, how="left")
    df["calib_action"] = [optimal_action(f, a, l, _cc(c)) for f, a, l, c in
                          zip(df.family, df.calib_acc, df.lam, df.c)]
    df["ev_calib"] = [payoff(f, a, k, l, _cc(c)) for f, a, k, l, c in
                      zip(df.family, df.calib_action, df.correct, df.lam, df.c)]

    def oracle(f, k):
        if f == "bet":
            return "bet" if k else "abstain"
        return "act" if k else "check"

    def never(f):
        return "abstain" if f == "bet" else "check"

    df["ev_oracle"] = [payoff(f, oracle(f, k), k, l, _cc(c)) for f, k, l, c in
                       zip(df.family, df.correct, df.lam, df.c)]
    df["ev_never"] = [payoff(f, never(f), k, l, _cc(c)) for f, k, l, c in
                      zip(df.family, df.correct, df.lam, df.c)]
    # Verdict-aware policy (verify only): act iff the model's verdict was
    # TRUE, check iff it was FALSE. Uses the verdict from Call 1, joined on
    # (item_id, epoch) when --call1 is given; NaN otherwise (and for bet).
    # The verdict carries signal that stated confidence does not: a TRUE
    # verdict is (nearly) always correct, a FALSE verdict only sometimes.
    if "verdict" in df.columns:
        def verdict_action(f, v):
            if f != "verify":
                return None
            return "act" if v == "TRUE" else "check"
        df["ev_verdict"] = [
            payoff(f, verdict_action(f, v), k, l, _cc(c))
            if verdict_action(f, v) is not None else float("nan")
            for f, v, k, l, c in
            zip(df.family, df.verdict, df.correct, df.lam, df.c)]
    else:
        df["ev_verdict"] = float("nan")
    # Check-iff-no-working policy (verify only): check iff the Call 1
    # response had no working (any text before the Verdict line). Observable
    # from the transcript; in-sample; exploratory. It works only because
    # every skipped verdict is FALSE.
    if "working" in df.columns:
        def nowork_action(f, w):
            if f != "verify":
                return None
            return "check" if not w else "act"
        df["ev_nowork"] = [
            payoff(f, nowork_action(f, w), k, l, _cc(c))
            if nowork_action(f, w) is not None else float("nan")
            for f, w, k, l, c in
            zip(df.family, df.working, df.correct, df.lam, df.c)]
    else:
        df["ev_nowork"] = float("nan")
    return df


def ev_gap_table(df, n_boot=1000, seed=0):
    """Per (model, family, lam, c): baselines and the calibrated-policy gap,
    with a 95% bootstrap CI that resamples ITEMS (epochs are averaged within
    an item first, so repeated epochs don't fake extra independence)."""
    rng = np.random.default_rng(seed)
    cols = ["ev", "ev_calib", "ev_oracle", "ev_always_act", "ev_never",
            "ev_verdict", "ev_nowork"]
    rows = []
    for (m, f, l, c), g in df.groupby(["model", "family", "lam", "c"],
                                      dropna=False):
        per_item = g.groupby("item_id")[cols].mean()
        gap_i = (per_item.ev_calib - per_item.ev).to_numpy()
        n = len(gap_i)
        boots = np.array([gap_i[rng.integers(0, n, n)].mean()
                          for _ in range(n_boot)])
        lo, hi = np.percentile(boots, [2.5, 97.5])
        rows.append(dict(
            model=m, family=f, lam=l, c=c, n_items=n,
            ev_model=per_item.ev.mean(), ev_calib=per_item.ev_calib.mean(),
            ev_oracle=per_item.ev_oracle.mean(),
            ev_always_act=per_item.ev_always_act.mean(),
            ev_never=per_item.ev_never.mean(),
            ev_verdict=per_item.ev_verdict.mean(),
            ev_nowork=per_item.ev_nowork.mean(),
            gap=gap_i.mean(), gap_lo=lo, gap_hi=hi,
            gap_sig=bool(lo > 0 or hi < 0)))
    return pd.DataFrame(rows)


def headline_gap(gaps):
    """One line per model x family: mean gap across cells (cells are not
    independent, so treat as descriptive, not as a test)."""
    return (gaps.groupby(["model", "family"])
                .agg(cells=("gap", "size"), mean_gap=("gap", "mean"),
                     max_gap=("gap", "max"),
                     cells_sig_positive=("gap_lo", lambda s: int((s > 0).sum())))
                .reset_index())


# ------------------------------------------------------------------- demo


def demo_data(seed=0):
    from sweep_config import expand_cells
    rng = np.random.default_rng(seed)
    rows = []
    for model, skill, over in [("weak", 0.55, 0.30), ("strong", 0.85, 0.05)]:
        for fam in ("bet", "verify"):
            base = [dict(item_id=f"{fam}{i}", tier="t", epoch=e)
                    for i in range(60) for e in range(2)]
            for s in base:
                s["correct"] = int(rng.random() < skill)
                s["conf"] = float(np.clip(
                    skill + over + rng.normal(0, 0.15)
                    + 0.1 * (s["correct"] - 0.5), 0.02, 0.999))
            for cell in expand_cells(fam, base):
                p, thr = cell["conf"], cell["threshold"]
                commit = (p + rng.normal(0, 0.08)) >= thr  # noisy follower
                act = ("bet" if fam == "bet" else "act") if commit else \
                      ("abstain" if fam == "bet" else "check")
                rows.append(dict(model=model, family=fam, item_id=cell["item_id"],
                                 tier=cell["tier"], epoch=cell["epoch"],
                                 lam=cell["lam"], c=cell["c"], conf=p,
                                 action=act, correct=cell["correct"]))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--call1", default=None,
                        help="Call 1 JSON (results_call1_a.json) to join the "
                             "verdict for the verdict-aware baseline")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--calib-by", choices=["tier", "global"], default="tier",
                    help="level at which empirical accuracy is estimated")
    ap.add_argument("--n-boot", type=int, default=1000)
    a = ap.parse_args()
    raw = demo_data() if a.demo else pd.read_csv(a.csv)
    if a.call1:
        import json as _json
        import re as _re
        c1 = _json.load(open(a.call1))
        verdict = {(r["id"], r["epoch"]): str(r.get("answer_text", "")).strip().upper()
                   for r in c1}
        raw["verdict"] = [verdict.get((i, e)) for i, e in
                          zip(raw.item_id, raw.epoch)]
        # "Working" = any text before the Verdict line (verify) or the
        # Answer line (bet). This is the classification the verify-first
        # analysis rests on, so it is computed here from the raw text.
        def _has_working(r):
            pat = r"verdict\s*:" if r["family"] == "verify" else r"answer\s*:"
            m = _re.search(pat, r.get("raw", ""), _re.IGNORECASE)
            return bool(m and len(r["raw"][:m.start()].strip()) > 0)
        working = {(r["id"], r["epoch"]): _has_working(r) for r in c1}
        raw["working"] = [working.get((i, e)) for i, e in
                          zip(raw.item_id, raw.epoch)]
        # REGRESSION CHECK (added 2026-11-14 after two parser bugs):
        # the sweep's `correct` column must equal Call 1's correctness joined
        # on (item_id, epoch). fix_parser.py once rebuilt this column by
        # joining FOUR Call 1 files (the A run, a re-pilot, and two slices
        # from different models) and let the later files overwrite the A
        # run's values on 14 keys, understating the sweep's bet accuracy to
        # 0.969 and making the bet EVs inconsistent with Table 1. This
        # assertion would have caught that immediately. It also pins the
        # expected wrong-instance counts (31 verify, 4 bet) from the
        # validated A run.
        c1_correct = {(r["id"], r["epoch"]): bool(r["initial_correct"])
                      for r in c1}
        mism = sum(1 for i, e, k in zip(raw.item_id, raw.epoch, raw.correct)
                   if c1_correct.get((i, e)) != bool(k))
        assert mism == 0, \
            f"sweep `correct` disagrees with Call 1 on {mism} rows"
        # Pin the expected wrong-instance counts, but only when the sweep
        # covers the full Call 1 set (3 epochs). The 1-epoch ablation has
        # fewer, so there the mismatch check above is the guard.
        u = raw.drop_duplicates(["item_id", "epoch"])
        if len(u) == len(c1_correct):
            for fam, expected_wrong in (("bet", 4), ("verify", 31)):
                n_wrong = int((~u[u.family == fam].correct.astype(bool)).sum())
                assert n_wrong == expected_wrong, \
                    f"{fam}: {n_wrong} wrong instances in Call 1, expected {expected_wrong}"
            print(f"regression check passed: sweep `correct` == Call 1 on "
                  f"{len(raw)} rows; wrong instances bet 4, verify 31")
        else:
            print(f"regression check passed: sweep `correct` == Call 1 on "
                  f"{len(raw)} rows ({len(u)} of {len(c1_correct)} "
                  f"Call 1 records; partial sweep, count check skipped)")
    df = add_calibrated(score_rows(raw), by=a.calib_by)
    os.makedirs(a.outdir, exist_ok=True)
    tabs = {"model_level": model_level(df), "cell_level": cell_level(df),
            "tier_level": tier_level(df)}
    tabs["sensitivity"] = sensitivity(tabs["cell_level"])
    tabs["ev_gap"] = ev_gap_table(df, n_boot=a.n_boot)
    tabs["ev_gap_headline"] = headline_gap(tabs["ev_gap"])
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    for name, t in tabs.items():
        t.to_csv(f"{a.outdir}/{name}.csv", index=False)
        print(f"\n== {name} ==")
        print(t.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
