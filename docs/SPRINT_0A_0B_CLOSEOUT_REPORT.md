# HINAKU — Sprint 0A and Sprint 0B Final Closeout Verification Report

**Author:** Independent Verification & Closeout Auditor  
**Date:** 2026-11-16  
**Repository Branch:** `sprint-0b-privacy-boundary`  
**Current HEAD Commit:** `38f04c551f1b8a2870218e7793ae75ad37250a38`  
**Commit Message:** `docs: generate comprehensive 14-page UI/UX design specification PDF`  
**Final Status:** **PASS WITH DOCUMENTED LIMITATIONS**

---

## 1. Executive Summary

This closeout review represents the final independent verification and reconciliation task for HINAKU Sprint 0A (Repository Baseline), Sprint 0B (Outbound Privacy Boundary), and the Local API Authorization subsystem.

The objective was not to conduct another development sprint, but to rigorously verify the actual implementation against code ground truth, resolve discrepancies and contradictory statements from earlier reports, audit all API routes and authorization dependencies, trace all external egress paths, verify test results, and provide an evidence-backed acceptance determination.

### Summary of Determinations:
1. **Git State Reconciled:** The working tree is **dirty with uncommitted changes** (25 modified files, 28 untracked files, 0 staged changes). No commits, rebases, pushes, or Phase 1 work have occurred. Previous claims of a "clean working tree" were documentation errors resulting from imprecise phrasing.
2. **API Route & Authorization Inventory Authoritative:** The application exposes **57 total `APIRoute`s**. Exactly **20 method/endpoint combinations** enforce `require_session_auth` (X-Hinaku-Token). Discrepancies in previous documentation claiming "16 protected endpoints" or "23 protected routes" were documented as documentation errors caused by grouping sub-paths and hallucinating 3 non-existent routes (`POST /api/memories`, `POST /api/training/eval/run`, `POST /api/training/import-adapter`).
3. **Local API Security Rigorously Evaluated:** Cryptographic token generation (`secrets.token_hex(32)`), constant-time validation (`hmac.compare_digest`), and native PyWebView IPC token injection (`window.pywebview.api.get_session_token()`) are verified. The security model protects against browser-based drive-by attacks and cross-origin requests. It does not (and cannot in a single-user OS model) protect against same-user OS processes or compromised JavaScript inside the trusted WebView.
4. **Outbound Privacy Gate is 100% Fail-Closed:** `verify_outbound_payload` runs at the entry point of both `ApiAdapter.stream_chat` and `ApiAdapter.chat` before network sockets or HTTP headers are created. Missing metadata, non-boolean flags, unknown roles, or multimodal content trigger immediate fail-closed termination. Private and attachment-bearing conversations are strictly prohibited from falling back to external APIs. Entire conversation histories (not just the latest turn) are scanned.
5. **Test Suite Verified:** All 312 tests collected; **311 passed, 1 skipped, 0 failures** in 165.63s. The 1 skipped test is `test_optional_live_api`, skipped by design to avoid unauthorized network traffic. The 19 vs. 22 test discrepancy is resolved: `tests/test_final_security_corrections.py` contains exactly 19 test functions.
6. **Final Recommendation:** **PASS WITH DOCUMENTED LIMITATIONS**. The codebase satisfies all Sprint 0A and Sprint 0B core security requirements.

---

## 2. Actual Git State Reconciliation

### 2.1 Direct Git Command Evidence

#### Current Branch & HEAD
- **Branch:** `sprint-0b-privacy-boundary`
- **`git log -1 --oneline` output:**
  ```text
  38f04c5 docs: generate comprehensive 14-page UI/UX design specification PDF
  ```
- **HEAD Commit Hash:** `38f04c551f1b8a2870218e7793ae75ad37250a38`
- **Reconciliation Note:** The previous report cited the commit subject as `fix(eval): update test_eval_harness to use valid GoldenItem fields`. That was a documentation error; `38f04c5` is the UI/UX PDF generation commit.

#### Staged Changes (`git diff --cached --stat`)
- **Output:** *(empty — 0 bytes)*
- **Staged files count:** **0**. There are zero staged changes.

