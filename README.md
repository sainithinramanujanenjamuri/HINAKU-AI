# HINAKU (ヒナク)

> "One name. An infinite void. No light at the end."

**HINAKU** is a personal AI assistant built for a single user (the owner). It runs locally on an HP V15 laptop (AMD Ryzen 7, NVIDIA RTX 4050 with 6 GB VRAM), remembers the owner across sessions, uses a hybrid local + API model router, and periodically fine-tunes its own small local model from curated interaction data.

---

## Architecture & Features

1. **Dark, Atmospheric Desktop Experience**
   - Built with FastAPI and a lightweight pywebview desktop shell.
   - Minimalist "universe without light" aesthetic: near-black canvas, soft cool-white typography, muted deep violet/steel blue accents, and subtle ambient drifting starfield.
   - Global summon/hide hotkey (`Ctrl+Shift+Space`) and system tray icon with Show/Hide/Exit controls.
   - Full support for reduced-motion settings (disables starfield and instantaneous animations).

2. **Persona & Strict Tone Control**
   - Editable personality prompt living in `config/hinaku_persona.md` with hot-reloading.
   - Calm, composed, observant, dry wit, no filler. Never gushes, preaches, or claims to be human.
   - Suppresses `<think>` tags and reasoning boilerplate.

3. **Hybrid Model Router & Privacy**
   - Seamlessly routes between **local inference** (Ollama - `gemma3:4b` default with `keep_alive: 30m`) and **API models** (OpenRouter free tier / OpenAI / Anthropic-compatible).
   - Router stickiness: short follow-ups stay on the previous backend unless forced or private.
   - **Privacy rule:** Personal statements about the owner stay local. Memories and personal facts are never sent to external API providers (`api_send_personal_context: false`).
   - **Private chats:** Set before the first message; never call any API in any mode and never store semantic memories.

4. **Hard Guards in Code (Before Any Model Call)**
   - **Sensitive-Data Guard:** Refuses and redacts PINs, passwords, payment cards, bank accounts, and government IDs to `[removed]`. Zero storage in memory, history, or interaction logs.
   - **Live-Data Guard:** Honest fixed refusals with tracker guidance for real-time stock/crypto prices, weather, live news, and sports scores.

5. **Semantic Memory Layer**
   - SQLite table `memories` combined with ChromaDB semantic search using `qwen3-embedding:0.6b` (1024 dims, `min_similarity: 0.46`).
   - Embedding model called with `keep_alive: 0` so it immediately yields VRAM back to `gemma3:4b`.
   - Local-only extraction of durable owner facts after turns; automatic deduplication and merging.
   - Collapsible slide-out memory drawer ("What HINAKU remembers") with inline view, search, edit, delete, and collection re-indexing.

6. **Feedback & Edit-Reply Capture**
   - Thumbs up (👍) and thumbs down (👎) rating on assistant responses.
   - Inline reply editing (✏️ Edit) allowing the owner to correct assistant answers, updating conversation history and recording ground-truth training data.
   - Guard replies are never used for training data.

7. **Dataset Curation & Review Screen**
   - Curates high-quality examples: thumbs-up, owner-edited answers, and accepted API replies.
   - Drops thumbs-down, private chats, deleted messages, guard replies, and secrets.
   - Interactive review screen in UI allowing the owner to inspect and remove items before training.
   - Exports versioned instruction-tuning datasets to `data/datasets/YYYY-MM/train.jsonl` with full metadata.

8. **QLoRA Self-Build & Cloud GPU Rental Support**
   - QLoRA fine-tuning for 1B-1.5B base models (`Qwen/Qwen2.5-1.5B-Instruct`) in 4-bit.
   - Hardware preflight: enforces minimum 5.5 GB VRAM fit for laptop RTX 4050 (6 GB).
   - One-click cloud export: bundles dataset, requirements, and standalone training script into a deployable zip for RunPod, Vast.ai, Lambda, or Google Colab.
   - One-click adapter import: loads fine-tuned weights directly into `models/hinaku-YYYY-MM/`.

9. **Evaluation Harness, Promotion & Rollback**
   - Evaluates against `eval/golden.jsonl` scoring persona consistency, factual accuracy, honesty on live queries, and owner corrections.
   - **Promotion rule:** Promotes and registers with Ollama only if the candidate beats the current local model by at least `min_improvement` (default 2%).
   - Retains the last 3 promoted versions with one-click rollback.

