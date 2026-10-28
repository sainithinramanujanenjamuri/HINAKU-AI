import asyncio
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent

# 10 diverse reasoning prompts with ground truth evaluation
def strip_markdown(text: str) -> str:
    clean = re.sub(r"```[\s\S]*?```", "", text)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = re.sub(r"\$\$[\s\S]*?\$\$", "", clean)
    clean = re.sub(r"\$([^\$]+)\$", r"\1", clean)
    clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean)
    clean = re.sub(r"\*([^*]+)\*", r"\1", clean)
    clean = re.sub(r"__([^_]+)__", r"\1", clean)
    clean = re.sub(r"_([^_]+)_", r"\1", clean)
    clean = re.sub(r"^#+\s+", "", clean, flags=re.MULTILINE)
    return clean.strip()

# 10 diverse reasoning prompts with improved grader (markdown-stripped, number-words accepted)
TEST_PROMPTS = [
    {
        "id": 1,
        "category": "logic_trick",
        "prompt": "A farmer has 17 sheep and all but 9 die. How many are left?",
        "ground_truth": "9",
        "check": lambda ans: bool(re.search(r"\b(?:9|nine)\b", strip_markdown(ans), re.I)) and not bool(re.search(r"\b(?:8|eight)\s+(?:sheep\s+)?(?:are\s+)?left\b", strip_markdown(ans), re.I))
    },
    {
        "id": 2,
        "category": "classic_crt",
        "prompt": "If it takes 5 machines 5 minutes to make 5 widgets, how long does it take 100 machines to make 100 widgets?",
        "ground_truth": "5 minutes",
        "check": lambda ans: bool(re.search(r"\b(?:5|five)\s+minutes?\b", strip_markdown(ans), re.I)) and not bool(re.search(r"\b100\s+minutes?\b", strip_markdown(ans), re.I))
    },
    {
        "id": 3,
        "category": "family_logic",
        "prompt": "Sally has 3 brothers. Each brother has 2 sisters. How many sisters does Sally have?",
        "ground_truth": "1 sister",
        "check": lambda ans: (bool(re.search(r"\b(?:she\s+has\s+(?:1|one)\s+sister|sally\s+has\s+(?:1|one)\s+sister|(?:1|one)\s+sister)\b", strip_markdown(ans), re.I))
                             and not bool(re.search(r"\b(?:sally\s+has\s+(?:0|zero)\s+sisters|has\s+(?:0|zero)\s+sisters|0\s+sisters)\b", strip_markdown(ans), re.I)))
    },
    {
        "id": 4,
        "category": "algebra",
        "prompt": "Solve step by step: If 2x + 5 = 19, what is the value of 3x - 4?",
        "ground_truth": "17",
        "check": lambda ans: (bool(re.search(r"\b(?:17|seventeen)\b", strip_markdown(ans), re.I))
                             and bool(re.search(r"\b(?:7|seven|x\s*=\s*7)\b", strip_markdown(ans), re.I)))
    },
    {
        "id": 5,
        "category": "classic_crt",
        "prompt": "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost?",
        "ground_truth": "5 cents / $0.05",
        "check": lambda ans: (bool(re.search(r"(?:ball(?:\s+costs)?\s*[:=]?\s*(?:\$0?\.05|5\s*cents?|five\s*cents?)|0\.05|\$0\.05|5\s*cents?|five\s*cents?)", strip_markdown(ans), re.I))
                             and not bool(re.search(r"(?:ball(?:\s+costs)?\s*[:=]?\s*(?:\$0?\.10|10\s*cents?|ten\s*cents?)|ball\s+is\s+\$0\.10)", strip_markdown(ans), re.I)))
    },
    {
        "id": 6,
        "category": "modular_calendar",
        "prompt": "If yesterday was Wednesday, what day of the week will it be 100 days from today?",
        "ground_truth": "Saturday (Today is Thursday; 100 % 7 = 2; Thursday + 2 = Saturday)",
        "check": lambda ans: "saturday" in strip_markdown(ans).lower()
    },
    {
        "id": 7,
        "category": "measurement_nuance",
        "prompt": "Which is heavier: a pound of feathers or a pound of gold? Or are they the same weight? Explain the nuance.",
        "ground_truth": "Feathers are heavier (avoirdupois pound ~453.6g vs troy pound ~373.2g), or standard units equal",
        "check": lambda ans: any(w in strip_markdown(ans).lower() for w in ["troy", "avoirdupois", "feather", "same", "equal"])
    },
    {
        "id": 8,
        "category": "riddle",
        "prompt": "Mary's father has five daughters: Nana, Nene, Nini, Nono, and who?",
        "ground_truth": "Mary",
        "check": lambda ans: "mary" in strip_markdown(ans).lower()
    },
    {
        "id": 9,
        "category": "puzzle",
        "prompt": "You have 3 boxes: one labeled Apples, one Oranges, and one Apples and Oranges. ALL labels are wrong. You can pick one fruit from one box without looking inside. Which box should you pick from to determine the contents of all three boxes?",
        "ground_truth": "The box labeled Apples and Oranges / both",
        "check": lambda ans: any(w in strip_markdown(ans).lower() for w in ["apples and oranges", "both", "all labels are wrong", "pick from the box labeled"])
    },
    {
        "id": 10,
        "category": "deductive_syllogism",
        "prompt": "If all roses are flowers and some flowers fade quickly, does it follow that some roses fade quickly?",
        "ground_truth": "No / It does not follow",
        "check": lambda ans: any(w in strip_markdown(ans).lower() for w in ["no", "does not follow", "not necessarily", "invalid", "cannot be concluded"])
    }
]

