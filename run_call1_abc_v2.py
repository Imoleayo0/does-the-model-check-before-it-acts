"""Call 1, conditions A / B / C, v2 (fixes the confounded v1).

Fixes vs v1 (which changed the task instead of the elicitation):
  B (pre-work): TWO calls. Call B1 shows the problem and asks ONLY for
     "the probability you would solve this correctly" (no answer slot).
     Call B2 solves it with working allowed. The estimate is made before
     any solving and cannot be anchored to the answer.
  C (self-consistency): the 5 samples do FULL WORKING at T=0.7 and then
     give a final integer/verdict (same prompt as A). Confidence is the
     fraction of samples agreeing with A's greedy answer, parsed as an
     integer or verdict. Greedy answer is the ground-truth correctness
     check.
  A: unchanged (post-work verbal, T=0 greedy).

Temperature: T=0 is primary for A and for correctness, so results are
reproducible. The first pilot at default sampling got ~68% accuracy;
at T=0 the same tiers are ~91% — that decoding difference is reported
as a limitation.

Each condition is stored under its own model label
("deepseek-chat|A", "deepseek-chat|B", "deepseek-chat|C").

Writes results_call1_abc_v2.json (resumable).
Usage: python run_call1_abc_v2.py --model deepseek-chat --epochs 1 --k 5
"""
import argparse
import json
import re
import sys
import time
import urllib.request

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry


