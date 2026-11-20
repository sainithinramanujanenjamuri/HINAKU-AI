# SPRINT 0A: Repository Baseline & Authoritative Source Assessment

> **Project:** HINAKU (ヒナク) — Personal AI Assistant  
> **Date:** November 2026  
> **Author:** Senior Software Engineer (HINAKU Core Team)  
> **Status:** Completed  
> **Target Environment:** HP V15 Laptop (AMD Ryzen 7, NVIDIA GeForce RTX 4050 6 GB VRAM, Windows 11, Python 3.11+)

---

## 1. Executive Summary

As part of **Sprint 0A**, a comprehensive inspection was conducted to establish the definitive repository baseline and evaluate the authoritative source of truth between the current Git repository (`D:\HINAKU-AI`) and the supplied project archive (`D:\hinaku-ai.zip`).

### Key Findings
1. **Authoritative Source:** The local Git repository (`origin/main`, commit `38f04c551f1b8a2870218e7793ae75ad37250a38`) provides full version control provenance, cryptographic commit history, and branch tracking. The supplied zip archive (`D:\hinaku-ai.zip`, modified 2026-11-13 13:56:46) is an unversioned filesystem export created directly from this working tree.
2. **Tracked File Parity:** Every single file tracked by Git (275 files) is present in the zip archive and is byte-for-byte identical to the current working tree. There are 0 missing or conflicting tracked files.
3. **Archive-Only Files (466 files):** The zip archive includes runtime state and untracked artifacts:
   - Ephemeral python bytecode (`__pycache__`: 250 files).
   - Precompiled local binaries (`tools/llama.cpp/*`: precompiled binaries and DLLs).
   - Local runtime databases (`data/hinaku.db`, `data/chroma/*`).
   - Local uploads (`data/uploads/*`) and test samples (`tests/real_samples/*`).
   - Private environment configuration (`.env`).
   - Manual UI review screenshots (`codex-UI/*`).
4. **Secrets & Privacy Audit:** No secrets, credentials, or API keys were detected in the Git commit history across all branches. The `.gitignore` file correctly excludes `.env`, `data/*`, `models/`, and `logs/`.
5. **Network / Remote Isolation:** Direct network access to remote GitHub (`git fetch origin`) was attempted and failed closed due to local sandbox network isolation (`getaddrinfo` blocked; permissions on `.git/FETCH_HEAD` restricted). The local repository commit `38f04c5` is aligned with `origin/main`.
6. **Working Branch:** A clean, dedicated working branch `sprint-0b-privacy-boundary` was established to isolate upcoming privacy gate implementations without modifying the `main` branch.

---

## 2. Repository Identity and Source Revision

- **Repository Root:** `D:\HINAKU-AI`
- **Current HEAD Commit SHA:** `38f04c551f1b8a2870218e7793ae75ad37250a38`
- **Short SHA:** `38f04c5`
- **Commit Subject:** `docs: generate comprehensive 14-page UI/UX design specification PDF`
- **Tracking Remote:** `origin` -> `https://github.com/sainithinramanujanenjamuri/HINAKU-AI.git`
- **Remote Tracking Branch:** `origin/main`
- **Local Active Branch:** `sprint-0b-privacy-boundary` (branched from `main` at `38f04c5`)
- **Git Tags:** None defined (`git tag -l` returned empty).

### Recent Commit History
| Commit SHA | Author | Date | Subject |
| :--- | :--- | :--- | :--- |
| `38f04c5` | Codex | 2026-11-10 | docs: generate comprehensive 14-page UI/UX design specification PDF |
| `06002c0` | Codex | 2026-11-08 | Phase 2c: Document QA eval, gate & hybrid retrieval, citations & faithfulness fixes |
| `cbe0d05` | Codex | 2026-11-06 | Phase 2c: Exhaustive call logging, 15x memory latency resolution, pypdf integration, count consistency, and faithfulness recall audit |
| `57523c4` | Codex | 2026-11-04 | Complete Phase 2b document understanding fixes, style verifier, precision faithfulness, real PDF reports, and tests |
| `d1a223f` | Codex | 2026-11-03 | Fix UI startup failure: restore missing attachCodeBlockCopyHandlers export in markdown.js and add ES module export integrity test |

---

## 3. Archive-versus-Git Comparison

### 3.1. Archive Metadata
- **Archive Path:** `D:\hinaku-ai.zip`
- **File Size:** 27,167,450 bytes (~25.9 MB)
- **Last Modified Timestamp:** 2026-11-13 13:56:46
- **Total Entries in Archive:** 741 files (excluding directories)
- **Git Metadata inside Archive:** None (no `.git/` database; only `.gitignore` is present).

### 3.2. Quantitative Comparison
- **Total files tracked by Git (`git ls-files`):** 275
- **Total files in zip archive:** 741
- **Tracked files in Git missing from Zip:** **0**
- **Files present in both Git working tree and Zip:** 275
- **Content diff between Git working tree and Zip for tracked files:** **0 files differ** (100% byte identical)
- **Files present ONLY in Zip:** 466

### 3.3. Breakdown of Zip-Only Files (466 total)
1. **Compiled Bytecode (`__pycache__`):** 250 files.
2. **Precompiled Tools (`tools/llama.cpp`):** 163 files (including `llama-quantize.exe`, DLLs, and python conversion scripts).
3. **Runtime Local Data (`data/*`):**
   - SQLite Database: `data/hinaku.db` (contains local test/runtime conversations and interactions).
   - ChromaDB Vector Store: `data/chroma/chroma.sqlite3` and binary index levels (`data_level0.bin`, `header.bin`, `link_lists.bin`).
   - Uploaded Attachments: `data/uploads/3ccfade0-.../` and `data/uploads/4e58d0d7-.../` (sample HTML midterm notes).
   - Measurement Logs: 13 files in `data/measure/` (latency and benchmark logs from Phase 2c testing).
   - Latency Profile: `data/latency_profile.json`, `data/think_bench_20261024_225808.jsonl`.
