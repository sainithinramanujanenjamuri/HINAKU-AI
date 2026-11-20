# HINAKU — Project Memory & Phase Closeout Repository

This directory serves as the persistent architectural memory of HINAKU. It stores the comprehensive closeout reports, architectural decisions, security audits, and verification records across every completed phase of the project.

---

## Phase Index & Milestones

| Milestone / Phase | Document | Description | Status |
|---|---|---|:---:|
| **Foundational Development (Phases A–H)** | [00_phase_a_through_h_implementation.md](file:///d:/HINAKU-AI/project_memory/00_phase_a_through_h_implementation.md) | Persona adherence, hybrid model routing, ChromaDB semantic memory, response feedback, dataset curation, QLoRA training pipeline, 6-month scheduler, and activity pause logic. | **Done** |
| **Sprint 0A — Repository Baseline** | [01_sprint_0a_repository_baseline.md](file:///d:/HINAKU-AI/project_memory/01_sprint_0a_repository_baseline.md) | Authoritative source determination against `origin/main` commit `38f04c5`, 100% byte-for-byte tracked file parity, secret scan, and `.gitignore` auditing. | **Done** |
| **Sprint 0B — Outbound Privacy Boundary** | [02_sprint_0b_privacy_audit.md](file:///d:/HINAKU-AI/project_memory/02_sprint_0b_privacy_audit.md) | Multi-tier outbound privacy boundary, fail-closed `OutboundPrivacyGate` at physical socket pre-egress, multi-turn history scanning, and attachment egress blocking. | **Done** |
| **Sprint 0B — Authorization Audit** | [03_sprint_0b_authorization_audit.md](file:///d:/HINAKU-AI/project_memory/03_sprint_0b_authorization_audit.md) | Universal enforcement of `require_session_auth` across all state-changing endpoints, side-effect prevention audit, and scoped internal token architecture. | **Done** |
| **Sprint 0A/0B — Final Security Acceptance** | [04_sprint_0a_0b_acceptance_report.md](file:///d:/HINAKU-AI/project_memory/04_sprint_0a_0b_acceptance_report.md) | Comprehensive audit of all 57 API endpoints, sensitive read endpoint protection, test suite verification (350 passed, 1 skipped), and technical debt logging. | **Done** |
| **Sprint 0A/0B — Repository Verification & Staging** | [05_sprint_0a_0b_repository_verification.md](file:///d:/HINAKU-AI/project_memory/05_sprint_0a_0b_repository_verification.md) | Complete reflection-based route inventory reconciliation, call-site authorization checks, and selective staging plan. | **Done** |
| **Phase 1 — Master Implementation Plan** | [06_phase_1_master_implementation_plan.md](file:///d:/HINAKU-AI/project_memory/06_phase_1_master_implementation_plan.md) | Comprehensive master plan for HINAKU's Intelligence Core, Project Intelligence, Knowledge Architecture, and Decision System. | **Active Plan** |

---

## Directory Organization Rules

1. **Immutable Historical Records:** Each phase closeout document represents a timestamped, evidence-backed snapshot of the system state, architecture, and test results at that milestone.
2. **Naming Convention:** Files are prefixed with two-digit sequence numbers (`00_`, `01_`, `02_`, etc.) reflecting project chronological progression.
3. **No Secret Storage:** Project memory documents must never log API keys, personal owner secrets, passwords, or confidential runtime databases.
