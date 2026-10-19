#!/usr/bin/env python3
"""
Compare Ollama embedding models for HINAKU's memory retrieval.

Usage (from your project folder, venv active, Ollama running):
    python compare_embeddings.py
    python compare_embeddings.py --verbose        # show every miss
    python compare_embeddings.py --selftest       # check the script itself, no Ollama needed

Uses only the Python standard library. All test data below is made up
(sample memories), so nothing personal is sent anywhere. Everything runs
against your local Ollama.
"""
import argparse, json, math, sys, time, urllib.request, urllib.error, hashlib

# ---------------------------------------------------------------- test data
MEMORIES = [
    "Uses a laptop with an RTX 4050 GPU and 6 GB of VRAM",                 # 0
    "Favorite code editor is VS Code",                                      # 1
    "Is a 4th-year computer science student",                               # 2
    "Prefers short, direct answers without long preambles",                 # 3
    "Wants the assistant to have a calm, composed personality",             # 4
    "Builds AI projects in Python 3.11",                                    # 5
    "Plans to retrain a small local model every 6 months",                  # 6
    "Uses Ollama to run local language models",                             # 7
    "Drinks tea instead of coffee",                                         # 8
    "Lives in Telangana, India",                                            # 9
    "Has a pet dog named Bruno",                                            # 10
    "Prefers dark mode in every app",                                       # 11
    "Wakes up at 6 AM on weekdays",                                         # 12
    "Likes watching anime in the evenings",                                 # 13
    "Is learning Japanese",                                                 # 14
    "Is building a tool that turns videos into training data",              # 15
    "Stores project code on GitHub",                                        # 16
    "Wants the app to work offline whenever possible",                      # 17
    "Prefers Windows over Linux for daily use",                             # 18
    "Wants a second monitor for coding",                                    # 19
]

# (query, index of the memory that should be retrieved) - paraphrased on purpose
POSITIVE = [
    ("Which graphics card should I plan model training around?", 0),
    ("Which editor should I set my shortcuts up in?", 1),
    ("How should I describe my background in an internship application?", 2),
    ("How long should your replies be?", 3),
    ("How should the assistant sound when it talks to me?", 4),
    ("Which Python version should I create the virtual environment with?", 5),
    ("How often should the retraining job run?", 6),
    ("What tool serves my local language models?", 7),
    ("What should I make for a hot drink in the morning?", 8),
    ("Which state am I located in?", 9),
    ("I want to buy a toy for my pet", 10),
    ("Which theme should the interface use by default?", 11),
    ("When should my morning reminder go off?", 12),
    ("Suggest something to watch tonight", 13),
    ("Recommend an app for practicing a new language", 14),
    ("Which of my projects converts video into datasets?", 15),
    ("Where is my code hosted?", 16),
    ("Should the assistant need an internet connection to work?", 17),
    ("Which operating system do I use every day?", 18),
    ("What hardware upgrade would improve my coding setup?", 19),
]

# unrelated queries: nothing should be retrieved for these
NEGATIVE = [
    "Give me a quick fact about bananas",
    "What is the capital of Australia?",
    "Explain how photosynthesis works",
    "What is 17 times 24?",
    "Tell me a joke about cats",
    "How tall is Mount Everest?",
    "What year did World War 2 end?",
    "How do vaccines train the immune system?",
]

QWEN_INSTRUCT = ("Instruct: Given the owner's message, retrieve stored facts "
                 "about the owner that help answer it\nQuery: ")

# (label, ollama model, query prefix, document prefix)
# If nomic-embed-text-v2-moe is installed, use it; otherwise default to nomic-embed-text
NOMIC_MODEL = "nomic-embed-text-v2-moe"

VARIANTS = [
    (f"{NOMIC_MODEL} (with prefixes)", NOMIC_MODEL, "search_query: ", "search_document: "),
    ("qwen3-embedding:0.6b (with instruction)", "qwen3-embedding:0.6b", QWEN_INSTRUCT, ""),
    ("qwen3-embedding:0.6b (no instruction)", "qwen3-embedding:0.6b", "", ""),
]

# ---------------------------------------------------------------- embedding
def ollama_embed(host, model, texts):
    body = json.dumps({"model": model, "input": texts}).encode()
    req = urllib.request.Request(host.rstrip("/") + "/api/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())["embeddings"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        sys.exit(f"\nOllama returned an error for '{model}': {e.code} {detail}\n"
                 f"Is the model pulled?  ->  ollama pull {model}")
    except urllib.error.URLError as e:
        sys.exit(f"\nCannot reach Ollama at {host}: {e.reason}\nIs Ollama running?")

