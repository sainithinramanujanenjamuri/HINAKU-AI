# SPRINT 0B: Outbound Privacy Boundary Audit & Implementation Report

> **Project:** HINAKU (ヒナク) — Personal AI Assistant  
> **Date:** November 2026  
> **Author:** Senior Software Engineer (HINAKU Core Team)  
> **Status:** Completed & Verified (15 of 15 Scenarios Passed, 270 Regression Tests Passing)  
> **Branch:** `sprint-0b-privacy-boundary`  
> **Target Environment:** HP V15 Laptop (AMD Ryzen 7, NVIDIA GeForce RTX 4050 6 GB VRAM, Windows 11, Python 3.11+)

---

## 1. Executive Summary

Under **Sprint 0B**, a comprehensive audit was executed across all components where conversation data could potentially egress to external third-party API providers (OpenRouter, OpenAI, Anthropic). 

Prior to this sprint, the model router evaluated prompt tokens and classified requests into local or API backends. However, **no final privacy inspection gate guarded the egress socket immediately before transmission**. As a consequence, several severe privacy leak vectors existed:
- Multi-turn conversation history containing earlier sensitive health, financial, or personal statements could be transmitted to external APIs if a subsequent turn asked a technical or coding query.
- Local model failures could fall back to external APIs even when the user prompt contained personal statements.
- Explicit API model selection or `api_only` mode bypassed personal statement detection.
- Untrusted origins could issue cross-origin requests to local API endpoints due to permissive wildcard CORS.

To resolve these vulnerabilities, we designed and implemented a **Final Outbound Privacy Gate** (`OutboundPrivacyGate` in `backend/models/privacy_gate.py`), embedded directly into both `ApiAdapter.stream_chat` (the physical egress boundary) and `ModelRouter` (the routing/fallback engine), backed by a tightened CORS origin policy in `backend/main.py`.

A new dedicated test suite (`tests/test_privacy_boundary.py`) covering all **15 required security scenarios** was created and executed. All 15 tests passed, and all 270 existing unit and integration tests passed with zero regressions.

---

## 2. Existing Outbound Data Flow (Pre-Audit)

Prior to Sprint 0B, the end-to-end chat data flow operated as follows:

```
[User Message] 
      │
      ▼
[chat_endpoint] (/api/chat)
      │
      ├─► Sensitive Topic Guard (sets is_private = True in SQLite if detected)
      ├─► Sensitive Data Guard (redacts PINs/Cards to [removed])
      ├─► ModelRouter.decide_backend(latest_user_text)
      │         │
      │         ▼
      │   Evaluates: is_private, is_personal_statement(latest_user_text)
      │   Returns: RouterDecision(target_backend, target_model, fallback_allowed)
      │
      ├─► MemoryManager.retrieve_context(..., send_personal_context=False if is_api)
      ├─► AttachmentManager.get_document_prompt_context(...)
      │
      ├─► Assembles trimmed_messages: [System Prompt] + [Prior Conversation History] + [Latest User Turn]
      │
      ▼
[ModelRouter.stream_chat(trimmed_messages)]
      │
      ├── If active_backend == "api":
      │         │
      │         ▼
      │   [ApiAdapter.stream_chat(trimmed_messages)] ──► [HTTP POST to external base_url]
      │
      └── If local fails and fallback_allowed == True:
                │
                ▼
          [ApiAdapter.stream_chat(trimmed_messages)] ──► [HTTP POST to external base_url]
```

---

## 3. Identified Privacy Risks & Vulnerabilities

During the line-by-line audit, four major security vulnerabilities were identified:

### Risk 1: Multi-Turn Conversation History Leaks to API (Critical)
- **Vulnerability:** `ModelRouter.decide_backend()` only evaluated `latest_user_text`.
- **Attack / Leak Path:** 
  1. In Turn 1, the owner confides sensitive personal details ("I was diagnosed with clinical depression and my salary is 40k").
  2. The assistant responds locally. The conversation history stores this turn.
  3. In Turn 2, the owner asks: "Explain the quicksort algorithm in Python."
  4. The router inspects `latest_user_text`, classifies it as a coding query, and selects the `"api"` backend.
  5. `trimmed_messages` contains the complete prior history including Turn 1.
  6. The complete message list was sent verbatim to OpenRouter/OpenAI/Anthropic, permanently logging the owner's personal health and financial data on external servers.

### Risk 2: Unsafe Fallback to API on Local Failure (High)
- **Vulnerability:** In `ModelRouter.decide_backend()`, when `is_personal_statement(user_prompt)` was classified as `"local"`, line 379 set `fallback_allowed=self.fallback_on_failure` (default: `True`).
- **Attack / Leak Path:** 
  If the local Ollama instance crashed or was busy, `ModelRouter.stream_chat()` caught the exception and executed line 494:
  `if active_backend == "local" and decision.fallback_allowed and not is_private and self.api_adapter.api_key:`
  The router then transmitted the personal prompt to the external API!

