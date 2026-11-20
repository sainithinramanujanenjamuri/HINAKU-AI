# HINAKU — Phase 1 Milestone 2 Completion & Acceptance Report
**Milestone:** Milestone 2 — Project Intelligence Engine & Repository Grounding  
**Branch:** `phase-1-intelligence-foundation`  
**Date:** November 20, 2026  
**Status:** Completed & Verified  

---

## 1. Executive Summary

Milestone 2 establishes HINAKU's first persistent **Project Intelligence Engine**, enabling HINAKU to understand projects as structured, persistent entities rather than treating project interactions as ephemeral chat history.

All code strictly adheres to the approved architecture and the four core principles:
1. **Domain Boundary Isolation:** Project intelligence resides in `KnowledgeDomain.PROJECT`, completely logically isolated from personal memory (`owner_memories`).
2. **Knowledge Provenance & Grounding:** Decoupled properties for source authority, claim confidence ($0.0 \le c \le 1.0$), verification status, and implementation evidence. Accepted decisions are strictly distinguished from implemented changes.
3. **Repository Grounding & Safety:** Authorized, read-only repository scanning with strict exclusion of credentials, private keys, `.env` files, databases, and version-control internals.
4. **Project Confidentiality & Egress Control:** Projects classified as `CONFIDENTIAL` or `RESTRICTED` enforce strict local-only execution and reject any context retrieval permitting external API transmission.

---

## 2. Files Created and Modified

