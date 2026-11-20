# HINAKU — Phase 1 Master Implementation Plan
## Foundation for Independent Intelligence

**Project:** HINAKU (ヒナク) — Personal AI Assistant  
**Phase:** Phase 1 — Foundation for Independent Intelligence  
**Authoritative Base Commit:** `98aab84` (`origin/main`)  
**Working Branch:** `phase-1-intelligence-foundation`  
**Target Hardware:** HP V15 Laptop (AMD Ryzen 7, NVIDIA GeForce RTX 4050 6GB VRAM, Windows 11)  
**Primary Principle:** *Language models are tools used by HINAKU, not HINAKU itself. Identity, memory, knowledge, decisions, and development remain model-independent.*

---

## 1. Current Architecture Understanding

HINAKU is an owner-dedicated, local-first personal assistant. Its existing runtime architecture operates as a FastAPI backend bound strictly to `127.0.0.1`, wrapped by a PyWebView desktop shell.

```
[ Desktop User Interface (PyWebView + vanilla JS) ]
                     │ (Loopback HTTP + X-Hinaku-Token)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI Application Boundary (main.py)                      │
│ - Strict Loopback CORS & require_session_auth               │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Pre-Model Hard Guards (guards.py)                           │
│ - Sensitive Data Guard: regex check, refusal & redaction    │
│ - Live Data Guard: prices, weather, scores refusal          │
│ - System Clock Context: real-time local timestamp           │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Router & Outbound Privacy Boundary                          │
│ - ModelRouter (router.py): auto/local/api decision          │
│ - Chat History Scan: forces local if personal context exists│
│ - OutboundPrivacyGate (privacy_gate.py): fail-closed pre-   │
│   socket payload validator before external network egress   │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
          ┌────────────────┴────────────────┐
          ▼                                 ▼
┌───────────────────────┐       ┌───────────────────────┐
│ Local Model Adapter   │       │ Cloud API Adapter     │
│ - Ollama (default:    │       │ - OpenAI-compatible / │
│   bonsai-2:9b / 4B)   │       │   Anthropic Messages  │
│ - Context budget: 8k  │       │ - Stripped personal   │
│ - Memory Injection    │       │   data & no attachments│
└──────────┬────────────┘       └───────────┬───────────┘
           └────────────────┬───────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Post-Response Pipeline                                      │
│ - Verification Engine: stylistic grounding, fact checks     │
│ - Interaction Logging: data/hinaku.db                       │
│ - Background Memory Extraction (Local Ollama only)          │
│ - 6-Month Self-Build Coordinator & QLoRA Preflight          │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Existing Implementations Relevant to Phase 1

The repository already possesses verified infrastructure that directly serves as the baseline for Phase 1. Before designing any new component, the actual implementation was verified:

### Authoritative Test Baseline (Merged `main` Commit `98aab84`)
- **Total Test Items Collected:** 351
- **Passed:** 350 passed (100% of executable tests)
- **Skipped:** 1 skipped (`tests/test_step4.py::test_optional_live_api`, skipped by design when third-party API key is absent)
- **Failed:** 0
- **Integrity Rule:** All existing tests and assertions must be strictly preserved throughout Phase 1. No tests may be weakened, deleted, or silently disabled.

| Existing Module | Verified Implementation & Configuration | Relevance to Phase 1 | Status |
|---|---|---|:---:|
| `backend/security/auth.py` | `SessionTokenManager`, `InternalTokenManager`, `InternalScope`, `assert_owner_session_required` | Baseline for desktop session auth, background tokens, and anti-autonomy guards | **Already Implemented** |
| `backend/models/privacy_gate.py` | `OutboundPrivacyGate` with fail-closed schema & role inspection | Ensures multi-step reasoning never leaks sensitive data to external APIs | **Already Implemented** |
| `backend/models/router.py` | Heuristic router with conversation history scan & fallback blocking | Starting point for the Model Orchestrator | **Partially Implemented** |
| `backend/memory/storage.py` | SQLite `memories` table + ChromaDB collection (`qwen3-embedding:0.6b`, 1024 dims) | Base storage for the expanded Knowledge Architecture | **Partially Implemented** |
| `backend/memory/extractor.py` | Local Ollama extraction of durable owner facts | Prototype for extracting project & decision knowledge | **Partially Implemented** |
| `backend/history.py` | SQLite interaction logging, conversation CRUD, metadata JSON | Foundation for task state and audit ledgers | **Already Implemented** |
| `backend/attachments/` | Multi-format parser (PDF, DOCX, TXT, HTML), vector indexing & citations | Ingestion subsystem for Project Intelligence files | **Already Implemented** |
| `backend/scheduler/activity.py` | Windows `GetLastInputInfo` user idle & battery state detection | Resource gating for background cognitive tasks | **Already Implemented** |
| `backend/training/` | QLoRA trainer, preflight VRAM check, Golden Set evaluation harness | Core for future controlled self-improvement workflows | **Already Implemented** |

---

## 3. Existing Functionality That Must Be Reused

To preserve stability and avoid unnecessary complexity:
1. **SQLite (`data/hinaku.db`) as Primary Relational Store:** Do not introduce external graph databases (e.g., Neo4j) or separate database server daemons (e.g., PostgreSQL). SQLite supports relational integrity, foreign keys, JSON columns, and indexed relationship edge tables with zero runtime overhead.
2. **ChromaDB (`data/chroma/`) as Vector Store:** Reuse ChromaDB with `qwen3-embedding:0.6b` (1024 dimensions) for semantic retrieval across projects, decisions, and documentation.
3. **`require_session_auth` & `InternalTokenManager`:** Reuse the completed Sprint 0B authorization boundary. Any new intelligence API routes must plug into `Depends(require_session_auth)`.
4. **`OutboundPrivacyGate`:** Multi-model and reasoning orchestration must pipe all outbound candidates through `OutboundPrivacyGate.verify_outbound_payload()`.
5. **Existing Attachment Ingestion:** Project Intelligence must ingest repository files and architectural specifications through the existing chunking, caching, and citation pipelines in `backend/attachments/`.

---

## 4. Intelligence Core Architecture

The Intelligence Core decouples HINAKU's cognitive operations from any single LLM. It consists of six coordinated components implemented as clean, modular Python subsystems within `backend/intelligence/`.

To avoid unnecessary abstractions, empty interfaces, and premature microservices:
- Each component is an in-process Python module with concrete, practical responsibilities.
- Shared state is passed via a unified dataclass (`IntelligenceContext`).
- **IntelligenceContext Security Boundary:**
  - `IntelligenceContext` must **never** store session tokens, authentication credentials, or reusable authorization secrets.
  - Authentication and authorization remain exclusively within the existing security layer (`backend/security/auth.py`).
  - `IntelligenceContext` holds only safe contextual metadata: an authorized actor identifier (`actor_id`), active project identifier (`active_project_id`), permitted knowledge domains (`permitted_domains`), and validated operation constraints (`operation_constraints`).
  - It is strictly a context container and must **never** become an authorization mechanism or bypass channel.
- Components communicate via clean method calls, not network protocols or distributed message queues.

```
                 ┌────────────────────────────────────────────────────────┐
                 │                   INTELLIGENCE CORE                    │
                 │                                                        │
                 │   ┌────────────────────────────────────────────────┐   │
                 │   │            1. REASONING ENGINE                 │   │
                 │   │  - Intent decomposition   - Assumptions & unk. │   │
                 │   │  - Hypothesis comparison  - Synthesis          │   │
                 │   └──────┬───────────────┬───────────────┬─────────┘   │
                 │          │               │               │             │
                 │          ▼               ▼               ▼             │
                 │   ┌──────────────┐┌──────────────┐┌──────────────┐     │
                 │   │  2. DECISION ││ 3. PLANNING  ││  4. MEMORY   │     │
                 │   │    ENGINE    ││    ENGINE    ││    ENGINE    │     │
                 │   │  - Risks     ││  - DAG Tasks ││  - Context   │     │
                 │   │  - Options   ││  - State     ││  - Provenance│     │
                 │   │  - Confidence││  - Queue     ││  - Knowledge │     │
                 │   └──────┬───────┘└──────┬───────┘└──────┬───────┘     │
                 │          │               │               │             │
                 │          └───────────────┼───────────────┘             │
                 │                          ▼                             │
                 │   ┌────────────────────────────────────────────────┐   │
                 │   │            5. MODEL ORCHESTRATOR               │   │
                 │   │  - Capability matching   - Latency/Cost trade  │   │
                 │   │  - Selective multi-eval  - Failover & recovery │   │
                 │   └──────────────────────┬─────────────────────────┘   │
                 │                          ▼                             │
                 │   ┌────────────────────────────────────────────────┐   │
                 │   │             6. LEARNING ENGINE                 │   │
                 │   │  - Outcome analysis      - Weakness catalog    │   │
                 │   │  - Experience records    - Improvement proposal│   │
                 │   └────────────────────────────────────────────────┘   │
                 └────────────────────────────────────────────────────────┘
