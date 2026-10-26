import asyncio
import time
import datetime
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.api.chat import model_router, memory_manager

async def main():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = ROOT / "data" / "measure" / f"{timestamp}_immediate_next_turn_with_idle.txt"
    out_lines = []

    def record(line):
        print(line)
        out_lines.append(line)

    record("COMMAND: venv\\Scripts\\python.exe scripts/measure_immediate_turn.py")
    record(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
    record("=== Test: Sending Next Message Immediately After Reply (with 5s Idle Debounce) ===")

    conv_id = f"test-idle-{timestamp}"

    # --- Turn 1 ---
    t1_prompt = "Hi, my favorite fruit is mango and I live in Seattle."
    record(f"\n[Turn 1] Prompt: {t1_prompt}")
    memory_manager.notify_user_message_received()

    t0 = time.time()
    t1_ttft = None
    t1_chunks = []
    async for item in model_router.stream_chat(
        messages=[{"role": "user", "content": t1_prompt}],
        user_prompt=t1_prompt,
        is_private=False
    ):
        chunk = item.get("chunk", "")
        if chunk:
            if t1_ttft is None:
                t1_ttft = time.time() - t0
            t1_chunks.append(chunk)
    t1_total = time.time() - t0
    record(f"[Turn 1] TTFT: {t1_ttft:.3f}s | Total: {t1_total:.3f}s")
    record(f"[Turn 1] Reply preview: {''.join(t1_chunks)[:60]}...")

    # Turn 1 completes: schedule extraction and start 5s idle timer
    memory_manager.schedule_extraction(
        conversation_id=conv_id,
        user_message=t1_prompt,
        assistant_message="".join(t1_chunks),
        is_private=False
    )
    memory_manager.notify_chat_completed()
    record(f"[Turn 1 Finished] Pending extraction items: {len(memory_manager._pending_extractions)}, idle timer active: {memory_manager._idle_task is not None}")

    # --- Turn 2 (IMMEDIATELY, delay = 0.05s) ---
    t2_prompt = "What is 12 + 15?"
    record(f"\n[Turn 2 - IMMEDIATE after 50ms] Prompt: {t2_prompt}")
    
    # User message arrives: notify memory manager to cancel/requeue pending extraction
    memory_manager.notify_user_message_received()
    record(f"[Turn 2 Arrival] Pending extraction items: {len(memory_manager._pending_extractions)}, idle timer cancelled: {memory_manager._idle_task is None or memory_manager._idle_task.cancelled()}")

    t2_start = time.time()
    t2_ttft = None
    t2_chunks = []
    async for item in model_router.stream_chat(
        messages=[
            {"role": "user", "content": t1_prompt},
            {"role": "assistant", "content": "".join(t1_chunks)},
            {"role": "user", "content": t2_prompt}
        ],
        user_prompt=t2_prompt,
        is_private=False
    ):
        chunk = item.get("chunk", "")
        if chunk:
            if t2_ttft is None:
                t2_ttft = time.time() - t2_start
            t2_chunks.append(chunk)
    t2_total = time.time() - t2_start
    record(f"[Turn 2 - IMMEDIATE] TTFT: {t2_ttft:.3f}s | Total: {t2_total:.3f}s")
    record(f"[Turn 2] Reply preview: {''.join(t2_chunks)[:60]}...")

    # Turn 2 completes: schedule extraction and start 5s idle timer
    memory_manager.schedule_extraction(
        conversation_id=conv_id,
        user_message=t2_prompt,
        assistant_message="".join(t2_chunks),
        is_private=False
    )
    memory_manager.notify_chat_completed()
    record(f"[Turn 2 Finished] Pending extraction items: {len(memory_manager._pending_extractions)}, idle countdown running...")

    # Wait for 5.5s idle window to complete
    record("\nWaiting 6.0s for idle countdown to trigger background memory extraction...")
    await asyncio.sleep(6.5)
    
    # Wait for any active extraction in progress
    if memory_manager._idle_task and not memory_manager._idle_task.done():
        await memory_manager._idle_task

    record(f"[Idle window complete] Pending extraction items left: {len(memory_manager._pending_extractions)}")

    # Check stored memories for this conversation
    memories = memory_manager.storage.get_memories()
    recent = [m["text"] for m in memories if "mango" in m["text"].lower() or "seattle" in m["text"].lower()]
    record(f"Extracted memory verified in storage: {recent}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    record(f"\nRaw measurement file saved: {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