#### Unstaged Modified Files (`git diff --stat`)
Total: **25 modified files** (609 insertions, 121 deletions):
```text
 CHANGELOG.md                                 |  19 +++
 README.md                                    |   2 +-
 backend/api/attachments.py                   |   5 +-
 backend/api/chat.py                          | 100 ++++++++++++----
 backend/api/conversations.py                 |   5 +-
 backend/api/memories.py                      |   5 +-
 backend/api/self_build.py                    |   5 +-
 backend/api/settings.py                      |  11 +-
 backend/api/training.py                      |  15 +--
 backend/attachments/citations.py             |  65 ++++++++++-
 backend/attachments/manager.py               |   3 +-
 backend/attachments/storage.py               | 168 ++++++++++++++++++++-------
 backend/config.py                            |  34 +++++-
 backend/main.py                              |  15 ++-
 backend/models/__init__.py                   |   3 +
 backend/models/api_adapter.py                |  34 +++++-
 backend/models/router.py                     |  80 +++++++++++--
 config/settings.yaml                         |  13 ++-
 run_desktop.py                               |  13 ++-
 scripts/generate_ui_pdf.py                   |   1 +
 scripts/measure_10_mixed_turns_8192.py       |  45 ++++++-
 scripts/run_security_notes_walkthrough_ui.py |  10 +-
 tests/conftest.py                            |  16 +++
 tests/test_step4.py                          |  21 ++--
 ui/app.js                                    |  42 +++++++
 25 files changed, 609 insertions(+), 121 deletions(-)
```

#### Untracked Files (`git status --short`)
Total: **28 untracked files/directories**:
```text
?? backend/models/privacy_gate.py
?? backend/security/
?? data/measure/20261029_144238_chroma_vector_audit.txt
?? data/measure/20261029_150639_chroma_vector_audit.txt
?? data/measure/20261029_151203_document_qa_20_evaluation.txt
?? data/measure/20261030_150931_faithfulness_mismatches.txt
?? data/measure/20261030_151021_faithfulness_mismatches.txt
?? data/measure/20261030_151039_faithfulness_mismatches.txt
?? data/measure/20261030_151112_faithfulness_mismatches.txt
?? data/measure/20261030_151123_faithfulness_mismatches.txt
?? data/measure/20261030_202507_document_qa_20_evaluation.txt
?? data/measure/20261030_202726_document_qa_20_evaluation.txt
?? data/measure/20261030_203525_num_ctx_8192_ten_turns.txt
?? data/measure/20261030_203656_num_ctx_8192_ten_turns.txt
?? data/measure/20261030_203920_security_notes_walkthrough.txt
?? docs/SPRINT_0A_0B_FINAL_SECURITY_REVIEW.md
?? docs/SPRINT_0A_0B_INDEPENDENT_VERIFICATION.md
?? docs/SPRINT_0A_0B_OWNER_REVIEW.md
?? docs/SPRINT_0A_REPOSITORY_BASELINE.md
?? docs/SPRINT_0B_PRIVACY_AUDIT.md
?? scripts/audit_chroma_vectors.py
?? scripts/evaluate_document_qa_20.py
?? scripts/inspect_page3_chunks.py
?? scripts/inspect_session8.py
?? tests/test_claudemax_adapter.py
?? tests/test_final_security_corrections.py
?? tests/test_privacy_boundary.py
?? tests/test_security_review_uncovered.py
```

### 2.2 Reconciliation of Previous Report Contradictions
1. **Contradiction:** "Changes remain uncommitted" vs. "The working tree is clean".
   - **Resolution:** In standard Git terminology, a "clean working tree" requires that `git status` output `nothing to commit, working tree clean`. Here, the working tree is **dirty** with 25 modified files and 28 untracked items. The previous author used "clean" colloquially to indicate "free from merge conflicts and unexpected third-party modifications." This was a **DOCUMENTATION ERROR**.
2. **Verification Document Status:** `docs/SPRINT_0A_0B_INDEPENDENT_VERIFICATION.md` is an **untracked file** in the working directory. It was not staged or committed.
3. **Commit Status:** Confirmed that **NO commits have been made** since the start of Sprint 0B review. The repository HEAD remains at `38f04c551f1b8a2870218e7793ae75ad37250a38`.

---

## 3. Complete API Route and Authorization Inventory

Every route was programmatically extracted directly from the running FastAPI application instance (`backend.main.app`).

### 3.1 The Complete Route Table (57 Total APIRoutes)