```

---

## 5. Component Responsibilities and Concrete Interfaces

### A. Reasoning Engine (`backend/intelligence/reasoning/`)
- **Practical Responsibilities:**
  - Decompose multi-step queries into structured sub-problems.
  - Formulate explicit hypotheses, assumptions, and unknown variables.
  - Determine whether external information or owner clarification is required.
  - Synthesize intermediate findings into clear, direct answers adhering to the Persona trait: short sentences, dry wit, no filler.
- **Reasoning Transparency Rule:**
  - Progress updates provide useful progress summaries, task status, important assumptions, decisions, and findings.
  - Raw private chain-of-thought traces, model scratchpads, or private prompts are **never** exposed in logs or user-facing messages.
- **Interface:**
  ```python
  class ReasoningEngine:
      async def analyze_request(self, prompt: str, context: IntelligenceContext) -> ReasoningPlan: ...
      async def synthesize_conclusion(self, steps: List[ReasoningStep]) -> ReasoningResult: ...
  ```

### B. Memory Engine (`backend/intelligence/memory/`)
- **Practical Responsibilities:**
  - Maintain knowledge across multiple distinct domains (Personal, Project, General, Decisions).
  - Track knowledge provenance across three orthogonal axes: Authority, Confidence, and Implementation Status.
  - Detect and resolve contradictory facts (new information supersedes outdated facts with an immutable audit trail).
- **Interface:**
  ```python
  class MemoryEngine:
      async def retrieve_context(self, query: str, domains: List[KnowledgeDomain], project_id: Optional[str] = None) -> ContextBundle: ...
      async def record_knowledge(self, item: KnowledgeItem, provenance: KnowledgeProvenance) -> RecordResult: ...
  ```

### C. Planning Engine (`backend/intelligence/planning/`)
- **Practical Responsibilities:**
  - Convert abstract goals into directed acyclic graphs (DAGs) of executable tasks.
  - Identify blocking dependencies, estimated resource requirements, and parallelizable work.
  - Checkpoint and preserve task execution state across application restarts.
- **Interface:**
  ```python
  class PlanningEngine:
      def create_plan(self, objective: str, constraints: Dict[str, Any]) -> TaskDAG: ...
      def update_plan_progress(self, task_id: str, status: TaskStatus, output: Any) -> PlanState: ...
  ```

### D. Decision Engine (`backend/intelligence/decision/`)
- **Practical Responsibilities:**
  - Systematically evaluate alternatives against owner preferences, hardware limits, and risks.
  - Quantify uncertainty (distinguishing verified facts from assumptions).
  - Respectfully identify poor decisions, explain risks, and suggest better alternatives without arguing after an owner decision is confirmed.
  - Enforce owner-approval gates for the 6 critical action categories.
  - Maintain an append-only `DecisionHistory` ledger.
- **Interface:**
  ```python
  class DecisionEngine:
      def evaluate_decision(self, proposition: Proposition, context: IntelligenceContext) -> DecisionEvaluation: ...
      def record_outcome(self, decision_id: str, outcome: OutcomeRecord) -> None: ...
  ```

### E. Learning Engine (`backend/intelligence/learning/`)
- **Practical Responsibilities:**
  - Ingest feedback signals (thumbs up/down, user corrections, model regenerations).
  - Maintain a catalog of recurring weaknesses and failed approaches.
  - Generate structured improvement proposals for the 6-month self-build cycle.
- **Interface:**
  ```python
  class LearningEngine:
      def log_experience(self, experience: ExperienceRecord) -> None: ...
      def generate_improvement_proposal(self) -> Optional[ImprovementProposal]: ...
  ```

### F. Model Orchestrator (`backend/intelligence/orchestration/`)
- **Practical Responsibilities:**
  - Select models dynamically based on active configuration (`config/settings.yaml`), live daemon availability (Ollama `/api/tags` and `/api/ps`), measured hardware state, privacy rules, and task needs.
  - Never rely on hardcoded model names or unverified performance assumptions.
  - Execute selective multi-model verification only when elevated uncertainty warrants it.
- **Interface:**
  ```python
  class ModelOrchestrator:
      async def execute_task(self, task: CognitiveTask, privacy_constraints: PrivacyConstraints) -> TaskResult: ...
  ```

---

## 6. Project Intelligence Design

Project Intelligence operates as a separate knowledge domain from personal owner memories.

### Schema & Entity Structure (`data/hinaku.db`)
```sql
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    purpose TEXT,
    tech_stack TEXT, -- JSON array of technologies
    confidentiality TEXT NOT NULL DEFAULT 'local_only', -- 'local_only' (default) | 'external_api_allowed'
    status TEXT NOT NULL DEFAULT 'active', -- 'active' | 'archived' | 'deleted'
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS project_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    alternatives TEXT, -- JSON array
    authority TEXT NOT NULL, -- 'owner_directive' | 'assistant_suggestion' | 'external_source'
    confidence REAL NOT NULL DEFAULT 1.0, -- 0.0 to 1.0
    status TEXT NOT NULL, -- 'proposed' | 'accepted' | 'in_progress' | 'implemented' | 'verified'
    implementation_evidence TEXT, -- JSON record of verified tests, file hashes, or commit SHAs
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id)
    -- Intentionally NO CASCADE: Preserves audit history if a project is soft-deleted
);

