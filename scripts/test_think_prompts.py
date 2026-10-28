import asyncio
import time
import httpx
import json
import subprocess

REASONING_PROMPTS = [
    "A farmer has 17 sheep and all but 9 die. How many are left? Explain your reasoning.",
    "If it takes 5 machines 5 minutes to make 5 widgets, how long does it take 100 machines to make 100 widgets?",
    "Sally has 3 brothers and each brother has 2 sisters. How many sisters does Sally have?",
    "Solve step by step: If 2x + 5 = 19, what is the value of 3x - 4?",
    "Which is heavier: a pound of feathers or a pound of gold? Explain the nuance."
]

def stop_model(model_name: str):
    try:
        subprocess.run(["ollama", "stop", model_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

async def test_prompt(model: str, prompt: str, num_predict: int = 3000):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are HINAKU, an AI. Answer calmly, correctly, and concisely."},
            {"role": "user", "content": prompt}
        ],
        "stream": True,
        "think": True,
        "options": {
            "num_predict": num_predict,
            "temperature": 0.6
        }
    }

    t0 = time.perf_counter()
    thinking_chunks = 0
    content_chunks = []
    done_reason = ""
    retry_fired = False

    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream("POST", url, json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    msg = data.get("message", {})
                    if "thinking" in msg and msg.get("thinking"):
                        thinking_chunks += 1
                    if "content" in msg and msg.get("content"):
                        content_chunks.append(msg.get("content"))
                    if data.get("done"):
                        done_reason = data.get("done_reason", "")
                except Exception:
                    continue

    latency = round(time.perf_counter() - t0, 2)
    ans = "".join(content_chunks).strip()

    if done_reason == "length" and not ans:
        # Triggered retry
        retry_fired = True
        t_retry0 = time.perf_counter()
        payload["think"] = False
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        msg = data.get("message", {})
                        if "content" in msg and msg.get("content"):
                            content_chunks.append(msg.get("content"))
                    except Exception:
                        continue
        latency = round(time.perf_counter() - t0, 2)
        ans = "".join(content_chunks).strip()

    return {
        "model": model,
        "prompt": prompt,
        "latency_sec": latency,
        "done_reason": done_reason,
        "retry_fired": retry_fired,
        "ans_len": len(ans),
        "ans_preview": ans[:100].replace("\n", " ")
    }

async def run_suite():
    models = ["bonsai-2:9b", "qwen3.5:4b"]
    all_results = {}

    for model in models:
        other = "qwen3.5:4b" if model == "bonsai-2:9b" else "bonsai-2:9b"
        stop_model(other)
        print(f"\n=== Testing {model} with think_num_predict=3000 ===")
        all_results[model] = []
        for i, p in enumerate(REASONING_PROMPTS, 1):
            print(f"[{model}] Prompt {i}/5: {p[:40]}...")
            res = await test_prompt(model, p, num_predict=3000)
            all_results[model].append(res)
            print(f"    -> Latency: {res['latency_sec']}s | Retry: {res['retry_fired']} | Done: {res['done_reason']} | Ans: {res['ans_preview']}...")

    print("\n\n=== FINAL SUMMARY ===")
    print(json.dumps(all_results, indent=2))

if __name__ == "__main__":
    asyncio.run(run_suite())

