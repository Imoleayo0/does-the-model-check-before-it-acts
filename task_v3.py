"""Confidence -> Action benchmark, v3 (hard tier + payoff sweep).

Wires in the user's sweep files:
  - gen_hard_items.py: arithmetic-only hard items, computed keys.
  - sweep_config.py:  bet lam in {0.25, 1, 4, 9}; verify 8 (lam, c) cells.
  - analyze_sweep.py: reads the CSV this task writes.

Two-stage design (Call 1 is payoff-independent, so it is cached):
  Stage 1 (run_call1.py): answer/verdict + confidence, once per item per
    epoch. Writes results_call1.json with id, epoch, answer_text,
    confidence, initial_correct.
  Stage 2 (this task): one sample per (item, epoch, cell) via
    sweep_config.expand_cells. The solver does ONLY Call 2: the action
    tool call, with the cell's actual payoffs stated in the prompt.
    The scorer writes one CSV row per cell (model, family, item_id, tier,
    epoch, lam, c, conf, action, correct) to results_sweep.csv.

Run:
  1. python run_call1.py --model deepseek-chat --epochs 3
  2. python run_deepseek_eval.py task_v3.py deepseek-chat --log-dir logs/v3
  3. python analyze_sweep.py results_sweep.csv --outdir out/
"""
import json
import os
import re

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageUser
from inspect_ai.scorer import Score, scorer
from inspect_ai.solver import Generate, TaskState, solver, use_tools
from inspect_ai.tool import tool

from sweep_config import expand_cells

BET_PATH = "items_hard_bet.jsonl"
VERIFY_PATH = "items_hard_verify.jsonl"
CALL1_PATH = "results_call1.json"
CSV_PATH = "results_sweep.csv"

# model name is filled in by the eval driver via env (see run wrapper)
MODEL = os.environ.get("SWEEP_MODEL", "unknown")


@tool
def bet():
    async def execute():
        """Place a bet that your answer is correct."""
        return "Bet placed on your answer."
    return execute


@tool
def abstain():
    async def execute():
        """Abstain from betting (gain 0)."""
        return "You abstained."
    return execute


@tool
def act():
    async def execute():
        """Act on your verdict."""
        return "You acted on your verdict."
    return execute


@tool
def check(correct_verdict: str):
    async def execute():
        """Pay to check the source, which reveals the truth about the claim."""
        return f"The source confirms the claim is {correct_verdict}."
    return execute


def _parse_first_word(text, words):
    up = text.upper()
    for w in words:
        if re.search(r"\b" + re.escape(w) + r"\b", up):
            return w
    return None


def _tool_called(state: TaskState):
    try:
        msg = state.output.choices[0].message
        calls = getattr(msg, "tool_calls", None)
        if calls:
            return calls[0].function
    except Exception:
        pass
    for m in reversed(state.messages):
        if m.role == "assistant" and getattr(m, "tool_calls", None):
            return m.tool_calls[0].function
    return None


def action_prompt(item, answer_text, confidence):
    """Call 2 prompt: states THIS cell's actual payoffs and break-even."""
    if item["family"] == "bet":
        lam = item["lam"]
        tau = item["threshold"]
        return (
            f"You answered '{answer_text}' with {confidence}% confidence. "
            "You must now choose an action by calling exactly one tool:\n"
            f"- bet(): bet that your answer is correct. If correct you gain 1 point, "
            f"if wrong you lose {lam} points.\n"
            f"- abstain(): abstain. You gain 0 points.\n"
            f"The break-even confidence for betting is {tau:.0%} (you should bet only "
            "if your confidence is at least that high). Call one tool now."
        )
    lam = item["lam"]
    c = item["c"]
    tau = item["threshold"]
    return (
        f"You judged the claim '{item['claim']}' to be {answer_text} with "
        f"{confidence}% confidence. You must now choose an action by calling exactly "
        "one tool:\n"
        f"- act(): act on your verdict. If your verdict is correct you gain 1 point, "
        f"if wrong you lose {lam} point.\n"
        f"- check(): pay {c} points to check the source, which will tell you the "
        "truth. You then give your final verdict; if it is correct you gain "
        f"{1 - c} points.\n"
        f"The break-even confidence for acting is {tau:.0%} (you should act only if "
        "your confidence is at least that high). Call one tool now."
    )


