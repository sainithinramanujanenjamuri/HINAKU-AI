# CHANGELOG: HINAKU

All notable development steps, architectural implementations, and verification results across project phases.

---

## [Phase H] - Polish, Documentation, and Repository Audit
- Fully updated `README.md` with installation, quickstart, hardware budget guidelines, test runner commands, and architecture overview.
- Added comprehensive `CHANGELOG.md` detailing all phases from Step 1 through Phase H.
- Verified zero leaked secrets in git, strict git-ignore validation for `.env`, `data/`, `models/`, `logs/`, and temporary databases.
- Confirmed all 89 test suite checks pass across all functional modules.

---

## [Phase G] - 6-Month Scheduler, Manual Trigger, Report View, and Activity Pause Logic
- **Activity & Power Pause Logic:** Implemented `backend/scheduler/activity.py` utilizing Windows `GetLastInputInfo` to detect mouse/keyboard activity and check battery state. Background fine-tuning automatically pauses when the owner is actively using the laptop or when running on battery power.
- **Self-Build Coordinator:** Created `backend/scheduler/coordinator.py` orchestrating the end-to-end 6-stage self-build pipeline (activity check, curation, dataset build, preflight/training, evaluation against golden set, promotion decision, and report generation).
- **Report Generator:** Writes human-readable Markdown reports (`logs/reports/self_build_YYYY-MM.md`) and JSON telemetry logs (`self_build_YYYY-MM.json`).
- **6-Month Scheduler Service:** Implemented `backend/scheduler/service.py` background runner managing 6-month cycles with manual `trigger_now` support.
- **UI Report View:** Added report viewer modal in desktop UI with cycle summary, candidate score vs local score comparison, improvement margins, and one-click rollback trigger.

---

## [Phase F] - QLoRA Training Harness, VRAM Preflight, Golden Evaluation, and Promotion/Rollback
- **Hardware Preflight:** Created `backend/training/preflight.py` verifying minimum 5.5 GB VRAM fit for laptop RTX 4050 6 GB.
- **QLoRA Trainer:** Implemented `backend/training/train.py` with 4-bit quantization, LoRA adapter configuration (`r=16`, `alpha=32`, `batch_size=1`, `grad_accum=16`), and safe dry-run mode.
- **Cloud GPU Export & Import:** Added `export_cloud_bundle` generating self-contained zip archives (dataset, `train_cloud.py`, `requirements.txt`) ready for RunPod/Vast.ai, and `import_cloud_adapter` for loading trained weights into `models/hinaku-YYYY-MM/`.
- **Evaluation Harness:** Created `backend/training/evaluate.py` testing against `eval/golden.jsonl` with rule scoring (must_include, must_avoid, tone consistency, accuracy).
- **Model Promotion & Rollback:** Implemented `backend/training/promote.py` enforcing strict promotion only when beating the local model by `min_improvement`, maintaining the last 3 promoted versions, and providing instant rollback.

---

## [Phase E] - Dataset Curation from Interactions and Review Screen
- **Curation Pipeline:** Implemented `backend/training/curate.py` extracting high-quality training pairs (thumbs-up, owner-edited answers, accepted API replies) while dropping negative feedback, private conversations, deleted items, guard replies, and sensitive data.
- **Dataset Versioning:** Exports instruction-tuning JSONL pairs with persona system prompt to `data/datasets/YYYY-MM/train.jsonl` along with `metadata.json`.
- **Review Screen:** Added interactive modal in `ui/index.html` and `ui/app.js` with candidate counts, minimum required status badge, and item removal before training.

---

## [Phase D] - Thumbs Up/Down Feedback and Edit-Reply on Assistant Messages
- **Database Schema Migration:** Added `message_id` foreign key index to `interactions` table with automatic column migration.
- **Assistant Actions UI:** Added thumbs up (👍), thumbs down (👎), and inline reply editor (✏️ Edit) on assistant messages.
- **Interactive Feedback & Edit:** Added `/api/messages/{id}/feedback` and `/api/messages/{id}/edit` endpoints to update conversation history and ground-truth interaction logs.
- **Guard Isolation:** Tagged guard responses as non-training data.

---

## [Phase C] - Memory Drawer, Settings Modal, Global Hotkey, and System Tray
- **Memory Drawer:** Implemented slide-out right drawer ("What HINAKU remembers") with inline fact editing, deletion, filtering, and re-indexing.
- **Settings Panel:** Modal supporting router mode selection, memory toggle, reduced motion toggle, data export, and confirmation-guarded wipe.
- **Desktop Enhancements:** Added system tray icon via `pystray` and global summon hotkey `Ctrl+Shift+Space` in `run_desktop.py`.

---

## [Step 0 & Bake-Off] - Guard Decoupling, Persona Examples, and Local Model Bake-Off
- Refined `config/hinaku_persona.md` tone examples to avoid overlap with evaluation test prompts.
- Updated `scripts/model_bakeoff.py` through the real application pipeline.
- Established `gemma3:4b` default model with `keep_alive: 30m` and `qwen3-embedding:0.6b` with `keep_alive: 0` for optimal 6 GB VRAM budget allocation on RTX 4050.
- Implemented in-code Sensitive-Data Guard and Live-Data Guard refusing prohibited queries before calling any model.

---

## [Steps 1-5] - Foundations, History, Router, and Semantic Memory
- **Step 1:** FastAPI backend and basic chat window with Ollama.
- **Step 2:** Dynamic persona loading from markdown file.
- **Step 3:** SQLite chat history, title generation, context trimming, and sidebar.
- **Step 4:** Hybrid model router (local Ollama + API models) with privacy isolation for private chats.
- **Step 5:** SQLite + ChromaDB semantic memory storage and retrieval with regex safety filters.