### Risk 3: Explicit API Selection & API-Only Mode Bypassed Personal Statement Filters (High)
- **Vulnerability:** Lines 266–295 in `router.py` routed directly to API when `requested_model == self.api_adapter.model` or `mode == "api_only"` without checking whether `user_prompt` or conversation history contained personal facts.

### Risk 4: Direct Adapter Invocation & Lack of Last-Line Defense (Medium)
- **Vulnerability:** `ApiAdapter.stream_chat` did not independently verify the privacy state of payloads. Any code path or future module invoking `api_adapter` directly would transmit without inspection.

### Risk 5: Overly Permissive CORS (Medium)
- **Vulnerability:** `backend/main.py` configured `CORSMiddleware` with `allow_origins=["*"]` and `allow_credentials=True`. Any malicious website opened in the owner's web browser could issue cross-origin requests to local memory, settings, or training endpoints.

---

## 4. All API Egress Paths

A repository-wide code search was conducted for network egress calls (`httpx`, `requests`, `urllib.request`, `socket`).

| File | Component | Target Destination | Classification | Privacy Boundary Enforcement |
| :--- | :--- | :--- | :--- | :--- |
| `backend/models/api_adapter.py` | `_stream_openai_compatible` | External API (`https://openrouter.ai/api/v1` or OpenAI) | **External Egress** | **Enforced** (OutboundPrivacyGate) |
| `backend/models/api_adapter.py` | `_stream_anthropic` | External API (`https://api.anthropic.com/v1`) | **External Egress** | **Enforced** (OutboundPrivacyGate) |
| `backend/models/ollama_adapter.py` | `stream_chat` / `check_health` | Loopback (`127.0.0.1:11434`) | Local Only | N/A (Local loopback) |
| `backend/attachments/storage.py` | `_default_embedder` | Loopback (`127.0.0.1:11434/api/embed`) | Local Only | N/A (Local loopback) |
| `backend/memory/storage.py` | `_embed_single` / `_embed_batch` | Loopback (`127.0.0.1:11434/api/embed`) | Local Only | N/A (Local loopback) |
| `backend/models/prewarm.py` | `_warm_llm` / `_warm_embed` | Loopback (`127.0.0.1:11434`) | Local Only | N/A (Local loopback) |

`backend/models/api_adapter.py` is the **sole external egress point** in the entire application.

---

## 5. Final Privacy Policy & Rules

The outbound privacy policy strictly enforces:

1. **Rule 1 — Private Conversation Isolation:** If `is_private == True`, zero bytes leave the machine to external APIs under any mode or fallback.
2. **Rule 2 — Attachment & Document Isolation:** If attachments exist or document citations/markers (`<document_reference>`, `[File:`, `[Section:`, `[Page:`) are present in any turn, the request is restricted to local processing.
3. **Rule 3 — Injected Memory Prohibition:** System prompts must never contain injected owner memories (`[What HINAKU remembers about you]`).
4. **Rule 4 — Complete Message Payload Scanning:** Every turn in `messages` (user, assistant, system) is scanned:
   - Personal statements & owner facts (feelings, health, finances, family, relationships, residence, hardware, preferences).
   - Sensitive topics (mental health, mood, finances, distress, breakup).
   - Sensitive credentials (unredacted PINs, passwords, credit card numbers, bank accounts, government IDs, API keys).
   - If *any* turn fails, the payload is blocked from external transmission.
5. **Rule 5 — Fail Closed:** If payload is malformed, missing, or ambiguous, external transmission is refused immediately.
6. **Rule 6 — Zero Secret Logging:** Log messages capture only sanitized categories and turn indices; sensitive contents and credentials are never written to logs.

---

## 6. Implementation Architecture & Enforcement Locations

### 6.1. Dedicated Privacy Gate (`backend/models/privacy_gate.py`)
- Implemented `OutboundPrivacyGate.inspect_payload(messages, is_private, has_attachments)` returning `PrivacyInspectionResult(is_safe, reason, category, turn_index)`.
- Implemented `OutboundPrivacyGate.verify_outbound_payload(...)` which raises `OutboundPrivacyViolation` if unsafe.

### 6.2. Physical Egress Boundary (`backend/models/api_adapter.py`)
- Inside `ApiAdapter.stream_chat(messages, model, is_private, has_attachments)`:
  `OutboundPrivacyGate.verify_outbound_payload()` is invoked **before** opening any `httpx.AsyncClient` or network socket. Direct adapter calls independently enforce the policy.