CREATE TABLE IF NOT EXISTS project_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL, -- 'pending' | 'in_progress' | 'completed' | 'blocked'
    priority INTEGER DEFAULT 1,
    dependencies TEXT, -- JSON array of task_ids
    created_at REAL NOT NULL,
    completed_at REAL,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS project_context_links (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    link_type TEXT NOT NULL, -- 'discussion' | 'implementation' | 'debugging'
    linked_at REAL NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);
```

### Project Data Privacy Rules
1. **Dedicated Privacy Classification:** Every project carries an explicit `confidentiality` setting (`local_only` vs `external_api_allowed`).
2. **No Egress Based on Chat Mode Alone:** Project information is **never** sent to an external API simply because a conversation is marked public. If a project is classified as `local_only`, all queries involving that project are locked to local models.
3. **Owner Authorization for External Routing:** Egress of project data requires both that the conversation is public and that the project is explicitly configured as `external_api_allowed` with owner consent.

### Project Deletion & Historical Integrity
1. **Approval-Gated Deletion:** Project deletion is a critical operation requiring explicit owner authorization via `assert_owner_session_required("delete_project", ...)`.
2. **No Cascading Destruction:** Tables use explicit foreign keys without `ON DELETE CASCADE`.
3. **Soft-Delete & Audit Preservation:** When a project is removed, its status transitions to `archived` or `deleted`. Decision records, lessons learned, and experience logs are preserved to maintain the repository's long-term intelligence memory.

### Knowledge Provenance Architecture
Knowledge provenance is explicitly separated into four independent, orthogonal properties:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                 KNOWLEDGE PROVENANCE                                    │
├─────────────────────────┬────────────────────────┬─────────────────────┬────────────────┤
│   1. SOURCE AUTHORITY   │  2. CLAIM CONFIDENCE   │ 3. VERIFICATION     │ 4. EVIDENCE    │
├─────────────────────────┼────────────────────────┼─────────────────────┼────────────────┤
│ • owner_directive       │ Continuous range       │ • proposed          │ Concrete proof │
│   (Owner-sourced claim; │ 0.0 to 1.0             │ • accepted          │ (Test names,   │
│   not automatically an  │ (Confidence in this    │   (Accepted choice; │  file paths,   │
│   independently         │  specific claim or     │    NOT implemented) │  hashes, or    │
│   verified fact)        │  assertion itself)     │ • in_progress       │  commit SHAs)  │
│ • assistant_suggestion  │                        │ • implemented       │                │
│   (Working option)      │                        │ • verified          │                │
│ • external_source       │                        │   (Requires actual  │                │
│   (Documentation/code)  │                        │    evidence proof)  │                │
└─────────────────────────┴────────────────────────┴─────────────────────┴────────────────┘
```

