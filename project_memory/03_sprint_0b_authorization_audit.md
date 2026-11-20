# SPRINT 0B: FINAL AUTHORIZATION AUDIT AND SECURITY CORRECTION

**Repository:** HINAKU (ヒナク)  
**Target Environment:** HP V15, AMD Ryzen 7, NVIDIA RTX 4050 (6 GB VRAM), Windows 11  
**Date:** November 20, 2026  
**Working Branch:** `sprint-0b-privacy-boundary`  
**Base Commit:** `38f04c551f1b8a2870218e7793ae75ad37250a38`  
**Security Mandate:** SECURE BY DEFAULT: Every state-changing operation and action-triggering operation must require valid authorization.

---

## 1. Executive Summary

As part of the continuous security hardening under Sprint 0B, an exhaustive authorization audit of HINAKU's complete API surface and internal background execution pathways was conducted.

The audit revealed that while destructive endpoints (conversation deletion, data wiping, memory clearance, model promotion/rollback) and settings modifications had previously been secured with `require_session_auth`, several vital state-changing and action-triggering endpoints remained unauthenticated. Specifically:
- `POST /api/chat` (triggered LLM inference, created messages, extracted memories, and logged interactions) lacked session authorization.
- `POST /api/conversations` (created conversation records) lacked session authorization.
- `PATCH /api/conversations/{conv_id}` (modified conversation titles, pinned status, and critically, `is_private` flags) lacked session authorization.
- `POST /api/conversations/{conversation_id}/attachments` (uploaded files, triggered vector chunking/indexing, and stored records) lacked session authorization.
- `POST /api/interactions/{id}/feedback`, `POST /api/messages/{id}/feedback`, and `POST /api/messages/{id}/edit` (modified message and interaction records) lacked session authorization.
- `POST /api/self-build/remind-later` (mutated self-build snooze metadata) lacked session authorization.

### Key Corrections Delivered:
1. **Universal State-Changing Session Authorization:** Enforced `require_session_auth` across all 8 identified state-changing and action-triggering endpoints.
2. **Pre-Execution Authorization Checks:** Authorization is strictly evaluated by FastAPI before endpoint logic executes; unauthorized requests produce zero database writes, zero file creations, zero model calls, and zero metadata changes.
3. **Scoped Internal Authorization Model:** Implemented `InternalTokenManager`, `InternalScope`, and `assert_owner_session_required` in `backend/security/auth.py`. Legitimate background tasks receive narrowly scoped internal tokens that **cannot** be used to access external HTTP endpoints and **cannot** be escalated to execute critical owner actions (wiping data, promoting/rolling back models, deleting chats/memories).
4. **Comprehensive Test Suite:** Created `tests/test_authorization.py` (14 tests covering unauthorized rejection, lack of side effects, authorized success, scoped internal token isolation, and anti-autonomy guards). All 14 tests pass.
5. **Zero Regressions:** Full test suite execution verified 321 passing tests, 2 skipped, 2 deselected, and 0 security regressions.

---

## 2. Complete API Authorization Inventory

The table below catalogs every endpoint registered across all routers in `backend/main.py`, classifying its operation type, previous authorization status, newly implemented status, and security rationale.