def fake_embed(_host, _model, texts):
    """Offline stand-in for --selftest: hashed bag of words (NOT a real model)."""
    out = []
    for t in texts:
        v = [0.0] * 256
        for w in "".join(c.lower() if c.isalnum() else " " for c in t).split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1.0
        out.append(v)
    return out

def normalize(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]

def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))

# ---------------------------------------------------------------- evaluation
def evaluate(embed, host, label, model, qpre, dpre, verbose):
    embed(host, model, ["warm up"])                       # load model, not timed
    t0 = time.time()
    docs = [normalize(v) for v in embed(host, model, [dpre + m for m in MEMORIES])]
    pos_q = [normalize(v) for v in embed(host, model, [qpre + q for q, _ in POSITIVE])]
    neg_q = [normalize(v) for v in embed(host, model, [qpre + q for q in NEGATIVE])]
    elapsed = time.time() - t0

    top1 = top3 = 0
    rr_sum = 0.0
    pos_top = []        # (score of best match, was it correct)
    misses = []
    for (q, want), qv in zip(POSITIVE, pos_q):
        scores = sorted(((cosine(qv, d), i) for i, d in enumerate(docs)), reverse=True)
        ranking = [i for _, i in scores]
        rank = ranking.index(want) + 1
        top1 += rank == 1
        top3 += rank <= 3
        rr_sum += 1.0 / rank
        pos_top.append((scores[0][0], rank == 1))
        if rank != 1:
            misses.append((q, MEMORIES[want], rank, MEMORIES[ranking[0]]))

    neg_top = [max(cosine(qv, d) for d in docs) for qv in neg_q]

    # best similarity threshold: retrieve only if score >= t
    cands = sorted({s for s, _ in pos_top} | set(neg_top))
    best = (-1, 0.0)
    for t in cands:
        correct = sum(1 for s, ok in pos_top if ok and s >= t) + sum(1 for s in neg_top if s < t)
        if correct > best[0] or (correct == best[0] and t > best[1]):
            best = (correct, t)
    total = len(POSITIVE) + len(NEGATIVE)

    return {
        "label": label, "model": model, "dims": len(docs[0]),
        "top1": top1 / len(POSITIVE), "top3": top3 / len(POSITIVE),
        "mrr": rr_sum / len(POSITIVE),
        "neg_max": max(neg_top), "neg_mean": sum(neg_top) / len(neg_top),
        "pos_min": min(s for s, _ in pos_top), "pos_mean": sum(s for s, _ in pos_top) / len(pos_top),
        "threshold": best[1], "threshold_acc": best[0] / total,
        "seconds": elapsed, "misses": misses,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="run with a fake embedder to check the script")
    ap.add_argument("--out", default="embedding_comparison.json")
    a = ap.parse_args()
    embed = fake_embed if a.selftest else ollama_embed
    if a.selftest:
        print("SELFTEST: using a fake word-hash embedder. Numbers below are NOT real model results.\n")

    results = []
    for label, model, qpre, dpre in VARIANTS:
        print(f"Testing {label} ...", flush=True)
        results.append(evaluate(embed, a.host, label, model, qpre, dpre, a.verbose))

    print("\n" + "=" * 100)
    print(f"{'variant':44}{'top-1':>8}{'top-3':>8}{'MRR':>7}{'dims':>6}{'secs':>7}  {'best thr':>9}{'thr acc':>9}")
    print("-" * 100)
    for r in results:
        print(f"{r['label']:44}{r['top1']:>8.0%}{r['top3']:>8.0%}{r['mrr']:>7.2f}{r['dims']:>6}"
              f"{r['seconds']:>7.1f}  {r['threshold']:>9.3f}{r['threshold_acc']:>9.0%}")
    print("=" * 100)
    print("top-1 / top-3 / MRR : did the right memory rank first / in the top 3 (higher is better)")
    print("best thr            : similarity cutoff that best separates 'relevant' from 'unrelated' queries")
    print("thr acc             : accuracy of the 28 queries (20 relevant + 8 unrelated) at that cutoff")
    print("\nScore separation (relevant best-match vs unrelated best-match):")
    for r in results:
        gap = r["pos_min"] - r["neg_max"]
        print(f"  {r['label']:44} relevant min {r['pos_min']:.3f} | unrelated max {r['neg_max']:.3f} | gap {gap:+.3f}")
    if a.verbose:
        for r in results:
            if r["misses"]:
                print(f"\nMisses for {r['label']}:")
                for q, want, rank, got in r["misses"]:
                    print(f"  Q: {q}\n     wanted: {want}  (ranked #{rank})\n     got:    {got}")
    with open(a.out, "w") as f:
        json.dump([{k: v for k, v in r.items() if k != "misses"} for r in results], f, indent=2)
    print(f"\nSaved numbers to {a.out}")

if __name__ == "__main__":
    main()