- **Source Authority:** Tracks origin (`owner_directive`, `assistant_suggestion`, `external_source`). An owner-provided statement is recorded as `owner_directive`, but remains an unverified assertion until evidence confirms it.
- **Claim Confidence:** Defined strictly as confidence in a specific knowledge claim or assertion (`0.0` to `1.0`), evaluated independently of who stated it or whether it has been implemented.
- **Verification Status:** Represents life-cycle progression (`proposed`, `accepted`, `in_progress`, `implemented`, `verified`). An accepted assistant suggestion is an accepted decision (`status: 'accepted'`), not an implemented change.
- **Implementation Evidence:** Implementation status (`implemented` or `verified`) strictly requires concrete implementation evidence (passing test logs, verified file existence, or commit SHAs). Without evidence, implementation status cannot be claimed.

---

## 7. Memory and Knowledge Architecture

### Four Isolated Knowledge Domains
1. **Personal Memory (`owner_memories`):** Personal owner facts, habits, communication preferences. Strictly local; unconditionally prohibited from outbound API egress.
2. **Project Intelligence (`project_*`):** Architecture, technology stack, requirements, decisions. Subject to project confidentiality classification.
3. **General Knowledge & Research (`documents`):** Extracted documentation and reference materials ingested via `backend/attachments/`.
4. **Decision & Experience Records (`decision_history`):** Append-only audit ledger of choices, trade-offs, and outcomes.

