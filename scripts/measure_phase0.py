import asyncio
import time
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.api.chat import model_router, memory_manager

async def run_measurement():
    print("=== Measuring 5 turns with bonsai-2:9b and memory extraction ===")
    conv = [
        "Hi, my favorite programming language is Python and I like building fast systems.",
        "What is 15 * 8?",
        "Can you remind me what language I like?",
        "What is the speed of light in vacuum in m/s?",
        "Give me one short sentence summarizing why Python is popular."
    ]
    
    for i, user_msg in enumerate(conv, 1):
        t0 = time.time()
        ttft = None
        chunks = []
        async for item in model_router.stream_chat(
            messages=[{"role": "user", "content": user_msg}],
            user_prompt=user_msg,
            is_private=False
        ):
            c = item.get("chunk", "")
            if c:
                if ttft is None:
                    ttft = time.time() - t0
                chunks.append(c)
        total = time.time() - t0
        res_snippet = "".join(chunks)[:40].replace("\n", " ")
        ttft_str = f"{ttft:.2f}s" if ttft is not None else "None"
        print(f"Turn {i}: TTFT={ttft_str}, Total={total:.2f}s, Response={res_snippet}...")
        
        # Test background memory extraction latency impact
        t_mem0 = time.time()
        extracted = await memory_manager.extract_and_store(
            user_message=user_msg,
            assistant_message="".join(chunks),
            conversation_id="test-measure-conv"
        )
        t_mem1 = time.time()
        print(f"  -> Memory extraction turn {i}: {t_mem1 - t_mem0:.2f}s, Extracted facts: {extracted}")

    # Check ollama ps after 5 turns
    ps_res = subprocess.run(["ollama", "ps"], capture_output=True, text=True)
    print("\n=== ollama ps after 5 turns ===")
    print(ps_res.stdout)

if __name__ == "__main__":
    asyncio.run(run_measurement())