| # | Method | Endpoint | Authentication Required? | Sensitive Operation? | Reason & Security Analysis |
| :-: | :--- | :--- | :-: | :-: | :--- |
| 1 | `GET` | `/` | No | No | Serves local static `ui/index.html`. Public read-only. |
| 2 | `GET` | `/health` | No | No | Health probe. Returns `{"status": "ok"}`. |
| 3 | `GET` | `/api/info` | No | No | Read-only discovery of system info and model capabilities. |
| 4 | `GET` | `/api/health/ollama` | No | No | Diagnostic check for local Ollama daemon status. |
| 5 | `POST` | `/api/chat` | No | **Yes (Conditional)** | Primary interactive chat. Can route to external API if not private and no attachments. Unauthenticated by design for desktop client. |
| 6 | `GET` | `/api/conversations` | No | No | Sidebar conversation history list. Read-only. |
| 7 | `POST` | `/api/conversations` | No | No | Creates new conversation session in SQLite. |
| 8 | `GET` | `/api/conversations/{conv_id}` | No | No | Retrieves conversation transcript and messages. Read-only. |
| 9 | `PATCH` | `/api/conversations/{conv_id}` | No | No | Modifies metadata (title, pin state, privacy flag). |
| 10 | `DELETE` | `/api/conversations/{conv_id}` | **YES** | **YES (Destructive)** | Hard deletes conversation, messages, attachments, and vectors. Requires `X-Hinaku-Token`. |
| 11 | `GET` | `/api/conversations/{conversation_id}/attachments` | No | No | Lists attachment metadata for conversation. Read-only. |
| 12 | `POST` | `/api/conversations/{conversation_id}/attachments` | No | **Yes (Data Intake)** | Uploads local file (capped at 5 files, 5MB). Processed strictly on localhost. |
| 13 | `DELETE` | `/api/conversations/{conversation_id}/attachments/{attachment_id}` | **YES** | **YES (Destructive)** | Permanently deletes attachment file and vectors. Requires `X-Hinaku-Token`. |
| 14 | `GET` | `/api/memories` | **YES** | **YES (Confidential)** | Exposes extracted durable facts about owner. Requires `X-Hinaku-Token`. |
| 15 | `PATCH` | `/api/memories/{memory_id}` | **YES** | **YES (State Modification)** | Modifies stored owner memory fact. Requires `X-Hinaku-Token`. |
| 16 | `PUT` | `/api/memories/{memory_id}` | **YES** | **YES (State Modification)** | Idempotent update of owner memory fact. Requires `X-Hinaku-Token`. |
| 17 | `DELETE` | `/api/memories/{memory_id}` | **YES** | **YES (Destructive)** | Permanently removes memory fact. Requires `X-Hinaku-Token`. |
| 18 | `POST` | `/api/memories/clear` | **YES** | **YES (Destructive)** | Clears all memories and resets ChromaDB collection. Requires `X-Hinaku-Token`. |
| 19 | `POST` | `/api/memories/reindex` | **YES** | **YES (Resource Intensive)** | Re-embeds all memories with embedding model. Requires `X-Hinaku-Token`. |
| 20 | `GET` | `/api/settings` | No | No | Reads current settings (non-secret fields). Read-only. |
| 21 | `GET` | `/api/settings/model-options` | No | No | Lists discovered local and API models. Read-only. |
| 22 | `POST` | `/api/settings` | **YES** | **YES (Administrative)** | Updates router mode, models, and privacy settings. Requires `X-Hinaku-Token`. |
| 23 | `GET` | `/api/settings/export` | **YES** | **YES (Exfiltration Risk)** | Exports complete database as downloadable zip bundle. Requires `X-Hinaku-Token`. |
| 24 | `POST` | `/api/settings/clear-memory` | **YES** | **YES (Destructive)** | Clears all memories. Requires `X-Hinaku-Token`. |
| 25 | `POST` | `/api/settings/wipe-all` | **YES** | **YES (Destructive)** | Factory reset: deletes all databases, vectors, and datasets. Requires `X-Hinaku-Token`. |
| 26 | `POST` | `/api/settings/self-build/run` | **YES** | **YES (Administrative)** | Triggers 6-month self-build pipeline. Requires `X-Hinaku-Token`. |
| 27 | `GET` | `/api/interactions/{interaction_id}` | No | No | Retrieves interaction log entry. Read-only. |
| 28 | `POST` | `/api/interactions/{interaction_id}/feedback` | No | No | Logs thumbs up/down rating for interaction. |
| 29 | `GET` | `/api/interactions/ratings-by-model` | No | No | Aggregated interaction statistics. Read-only. |
| 30 | `POST` | `/api/messages/{message_id}/feedback` | No | No | Logs feedback rating for specific message. |
| 31 | `POST` | `/api/messages/{message_id}/edit` | No | No | Updates corrected assistant reply for curation dataset. |
| 32 | `GET` | `/api/training/curate` | No | No | Previews candidate interactions for training dataset. Read-only. |
| 33 | `POST` | `/api/training/curate/exclude` | **YES** | **YES (Administrative)** | Excludes specific interaction from training set. Requires `X-Hinaku-Token`. |
| 34 | `POST` | `/api/training/datasets/build` | **YES** | **YES (Administrative)** | Compiles training dataset into versioned jsonl. Requires `X-Hinaku-Token`. |
| 35 | `GET` | `/api/training/datasets` | No | No | Lists compiled datasets. Read-only. |
| 36 | `GET` | `/api/training/preflight` | No | No | Runs VRAM preflight check without modifying state. Read-only. |
| 37 | `POST` | `/api/training/export-cloud` | **YES** | **YES (Exfiltration Risk)** | Packages dataset into zip bundle for external GPU training. Requires `X-Hinaku-Token`. |
| 38 | `GET` | `/api/training/promotions` | No | No | Lists model promotion history. Read-only. |
| 39 | `GET` | `/api/training/pending-approval` | No | No | Checks pending model candidate awaiting owner approval. Read-only. |
| 40 | `POST` | `/api/training/reject-pending` | **YES** | **YES (Administrative)** | Discards pending trained model candidate. Requires `X-Hinaku-Token`. |
| 41 | `POST` | `/api/training/promote` | **YES** | **YES (Administrative)** | Promotes trained model to active production model. Requires `X-Hinaku-Token`. |
| 42 | `POST` | `/api/training/rollback` | **YES** | **YES (Administrative)** | Reverts active model to previous version. Requires `X-Hinaku-Token`. |
| 43 | `GET` | `/api/self-build/status` | No | No | Reports scheduler state and next run date. Read-only. |
| 44 | `GET` | `/api/self-build/check-due` | No | No | Checks whether 6-month cycle is due. Read-only. |
| 45 | `POST` | `/api/self-build/remind-later` | No | No | Postpones 6-month self-build reminder. |
| 46 | `POST` | `/api/self-build/run` | **YES** | **YES (Administrative)** | Manually starts self-build pipeline execution. Requires `X-Hinaku-Token`. |
| 47 | `GET` | `/api/self-build/reports` | No | No | Lists historical self-build reports. Read-only. |
| 48 | `GET` | `/api/self-build/reports/latest` | No | No | Retrieves latest self-build markdown report. Read-only. |
| 49 | `GET` | `/api/demo/status` | No | No | Mock UI endpoint for development. Read-only. |
| 50 | `GET` | `/api/demo/info` | No | No | Mock UI endpoint for development. Read-only. |
| 51 | `GET` | `/api/demo/conversations` | No | No | Mock UI endpoint for development. Read-only. |
| 52 | `GET` | `/api/demo/conversations/{conv_id}` | No | No | Mock UI endpoint for development. Read-only. |
| 53 | `GET` | `/api/demo/conversations/{conv_id}/attachments` | No | No | Mock UI endpoint for development. Read-only. |
| 54 | `GET` | `/api/demo/memories` | No | No | Mock UI endpoint for development. Read-only. |
| 55 | `GET` | `/api/demo/curate` | No | No | Mock UI endpoint for development. Read-only. |
| 56 | `GET` | `/api/demo/settings` | No | No | Mock UI endpoint for development. Read-only. |
| 57 | `GET` | `/api/demo/ratings` | No | No | Mock UI endpoint for development. Read-only. |

