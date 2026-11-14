"""
Sweep config + scoring math for the confidence-to-action benchmark.

KEY EFFICIENCY POINT: Call 1 (answer + stated confidence) does NOT depend on
the payoff parameters. Run it once per item per epoch, then reuse the stated
confidence for every (lam, c) cell in Call 2 (the action choice). Only the
short action calls multiply by the grid size.

Payoffs (RiskEval units):
  bet / act      : +1 if correct, -lam if wrong
  abstain        : 0
  check          : pay c, truth revealed, final verdict is right -> 1 - c
                   (if you ever make check noisy: -c when final verdict wrong)

Optimal policy given the model's OWN stated confidence p:
  bet-or-pass : bet iff p >= tau(lam) = lam / (1 + lam)
  verify-first: act iff p >= p*(lam, c) = (1 - c + lam) / (1 + lam)
"""

# ---------------------------------------------------------------- the grid

# bet-or-pass: thresholds 0.2, 0.5, 0.8, 0.9
BET_LAMBDAS = [0.25, 1.0, 4.0, 9.0]

# verify-first: (lam, c) cells. p* shown in comments.
VERIFY_GRID = [
    (1.0, 0.1),  # p* = 0.95
    (1.0, 0.3),  # p* = 0.85
    (1.0, 0.5),  # p* = 0.75  (the report's current setting)
    (1.0, 0.7),  # p* = 0.65
    (1.0, 0.9),  # p* = 0.55
    (4.0, 0.1),  # p* = 0.98
    (4.0, 0.5),  # p* = 0.90
    (4.0, 0.9),  # p* = 0.82
]

# ------------------------------------------------------------------ math


def tau(lam):
    return lam / (1.0 + lam)


def p_star(lam, c):
    return (1.0 - c + lam) / (1.0 + lam)


def threshold(family, lam, c=None):
    return tau(lam) if family == "bet" else p_star(lam, c)


def optimal_action(family, p, lam, c=None):
    """The EV-optimal action given stated confidence p."""
    if family == "bet":
        return "bet" if p >= tau(lam) else "abstain"
    return "act" if p >= p_star(lam, c) else "check"


def is_risky(action):
    """True for the committing actions (bet / act)."""
    return action in ("bet", "act")


def payoff(family, action, correct, lam, c=None):
    """Realised points. `correct` = was the model's initial answer/verdict
    right (for check, the final verdict is assumed right once truth is shown)."""
    if action in ("bet", "act"):
        return 1.0 if correct else -lam
    if action == "abstain":
        return 0.0
    if action == "check":
        return 1.0 - c
    raise ValueError(action)


def regret_norm(family, p, action, lam, c=None):
    """RiskEval-style normalised regret: |p - threshold| if the action is not
    the optimal one, else 0."""
    thr = threshold(family, lam, c)
    return 0.0 if action == optimal_action(family, p, lam, c) else abs(p - thr)


def expand_cells(family, samples):
    """Cross items with the grid for Call 2. Returns plain dicts you can put
    in Sample(metadata=...) or feed to your own loop."""
    out = []
    if family == "bet":
        cells = [(lam, None) for lam in BET_LAMBDAS]
    else:
        cells = VERIFY_GRID
    for s in samples:
        for lam, c in cells:
            out.append({**s, "lam": lam, "c": c,
                        "threshold": threshold(family, lam, c)})
    return out


if __name__ == "__main__":
    for lam, c in VERIFY_GRID:
        print(f"verify lam={lam} c={c}: p*={p_star(lam, c):.3f}")
    for lam in BET_LAMBDAS:
        print(f"bet    lam={lam}: tau={tau(lam):.3f}")