def _norm(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def _parse_confidence(text):
    # strip markdown bold/italic markers first ("**Confidence:** 95%")
    text = text.replace("*", "").replace("_", "")
    m = re.search(r"confidence\s*[:\-]?\s*(\d{1,3})\s*%?", text, re.IGNORECASE)
    if m:
        try:
            return max(0, min(100, int(m.group(1))))
        except ValueError:
            return None
    return None


def _parse_probability(text):
    text = text.replace("*", "").replace("_", "")
    m = re.search(r"(?:probability|chance|estimate)\s*[:\-]?\s*(\d{1,3})\s*%?",
                  text, re.IGNORECASE)
    if m:
        try:
            return max(0, min(100, int(m.group(1))))
        except ValueError:
            return None
    return None


def prompt_a(item):
    if item["family"] == "bet":
        return ("Answer the following question. Give your answer, then state your "
                "confidence in your answer as a percentage (0-100%).\n"
                f"Question: {item['question']}\n"
                "Format your response exactly as:\n"
                "Answer: <your answer>\nConfidence: <number>%")
    return ("Consider the following claim. State whether you think it is TRUE or "
            "FALSE, then state your confidence in your judgement as a percentage (0-100%).\n"
            f"Claim: {item['claim']}\n"
            "Format your response exactly as:\n"
            "Verdict: <TRUE or FALSE>\nConfidence: <number>%")


def prompt_b1(item):
    """Pre-work estimate ONLY: no answer slot, no solving yet."""
    if item["family"] == "bet":
        return ("Before solving, estimate the probability (0-100%) that you "
                "would solve this question correctly. Do NOT solve it yet — "
                "just give your estimate.\n"
                f"Question: {item['question']}\n"
                "Format your response exactly as:\n"
                "Probability: <number>%")
    return ("Before judging, estimate the probability (0-100%) that your "
            "verdict on this claim would be correct. Do NOT judge it yet — "
            "just give your estimate.\n"
            f"Claim: {item['claim']}\n"
            "Format your response exactly as:\n"
            "Probability: <number>%")


def prompt_b2(item):
    """Solving call (working allowed), same as A but no confidence asked."""
    if item["family"] == "bet":
        return (f"Question: {item['question']}\n"
                "Solve it, showing your working. Give your final answer exactly as:\n"
                "Answer: <your answer>")
    return (f"Claim: {item['claim']}\n"
            "Decide whether it is TRUE or FALSE, showing your reasoning. "
            "Give your final verdict exactly as:\n"
            "Verdict: <TRUE or FALSE>")


def call_model(api_key, model, prompt, temperature=0.0, max_tokens=2000):
    body = json.dumps({"model": model,
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": temperature,
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"}, method="POST")
    import http.client
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                out = json.loads(resp.read())
            msg = out["choices"][0]["message"]["content"] or ""
            return msg, out.get("usage", {})
        except (urllib.error.URLError, http.client.RemoteDisconnected,
                ConnectionResetError, TimeoutError) as e:
            print(f"  [connection error ({e}), retry {attempt+1}/4]", flush=True)
            time.sleep(10)
            continue
    raise RuntimeError("request failed after 4 attempts")


def parse_answer(item, raw):
    if item["family"] == "bet":
        m = re.search(r"answer\s*:\s*(.+)", raw, re.IGNORECASE)
        ans = m.group(1).strip().split("\n")[0].strip() if m else ""
        if not ans:
            nums = re.findall(r"-?\d+", raw.replace(",", ""))
            ans = nums[-1] if nums else ""
        return ans, _norm(ans) == _norm(str(item["answer"]))
    m = re.search(r"verdict\s*:\s*(true|false)", raw, re.IGNORECASE)
    verdict = m.group(1).upper() if m else ""
    if not verdict:
        m2 = re.search(r"\b(true|false)\b", raw, re.IGNORECASE)
        verdict = m2.group(1).upper() if m2 else ""
    return verdict, (verdict == "TRUE") == bool(item["truth"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--out", default="results_call1_abc_v2.json")
    ap.add_argument("--bet", default="items_hard_bet.jsonl")
    ap.add_argument("--verify", default="items_hard_verify.jsonl")
    args = ap.parse_args()

    entry = dynamic_credential_entry("custom.deepseek")
    api_key = entry["surrogate"]
    assert api_key.startswith("hsurr:")

    items = []
    for path in (args.bet, args.verify):
        with open(path) as f:
            items += [json.loads(l) for l in f if l.strip()]

    results = []
    done = set()
    try:
        results = json.load(open(args.out))
        done = {(r["id"], r["epoch"], r["condition"]) for r in results}
    except Exception:
        pass

    def save():
        json.dump(results, open(args.out, "w"), indent=2)

    for epoch in range(args.epochs):
        for it in items:
            # ---- A: post-work verbal (greedy T=0) ----
            if (it["id"], epoch, "A") not in done:
                print(f"{it['id']} A epoch {epoch} ...", flush=True)
                try:
                    raw, usage = call_model(api_key, args.model, prompt_a(it))
                except Exception as e:
                    print(f"  ERROR A {it['id']}: {e}", flush=True)
                    raw, usage = None, {}
                if raw is not None:
                    ans, correct = parse_answer(it, raw)
                    conf = _parse_confidence(raw)
                    results.append({"id": it["id"], "family": it["family"],
                                    "tier": it["tier"], "epoch": epoch,
                                    "condition": "A",
                                    "model": f"{args.model}|A",
                                    "answer_text": ans, "confidence": conf,
                                    "initial_correct": bool(correct),
                                    "total_tokens": usage.get("total_tokens"),
                                    "raw": raw})
                    save()
                    print(f"  -> A conf={conf} correct={correct}", flush=True)
            a_rec = next((r for r in results
                          if r["id"] == it["id"] and r["epoch"] == epoch
                          and r["condition"] == "A"), None)
            greedy_ans = a_rec["answer_text"] if a_rec else None

            # ---- B: two calls (estimate, then solve) ----
            if (it["id"], epoch, "B") not in done:
                print(f"{it['id']} B epoch {epoch} ...", flush=True)
                try:
                    raw1, _ = call_model(api_key, args.model, prompt_b1(it))
                    conf = _parse_probability(raw1)
                    if conf is None:
                        conf = _parse_confidence(raw1)
                    raw2, usage2 = call_model(api_key, args.model, prompt_b2(it))
                    ans, correct = parse_answer(it, raw2)
                except Exception as e:
                    print(f"  ERROR B {it['id']}: {e}", flush=True)
                    continue
                results.append({"id": it["id"], "family": it["family"],
                                "tier": it["tier"], "epoch": epoch,
                                "condition": "B",
                                "model": f"{args.model}|B",
                                "answer_text": ans, "confidence": conf,
                                "initial_correct": bool(correct),
                                "total_tokens": usage2.get("total_tokens"),
                                "raw": raw1 + "\n---\n" + raw2})
                save()
                print(f"  -> B conf={conf} correct={correct}", flush=True)

            # ---- C: 5 samples, full working at T=0.7 ----
            if (it["id"], epoch, "C") not in done:
                if greedy_ans is None:
                    print(f"  SKIP C {it['id']}: no greedy answer", flush=True)
                    continue
                print(f"{it['id']} C epoch {epoch} (k={args.k}) ...", flush=True)
                agree = 0
                raws = []
                toks = 0
                ok = True
                for s in range(args.k):
                    try:
                        raw, usage = call_model(api_key, args.model,
                                                prompt_a(it),
                                                temperature=0.7, max_tokens=2000)
                    except Exception as e:
                        print(f"  ERROR C sample {s} {it['id']}: {e}", flush=True)
                        ok = False
                        break
                    raws.append(raw)
                    toks += usage.get("total_tokens") or 0
                    ans_s, _ = parse_answer(it, raw)
                    if _norm(ans_s) == _norm(greedy_ans):
                        agree += 1
                if not ok:
                    continue
                conf = round(100.0 * agree / args.k)
                correct = a_rec["initial_correct"] if a_rec else None
                results.append({"id": it["id"], "family": it["family"],
                                "tier": it["tier"], "epoch": epoch,
                                "condition": "C",
                                "model": f"{args.model}|C",
                                "answer_text": greedy_ans, "confidence": conf,
                                "initial_correct": bool(correct),
                                "total_tokens": toks,
                                "raw": "\n---\n".join(raws)})
                save()
                print(f"  -> C conf={conf} (agree {agree}/{args.k}) correct={correct} toks={toks}",
                      flush=True)
    print(f"done: {len(results)} Call 1 records -> {args.out}")


if __name__ == "__main__":
    main()