### Created Source Files
- [`backend/intelligence/project_types.py`](file:///d:/HINAKU-AI/backend/intelligence/project_types.py):
  - Enums: `ProjectStatus` (`PROVISIONAL`, `ACTIVE`, `PAUSED`, `COMPLETED`, `ARCHIVED`), `ProjectConfidentiality` (`INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`), and `KnowledgeCategory` (12 categories: identity, requirements, architecture, decisions, implementation, tasks, etc.).
  - Dataclasses: `ProjectRecord`, `ProjectKnowledgeItem`, `ProjectKnowledgeRevision`, `RepositoryFileIndex`, and `ProjectDiscoveryCandidate`.
- [`backend/intelligence/project_store.py`](file:///d:/HINAKU-AI/backend/intelligence/project_store.py):
  - SQLite persistent storage managing `projects`, `project_knowledge`, `project_knowledge_revisions`, and `project_repo_files`.
  - Enforces duplicate prevention (by ID or case-insensitive name).
  - Enforces non-destructive soft deletion (`deleted=1`) by default, preserving historical records; requires explicit owner confirmation for hard deletion.
  - Automatically records immutable audit revisions in `project_knowledge_revisions` upon every knowledge modification.
- [`backend/intelligence/repo_grounding.py`](file:///d:/HINAKU-AI/backend/intelligence/repo_grounding.py):
  - Read-only repository scanner calculating file sizes, last modified timestamps, and SHA256 content hashes.
  - Excludes secrets, `.git`, `venv`, `node_modules`, `.env*`, `*.db`, `*.pem`, `*.key`.
  - Implements stale-index detection and concrete file evidence generation.
- [`backend/intelligence/project_discovery.py`](file:///d:/HINAKU-AI/backend/intelligence/project_discovery.py):
  - Conversational project inference matching existing projects (by name, ID, tech stack, and purpose keywords) or detecting new candidate declarations.
  - Flags ambiguity and enforces `needs_owner_confirmation = True` before promoting provisional entities.
- [`backend/intelligence/project_engine.py`](file:///d:/HINAKU-AI/backend/intelligence/project_engine.py):
  - Primary service facade unifying project lifecycle, structured knowledge, repository grounding, conversational discovery, and domain-isolated context retrieval.
  - Enforces domain validation (`KnowledgeDomain.PROJECT`) and confidentiality egress gates.
- [`tests/test_project_intelligence.py`](file:///d:/HINAKU-AI/tests/test_project_intelligence.py):
  - 14 comprehensive unit and integration tests covering registration, discovery, provenance invariants, audit revisions, repository grounding, stale detection, and confidentiality barriers.

### Modified Files
- [`backend/intelligence/errors.py`](file:///d:/HINAKU-AI/backend/intelligence/errors.py): Added `ProjectNotFoundError`, `DuplicateProjectError`, `ProjectConfidentialityViolation`, `UnauthorizedRepositoryAccessError`, and `RepositoryAccessViolation`.
- [`backend/intelligence/__init__.py`](file:///d:/HINAKU-AI/backend/intelligence/__init__.py): Exported all Milestone 2 types, models, exceptions, and engine components.
- [`docs/milestone_reports/README.md`](file:///d:/HINAKU-AI/docs/milestone_reports/README.md): Updated index of milestone reports.

---

## 3. Architecture & Data Contracts Implemented

```
+-----------------------------------------------------------------------------------+
|                                  ProjectEngine                                    |
+-----------------------------------------------------------------------------------+
           |                          |                         |
           v                          v                         v
+---------------------+    +--------------------+    +--------------------+
|    ProjectStore     |    |   RepoGrounding    |    |  ProjectDiscovery  |
| - SQLite Tables     |    | - Read-only scan   |    | - Exact/tech match |
| - projects          |    | - SHA256 hashing   |    | - New project flag |
| - project_knowledge |    | - Stale detection  |    | - Confirmation gate|
| - revisions (audit) |    | - Secret exclusion |    +--------------------+
| - project_repo_files|    | - Evidence pointer |
+---------------------+    +--------------------+
```

### Key Architectural Invariants
1. **Decision vs. Implementation Distinction:**
   - Calling `record_decision()` assigns status `ACCEPTED`, never `IMPLEMENTED`.
   - Calling `record_implementation()` strictly requires concrete evidence (e.g. file path, SHA256 hash, line count), raising `ProvenanceError` if evidence is missing.
2. **Immutable Knowledge Revision History:**
   - Any update to a knowledge item appends a full audit snapshot to `project_knowledge_revisions` capturing previous content, new content, reason, actor, and provenance.
3. **Confidentiality & Egress Control:**
   - Context retrieval for `CONFIDENTIAL` or `RESTRICTED` projects actively inspects `operation_constraints`. Attempting to retrieve confidential context when external API routing is permitted raises `ProjectConfidentialityViolation`.
4. **Non-Destructive Deletion:**
   - Project and knowledge deletions are soft deletes by default (`deleted = 1`), preventing accidental destruction of decision history.

---

## 4. Test Verification Results

| Suite | Items | Passed | Failed | Skipped | Duration | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Milestone 1 Foundation** (`test_intelligence_foundation.py`) | 13 | 13 | 0 | 0 | 3.21s | PASSED |
| **Milestone 2 Project Intelligence** (`test_project_intelligence.py`) | 14 | 14 | 0 | 0 | 8.49s | PASSED |
| **Combined Milestone 1 & 2** | 27 | 27 | 0 | 0 | 17.33s | PASSED |
| **Full Repository Test Suite** (`pytest -q` / `pytest -x`) | 378 | 377 | 0 | 1* | 229.45s | PASSED |

*\*Note: 1 test (`tests/test_step4.py::test_optional_live_api`) is skipped as designed when third-party cloud API keys are unconfigured in local test mode.*

All 27 new Phase 1 tests (Milestones 1 & 2) and all 350 existing regression tests passed with zero failures and zero regressions.

---

## 5. Existing Functionality Preserved

- **Personal Memory (`owner_memories`):** Untouched; operates on its existing SQLite table and Chroma collection.
- **Chat & Router:** Existing router rules and handlers remain intact and backward compatible.
- **Security Boundaries:** Session authentication, internal tokens, and privacy boundary tests continue to pass 100%.

---

## 6. Known Limitations & Milestone 3 Readiness

### Boundaries Scoped for Milestone 3
- Dynamic cognitive task execution and autonomous task breakdown will be implemented in **Milestone 3 (Cognitive Task & Planning System)**.
- Model routing will be adapted to utilize project context in Milestone 5.

### Acceptance Assessment
Milestone 2 satisfies 100% of the specified acceptance criteria and is ready for review.