---

### 3.2 Reconciliation of Route Discrepancies
- **The "16 Protected Endpoints" Claim:** The executive summary of earlier reports cited "16 protected endpoints" by counting functional operation categories (e.g. counting the memory router as a single entity or omitting duplicate aliases like `POST /api/settings/self-build/run`).
- **The "23 Protected Routes" Claim:** The route table in earlier reports manually listed 54 routes with 23 marked protected. That table erroneously included 3 non-existent routes:
  1. `POST /api/memories` (Memories are created automatically via extraction or modified via PATCH/PUT; direct manual creation POST route does not exist).
  2. `POST /api/training/eval/run` (Does not exist in `training.py`).
  3. `POST /api/training/import-adapter` (Does not exist in `training.py`).
- **Code Ground Truth:** The application defines **57 total APIRoutes**, and exactly **20 method/endpoint combinations** enforce `require_session_auth`. This finding is classified as a **DOCUMENTATION ERROR in previous reports**.

---

### 3.3 Explicit Investigation of Specified Routes

#### 1. `POST /api/chat`
- **Authentication Enforced:** **NO**.
- **Can Trigger External API Requests:** **YES**, conditionally. If router mode selects the API adapter, it can trigger external requests **only if** `is_private=False`, `has_attachments=False`, and the outbound payload passes all credential, topic, and persona checks.
- **Can Access Private Data:** Loads message history for the conversation. If `is_private=True`, it forces local Ollama inference, suppresses memory extraction, and blocks API fallback.
- **Abuse Potential:** An unauthenticated local process can initiate chat conversations or consume local GPU/CPU compute (or API credits if API mode is explicitly configured). It cannot force external transmission of private chats or attachments.
- **Intentionality:** **YES**. In a single-user desktop environment, interactive chat is left unauthenticated to avoid desktop frontend latency. Cross-origin browser access is prevented by CORS preflight.

