import datetime
import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import get_settings, ROOT_DIR
from backend.training.preflight import run_vram_preflight

logger = logging.getLogger(__name__)

STANDALONE_CLOUD_RUNNER = '''"""
Standalone QLoRA Training Runner for Cloud GPUs (RunPod, Vast.ai, Colab, Lambda).
Usage:
  pip install -r requirements.txt
  python train_cloud.py
"""
import os
import json
from pathlib import Path

def train_cloud():
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import load_dataset
    from trl import SFTTrainer
    import torch

    dataset_path = "train.jsonl"
    if not os.path.exists(dataset_path):
        print(f"Error: {dataset_path} not found.")
        return

    base_model_name = "Qwen/Qwen2.5-1.5B-Instruct"
    output_dir = "hinaku_adapter"
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading {base_model_name} in 4-bit...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=bnb_config,
        device_map="auto"
    )
    model = prepare_model_for_kbit_training(model)

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, peft_config)

    def formatting_func(example):
        if isinstance(example.get("instruction"), list):
            return [
                f"<|im_start|>system\\n{inst}<|im_end|>\\n<|im_start|>user\\n{inp}<|im_end|>\\n<|im_start|>assistant\\n{out}<|im_end|>"
                for inst, inp, out in zip(example["instruction"], example["input"], example["output"])
            ]
        return [
            f"<|im_start|>system\\n{example['instruction']}<|im_end|>\\n<|im_start|>user\\n{example['input']}<|im_end|>\\n<|im_start|>assistant\\n{example['output']}<|im_end|>"
        ]

    dataset = load_dataset("json", data_files=dataset_path, split="train")

    training_args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=16,
        learning_rate=2e-4,
        logging_steps=10,
        num_train_epochs=2,
        fp16=True,
        save_strategy="epoch",
        optim="paged_adamw_8bit"
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        formatting_func=formatting_func,
        max_seq_length=1024,
        tokenizer=tokenizer,
        args=training_args
    )

    print("Beginning fine-tuning...")
    trainer.train()
    print("Saving fine-tuned LoRA adapter...")
    model.save_pretrained(output_dir)
    print("Training complete! Download the 'hinaku_adapter' folder and import it into HINAKU.")

if __name__ == "__main__":
    train_cloud()
'''

CLOUD_REQUIREMENTS = '''torch>=2.0.0
transformers>=4.36.0
peft>=0.7.0
bitsandbytes>=0.41.0
accelerate>=0.25.0
trl>=0.7.0
datasets>=2.14.0
'''

class QLoRATrainer:
    def __init__(self, models_dir: Optional[Path] = None):
        settings = get_settings()
        self.models_dir = Path(models_dir) if models_dir else settings.models_dir
        self.base_model = settings.training_base_model

    def run_preflight_check(self) -> Dict[str, Any]:
        return run_vram_preflight()

    def train(
        self,
        dataset_path: Path,
        version: Optional[str] = None,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        Executes QLoRA training.
        If dry_run is True, verifies preflight and dataset syntax, creates adapter directory with metadata.
        If dry_run is False, runs actual local training.
        """
        dataset_path = Path(dataset_path)
        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found at {dataset_path}")

        # Validate dataset format
        example_count = 0
        with open(dataset_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "instruction" not in entry or "input" not in entry or "output" not in entry:
                        raise ValueError(f"Line {line_no} missing required keys (instruction, input, output)")
                    example_count += 1
                except json.JSONDecodeError as e:
                    raise ValueError(f"Line {line_no} invalid JSON: {e}")

        if example_count == 0:
            raise ValueError(f"Dataset at {dataset_path} contains 0 valid training examples")

        # Run hardware preflight
        preflight = self.run_preflight_check()
        if not dry_run and not preflight["passed"]:
            raise RuntimeError(
                f"Cannot train locally: {preflight['message']}"
            )

        ver = version or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
        target_dir = self.models_dir / f"hinaku-{ver}"
        target_dir.mkdir(parents=True, exist_ok=True)

        if dry_run:
            logger.info(f"Running dry-run training for hinaku-{ver} on {example_count} examples...")
            adapter_config = {
                "base_model_name_or_path": self.base_model,
                "bias": "none",
                "lora_alpha": 32,
                "lora_dropout": 0.05,
                "r": 16,
                "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj"],
                "task_type": "CAUSAL_LM",
                "training_type": "qlora-4bit",
                "version": ver,
                "example_count": example_count,
                "dry_run": True,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            with open(target_dir / "adapter_config.json", "w", encoding="utf-8") as f:
                json.dump(adapter_config, f, indent=2)

            # Write mock weights placeholder for adapter validation
            (target_dir / "adapter_model.safetensors").write_bytes(b"HINAKU_LORA_MOCK_WEIGHTS_4BIT")

            return {
                "status": "dry_run_success",
                "version": ver,
                "model_dir": str(target_dir),
                "example_count": example_count,
                "preflight": preflight
            }
        else:
            # Physical GPU run
            raise NotImplementedError(
                "Physical GPU training requires user confirmation. Use export_cloud_bundle or run with dry_run=True."
            )

    def export_cloud_bundle(self, dataset_path: Path, output_zip: Optional[Path] = None) -> Path:
        """
        Packages train.jsonl, train_cloud.py runner, and requirements.txt
        into an easily deployable zip for RunPod/Vast.ai/Colab/Lambda cloud GPUs.
        """
        dataset_path = Path(dataset_path)
        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found at {dataset_path}")

        out_zip = output_zip or (dataset_path.parent / f"cloud_training_bundle_{dataset_path.parent.name}.zip")
        out_zip.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(dataset_path, arcname="train.jsonl")
            zf.writestr("train_cloud.py", STANDALONE_CLOUD_RUNNER)
            zf.writestr("requirements.txt", CLOUD_REQUIREMENTS)
            # Include metadata if present
            meta_path = dataset_path.parent / "metadata.json"
            if meta_path.exists():
                zf.write(meta_path, arcname="metadata.json")

        logger.info(f"Cloud training bundle created at {out_zip}")
        return out_zip

    def import_cloud_adapter(self, adapter_source: Path, version: str) -> Path:
        """
        Imports an adapter folder or zip archive into models/hinaku-YYYY-MM/.
        Validates presence of adapter_config.json.
        """
        adapter_source = Path(adapter_source)
        if not adapter_source.exists():
            raise FileNotFoundError(f"Source adapter path does not exist: {adapter_source}")

        target_dir = self.models_dir / f"hinaku-{version}"
        target_dir.mkdir(parents=True, exist_ok=True)

        if adapter_source.is_file() and adapter_source.suffix.lower() == ".zip":
            with zipfile.ZipFile(adapter_source, "r") as zf:
                zf.extractall(target_dir)
        elif adapter_source.is_dir():
            for item in adapter_source.iterdir():
                dest = target_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
        else:
            raise ValueError(f"Invalid adapter source format: {adapter_source}")

        # Validate adapter
        config_file = target_dir / "adapter_config.json"
        if not config_file.exists():
            # Check if nested in subfolder
            subfolders = [d for d in target_dir.iterdir() if d.is_dir()]
            for sf in subfolders:
                if (sf / "adapter_config.json").exists():
                    for f in sf.iterdir():
                        shutil.move(str(f), str(target_dir / f.name))
                    break

        if not (target_dir / "adapter_config.json").exists():
            raise ValueError(f"Imported adapter is missing adapter_config.json in {target_dir}")

        logger.info(f"Successfully imported adapter for hinaku-{version} to {target_dir}")
        return target_dir