### Hybrid Storage Model (Relational + Semantic Graph)
- **Relational Integrity (SQLite):** Explicit entities with foreign keys, timestamps, and confidence scores.
- **Semantic Retrieval (ChromaDB):** Domain-segregated collections (`hinaku_personal_memory`, `hinaku_project_memory`, `hinaku_documents`).
- **Graph Associations (SQLite `knowledge_edges`):**
  ```sql
  CREATE TABLE IF NOT EXISTS knowledge_edges (
      id TEXT PRIMARY KEY,
      source_id TEXT NOT NULL,
      source_domain TEXT NOT NULL,
      target_id TEXT NOT NULL,
      target_domain TEXT NOT NULL,
      relationship TEXT NOT NULL, -- 'depends_on' | 'implements' | 'supersedes' | 'contradicts'
      weight REAL NOT NULL DEFAULT 1.0,
      created_at REAL NOT NULL
  );
  ```
  Provides relationship graph traversal without introducing an external graph database.

---

## 8. Decision and Planning Architecture

### Uncertainty Management Matrix
Every cognitive proposal or reasoning step evaluates four categories:
- **Known Facts:** Grounded directly in verified knowledge or owner input.
- **Assumptions:** Working inferences required to proceed. Flagged explicitly to the owner when risk is non-trivial.
- **Unknowns:** Missing variables that prevent high-confidence execution. Triggers inquiry if critical.
- **Conflicts:** Inconsistencies between past and present data. Requires explicit reconciliation.

