"""Regenerate figure_ev.png from the corrected out/ev_gap.csv.
Two panels: (a) bet EV vs lambda, (b) verify EV vs check cost c (lam=1 and lam=4),
showing the model, the calibrated policy, and the check-iff-no-working baseline
(in-sample, observable from the transcript)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

eg = pd.read_csv("out/ev_gap.csv")

fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))

# Panel A: bet EV vs lambda
bet = eg[eg.family == "bet"].sort_values("lam")
ax = axes[0]
ax.plot(bet.lam, bet.ev_model, "o-", label="Model", color="#1f77b4")
ax.plot(bet.lam, bet.ev_calib, "s--", label="Calibrated policy (in-sample)", color="#ff7f0e")
ax.axhline(0, color="grey", linewidth=0.8, linestyle=":")
ax.set_xlabel("Penalty  λ")
ax.set_ylabel("Expected value per item")
ax.set_title("(a) Bet-or-pass: EV vs penalty")
ax.set_xticks(bet.lam.tolist())
ax.legend(fontsize=8, loc="lower left")
ax.grid(alpha=0.3)

# Panel B: verify EV vs check cost c, for lam=1 and lam=4
ver = eg[eg.family == "verify"]
ax = axes[1]
for lam, marker, color in [(1.0, "o", "#1f77b4"), (4.0, "s", "#2ca02c")]:
    d = ver[ver.lam == lam].sort_values("c")
    ax.plot(d["c"], d.ev_model, marker + "-", label=f"Model, λ={lam:g}", color=color)
    ax.plot(d["c"], d.ev_calib, marker + "--", label=f"Calibrated, λ={lam:g}", color=color, alpha=0.6)
    ax.plot(d["c"], d.ev_nowork, marker + ":", label=f"Check iff no working, λ={lam:g}", color=color, alpha=0.85)
ax.set_xlabel("Check cost  c")
ax.set_ylabel("Expected value per item")
ax.set_title("(b) Verify-first: EV vs check cost")
ax.legend(fontsize=7, loc="lower left")
ax.grid(alpha=0.3)

fig.tight_layout()
fig.savefig("figure_ev.png", dpi=200)
print("wrote figure_ev.png")