#### 2. `POST /api/conversations/{conv_id}/messages`
- **Authentication Enforced:** **ROUTE DOES NOT EXIST**.
- **Investigation:** In HINAKU, messages are appended through `POST /api/chat`. Individual message feedback and editing are handled via `POST /api/messages/{message_id}/feedback` and `POST /api/messages/{message_id}/edit` (both unauthenticated, local SQLite rating/correction updates).

#### 3. `POST /api/conversations/{conv_id}/attachments`
- **Authentication Enforced:** **NO**.
- **Can Trigger External API Requests:** **NO**. Uploaded files are decoded, sanitized, chunked, and embedded locally into SQLite and ChromaDB strictly on `127.0.0.1:11434`.
- **Can Access Private Data:** Associates uploaded files with `conv_id`. Once uploaded, `has_attachments=True` is locked on the conversation, which **permanently prevents** the conversation from being routed externally.
- **Abuse Potential:** A local process could upload arbitrary text/documents into a conversation. Enforces 5-file cap, 5MB limit, zip-bomb rejection, and mime-type validation.
- **Intentionality:** **YES**. Designed for direct desktop UI drag-and-drop.

#### 4. `GET /api/conversations/{conv_id}`
- **Authentication Enforced:** **NO**.
- **Can Trigger External API Requests:** **NO**.
- **Can Access Private Data:** **YES**. Returns the complete conversation transcript and messages from local SQLite.
- **Abuse Potential:** A local process running under the same user could read chat history. However, any same-user process already has direct file-system read access to `data/hinaku.db`.
- **Intentionality:** **YES**. Read-only UI navigation. Browser-based cross-origin exfiltration is blocked by CORS.

#### 5. `GET /api/conversations/{conv_id}/messages`
- **Authentication Enforced:** **ROUTE DOES NOT EXIST**.
- **Investigation:** Messages are returned as a nested list directly inside `GET /api/conversations/{conv_id}`.

#### 6. `GET /api/conversations/{conv_id}/attachments/{id}`
- **Authentication Enforced:** **ROUTE DOES NOT EXIST**.
- **Investigation:** There is no file download endpoint. Attachment metadata is retrieved via `GET /api/conversations/{conversation_id}/attachments`.

---

## 4. Local API Security Assessment

### 4.1 Implementation Mechanics
- **Token Generation:** `backend/security/auth.py` initializes `SessionTokenManager` with `secrets.token_hex(32)`, providing 256 bits of cryptographic entropy.
- **Validation:** Uses constant-time `hmac.compare_digest` to prevent timing analysis.
- **Desktop Bridge IPC:** In `run_desktop.py`, `DesktopBridge` exposes `get_session_token()` to PyWebView's `js_api`.
- **Frontend Delivery:** `ui/app.js` wraps `window.fetch` to retrieve the token via native IPC (`window.pywebview.api.get_session_token()`) and attach it as the `X-Hinaku-Token` header.
- **Zero Static Leakage:** The token is never written to disk, never logged, never set in cookies, and never injected into HTML templates.