### Decision System & Respectful Disagreement
- HINAKU must not automatically agree with every owner proposal.
- It respectfully identifies poor decisions, explains trade-offs and risks, and suggests better alternatives when justified.
- It does not manipulate the owner or repeatedly argue once the owner makes a confirmed decision.

---

## 9. Adaptive Model Orchestration

### Model Selection Criteria
The Model Orchestrator resolves model selection without hardcoded assumptions:
1. **Configuration Inspection:** Reads active settings from `config/settings.yaml` (`default_local_model: bonsai-2:9b`, `allowed_local_models`, `api_provider`, `api_model`).
2. **Runtime Daemon Probe:** Queries Ollama API (`/api/tags` and `/api/ps`) to determine which models are currently installed and loaded in VRAM.
3. **Hardware Capacity Awareness:** Respects the 6GB VRAM ceiling on the RTX 4050. Enforces sequential execution for multi-model verification to prevent Out-Of-Memory crashes.
4. **Task Needs Matching:** Matches task requirements (code generation, concise extraction, architectural planning) to verified model capabilities.
5. **Privacy Gate Enforcement:** All candidates pass through `OutboundPrivacyGate.verify_outbound_payload()`.

---

## 10. Controlled Learning and Self-Improvement

### 10-Step Self-Improvement Lifecycle
1. **Weakness Identification:** Interaction feedback logging detects repeated user edits or thumbs-down ratings.
2. **Cataloging:** Issue cataloged in `experience_records` with error type and failure mode.
3. **Research:** Analyze past successful turns or similar domain examples.
4. **Proposal:** Generate a formal improvement proposal (`data/improvements/YYYY-MM-DD_<id>.json`).
5. **Isolated Workspace:** Prepare test cases in a temporary sandbox branch.
6. **Execution:** Run automated regression suites and evaluation harness (`eval/golden.jsonl`).
7. **Evaluation:** Candidate is evaluated against task-specific benchmarks, golden test sets, and regression suites. Evaluation criteria must be measurable and objective; arbitrary mandatory percentage thresholds (e.g., +2%) are not enforced. Zero unacceptable regressions across existing passing tests are permitted. No unauthorized production modifications are allowed.
8. **Candidate Release:** Package promoted weights or prompt modifications.
9. **Owner Presentation:** Present side-by-side comparison report in desktop UI.
10. **Deployment:** Applied **only** after explicit owner confirmation.

### Inviolable Safety Boundaries
Learning mechanisms can **never** modify:
- Core identity or persona boundaries (`config/hinaku_persona.md`).
- Security policies, authorization dependencies, or privacy gates.
- Autonomy constraints or the 6 critical approval categories.

---

## 11. Security and Database Reliability

### The Six Critical Owner-Approval Actions
The following operations unconditionally halt and demand direct owner confirmation via `assert_owner_session_required()`:
1. **File Modification & Deletion:** Outside of isolated cache/temp data directories.
2. **Financial Transactions & Purchases:** Unconditionally forbidden.
3. **External Communications:** Zero network requests outside explicitly configured LLM API endpoints.
4. **System Operations & Software Installation:** No arbitrary OS shell execution.
5. **Security & Identity Configuration:** Modification of tokens, keys, passwords, or permissions.
6. **Self-Modification of Core Code:** Modification of backend production code or guardrails.

### Background Authorization Hardening
- Background services (`backend/scheduler/service.py`, `backend/models/prewarm.py`, background planning/memory tasks) must obtain scoped internal tokens (`InternalTokenManager.issue_token(scope)`).
- Internal operations validate their scope via `validate_internal_scope(token, required_scope)`.
- Internal tokens are explicitly rejected at the HTTP API layer (`require_session_auth`) and cannot execute `CRITICAL_OWNER_ACTIONS`.