10. **6-Month Automated Scheduler & Laptop Activity Detection**
    - Autonomous 6-month cycle plus manual "Run Now" trigger.
    - Pauses background training when the owner is actively using the laptop (keyboard/mouse idle detection) or when running on battery power.
    - Generates detailed Markdown and JSON reports stored in `logs/reports/` and visible in the UI.

---

## Target Environment

- **Laptop:** HP V15, AMD Ryzen 7, NVIDIA RTX 4050 Laptop GPU (6 GB VRAM).
- **OS:** Windows 11 / Windows 10 (Python 3.11+).
- **Local Model:** `gemma3:4b` at Q4 via Ollama.
- **Embedding Model:** `qwen3-embedding:0.6b` via Ollama.

---

## Quickstart

### 1. Install Ollama Models
Ensure Ollama is running, then pull the required models:
```powershell
ollama pull gemma3:4b
ollama pull qwen3-embedding:0.6b
```

### 2. Virtual Environment Setup
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Run HINAKU Desktop App
```powershell
.\venv\Scripts\python.exe run_desktop.py
```
- Global shortcut: `Ctrl + Shift + Space` summons or hides the window.
- System tray icon: right-click for Show / Hide / Exit.

### 4. Run Backend Server Only (Browser Mode)
```powershell
.\venv\Scripts\python.exe run_desktop.py --server-only
```
Navigate to `http://127.0.0.1:8000` in your web browser.

---

## Training Environment & Fine-Tuning Setup

Training runs use a dedicated virtual environment (`venv-train`) to isolate heavy CUDA, PyTorch, bitsandbytes, and Hugging Face dependencies from the core desktop app:

### 1. Create Training Environment
```powershell
python -m venv venv-train
```

### 2. Install Pinned Training Dependencies
```powershell
.\venv-train\Scripts\pip.exe install -r requirements-training.txt
```

### 3. Verify Hardware & bitsandbytes 4-Bit Execution
```powershell
.\venv-train\Scripts\python.exe scripts/check_training_env.py
```

### 4. QLoRA Smoke Test (20 Steps Verification)
> [!NOTE]
> Smoke test runs 20 steps on a synthetic dataset in a temp folder and never promotes models. Requires explicit owner approval before first run.
```powershell
.\venv-train\Scripts\python.exe scripts/train_smoke.py
```

### Model Export & llama.cpp Pinning
- **llama.cpp Release:** Pinned to tag `b11829` ([`github.com/ggml-org/llama.cpp`](https://github.com/ggml-org/llama.cpp/releases/tag/b11829)).
- **Tools Location:** `tools/llama.cpp/` (git-ignored, no binaries in git).
- **Components:** `llama-quantize.exe` (CPU Windows x64 binary) and `convert_hf_to_gguf.py` + `gguf-py` (source archive of tag `b11829`).
- **Smoke Export Verification:**
```powershell
.\venv-train\Scripts\python.exe scripts/train_smoke.py --export
```

---

## Running the Test Suite

All tests run against temporary, isolated databases and mock adapters. Tests never touch or delete user data in `data/hinaku.db`.

```powershell
.\venv\Scripts\python.exe -m pytest -v
```

---

## Repository Structure

```
/backend
  /api              FastAPI routes (chat, conversations, memories, settings, interactions, training, self-build)
  /memory           Semantic memory extraction, storage (SQLite + ChromaDB), retrieval
  /models           OllamaAdapter, ApiAdapter, ModelRouter, guards
  /scheduler        6-month scheduler, laptop activity detection, self-build coordinator
  /training         Dataset curation, VRAM preflight, QLoRA training harness, evaluation, promotion
/config
  settings.yaml     App settings, models, router rules, guards, training config
  hinaku_persona.md Editable persona prompt (source of truth)
/data               (git-ignored) SQLite databases, Chroma collections, versioned datasets
/eval
  golden.jsonl      15 fixed evaluation scenarios covering persona, honesty, accuracy, support, boundaries, memory
/models             (git-ignored) Fine-tuned LoRA adapters and exported GGUF files
/logs               (git-ignored) Training reports, application logs
/tests              Comprehensive pytest suite (201 passing tests across isolation, verification, memory, router, detail mode, and guards)
/ui                 Minimalist dark desktop web UI (HTML, CSS, JS, ambient starfield canvas)
AGENTS.md           Project specification and developer rules
CHANGELOG.md        Step-by-step history of built phases
README.md           Getting started and architecture documentation
run_desktop.py      Desktop entrypoint with system tray & global hotkey
```