4. **Environment Secret File:** `.env` (contains local environment variables).
5. **Real Test Samples (`tests/real_samples/`):** 4 files (PDF and HTML midterm notes used for manual testing).
6. **UI Screenshots (`codex-UI/`):** 8 PNG screenshots.
7. **Ad-hoc Diagnostic Scripts (`scripts/`):** 4 untracked helper scripts (`audit_chroma_vectors.py`, `evaluate_document_qa_20.py`, `inspect_page3_chunks.py`, `inspect_session8.py`).

---

## 4. Working Tree Status & Important File Differences

At the start of this sprint, the working tree contained 8 uncommitted modified files and several untracked measurement files. These modifications are identical to what was captured in `D:\hinaku-ai.zip`.

### Modified Working Tree Files
1. `README.md`: Updated test suite count description from 216 to 259 passing tests.
2. `backend/api/chat.py`: Added `clean_history_text` to strip model-written citation lines from prior assistant history; updated rolling progress estimation for walkthroughs; refined grounded outline sections formatting.
3. `backend/attachments/citations.py`: Refined format outline citations helper functions.
4. `backend/attachments/manager.py`: Added storage usage query delegation.
5. `backend/attachments/storage.py`: Configured cosine distance space metadata (`hnsw:space: cosine`) on `hinaku_documents` collection; refined hybrid keyword/vector search scoring weights.
6. `scripts/generate_ui_pdf.py`: Minor formatting tweak.
7. `scripts/measure_10_mixed_turns_8192.py`: Added assertions verifying 0 invented citations across multi-turn exchanges.
8. `scripts/run_security_notes_walkthrough_ui.py`: Added telemetry logging for style checking and missing terms.

---

## 5. Sensitive File and Git History Findings

### 5.1. Git Commit History Scan
- An automated regex audit across the entire commit history (`git log -p --all`) was conducted searching for:
  - Private API keys (`sk-[a-zA-Z0-9_-]{20,}`).
  - Credential assignments (`api_key`, `secret`, `password`, `token`).
  - Specific env vars (`HINAKU_API_KEY`).
- **Result:** **0 secrets found** in Git history. All historical commits used placeholders, dummy keys, or environment variables.

### 5.2. Tracked Files Audit
- Executed check against all 275 tracked files for sensitive names (`.env`, `.db`, `.sqlite`, `key`, `secret`, `token`, `credential`).
- Only `ui/css/tokens_and_shell.css` matched (which contains CSS design tokens).
- **Result:** **0 sensitive files are tracked in Git**.

### 5.3. `.gitignore` Verification
- `.gitignore` explicitly excludes:
  - `.env`
  - `data/*` (with exceptions for `!data/bakeoff/` and `!data/measure/`)
  - `models/`
  - `logs/`
  - `tools/`
  - `tests/real_samples/`
  - `*.gguf`, `*.safetensors`, `*.bin`, `*.pt`
- Verified via `git check-ignore -v .env data/hinaku.db data/chroma data/uploads logs`: all are properly ignored.

---

## 6. Configuration and Documentation Inconsistencies

During baseline inspection, the following inconsistencies across configuration, rules, and documentation were identified:

1. **Default Local Model:**
   - `AGENTS.md` (Section 2) specifies: `gemma3:4b` at Q4 via Ollama with `keep_alive: 30m`.
   - `config/settings.yaml` (Line 43) specifies: `default_model: bonsai-2:9b` (established in Phase 0 commit `162bcd1` for 6 GB VRAM fit with `num_ctx: 8192`).
   - `README.md` (Line 82) specifies: `gemma3:4b` under Quickstart.
   - *Recommendation:* Keep `settings.yaml` as the runtime truth, but document that `gemma3:4b` and `bonsai-2:9b` are both supported local models.

2. **Summon / Hide Hotkey:**
   - `config/settings.yaml` (Line 6) specifies: `hotkey: ctrl+alt+h`.
   - `README.md` (Lines 14 & 58) specifies: `Ctrl+Shift+Space`.
   - *Recommendation:* Reconcile documentation to reflect the active hotkey binding.

3. **Implementation Report Scope:**
   - `docs/HINAKU_IMPLEMENTATION_REPORT.md` concludes at Phase H (commit `cfde97c`).
   - Subsequent phases (Phase 0, Phase 1, Phase 2, Phase 2b, Phase 2c) were committed later (up to `38f04c5`).
   - *Recommendation:* Future documentation updates should index Phases 0 through 2c.

---

## 7. Recommended Source of Truth

**Recommendation: The Git repository at `D:\HINAKU-AI` is the authoritative source of truth.**

### Justification
1. The Git repository possesses complete commit history, author attribution, and cryptographically verified tree objects.
2. The supplied `D:\hinaku-ai.zip` is a point-in-time filesystem dump of this exact working tree, containing no additional or alternate source code.
3. The zip archive includes machine-specific build artifacts, runtime databases with personal test data, and `.env` credentials that should remain local and never be treated as repository source code.
4. Preserving the working tree on a dedicated branch allows continuous development while adhering to the rule of not committing without owner approval.

---

## 8. Recommended Next Actions

1. Proceed immediately with **Sprint 0B: Outbound Privacy Boundary Audit and Implementation**.
2. Work exclusively on branch `sprint-0b-privacy-boundary`.
3. Keep the original source archive `D:\hinaku-ai.zip` unmodified as reference.
4. Implement the final outbound privacy gate to enforce that no private conversation, personal owner facts, attachments, or sensitive context can leak to external API providers.
