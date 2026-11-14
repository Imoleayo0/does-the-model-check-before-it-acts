"""Call 1, condition A only, T=0, multi-epoch (the full primary run).

Post-work verbal confidence, greedy (T=0) for reproducibility. The first
pilot at default sampling got ~68% accuracy; at T=0 the frozen tiers are
50-80% — that decoding difference is reported as a limitation.

Writes results_call1_a.json (resumable). Used by task_v3.py for the
action sweep (Call 2).
Usage: python run_call1_a.py --model deepseek-chat --epochs 3 --out results_call1_a.json
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
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--out", default="results_call1_a.json")
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
        done = {(r["id"], r["epoch"]) for r in results}
    except Exception:
        pass

    for epoch in range(args.epochs):
        for it in items:
            if (it["id"], epoch) in done:
                continue
            print(f"{it['id']} A epoch {epoch} ...", flush=True)
            try:
                raw, usage = call_model(api_key, args.model, prompt_a(it))
            except Exception as e:
                print(f"  ERROR A {it['id']}: {e}", flush=True)
                continue
            ans, correct = parse_answer(it, raw)
            conf = _parse_confidence(raw)
            results.append({"id": it["id"], "family": it["family"],
                            "tier": it["tier"], "epoch": epoch,
                            "condition": "A", "model": f"{args.model}|A",
                            "answer_text": ans, "confidence": conf,
                            "initial_correct": bool(correct),
                            "total_tokens": usage.get("total_tokens"),
                            "raw": raw})
            json.dump(results, open(args.out, "w"), indent=2)
            print(f"  -> A conf={conf} correct={correct} toks={usage.get('total_tokens')}",
                  flush=True)
    print(f"done: {len(results)} Call 1 A records -> {args.out}")


if __name__ == "__main__":
    main()