### 6.3. Router Defense & Automatic Fallback Protection (`backend/models/router.py`)
- In `ModelRouter.decide_backend()`:
  - Added `has_personal_context` parameter.
  - If prompt or history contains personal statements or sensitive topics: target `"local"`, `fallback_allowed = False` (even under `api_only` mode or explicit API selection).
- In `ModelRouter.stream_chat()`:
  - Pre-flight check before API call: if payload fails privacy gate, router automatically diverts execution to `"local"`.
  - Fallback from local to API: if local Ollama fails, API fallback is **blocked** if the payload contains any private or personal content, failing closed with a clear error.

### 6.4. Chat Endpoint Integration (`backend/api/chat.py`)
- `chat_endpoint` scans `messages_to_trim` for personal history and passes `has_personal_context` to `decide_backend()`.
- Passes `is_private` and `has_attachments` into `stream_chat()`.

### 6.5. Deliberate CORS Policy (`backend/main.py`)
- Replaced wildcard `allow_origins=["*"]` with:
  - Allowed local origins: `http://127.0.0.1:8000`, `http://localhost:8000`, `http://127.0.0.1:5173`, `http://localhost:5173`, `pywebview://localhost`, `app://localhost`, `null`.
  - Allowed origin regex: `^https?://(127\.0\.0\.1|localhost)(:\d+)?$`.
  - Allowed methods: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`.

---

## 7. Verification & Test Execution Matrix

A comprehensive test suite (`tests/test_privacy_boundary.py`) was implemented and executed covering the 15 required scenarios. All adapters are mocked; zero external requests were made.

| # | Scenario Tested | Policy Expected | Verification Result |
| :-: | :--- | :--- | :---: |
| 1 | Private conversation in auto routing mode | Stays local, API adapter never invoked | **PASSED** |
| 2 | Private conversation in API-only mode | Stays local, API adapter never invoked | **PASSED** |
| 3 | Private conversation with explicit API model selection | Stays local, API adapter never invoked | **PASSED** |
| 4 | Personal information in latest message | Stays local across all modes, fallback prohibited | **PASSED** |
| 5 | Personal information in earlier conversation history | Prior turn personal data blocks subsequent coding query from API | **PASSED** |
| 6 | Mixed personal and non-personal conversation history | Multi-turn dialogue with mixed personal statements stays local | **PASSED** |
| 7 | Follow-up messages after personal discussions | Follow-ups after personal turns stay strictly local | **PASSED** |
| 8 | Attachments and extracted document content | Document content restricted to local processing | **PASSED** |
| 9 | Automatically triggered private mode | Sensitive topic triggers private mode and blocks API | **PASSED** |
| 10 | Private-mode transitions and undo behavior | Untoggling private mode does not leak earlier personal history | **PASSED** |
| 11 | API failure and local fallback | Safe technical query safely falls back to local on API outage | **PASSED** |
| 12 | Local failure and API fallback | Unsafe fallback blocked on personal data; safe query falls back | **PASSED** |
| 13 | Short-follow-up router stickiness | Sticky follow-ups never leak personal history to API | **PASSED** |
| 14 | Retry and regeneration paths | Retries and regenerations enforce privacy gate | **PASSED** |
| 15 | Direct API adapter invocation | `api_adapter.stream_chat` independently raises `OutboundPrivacyViolation` | **PASSED** |

### Regression Suite Results
- `pytest tests/test_privacy_boundary.py`: **15 passed** in 4.23s.
- `pytest tests/`: **270 passed**, 1 skipped, 3 deselected (offline local Ollama tests) in 130.99s. Zero regressions.

---

## 8. Remaining Risks & Mitigations

1. **User Deliberately Obfuscating Personal Data:**
   - *Risk:* If an owner uses non-standard ciphers, uncommon slang, or foreign languages to state personal facts in a non-private chat, regex heuristics might not classify it as personal.
   - *Mitigation:* The owner can set the conversation to **Private** (`is_private = True`) before or during the chat, which provides an unconditional guarantee that no data leaves the machine.
2. **Third-Party API Provider Logging:**
   - *Risk:* Non-personal coding and factual queries routed to API models may be logged by providers according to their data retention policies.
   - *Mitigation:* Documented in `settings.yaml` (`logged_by_provider: true`) and surfaced via backend badge indicator in the UI. For complete zero-logging privacy, the owner can use `local_only` mode.

---

## 9. Rollback Instructions

If any rollback of Sprint 0B is required:
1. All changes are isolated on branch `sprint-0b-privacy-boundary`.
2. To return to the initial state without these changes:
   ```powershell
   git checkout main
   ```
3. To delete the working branch if rejected by the owner:
   ```powershell
   git branch -D sprint-0b-privacy-boundary
   ```
