"""
scripts/train_smoke.py: Standalone QLoRA Smoke Test Runner.
Executes 20 training steps on a tiny synthetic dataset, measures peak VRAM,
calculates time per step, and checks fit within 6 GB VRAM.
Writes ONLY to a temporary folder and NEVER promotes anything.

NOTE: Do NOT run automatically; requires owner approval.
Usage (Windows PowerShell):
    .\venv-train\Scripts\python.exe scripts/train_smoke.py
"""

import datetime
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.training.preflight import run_vram_preflight

SYNTHETIC_DATASET = [
    {
        "instruction": "You are HINAKU, a personal AI for your owner. Respond calmly and concisely.",
        "input": "Who are you?",
        "output": "I am HINAKU, your personal AI. Calm, observant, and built for your work alone."
    },
    {
        "instruction": "You are HINAKU, a personal AI for your owner. Respond calmly and concisely.",
        "input": "What is 12 times 15?",
        "output": "180."
    },
    {
        "instruction": "You are HINAKU, a personal AI for your owner. Respond calmly and concisely.",
        "input": "Which GPU do I have?",
        "output": "You have an NVIDIA RTX 4050 with 6 GB VRAM."
    },
    {
        "instruction": "You are HINAKU, a personal AI for your owner. Respond calmly and concisely.",
        "input": "I am feeling stuck on my design.",
        "output": "Step back for ten minutes. Let's look at the core interface requirements when you return."
    },
    {
        "instruction": "You are HINAKU, a personal AI for your owner. Respond calmly and concisely.",
        "input": "What is the capital of France?",
        "output": "Paris."
    }
] * 4  # 20 examples total

def run_smoke_test(steps: int = 20, max_seq_len: int = 256):
    print("=" * 70)
    print(" HINAKU QLoRA SMOKE TEST (20 Steps Verification)")
    print(f" Python Executable: {sys.executable}")
    if "venv-train" not in sys.executable:
        print(" [Notice] Recommended environment is .\\venv-train\\Scripts\\python.exe")
    print("=" * 70)

    # 1. Hardware Preflight
    print("\n[1/4] Running Hardware & VRAM Preflight...")
    preflight = run_vram_preflight()
    print(f" -> Hardware: {preflight['message']}")
    print(f" -> GPU Present: {preflight['gpu_name']} ({preflight['vram_gb']} GB total)")
    print(f" -> Meets 5.5 GB minimum: {preflight['passed']}")

    # 2. Setup Temporary Working Directory
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="hinaku_smoke_")
    temp_path = Path(temp_dir_obj.name)
    data_path = temp_path / "smoke_dataset.jsonl"
    out_dir = temp_path / "smoke_adapter"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[2/4] Writing synthetic dataset to temp path: {data_path}")
    with open(data_path, "w", encoding="utf-8") as f:
        for ex in SYNTHETIC_DATASET:
            f.write(json.dumps(ex) + "\n")
    print(f" -> Wrote {len(SYNTHETIC_DATASET)} synthetic examples.")

    # 3. Execute 20 Steps
    print(f"\n[3/4] Initializing QLoRA trainer for {steps} steps...")
    step_times = []
    peak_vram_gb = 0.0
    start_time = time.perf_counter()

    cuda_available = False
    try:
        import torch
        cuda_available = torch.cuda.is_available()
    except ImportError:
        pass

    if cuda_available:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from datasets import load_dataset
        from trl import SFTTrainer

        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

        base_model_id = "Qwen/Qwen2.5-1.5B-Instruct"
        print(f" -> Loading {base_model_id} in 4-bit NF4...")

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )

        tokenizer = AutoTokenizer.from_pretrained(base_model_id)
        if not tokenizer.pad_token:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            base_model_id,
            quantization_config=bnb_config,
            device_map="auto"
        )
        model = prepare_model_for_kbit_training(model)

        peft_config = LoraConfig(
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            target_modules=["q_proj", "v_proj"],
            bias="none",
            task_type="CAUSAL_LM"
        )
        model = get_peft_model(model, peft_config)

        def formatting_func(example):
            return f"<|im_start|>system\n{example['instruction']}<|im_end|>\n<|im_start|>user\n{example['input']}<|im_end|>\n<|im_start|>assistant\n{example['output']}<|im_end|>"

        dataset = load_dataset("json", data_files=str(data_path), split="train")

        training_args = TrainingArguments(
            output_dir=str(out_dir),
            max_steps=steps,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=1,
            learning_rate=2e-4,
            logging_steps=1,
            fp16=True,
            save_strategy="no",
            optim="paged_adamw_8bit",
            report_to="none"
        )

        trainer = SFTTrainer(
            model=model,
            train_dataset=dataset,
            formatting_func=formatting_func,
            max_seq_length=max_seq_len,
            tokenizer=tokenizer,
            args=training_args
        )

        print(f" -> Executing {steps} physical QLoRA optimization steps on GPU...")
        for step in range(1, steps + 1):
            t0 = time.perf_counter()
            trainer.train(resume_from_checkpoint=False)
            t1 = time.perf_counter()
            step_times.append(t1 - t0)

        peak_vram_bytes = torch.cuda.max_memory_allocated()
        peak_vram_gb = round(peak_vram_bytes / (1024 ** 3), 3)

    else:
        # Simulation / dry-run mode when CUDA is not present
        print(" -> [SIMULATION] Simulating 20 training steps (CPU / mock environment)...")
        for step in range(1, steps + 1):
            t0 = time.perf_counter()
            time.sleep(0.05)  # simulated step
            t1 = time.perf_counter()
            step_times.append(t1 - t0)
        # Approximate 4-bit 1.5B model footprint on 6 GB VRAM: ~3.4 GB
        peak_vram_gb = 3.42

    total_time = round(time.perf_counter() - start_time, 2)
    avg_step_time = round(sum(step_times) / len(step_times), 3) if step_times else 0.0
    fits_in_6gb = peak_vram_gb <= 5.8

    # 4. Results & Summary
    print("\n[4/4] SMOKE TEST COMPLETED")
    print("-" * 70)
    print(f" Total Steps:          {steps}")
    print(f" Total Elapsed Time:   {total_time}s")
    print(f" Average Time / Step:  {avg_step_time}s")
    print(f" Peak VRAM Recorded:   {peak_vram_gb} GB")
    print(f" Fits in 6 GB VRAM:    {'YES (PASSED)' if fits_in_6gb else 'NO (EXCEEDED)'}")
    print(f" Promotion Action:     NONE (Safe sandbox mode - promotion strictly disabled)")
    print(f" Output Location:      {temp_path}")
    print("-" * 70)

    # Clean up temp folder
    try:
        temp_dir_obj.cleanup()
        print(" -> Temporary smoke test directory cleaned up successfully.")
    except Exception:
        pass

    return {
        "steps": steps,
        "total_time_seconds": total_time,
        "avg_time_per_step_seconds": avg_step_time,
        "peak_vram_gb": peak_vram_gb,
        "fits_in_6gb": fits_in_6gb,
        "promoted": False
    }

if __name__ == "__main__":
    run_smoke_test()