### Database Reliability & Recovery Procedures
SQLite WAL mode improves concurrency, but does not eliminate corruption. The system implements:
1. **Strict Transactional Boundaries:** All state changes execute within explicit `BEGIN IMMEDIATE` / `COMMIT` blocks with automatic `ROLLBACK` on error.
2. **Automated Backups:** Scheduled invocation of the SQLite Online Backup API (`sqlite3.Connection.backup`) to create timestamped database snapshots in `data/backups/`.
3. **Startup Integrity Checks:** Runs `PRAGMA integrity_check;` on startup before accepting API requests.
4. **Disaster Recovery:** If corruption is detected, the database automatically halts safely and alerts the owner with a safe restore path from the latest verified backup.

---

## 12. Phase 1 Milestone Breakdown

The seven-milestone sequence is maintained:

```
[ Milestone 1: Intelligence Architecture Foundation ]
                        │
                        ▼
[ Milestone 2: Project Intelligence Foundation ]
                        │
                        ▼
[ Milestone 3: Memory & Knowledge Architecture ]
                        │
                        ▼
[ Milestone 4: Decision & Planning Foundation ]
                        │
                        ▼
[ Milestone 5: Adaptive Model Orchestration ]
                        │
                        ▼
[ Milestone 6: Controlled Learning Foundation ]
                        │
                        ▼
[ Milestone 7: Integration, Desktop UI & Hardening ]
```

### Milestone Overviews

#### Milestone 1 — Intelligence Architecture Foundation
- **Objective:** Establish the foundational data contracts, shared context objects, error hierarchies, and component interfaces in `backend/intelligence/` without breaking existing functionality.
- **Repository Additions:**
  - `backend/intelligence/__init__.py`
  - `backend/intelligence/types.py` (concrete enums, provenance dataclasses, cognitive task models)
  - `backend/intelligence/context.py` (`IntelligenceContext` supporting multi-domain state)
  - `backend/intelligence/errors.py` (intelligence exception hierarchy)
  - `tests/test_intelligence_foundation.py`

#### Milestone 2 — Project Intelligence Foundation
- **Objective:** Implement project tracking, project confidentiality controls, and decision ledgers with strict provenance separation.
- **Repository Additions:** `backend/intelligence/projects/`, database migration for `projects` and `project_decisions`, API endpoints in `backend/api/projects.py`.

#### Milestone 3 — Memory and Knowledge Architecture
- **Objective:** Implement domain-isolated memory retrieval, `knowledge_edges` relationship mapping, and contradiction handling.
- **Repository Additions:** `backend/memory/domain_router.py`, `backend/memory/knowledge_graph.py`.

#### Milestone 4 — Decision and Planning Foundation
- **Objective:** Implement uncertainty management, risk assessment, append-only decision ledgers, and DAG task planning.
- **Repository Additions:** `backend/intelligence/decision/`, `backend/intelligence/planning/`, database migrations for `project_tasks` and `decision_history`.

#### Milestone 5 — Adaptive Model Orchestration
- **Objective:** Implement runtime model discovery, hardware-aware latency budgets, task capability matching, and selective dual-model verification.
- **Repository Additions:** `backend/intelligence/orchestration/`, refactored `backend/models/router.py`.

#### Milestone 6 — Controlled Learning Foundation
- **Objective:** Implement experience logging from feedback, weakness cataloging, and isolated candidate improvement evaluation workflows.
- **Repository Additions:** `backend/intelligence/learning/`, `backend/training/experience.py`.

#### Milestone 7 — Integration, Desktop UI & Hardening
- **Objective:** Connect the Intelligence Core into `/api/chat`, build desktop project and task drawers in `ui/app.js`, and verify loopback reliability.
- **Repository Additions:** `backend/api/chat.py`, `ui/app.js`, `ui/index.html`.

---

## 13. Acceptance Criteria (Functional & Measurable)

Acceptance criteria are strictly tied to functional correctness, security verification, and regression prevention rather than arbitrary test counts:

- **Milestone 1:**
  - 100% of new unit tests in `tests/test_intelligence_foundation.py` pass.
  - Zero regressions across all 350 existing tests.
  - Context serialization and deserialization cleanly handles all domain types.
  - Provenance tiers enforce separation between authority, confidence, and implementation status.
- **Milestone 2:**
  - Projects and decisions persist in SQLite with strict foreign keys and soft-delete protection.
  - Project confidentiality (`local_only`) strictly prevents outbound API egress in privacy gate tests.
  - Accepted assistant suggestions are verified to remain in `status: 'accepted'` until concrete implementation proof is provided.
- **Milestone 3:**
  - Domain isolation verified: personal memories never leak into project contexts.
  - Contradiction handling logs superseding facts while preserving historical provenance.
- **Milestone 4:**
  - Anti-autonomy guards trigger on 100% of critical action attempts without owner desktop session.
  - Task execution state serializes, survives simulated process restarts, and resumes cleanly.
- **Milestone 5:**
  - Orchestrator queries live Ollama API and selects installed models without hardcoded assumptions.
  - Sequential execution pattern prevents RTX 4050 VRAM exhaustion during dual-model verification.
- **Milestone 6:**
  - User edits and feedback generate structured experience records.
  - Refusal to modify core persona, security policies, or permissions during self-improvement is verified.
- **Milestone 7:**
  - Desktop UI renders project and task drawers without console errors.
  - Startup `PRAGMA integrity_check;` and transactional backup procedures pass cleanly.

---

## 14. Revised Milestone 1: Scope & Acceptance Criteria

### Scope of Milestone 1
Milestone 1 builds the foundational data contracts and interfaces for the Intelligence Core in a self-contained package (`backend/intelligence/`). It does not modify existing chat behavior or API routes, ensuring zero risk of regression:

1. **`backend/intelligence/types.py`:**
   - `KnowledgeDomain` enum: `PERSONAL`, `PROJECT`, `GENERAL`, `DECISION`.
   - `SourceAuthority` enum: `OWNER_DIRECTIVE`, `ASSISTANT_SUGGESTION`, `EXTERNAL_SOURCE`.
   - `ImplementationStatus` enum: `PROPOSED`, `ACCEPTED`, `IN_PROGRESS`, `IMPLEMENTED`, `VERIFIED`.
   - `KnowledgeProvenance` dataclass: Separating `authority`, `confidence` (`0.0`–`1.0`), `status`, and `evidence`.
   - `CognitiveTask` & `TaskPriority` dataclasses.
   - `ReasoningStep` & `ReasoningResult` dataclasses.
2. **`backend/intelligence/context.py`:**
   - `IntelligenceContext`: Shared container carrying actor identifier (`actor_id`), conversation context, active project ID, permitted knowledge domains, and validated operation constraints. Strictly contains no session tokens, passwords, or authentication credentials.
3. **`backend/intelligence/errors.py`:**
   - `IntelligenceError`, `ProvenanceError`, `DomainIsolationViolation`, `UncertaintyThresholdExceeded`.
4. **`backend/intelligence/__init__.py`:**
   - Clean module exports.
5. **`tests/test_intelligence_foundation.py`:**
   - Comprehensive test suite validating context creation, provenance separation, immutability rules, and serialization.

### Milestone 1 Acceptance Criteria
1. **Functional Integrity:**
   - All tests in `tests/test_intelligence_foundation.py` pass.
   - Provenance models enforce that an owner directive is stored with `authority=OWNER_DIRECTIVE`, but cannot have `status=IMPLEMENTED` without concrete evidence.
   - `IntelligenceContext` enforces domain boundary flags (e.g., forbidding `PERSONAL` domain when context is flagged for external evaluation).
2. **Zero Regression:**
   - All 350 existing tests across the repository pass without modification.
3. **No Breaking Changes:**
   - Zero modifications to existing database tables, API routes, or UI components.

---

*(Revised plan complete. Awaiting explicit owner authorization before beginning Milestone 1 implementation.)*