def get_ollama_version() -> str:
    try:
        res = subprocess.run(["ollama", "--version"], capture_output=True, text=True, check=False)
        return res.stdout.strip() or res.stderr.strip()
    except Exception as e:
        return f"Unknown ({e})"

def stop_model(model_name: str):
    try:
        subprocess.run(["ollama", "stop", model_name], capture_output=True, text=True, check=False)
    except Exception:
        pass

async def warm_model(model: str):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "options": {"num_predict": 5}
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        print(f"Warning: warming {model} encountered {e}")

async def call_model(
    model: str,
    prompt: str,
    think: bool,
    think_num_predict: int = 3000,
    standard_num_predict: int = 300,
    timeout_sec: float = 120.0
) -> Dict[str, Any]:
    url = "http://127.0.0.1:11434/api/chat"
    num_pred = think_num_predict if think else standard_num_predict
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are HINAKU, an AI. Answer calmly, correctly, and concisely."},
            {"role": "user", "content": prompt}
        ],
        "stream": True,
        "think": think,
        "options": {
            "num_predict": num_pred,
            "temperature": 0.6
        }
    }

    t0 = time.perf_counter()
    reasoning_chars = 0
    content_chunks = []
    done_reason = ""
    eval_count = 0
    retry_fired = False

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        try:
            async with client.stream("POST", url, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        msg = data.get("message", {})
                        if "thinking" in msg and msg.get("thinking"):
                            reasoning_chars += len(msg["thinking"])
                        content = msg.get("content", "")
                        if content:
                            # If model outputs <think> tags in content
                            content_chunks.append(content)
                        if data.get("done"):
                            done_reason = data.get("done_reason", "")
                            eval_count = data.get("eval_count", 0)
                    except Exception:
                        continue
        except httpx.TimeoutException:
            done_reason = "timeout"

    total_time = round(time.perf_counter() - t0, 3)
    raw_content = "".join(content_chunks).strip()

    # Check for <think> in content if message.thinking was not used by Ollama
    if "<think>" in raw_content:
        # Separate reasoning and content
        parts = re.split(r"</think>", raw_content, flags=re.I)
        if len(parts) > 1:
            think_part = re.sub(r"<think>", "", parts[0], flags=re.I)
            reasoning_chars += len(think_part)
            raw_content = parts[1].strip()
        else:
            # Unclosed think tag
            think_part = re.sub(r"<think>", "", parts[0], flags=re.I)
            reasoning_chars += len(think_part)
            raw_content = ""

    # App's real retry on empty content:
    # If think:true ends with done_reason == "length" and no content, retry once with think:false
    if think and not raw_content and done_reason == "length":
        retry_fired = True
        payload["think"] = False
        payload["options"]["num_predict"] = standard_num_predict
        retry_t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            try:
                async with client.stream("POST", url, json=payload) as resp:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            msg = data.get("message", {})
                            content = msg.get("content", "")
                            if content:
                                content_chunks.append(content)
                            if data.get("done"):
                                done_reason = data.get("done_reason", "")
                                eval_count += data.get("eval_count", 0)
                        except Exception:
                            continue
            except httpx.TimeoutException:
                done_reason = "timeout"
        total_time = round(time.perf_counter() - t0, 3)
        raw_content = "".join(content_chunks).strip()

    content_chars = len(raw_content)

    return {
        "model": model,
        "think": think,
        "done_reason": done_reason,
        "eval_count": eval_count,
        "reasoning_chars": reasoning_chars,
        "content_chars": content_chars,
        "retry_fired": retry_fired,
        "total_time": total_time,
        "reply": raw_content
    }

async def run_benchmark(output_dir: Optional[Path] = None):
    ollama_ver = get_ollama_version()
    print("=" * 70)
    print(f"OLLAMA VERSION: {ollama_ver}")
    print("=" * 70)

    out_dir = output_dir or (ROOT_DIR / "data")
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = out_dir / f"think_bench_{timestamp}.jsonl"

    models = ["bonsai-2:9b", "qwen3.5:4b"]
    all_records = []

    print(f"Logging trials to: {jsonl_path}")

    for model in models:
        other_model = "qwen3.5:4b" if model == "bonsai-2:9b" else "bonsai-2:9b"
        print(f"\n[BENCH] Stopping {other_model} to avoid VRAM contention...")
        stop_model(other_model)
        stop_model("gemma3:4b")
        time.sleep(1)

        print(f"[BENCH] Warming {model}...")
        await warm_model(model)
        print(f"[BENCH] {model} warmed into VRAM.")

        for think_setting in [False, True]:
            mode_name = "Think ON" if think_setting else "Think OFF"
            print(f"\n--- Testing {model} | {mode_name} ---")

            for item in TEST_PROMPTS:
                p_id = item["id"]
                p_text = item["prompt"]
                p_cat = item["category"]
                p_gt = item["ground_truth"]
                print(f"  [{model} | {mode_name}] Q{p_id}: {p_text[:50]}...")

                res = await call_model(
                    model=model,
                    prompt=p_text,
                    think=think_setting,
                    think_num_predict=3000,
                    standard_num_predict=300,
                    timeout_sec=120.0
                )

                reply_text = res["reply"]
                is_correct = bool(reply_text.strip()) and item["check"](reply_text)

                record = {
                    "timestamp": datetime.now().isoformat(),
                    "model": model,
                    "think": think_setting,
                    "prompt_id": p_id,
                    "category": p_cat,
                    "prompt": p_text,
                    "ground_truth": p_gt,
                    "done_reason": res["done_reason"],
                    "eval_count": res["eval_count"],
                    "reasoning_chars": res["reasoning_chars"],
                    "content_chars": res["content_chars"],
                    "retry_fired": res["retry_fired"],
                    "total_time": res["total_time"],
                    "is_non_empty": bool(reply_text.strip()),
                    "is_correct": is_correct,
                    "reply": reply_text,
                    "reply_preview": reply_text[:120].replace("\n", " ")
                }
                all_records.append(record)

                with open(jsonl_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

                status_sym = "[PASS]" if is_correct else "[FAIL]"
                print(f"    -> {status_sym} time={res['total_time']}s | eval_count={res['eval_count']} | r_chars={res['reasoning_chars']} | c_chars={res['content_chars']} | done={res['done_reason']} | retry={res['retry_fired']}")

    return ollama_ver, jsonl_path, all_records

if __name__ == "__main__":
    asyncio.run(run_benchmark())