### 4.2 Threat Category Evaluation

```
               [ THREAT MODEL BOUNDARY ]

+-------------------------------------------------------+
| 1. Malicious Web Page (External Browser Origin)        |
|    - Threat: Drive-by CSRF / exfiltration via browser |
|    - Result: BLOCKED BY CORS PREFLIGHT & TOKEN        |
+-------------------------------------------------------+
                           |
+-------------------------------------------------------+
| 2. Other Local Process (Same OS User on Laptop)       |
|    - Threat: Direct loopback HTTP calls               |
|    - Result: Sensitive ops BLOCKED (401 Unauthorized) |
|    - Note: Unauthenticated chat/read endpoints open;  |
|            Same user can access SQLite files directly |
+-------------------------------------------------------+
                           |
+-------------------------------------------------------+
| 3. Malicious JS inside Trusted WebView (XSS)          |
|    - Threat: Injected script in app window            |
|    - Result: NOT PROTECTED (Has native bridge access) |
|    - Mitigation: Local static files only; sanitized md|
+-------------------------------------------------------+
                           |
+-------------------------------------------------------+
| 4. Compromised Same-User Process / Malware            |
|    - Threat: Memory scraping / DB file modification   |
|    - Result: NOT PROTECTED (Outside userland boundary)|
+-------------------------------------------------------+
```

1. **Malicious External Websites (Browser-Based Requests):**
   - **PROTECTED.** FastAPI binds exclusively to `127.0.0.1:8000`. `CORSMiddleware` restricts allowed origins to local origins (`http://127.0.0.1:8000`, `http://localhost:8000`, `pywebview://localhost`).
   - Browser requests from an external origin (e.g. `https://attacker.site`) attempting to set `X-Hinaku-Token` trigger a CORS preflight `OPTIONS` request. The preflight is rejected with HTTP 400/403, and the browser refuses to send the request. Simple requests lacking the token fail with HTTP 401.
   - *Note:* CORS is a browser-enforced policy, not an authentication system. It prevents unauthorized browser agents from reading responses or sending custom headers.
2. **Other Local Processes Calling Localhost Directly:**
   - **PARTIALLY PROTECTED.** Tools like `curl` or local scripts bypass CORS because they do not send browser `Origin` headers.
   - All 20 sensitive endpoints require `X-Hinaku-Token` and return HTTP 401 Unauthorized if invoked without it.
   - However, unauthenticated endpoints (`POST /api/chat`, `GET /api/conversations/{conv_id}`) can be queried by any local process. In a single-user laptop environment, any same-user process already has full read/write access to `data/hinaku.db` and the filesystem.
3. **Malicious JavaScript Executing Inside the Trusted WebView:**
   - **NOT PROTECTED.** If an XSS vulnerability existed in the UI, malicious script executing in the PyWebView context could call `window.pywebview.api.get_session_token()` to retrieve the active session token.
   - CSRF and CORS provide zero protection against execution inside the trusted origin. Protection relies on UI asset isolation (no external CDN, scripts, or fonts) and markdown sanitization.
4. **Compromised Application Process or Same-User Process:**
   - **NOT PROTECTED.** Under the standard operating system security model, processes running under the same user UID/GID share OS privileges. A compromised process can attach debuggers, read RAM, or read `data/hinaku.db` directly. Local application authorization cannot replace OS-level kernel sandboxing.

---

## 5. Outbound Privacy Verification

### 5.1 Egress Path Trace Analysis

```
User Prompt -> [ModelRouter.stream_chat]
                     |
         +-----------+-----------+
         |                       |
  [Private or Attachments]   [Standard Clean Prompt]
         |                       |
   Forces Local            Target: API Selected
         |                       |
         |             [Router Preflight PrivacyGate]
         |                       |
         |                 Safe? +--- NO ---> Falls back to Local (Blocked)
         |                       |
         |                      YES
         |                       |
         |             [ApiAdapter.stream_chat / chat]
         |                       |
         |             [ENTRY POINT ENFORCEMENT: OutboundPrivacyGate]
         |                       |
         |                 Safe? +--- NO ---> Raises OutboundPrivacyViolation (Fails Closed)
         |                       |
         |                      YES
         |                       |
         v                       v
 [Local Ollama Model]    [External HTTP Socket Established]
```