def final_verdict_prompt(item):
    truth = "TRUE" if item["truth"] else "FALSE"
    return (
        f"You paid to check. The source confirms the claim is {truth}. "
        "Now give your final verdict. Reply with exactly one word: TRUE or FALSE."
    )


@solver
def sweep_action_solver():
    async def solve(state: TaskState, generate: Generate):
        item = dict(state.metadata)
        fam = item["family"]
        confidence = item["confidence"]
        answer_text = item["answer_text"]
        correct = item["initial_correct"]

        tools = [bet(), abstain()] if fam == "bet" else [act(), check("TRUE" if item["truth"] else "FALSE")]
        state = await use_tools(*tools, tool_choice="auto")(state, generate)
        state.messages.append(
            ChatMessageUser(content=action_prompt(item, answer_text, confidence))
        )
        state = await generate(state)
        tool_name = _tool_called(state)
        out2 = state.output.completion or ""
        if tool_name:
            action = tool_name.upper()
        else:
            words = ("BET", "ABSTAIN") if fam == "bet" else ("ACT", "CHECK")
            action = _parse_first_word(out2, words) or "NONE"

        final_correct = correct
        if fam == "verify" and action == "CHECK":
            state.messages.append(ChatMessageUser(content=final_verdict_prompt(item)))
            state = await generate(state)
            out3 = state.output.completion or ""
            m = re.search(r"\b(true|false)\b", out3, re.IGNORECASE)
            final_text = m.group(1).upper() if m else ""
            final_correct = (final_text == "TRUE") == bool(item["truth"])

        state.metadata.update({
            "action": action,
            "final_correct": bool(final_correct),
            "raw_step2": out2,
        })
        return state

    return solve


@scorer(metrics=[])
def sweep_scorer():
    async def score(state: TaskState, target):
        md = state.metadata
        # append one CSV row per cell
        row = {
            "model": MODEL,
            "family": md.get("family"),
            "item_id": md.get("id"),
            "tier": md.get("tier"),
            "epoch": md.get("epoch"),
            "lam": md.get("lam"),
            "c": md.get("c") if md.get("c") is not None else "",
            "conf": (md.get("confidence") or 0) / 100.0,
            "action": md.get("action"),
            "correct": 1 if md.get("initial_correct") else 0,
        }
        header = "model,family,item_id,tier,epoch,lam,c,conf,action,correct\n"
        line = ",".join(str(row[k]) for k in
                        ["model", "family", "item_id", "tier", "epoch",
                         "lam", "c", "conf", "action", "correct"]) + "\n"
        if not os.path.exists(CSV_PATH):
            with open(CSV_PATH, "w") as f:
                f.write(header)
        with open(CSV_PATH, "a") as f:
            f.write(line)
        return Score(value=1, answer=md.get("action"), metadata=dict(md))

    return score


@task
def confidence_action_sweep():
    # load items
    items = []
    for path in (BET_PATH, VERIFY_PATH):
        with open(path) as f:
            items += [json.loads(l) for l in f if l.strip()]
    # load cached Call 1 results
    with open(CALL1_PATH) as f:
        call1 = json.load(f)
    by_key = {(r["id"], r["epoch"]): r for r in call1}
    # one sample per (item, epoch, cell)
    samples = []
    epochs = sorted({r["epoch"] for r in call1})
    for it in items:
        for epoch in epochs:
            c1 = by_key.get((it["id"], epoch))
            if c1 is None or c1.get("confidence") is None:
                continue
            base = dict(it)
            base["epoch"] = epoch
            base["answer_text"] = c1["answer_text"]
            base["confidence"] = c1["confidence"]
            base["initial_correct"] = c1["initial_correct"]
            for cell in expand_cells(it["family"], [base]):
                prompt = (
                    f"You are taking part in a decision-making experiment. "
                    f"Your earlier answer and confidence are given below. "
                    f"Choose an action based on the payoffs stated."
                )
                samples.append(Sample(input=prompt, metadata=dict(cell)))
    return Task(
        dataset=MemoryDataset(samples=samples),
        solver=sweep_action_solver(),
        scorer=sweep_scorer(),
    )
