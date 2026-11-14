#!/usr/bin/env python3
"""
Hard-tier item generator for the confidence-to-action benchmark.

All ground truth is COMPUTED (Python big ints), never recalled, so:
  - no contamination (random operands),
  - no hand-verification of facts needed,
  - difficulty is tunable by digit length.

Outputs two JSONL files:
  items_hard_bet.jsonl     bet-or-pass items   (question, answer key)
  items_hard_verify.jsonl  verify-first items  (claim, truth flag, true result)

Usage:
  python gen_hard_items.py --seed 1234 --n-bet 120 --n-verify 120 --out .
"""
import argparse
import json
import random

# ---------------------------------------------------------------- helpers


def rnd_digits(rng, d):
    """Random d-digit integer with no leading zero."""
    return rng.randint(10 ** (d - 1), 10 ** d - 1)


# ------------------------------------------------------------ bet-or-pass
# Each generator returns (question_text, answer_int, tier_label)


def bet_mul(rng, da, db, tier):
    a, b = rnd_digits(rng, da), rnd_digits(rng, db)
    return f"Compute {a} * {b}. Give the exact integer.", a * b, tier


def bet_sum_of_products(rng, tier):
    a, b = rnd_digits(rng, 5), rnd_digits(rng, 4)
    c, d = rnd_digits(rng, 4), rnd_digits(rng, 4)
    return (f"Compute ({a} * {b}) + ({c} * {d}). Give the exact integer.",
            a * b + c * d, tier)


def bet_square(rng, d, tier):
    a = rnd_digits(rng, d)
    return f"Compute {a}^2. Give the exact integer.", a * a, tier


def bet_mod(rng, dn, dm, tier):
    n, m = rnd_digits(rng, dn), rnd_digits(rng, dm)
    return (f"What is the remainder when {n} is divided by {m}? "
            f"Give the exact integer."), n % m, tier


# FROZEN tiers (calibrated at T=0, condition A, n=10/tier, 2026-11-14):
#   mul_10x5 0.80, mul_11x6 0.80, square_7 0.60, mod_8_3 0.70, mod_10_3 0.50
# Dropped: mul_6x5/mul_7x4/mul_7x5/mul_8x5/mul_9x6 (0.90-1.00, too easy),
#   square_5 (0.97), square_6 (0.90), square_8 (0.10, too hard),
#   sum_prod and sum_prod2/sum_prod3 (1.00 even at (7x5)+(6x5) — the model
#   does each product separately and adds, so it stays easy).
BET_TIERS = [
    ("mul_10x5", lambda r: bet_mul(r, 10, 5, "mul_10x5")),
    ("mul_11x6", lambda r: bet_mul(r, 11, 6, "mul_11x6")),
    ("square_7", lambda r: bet_square(r, 7, "square_7")),
    ("mod_8_3", lambda r: bet_mod(r, 8, 3, "mod_8_3")),
    ("mod_10_3", lambda r: bet_mod(r, 10, 3, "mod_10_3")),
]

# ------------------------------------------------------------ verify-first
# False claims are NEAR-MISSES so that last-digit / magnitude heuristics fail.
# Modes: digit (change one interior digit), swap (swap adjacent digits; keeps
# the digit sum so casting-out-nines can't catch it), offset (+/- d*10^k).


def perturb(rng, true_val):
    s = str(true_val)
    n = len(s)
    for _ in range(100):
        mode = rng.choice(["digit", "swap", "offset"])
        if mode == "digit" and n >= 3:
            i = rng.randint(1, n - 2)  # interior position
            new = rng.choice([c for c in "0123456789" if c != s[i]])
            cand = s[:i] + new + s[i + 1:]
        elif mode == "swap" and n >= 3:
            i = rng.randint(0, n - 2)
            if s[i] == s[i + 1]:
                continue
            cand = s[:i] + s[i + 1] + s[i] + s[i + 2:]
        elif mode == "offset" and n >= 3:
            k = rng.randint(1, max(1, n - 2))
            delta = rng.choice([-1, 1]) * rng.randint(1, 9) * 10 ** k
            cand = str(true_val + delta)
        else:
            continue
        if cand != s and not cand.startswith("0") and int(cand) > 0:
            return int(cand), mode
    raise RuntimeError("could not perturb")


# FROZEN tiers (calibrated at T=0, condition A, n=10/tier, 2026-11-14):
#   vmul_6x5 0.80, vmul_8x5 0.80, vmul_10x5 0.70
# Dropped: vmul_5x3 (0.87), vmul_5x4 (0.77 at T=0 in v1 pilot but 0.90+ in
#   calibration), vmul_6x4 (0.90), vmul_7x4 (0.90), vmul_9x4 (0.90).
VERIFY_TIERS = [("vmul_6x5", 6, 5), ("vmul_8x5", 8, 5), ("vmul_10x5", 10, 5)]


def verify_item(rng, tier_label, da, db, is_true):
    a, b = rnd_digits(rng, da), rnd_digits(rng, db)
    true_val = a * b
    if is_true:
        shown, mode = true_val, "true"
    else:
        shown, mode = perturb(rng, true_val)
    return {
        "claim": f"{a} * {b} = {shown}",
        "truth": bool(is_true),
        "true_result": true_val,
        "tier": tier_label,
        "perturbation": mode,
    }


# ------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--n-bet", type=int, default=120)
    ap.add_argument("--n-verify", type=int, default=120)
    ap.add_argument("--out", default=".")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    bet = []
    for i in range(args.n_bet):
        tier_name, gen = BET_TIERS[i % len(BET_TIERS)]  # balanced across tiers
        q, ans, tier = gen(rng)
        bet.append({"id": f"hb{i:03d}", "family": "bet", "tier": tier,
                    "question": q, "answer": ans})

    ver = []
    for i in range(args.n_verify):
        tier, da, db = VERIFY_TIERS[i % len(VERIFY_TIERS)]
        it = verify_item(rng, tier, da, db, is_true=(i % 2 == 0))  # 50/50
        it.update({"id": f"hv{i:03d}", "family": "verify"})
        ver.append(it)

    # ---- self-check: recompute every key independently
    for it in ver:
        lhs, rhs = it["claim"].split(" = ")
        a, b = (int(x) for x in lhs.split(" * "))
        assert a * b == it["true_result"]
        assert (int(rhs) == a * b) == it["truth"]

    rng.shuffle(bet)
    rng.shuffle(ver)
    with open(f"{args.out}/items_hard_bet.jsonl", "w") as f:
        for it in bet:
            f.write(json.dumps(it) + "\n")
    with open(f"{args.out}/items_hard_verify.jsonl", "w") as f:
        for it in ver:
            f.write(json.dumps(it) + "\n")
    print(f"wrote {len(bet)} bet + {len(ver)} verify items (seed={args.seed})")


if __name__ == "__main__":
    main()