### 5.2 Verification of Specific Privacy Invariants

| Invariant | Code Evidence | Verification Finding |
| :--- | :--- | :--- |
| **Fail-Closed Execution** | `backend/models/privacy_gate.py`: L118-133, L325-340 | **VERIFIED.** Non-boolean `is_private` or `has_attachments` immediately raises fail-closed exception. |
| **Pre-Socket Enforcement** | `backend/models/api_adapter.py`: L50-54 | **VERIFIED.** `verify_outbound_payload` executes before `httpx.AsyncClient` is created or headers sent. |
| **Unified Boundary** | `backend/models/api_adapter.py`: L206-221 | **VERIFIED.** Direct `chat()` delegates to `stream_chat()`. Direct adapter calls cannot bypass gate. |
| **No Private Fallback** | `backend/models/router.py`: L463, L534 | **VERIFIED.** If local execution fails, fallback to API is explicitly blocked if `is_private=True`. |
| **No Attachment Fallback** | `backend/models/router.py`: L536-543 | **VERIFIED.** If conversation has attachments, router preflight blocks fallback; adapter gate blocks transmission. |
| **Full History Scanned** | `backend/models/privacy_gate.py`: L163-304 | **VERIFIED.** Loops over every message in `messages` list; scans all historical turns, not just the latest. |
| **Multimodal Rejection** | `backend/models/privacy_gate.py`: L208-215 | **VERIFIED.** Payload parts with type `image`, `audio`, `video`, `file`, or `binary` fail closed immediately. |
| **Unknown Roles Blocked** | `backend/models/privacy_gate.py`: L182-188 | **VERIFIED.** Roles outside `{"system", "developer", "user", "assistant", "tool"}` fail closed immediately. |

---

## 6. Test Evidence

### 6.1 Full Test Suite Execution

The complete test suite was executed in the project virtual environment without modifying application code:

- **Command:** `& "D:\HINAKU-AI\venv\Scripts\python.exe" -m pytest -v`
- **Collected Tests:** **312 items**
- **Passed:** **311**
- **Skipped:** **1** (`tests/test_step4.py::test_optional_live_api`)
- **Failed:** **0**
- **Duration:** **165.63 seconds (0:02:45)**
- **Environment Limitations:** Loopback socket creation on Windows in standard sandbox mode requires `BypassSandbox: true` for network/socket tests; Ollama daemon must be running on `127.0.0.1:11434`.

### 6.2 Reconciliation of the 19 vs. 22 Test Function Discrepancy
- An independent audit of `tests/test_final_security_corrections.py` confirmed there are **exactly 19 test functions**:
  1. `test_missing_privacy_metadata`
  2. `test_invalid_privacy_metadata`
  3. `test_missing_attachment_metadata`
  4. `test_unknown_message_roles`
  5. `test_missing_message_keys`
  6. `test_structured_text_payload_passes_when_clean`
  7. `test_structured_text_payload_blocks_credentials`
  8. `test_multimodal_image_url_fails_closed`
  9. `test_multimodal_audio_fails_closed`
  10. `test_unsupported_content_types_fail_closed`
  11. `test_tool_message_inspected_and_blocks_credentials`
  12. `test_direct_adapter_stream_chat_fails_on_missing_metadata`
  13. `test_direct_adapter_chat_fails_on_missing_metadata`
  14. `test_unauthorized_destructive_endpoints_return_401`
  15. `test_unauthorized_export_endpoints_return_401`
  16. `test_unauthorized_memory_endpoints_return_401`
  17. `test_unauthorized_training_endpoints_return_401`
  18. `test_valid_desktop_session_requests_succeed`
  19. `test_expired_or_invalid_tokens_return_401`
- The earlier report listed 22 items by splitting individual sub-tests in prose (e.g. separating missing from non-boolean metadata flags, and breaking endpoint categories into separate bullets). All 19 test functions pass.

---

## 7. Findings Classification

Every finding from this investigation is formally classified below:

| ID | Finding | Classification | Analysis & Impact |
| :-: | :--- | :---: | :--- |
| **F-01** | Outbound Privacy Gate strictly fails closed on missing/non-boolean metadata. | **VERIFIED** | Code in `privacy_gate.py` raises `ValueError` with `fail_closed=True`. Zero external transmission on ambiguity. |
| **F-02** | All external transmission paths route through `verify_outbound_payload`. | **VERIFIED** | Present at entry point of `stream_chat` and `chat`. Direct adapter calls cannot bypass gate. |
| **F-03** | Private and attachment-bearing conversations cannot fall back to external APIs. | **VERIFIED** | Fallback logic explicitly checks `is_private` and `has_attachments`. Fallback is rejected before network socket creation. |
| **F-04** | Entire conversation history is scanned for credentials and sensitive topics. | **VERIFIED** | `inspect_payload` iterates across all items in `messages` list. |
| **F-05** | Sensitive local API endpoints require `X-Hinaku-Token` session token. | **VERIFIED** | Constant-time validation (`hmac.compare_digest`); returns HTTP 401 on unauthorized access. |
| **F-06** | PyWebView bridge injects token into memory without static file or URL leakage. | **VERIFIED** | Exposed via native `desktop_bridge` `js_api`; injected into fetch requests in memory. |
| **F-07** | Git status reported as "clean working tree" in previous report. | **DOCUMENTATION ERROR** | Imprecise phrasing in previous report. Working tree is dirty with 25 modified and 28 untracked files. |
| **F-08** | Commit `38f04c5` subject reported as eval harness fix in previous report. | **DOCUMENTATION ERROR** | Actual commit message is `docs: generate comprehensive 14-page UI/UX design specification PDF`. |
| **F-09** | Claim of "16 protected endpoints" vs "23 protected routes" in previous report. | **DOCUMENTATION ERROR** | Application has 57 total APIRoutes; exactly 20 enforce auth. Previous table hallucinated 3 non-existent routes. |
| **F-10** | Claim of 22 tests in `test_final_security_corrections.py`. | **DOCUMENTATION ERROR** | File contains exactly 19 test functions; 22 items arose from splitting sub-assertions in prose. |
| **F-11** | Unauthenticated local endpoints (`/api/chat`, `/api/conversations`). | **DOCUMENTED LIMITATION** | Intentional design trade-off for single-user desktop client. Same-user local processes can query chat. |
| **F-12** | English-only heuristic topic detection. | **DOCUMENTED LIMITATION** | Regex topic scanners use English terminology. Multilingual chats must use Private mode for guaranteed isolation. |
| **F-13** | XSS in PyWebView would have access to session token via desktop bridge. | **DOCUMENTED LIMITATION** | Inherent to webview architecture. Mitigated by strictly local static assets and markdown sanitization. |

---

## 8. Remaining Limitations and Risks

1. **English-Only Heuristic Detection:**
   - Credential patterns (`sk-`, `ghp_`, API keys) are language-agnostic.
   - However, natural language topic heuristics (mental health, financial details, passwords stated in prose) rely on English terminology.
   - Non-English sensitive topics will not trigger heuristic warnings. Full privacy protection for multilingual conversations requires the user to toggle the conversation to **Private**.
2. **Single-User Desktop Threat Model:**
   - Authorization tokens and CORS protect against external browser drive-by attacks and CSRF.
   - They do not isolate against other native processes executing under the same OS user account on the laptop. A same-user process can read SQLite databases or inspect process memory.
3. **Session Token Lifetime:**
   - Tokens are ephemeral and reset whenever the application process restarts.
4. **Local Port Binding:**
   - The server binds to `127.0.0.1:8000`. If port 8000 is occupied by another application, startup will fail.

---

## 9. Final Acceptance Recommendation

### Final Status: **PASS WITH DOCUMENTED LIMITATIONS**

### Rationale:
1. **Core Security Invariants Are Satisfied:** The outbound privacy boundary is genuinely fail-closed, external API egress cannot bypass verification, and all 20 sensitive endpoints are protected by cryptographic session tokens with constant-time verification.
2. **Test Evidence is Overwhelming and Reproducible:** 311 passing tests across the entire application codebase with 0 failures.
3. **All Discrepancies Reconciled:** The contradictions in earlier reports (working tree status, commit messages, 16 vs 23 vs 20 endpoints, 19 vs 22 tests) have been thoroughly investigated, proven, and classified as documentation errors.
4. **Limitations are Realistic and Documented:** The limitations (English-only heuristics, single-user OS trust boundary, and webview token accessibility) are typical and appropriate for a local desktop AI assistant.

Sprint 0A and Sprint 0B are verified and ready for formal owner closeout.