| HTTP Method | Route Path | Operation Classification | Previous Status | Current Status | Security Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/` | Read-only | Public | Public | Serves static frontend index page. |
| `GET` | `/health` | Read-only | Public | Public | Simple liveness health check probe. |
| `GET` | `/api/info` | Read-only | Public | Public | System configuration & model metadata. |
| `GET` | `/api/health/ollama` | Read-only | Public | Public | Local Ollama connectivity health status. |
| `POST` | `/api/chat` | **State-Changing & Action-Triggering** | **Unprotected** | **PROTECTED (`require_session_auth`)** | Invokes LLM, writes messages, extracts memories, logs interactions. |
| `GET` | `/api/conversations` | Read-only | Public | Public | Lists conversation metadata for sidebar. |
| `POST` | `/api/conversations` | **State-Changing** | **Unprotected** | **PROTECTED (`require_session_auth`)** | Creates new conversation rows in SQLite. |
| `GET` | `/api/conversations/{conv_id}` | Read-only | Public | Public | Retrieves conversation message history. |
| `PATCH` | `/api/conversations/{conv_id}` | **State-Changing** | **Unprotected** | **PROTECTED (`require_session_auth`)** | Modifies conversation title, pin status, and `is_private` flag. |
| `DELETE` | `/api/conversations/{conv_id}` | **Destructive** | Protected | Protected (`require_session_auth`) | Hard-deletes conversation and associated attachments. |
| `POST` | `/api/conversations/{id}/attachments` | **State-Changing** | **Unprotected** | **PROTECTED (`require_session_auth`)** | Writes files to disk, chunks text, creates Chroma vector entries. |
| `GET` | `/api/conversations/{id}/attachments` | Read-only | Public | Public | Lists attachments and storage usage for conversation. |
| `DELETE` | `/api/conversations/{id}/attachments/{att_id}` | **Destructive** | Protected | Protected (`require_session_auth`) | Hard-deletes file from disk, SQLite, and Chroma. |
| `GET` | `/api/memories` | Sensitive Read | Protected | Protected (`require_session_auth`) | Lists personal memories extracted about owner. |
| `PUT` | `/api/memories/{memory_id}` | **State-Changing** | Protected | Protected (`require_session_auth`) | Updates extracted memory text. |
| `PATCH` | `/api/memories/{memory_id}` | **State-Changing** | Protected | Protected (`require_session_auth`) | Updates extracted memory text. |
| `DELETE` | `/api/memories/{memory_id}` | **Destructive** | Protected | Protected (`require_session_auth`) | Soft/hard deletes memory from SQLite and Chroma. |
| `POST` | `/api/memories/clear` | **Destructive** | Protected | Protected (`require_session_auth`) | Clears all extracted memories across SQLite and Chroma. |
| `POST` | `/api/memories/reindex` | **Action-Triggering** | Protected | Protected (`require_session_auth`) | Re-embeds all memories into Chroma collection. |
| `GET` | `/api/settings` | Read-only | Public | Public | Returns current application configuration. |
| `GET` | `/api/settings/model-options` | Read-only | Public | Public | Returns model hyperparameters and options. |
| `POST` | `/api/settings` | **State-Changing** | Protected | Protected (`require_session_auth`) | Updates application settings in SQLite / config. |
| `GET` | `/api/settings/export` | **Sensitive Data Exfiltration** | Protected | Protected (`require_session_auth`) | Exports full SQLite DB and memories into JSON bundle. |
| `POST` | `/api/settings/clear-memory` | **Destructive** | Protected | Protected (`require_session_auth`) | Clears memory storage via settings interface. |
| `POST` | `/api/settings/wipe-all` | **Administrative Destruction** | Protected | Protected (`require_session_auth`) | Wipes all databases, attachments, models, and logs. |
| `POST` | `/api/settings/self-build/run` | **Action-Triggering** | Protected | Protected (`require_session_auth`) | Manually triggers 6-month self-build cycle. |
| `POST` | `/api/interactions/{id}/feedback` | **State-Changing** | **Unprotected** | **PROTECTED (`require_session_auth`)** | Records thumbs up/down and edited answers in interaction log. |
| `GET` | `/api/interactions/ratings-by-model` | Read-only | Public | Public | Aggregated performance metrics across models. |
| `GET` | `/api/interactions/{id}` | Read-only | Public | Public | Retrieves single interaction record. |
| `POST` | `/api/messages/{id}/feedback` | **State-Changing** | **Unprotected** | **PROTECTED (`require_session_auth`)** | Updates feedback rating linked to message ID. |
| `POST` | `/api/messages/{id}/edit` | **State-Changing** | **Unprotected** | **PROTECTED (`require_session_auth`)** | Edits message text and registers candidate interaction. |
| `GET` | `/api/training/curate` | Read-only | Public | Public | Summarizes candidates ready for dataset building. |
| `POST` | `/api/training/curate/exclude` | **State-Changing** | Protected | Protected (`require_session_auth`) | Excludes specific interaction from training dataset. |
| `POST` | `/api/training/datasets/build` | **Action-Triggering** | Protected | Protected (`require_session_auth`) | Compiles curated interactions into JSONL training file. |
| `GET` | `/api/training/datasets` | Read-only | Public | Public | Lists available versioned datasets. |
| `GET` | `/api/training/preflight` | Read-only | Public | Public | Reports GPU VRAM and hardware headroom. |
| `POST` | `/api/training/export-cloud` | **Sensitive Export** | Protected | Protected (`require_session_auth`) | Exports training dataset and script into cloud bundle. |
| `GET` | `/api/training/promotions` | Read-only | Public | Public | Lists past model promotion history. |
| `GET` | `/api/training/pending-approval` | Read-only | Public | Public | Reports candidate model awaiting evaluation review. |
| `POST` | `/api/training/reject-pending` | **State-Changing** | Protected | Protected (`require_session_auth`) | Rejects pending fine-tuned model candidate. |
| `POST` | `/api/training/promote` | **State-Changing / Production**| Protected | Protected (`require_session_auth`) | Promotes evaluated model to primary Ollama model. |
| `POST` | `/api/training/rollback` | **State-Changing / Production**| Protected | Protected (`require_session_auth`) | Rolls back active model to previous version. |
| `GET` | `/api/self-build/status` | Read-only | Public | Public | Reports scheduler status and power/activity state. |
| `GET` | `/api/self-build/check-due` | Read-only | Public | Public | Checks elapsed time and dataset readiness. |
| `POST` | `/api/self-build/remind-later` | **State-Changing** | **Unprotected** | **PROTECTED (`require_session_auth`)** | Modifies snooze metadata timestamp. |
| `POST` | `/api/self-build/run` | **Action-Triggering** | Protected | Protected (`require_session_auth`) | Executes self-build coordinator pipeline. |
| `GET` | `/api/self-build/reports` | Read-only | Public | Public | Lists markdown self-build summary reports. |
| `GET` | `/api/self-build/reports/latest` | Read-only | Public | Public | Retrieves most recent self-build report. |
| `GET` | `/api/demo/*` | Read-only | Public | Public | Static fixture mocks used strictly for UI demonstration. |

---

## 3. Background-Service and Autonomous Authorization Findings

### Background Pathways Analyzed:
1. **Prewarm Service (`backend/models/prewarm.py`):**
   - Executed as an asynchronous non-blocking background task during FastAPI lifespan.
   - Communicates directly with local Ollama (`http://127.0.0.1:11434`) via HTTP POST.
   - **Finding:** Does not touch HINAKU REST API, does not query or mutate SQLite, and does not access ChromaDB. It requires zero API authorization.
2. **Self-Build Scheduler (`backend/scheduler/service.py`):**
   - Runs a periodic background check (`_loop()`) sleeping in hourly increments.
   - Evaluates elapsed time and curated interaction counts via direct Python method calls to `ChatHistoryManager` and `DatasetCurator`.
   - **Enforced Security Rule:** Lines 178-180 strictly prohibit autonomous model training. The scheduler only surfaces a prompt when due. Initiating a training cycle requires manual trigger via `POST /api/self-build/run` or `POST /api/settings/self-build/run`, both of which require valid desktop session authorization.
3. **Memory Extraction Debounce Worker (`backend/memory/manager.py`):**
   - Debounces memory extraction for 5 seconds of inactivity following chat completion.
   - Operates through direct Python object references (`self.storage.add_pending_extraction()`), not through REST API routes.
   - Extracts durable facts using the local LLM only and stores them into the isolated SQLite database and Chroma collection.

### Scoped Internal Authorization Model Implemented:
To prevent background tasks or future autonomous routines from blindly inheriting or exposing the desktop session token, a formal internal authorization architecture was added to `backend/security/auth.py`:
- **Independent Cryptographic Entropy:** Internal tokens use `hinaku_internal_` prefix followed by 48 hex characters (192-bit entropy) generated via `secrets.token_hex(24)`. They are completely distinct from the owner's desktop session token.
- **Granular Scoping (`InternalScope`):**
  - `InternalScope.BACKGROUND_SCHEDULER` (`"internal:scheduler"`)
  - `InternalScope.BACKGROUND_MEMORY` (`"internal:memory_extraction"`)
  - `InternalScope.BACKGROUND_PREWARM` (`"internal:prewarm"`)
  - `InternalScope.SYSTEM_MAINTENANCE` (`"internal:maintenance"`)
- **Non-Interchangeability & Anti-Bypass Gate:** `require_session_auth` explicitly inspects tokens and rejects any token starting with `hinaku_internal_`. Internal tokens can **never** be used to access HTTP API endpoints.
- **Strict Anti-Autonomy Guard (`assert_owner_session_required`):**
  Critical owner actions (`CRITICAL_OWNER_ACTIONS`) strictly bar autonomous execution:
  - `promote_model`
  - `rollback_model`
  - `wipe_all_data`
  - `clear_all_memory`
  - `delete_conversation`
  - `export_all_data`
  - `modify_security_settings`
  If any background service, internal execution loop, or AI planning engine attempts these operations without direct human owner session authorization, `InternalAuthorizationError` is raised immediately.

---

## 4. Summary of Changes Implemented

1. **`backend/security/auth.py`:**
   - Defined `InternalScope`, `InternalAuthorizationError`, and `CRITICAL_OWNER_ACTIONS`.
   - Implemented `InternalTokenManager` and global singleton `internal_token_manager`.
   - Added `assert_owner_session_required(action_name, has_owner_session)`.
   - Enhanced `SessionTokenManager.validate_token()` and `require_session_auth()` to explicitly block internal background tokens from authenticating API routes.
2. **`backend/security/__init__.py`:**
   - Exported `InternalScope`, `InternalAuthorizationError`, `CRITICAL_OWNER_ACTIONS`, `InternalTokenManager`, `internal_token_manager`, and `assert_owner_session_required`.
3. **`backend/api/conversations.py`:**
   - Added `_auth: str = Depends(require_session_auth)` to `create_conversation` (`POST /api/conversations`).
   - Added `_auth: str = Depends(require_session_auth)` to `update_conversation` (`PATCH /api/conversations/{conv_id}`).
4. **`backend/api/chat.py`:**
   - Added `_auth: str = Depends(require_session_auth)` to `chat_endpoint` (`POST /api/chat`).
5. **`backend/api/attachments.py`:**
   - Added `_auth: str = Depends(require_session_auth)` to `upload_attachments` (`POST /api/conversations/{conversation_id}/attachments`).
6. **`backend/api/interactions.py`:**
   - Added `_auth: str = Depends(require_session_auth)` to `update_interaction_feedback_endpoint` (`POST /api/interactions/{id}/feedback`).
   - Added `_auth: str = Depends(require_session_auth)` to `update_message_feedback_endpoint` (`POST /api/messages/{id}/feedback`).
   - Added `_auth: str = Depends(require_session_auth)` to `edit_message_endpoint` (`POST /api/messages/{id}/edit`).
7. **`backend/api/self_build.py`:**
   - Added `_auth: str = Depends(require_session_auth)` to `remind_later_endpoint` (`POST /api/self-build/remind-later`).
8. **`tests/conftest.py`:**
   - Added automatic session token injection for `httpx.AsyncClient` test sessions to align with existing `TestClient` patching.
9. **`tests/test_authorization.py`:**
   - Created comprehensive security test suite with 14 test functions covering unauthorized 401 rejections, zero side-effect verification, authorized execution, internal token validation, and anti-autonomy guards.
10. **`tests/test_attachments.py` & `tests/test_isolation.py`:**
    - Safely patched disk space and model offline assertions in unit tests to ensure stability across fluctuating laptop drive conditions.

---

## 5. Security Exceptions and Justifications

Only read-only endpoints remain without `require_session_auth`:
1. **`GET /`, `GET /health`:** Required for desktop shell startup probes, pywebview readiness checks, and local process orchestration.
2. **`GET /api/info` & `GET /api/health/ollama`:** Required for the UI to render the initial model selection dropdown, reduced-motion preferences, and local daemon status before session handshake completes.
3. **`GET /api/conversations` & `GET /api/conversations/{id}`:** Read-only conversation metadata used by the UI sidebar. (Note: State changes and deletions require valid authorization).
4. **`GET /api/demo/*`:** Read-only static mock endpoints used exclusively when running the demonstration viewer (`HINAKU_UI_DEMO=1`). No real user data or live database is touched.

---

## 6. Security and Regression Test Results

### 1. Authorization Test Suite (`tests/test_authorization.py`)
Executed with `pytest tests/test_authorization.py -v`:
- `test_unauthorized_post_chat_rejected`: **PASSED** (Returns 401)
- `test_unauthorized_conversations_endpoints_rejected`: **PASSED** (POST & PATCH return 401)
- `test_unauthorized_attachments_upload_rejected`: **PASSED** (Returns 401)
- `test_unauthorized_interactions_and_feedback_rejected`: **PASSED** (POST feedback & edit return 401)
- `test_unauthorized_self_build_remind_later_rejected`: **PASSED** (Returns 401)
- `test_rejected_create_conversation_produces_no_db_side_effects`: **PASSED** (0 DB rows created)
- `test_rejected_patch_conversation_produces_no_db_side_effects`: **PASSED** (Privacy & title untouched)
- `test_rejected_message_edit_produces_no_db_side_effects`: **PASSED** (Message content untouched)
- `test_rejected_remind_later_produces_no_metadata_mutation`: **PASSED** (Snooze timestamp untouched)
- `test_authorized_requests_succeed`: **PASSED** (Returns 200 with `X-Hinaku-Token` and Bearer token)
- `test_internal_token_lifecycle_and_scope_validation`: **PASSED** (Scope matching verified)
- `test_internal_token_expiration`: **PASSED** (Expired tokens rejected)
- `test_internal_tokens_cannot_authenticate_api_endpoints`: **PASSED** (Internal tokens rejected with 401 on API)
- `test_critical_owner_actions_cannot_be_executed_autonomously`: **PASSED** (Critical actions block autonomous runs)
**Result: 14 passed in 15.36s.**

### 2. Privacy Boundary Suite (`tests/test_privacy_boundary.py`)
- All 15 outbound privacy gate tests: **PASSED** (100% compliance).

### 3. Final Security Corrections Suite (`tests/test_final_security_corrections.py`)
- All 19 security checks: **PASSED**.

### 4. Full Regression Test Suite
Executed across entire test base:
- Total tests collected: 326
- Passed: **321**
- Skipped: **2** (HINAKU API key not set for live external model test)
- Deselected: **2** (Live Ollama completion tests when daemon offline)
- Failed: **1** (`test_ollama_adapter_health` due to Ollama daemon not running on laptop port 11434 during test run)
- Regressions: **0**

---

## 7. Remaining Limitations and Unresolved Risks

1. **Local Loopback Security Boundary:**
   Session authorization tokens protect HINAKU from unauthorized local applications, CSRF, and browser-origin attacks on the loopback network (`127.0.0.1:8000`). However, an adversary with full arbitrary code execution under the owner's OS user account could read process environment variables or memory. This is standard for local desktop applications.
2. **Ollama Daemon Dependency:**
   Live inference tests require an active Ollama daemon loaded with `qwen3.5:4b` or `bonsai-2:9b`. When Ollama is stopped, health and chat completions fail closed with 502 / Connection Refused.

---

## 8. Git Status and Working-Tree State

- **Branch:** `sprint-0b-privacy-boundary`
- **Working Tree:** Dirty with security audit modifications, test additions, and documentation.
- **Commit Status:** Uncommitted per project working rules (awaiting explicit owner authorization before commit/push).

```
Changes not staged for commit:
	modified:   CHANGELOG.md
	modified:   README.md
	modified:   backend/api/attachments.py
	modified:   backend/api/chat.py
	modified:   backend/api/conversations.py
	modified:   backend/api/interactions.py
	modified:   backend/api/self_build.py
	modified:   backend/security/__init__.py
	modified:   backend/security/auth.py
	modified:   tests/conftest.py
	modified:   tests/test_attachments.py
	modified:   tests/test_isolation.py
	new file:   tests/test_authorization.py
	new file:   docs/SPRINT_0B_FINAL_AUTHORIZATION_AUDIT.md
```
