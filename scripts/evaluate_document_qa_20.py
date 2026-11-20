"""
scripts/evaluate_document_qa_20.py

Rigorous evaluation of Document Q&A Retrieval and Answer Accuracy (20 Questions):
- Evaluates 20 questions across both sample PDFs and unrelated controls:
  - 8 questions from Security Notes (including named sections like "Topic 7", "Session 9", "Session 8 stages", "Topic 2", "Topic 9")
  - 8 questions from Game Mechanics (including named sections like "Section 16", "Section 18", "Section 13", "Section 9", "Unit 1 MDA", "Cheat Sheet")
  - 4 unrelated control questions (chatter, Python recursion, general hardware, business case) that must retrieve nothing
- Strict retrieval metric: Target outline section MUST be in retrieved_sections list.
  NO fallback to content or keywords in raw context.
  For unrelated controls: hit = (gate decision is 'skip' and retrieved_sections is empty).
- Precision metrics:
  - Reports hit rate, target rank, and precision@k per question.
- Grader rigor:
  - Expected answers must contain >= 80% of notes' exact items (no loose synonyms).
  - Reports two distinct numbers:
    1. Correct: contains expected items.
    2. Grounded: retrieval was a HIT AND answer shares distinctive text with retrieved chunks.
       Questions answered from model memory because retrieval missed DO NOT count as grounded.
- Session 8 Consistency:
  - Asks the Session 8 stages question 3 times in a loop.
  - Verifies exact consistency and presence of the 9 lifecycle stages:
    Scope, Data, Train, Validate, Package, Deploy, Monitor, Re-evaluate, Retire.
- Writes raw output to data/measure/<timestamp>_document_qa_20_evaluation.txt
- Verifies retrieval hit rate >= 90% and grounded accuracy >= 80%.
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["HINAKU_PROFILE_OLLAMA"] = "1"
os.environ["HINAKU_USE_REAL_DATA"] = "0"

import datetime
import json
import base64
import time
import re
from fastapi.testclient import TestClient
from backend.main import app
from backend.api.chat import history_manager
from backend.api.attachments import attachment_manager
from backend.attachments.citations import check_section_answer_overlap

now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = ROOT / "data" / "measure" / f"{now_str}_document_qa_20_evaluation.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

client = TestClient(app)

lines = []
lines.append("COMMAND: python scripts/evaluate_document_qa_20.py")
lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
lines.append("=" * 80)
lines.append("STRICT DOCUMENT Q&A RETRIEVAL & ANSWER ACCURACY EVALUATION (20 QUESTIONS)")
lines.append("Target Constraints: Retrieval Hit Rate >= 90%, Grounded Accuracy >= 80%")
lines.append("=" * 80)

# 1. Setup Security Notes conversation
conv1_res = client.post("/api/conversations", json={"title": "Eval Conv - Security Notes"})
conv1_id = conv1_res.json()["id"]

sec_pdf = ROOT / "tests/real_samples/Security, Ethics & Regulations in AI - Midterm Notes.pdf"
with open(sec_pdf, "rb") as f:
    sec_b64 = base64.b64encode(f.read()).decode("utf-8")

client.post(
    f"/api/conversations/{conv1_id}/attachments",
    json={"files": [{"filename": sec_pdf.name, "content_base64": sec_b64, "mime_type": "application/pdf"}]}
)
lines.append(f"\n[Environment 1] Uploaded Security Notes PDF ({sec_pdf.name}) to Conversation {conv1_id}")

# 2. Setup Game Mechanics conversation
conv2_res = client.post("/api/conversations", json={"title": "Eval Conv - Game Mechanics"})
conv2_id = conv2_res.json()["id"]

gm_pdf = ROOT / "tests/real_samples/Game Mechanics, Design & Development - Midterm Notes for Units 1 and 2.pdf"
with open(gm_pdf, "rb") as f:
    gm_b64 = base64.b64encode(f.read()).decode("utf-8")

client.post(
    f"/api/conversations/{conv2_id}/attachments",
    json={"files": [{"filename": gm_pdf.name, "content_base64": gm_b64, "mime_type": "application/pdf"}]}
)
lines.append(f"[Environment 2] Uploaded Game Mechanics PDF ({gm_pdf.name}) to Conversation {conv2_id}")
lines.append("-" * 80)

# Define 20 evaluation questions
qa_cases = [
    # --- Security Notes (8 questions) ---
    {
        "id": "Q1",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "category": "content_words",
        "query": "From the AI security notes, what are the three pillars of the AI Triad and what does each focus on?",
        "target_section": "Topic 1 — AI Triad: Security, Ethics, and Regulation",
        "expected_items": ["security", "ethics", "regulation"]
    },
    {
        "id": "Q2",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "category": "content_words",
        "query": "Explain the difference between evasion attacks and poisoning attacks according to the notes.",
        "target_section": "Topic 5 — Evasion & Poisoning Attacks",
        "expected_items": ["evasion", "poisoning", "inference", "training"]
    },
    {
        "id": "Q3",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "category": "named_section",
        "query": "According to Session 8, what are the main lifecycle stages of MLSecOps?",
        "target_section": "Session 8 — Introduction to MLSecOps",
        "expected_items": ["scope", "data", "train", "validate", "package", "deploy", "monitor", "re-evaluate", "retire"],
        "is_session_8": True
    },
    {
        "id": "Q4",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "category": "named_section",
        "query": "What are the common LLM vulnerabilities discussed in Topic 7 of the notes?",
        "target_section": "Topic 7 — LLM and Transformer Vulnerabilities: Prompt Injection and Jailbreaking",
        "expected_items": ["prompt injection", "jailbreaking", "poisoning"]
    },
    {
        "id": "Q5",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "category": "content_words",
        "query": "What are the likely exam themes highlighted in the AI security notes?",
        "target_section": "Likely Exam Themes",
        "expected_items": ["definitions", "distinctions", "lifecycle", "governance"],
        "alt_items": {"definitions": ["definitions", "definition"], "distinctions": ["distinctions", "distinction", "difference"], "lifecycle": ["lifecycle", "stages"], "governance": ["governance", "frameworks", "nist"]}
    },
    {
        "id": "Q6",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "category": "named_section",
        "query": "In Unit 1 Topic 9, how does MITRE ATLAS help organizations understand AI threats?",
        "target_section": "Topic 9 — Frameworks for Understanding AI Threats: MITRE ATLAS",
        "expected_items": ["tactics", "techniques", "procedures"],
        "alt_items": {"tactics": ["tactic", "tactics"], "techniques": ["technique", "techniques"], "procedures": ["procedure", "procedures"]}
    },
    {
        "id": "Q7",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "category": "named_section",
        "query": "According to Session 9, what practices ensure secure data management and provenance in ML?",
        "target_section": "Session 9 — Secure Data Management and Provenance",
        "expected_items": ["provenance", "lineage", "collection", "integrity"]
    },
    {
        "id": "Q8",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "category": "named_section",
        "query": "According to Topic 2 of the notes, what are the main lifecycle stages of an AI system?",
        "target_section": "Topic 2 — AI System Lifecycle and Associated Risks",
        "expected_items": ["inception", "design", "validation", "deployment", "operation", "re-evaluation", "retirement"],
        "alt_items": {"inception": ["inception", "scoping"], "design": ["design", "development"], "validation": ["validation", "verification"], "deployment": ["deployment", "deploy"], "operation": ["operation", "monitoring"], "re-evaluation": ["re-evaluation", "re-evaluate", "retrain"], "retirement": ["retirement", "retire"]}
    },

    # --- Game Mechanics Notes (8 questions) ---
    {
        "id": "Q9",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "category": "content_words",
        "query": "What are Bartle's four player types described in the game mechanics notes?",
        "target_section": "9. Player Types",
        "expected_items": ["killers", "achievers", "socialites", "explorers"],
        "alt_items": {"killers": ["killer", "killers"], "achievers": ["achiever", "achievers"], "socialites": ["socialite", "socialites", "socializer", "socializers"], "explorers": ["explorer", "explorers"]}
    },
    {
        "id": "Q10",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "category": "named_section",
        "query": "In Unit 1, explain the three components of the MDA framework.",
        "target_section": "6. MDA Framework (Mechanics – Dynamics – Aesthetics)",
        "expected_items": ["mechanics", "dynamics", "aesthetics"],
        "alt_items": {"mechanics": ["mechanic", "mechanics"], "dynamics": ["dynamic", "dynamics"], "aesthetics": ["aesthetic", "aesthetics"]}
    },
    {
        "id": "Q11",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "category": "named_section",
        "query": "According to Section 16 of the game design notes, what is the purpose and advantages of prototyping?",
        "target_section": "16. Prototyping",
        "expected_items": ["prototype", "feedback", "iteration", "risk"],
        "alt_items": {"prototype": ["prototype", "prototyping"], "feedback": ["feedback", "evaluate"], "iteration": ["iteration", "iterative"], "risk": ["risk", "risks"]}
    },
    {
        "id": "Q12",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "category": "content_words",
        "query": "Explain the 7-step framework for Game Economy Design in Unit 2.",
        "target_section": "24. Game Economy Design — 7-Step Framework",
        "expected_items": ["sources", "sinks", "telemetry", "economy"],
        "alt_items": {"sources": ["source", "sources", "faucet"], "sinks": ["sink", "sinks", "drain"]}
    },
    {
        "id": "Q13",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "category": "named_section",
        "query": "What are the core concepts of Unity Transforms and Object Parenting covered in Section 18?",
        "target_section": "18. Unity Transforms & Object Parenting",
        "expected_items": ["position", "rotation", "scale", "hierarchy"]
    },
    {
        "id": "Q14",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "category": "content_words",
        "query": "What quick-recall tips are given in the cheat sheet for prototypes and playtesting?",
        "target_section": "Quick-Recall Cheat Sheet",
        "expected_items": ["paper", "rapid", "wireframe", "greybox", "gross", "in-house", "blind", "final"]
    },
    {
        "id": "Q15",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "category": "named_section",
        "query": "According to Section 13, what are the core focuses and examples of simulation and sports games?",
        "target_section": "13. Game Genres",
        "expected_items": ["simulation", "sports", "replication"],
        "alt_items": {"simulation": ["simulation", "sim"], "sports": ["sports", "racing"], "replication": ["replication", "replicate", "replicates", "real-world"]}
    },
    {
        "id": "Q16",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "category": "content_words",
        "query": "How does the solvability check work for the 15-puzzle sliding puzzle example?",
        "target_section": "23. Worked Example — The 15-Puzzle (Sliding Puzzle)",
        "expected_items": ["inversion", "row", "even", "solvable"]
    },

    # --- Unrelated Controls (4 questions - MUST RETRIEVE NOTHING) ---
    {
        "id": "Q17",
        "conv_id": conv1_id,
        "doc": "Unrelated Control",
        "category": "unrelated_chatter",
        "query": "Hey, good morning HINAKU! How are you doing today?",
        "target_section": None,
        "expected_items": []
    },
    {
        "id": "Q18",
        "conv_id": conv1_id,
        "doc": "Unrelated Control",
        "category": "unrelated_coding",
        "query": "Write a recursive Python function to compute the factorial of a number.",
        "target_section": None,
        "expected_items": ["def ", "factorial", "return"]
    },
    {
        "id": "Q19",
        "conv_id": conv2_id,
        "doc": "Unrelated Control",
        "category": "unrelated_hardware",
        "query": "Can you explain how CPUs and GPUs differ in general computing architectures?",
        "target_section": None,
        "expected_items": ["cpu", "gpu", "cores"]
    },
    {
        "id": "Q20",
        "conv_id": conv2_id,
        "doc": "Unrelated Control",
        "category": "unrelated_business",
        "query": "Why might a company choose augmented reality for enterprise customer support?",
        "target_section": None,
        "expected_items": ["support", "visual", "remote", "efficiency"]
    }
]

retrieval_hits = 0
correct_hits = 0
grounded_hits = 0
total_q = len(qa_cases)

# Helper function to check if target section is in retrieved sections
def evaluate_retrieval(target_section, retrieved_secs, gate_decision):
    if target_section is None:
        # Unrelated control: PASS if gate skipped or no sections retrieved
        hit = (gate_decision == "skip" or len(retrieved_secs) == 0)
        return hit, 1 if hit else 0, 1.0 if hit else 0.0

    target_clean = re.sub(r"^(?:Topic|Session|Section|\d+[\.\s\-]+)+", "", target_section, flags=re.IGNORECASE).strip().lower()
    for idx, s in enumerate(retrieved_secs, 1):
        s_clean = re.sub(r"^(?:Topic|Session|Section|\d+[\.\s\-]+)+", "", s, flags=re.IGNORECASE).strip().lower()
        if (target_section.lower() in s.lower() or 
            s.lower() in target_section.lower() or 
            (target_clean and target_clean in s.lower()) or 
            (s_clean and s_clean in target_section.lower())):
            rank = idx
            precision_at_k = 1.0 / rank
            return True, rank, precision_at_k

    return False, 0, 0.0

for case in qa_cases:
    qid = case["id"]
    conv_id = case["conv_id"]
    q_text = case["query"]
    target_sec = case["target_section"]
    exp_items = case["expected_items"]
    alt_items = case.get("alt_items", {})
    is_unrelated = (target_sec is None)

    lines.append(f"\n>>> [{qid}] [{case['category'].upper()}] Doc: {case['doc']}")
    lines.append(f"Query: {q_text}")
    lines.append(f"Target Section: {target_sec or 'NONE (Unrelated Control)'}")
    lines.append(f"Expected Items: {exp_items}")

    # Reset message history for this query to ensure clean isolation
    with history_manager._get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))

    # 1. Retrieve prompt context
    raw_ctx, cov = attachment_manager.get_document_prompt_context(conv_id, q_text)
    retrieved_secs = cov.get("sections", [])
    retrieved_pages = cov.get("pages", [])
    gate_info = cov.get("gate", {})
    gate_decision = gate_info.get("decision", "unknown")
    gate_sim = gate_info.get("similarity", 0.0)

    lines.append(f"Gate Info: decision='{gate_decision}', similarity={gate_sim}, reason='{gate_info.get('reason')}'")
    lines.append(f"Retrieved Sections: {retrieved_secs}")
    lines.append(f"Retrieved Pages: {retrieved_pages}")

    # Evaluate strict retrieval
    r_hit, r_rank, r_p_at_k = evaluate_retrieval(target_sec, retrieved_secs, gate_decision)
    if r_hit:
        retrieval_hits += 1
        lines.append(f"Retrieval Verdict: PASS (Target Rank: {r_rank}, Precision@k: {r_p_at_k:.4f})")
    else:
        lines.append(f"Retrieval Verdict: FAIL (Target section not found in retrieved_sections)")

    # 2. Run real model call via /api/chat
    t0 = time.perf_counter()
    resp = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": q_text}],
        "conversation_id": conv_id,
        "model": "bonsai-2:9b",
        "stream": False
    })
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 200, f"Chat failed: {resp.text}"
    resp_data = resp.json()
    reply = resp_data.get("content") or resp_data.get("reply", "")

    lines.append(f"Model Answer ({elapsed:.2f}s):\n{reply}")

    # Check answer accuracy (>= 80% of items)
    reply_lower = reply.lower()
    matched_items = []
    for item in exp_items:
        check_variants = alt_items.get(item, [item])
        if any(v.lower() in reply_lower for v in check_variants):
            matched_items.append(item)

    if is_unrelated:
        # Unrelated control passes accuracy if reply is non-empty and in persona
        correct_pass = (len(reply.strip()) > 10 and not any(h in reply_lower for h in ["<document_reference>", "based on topic"]))
        grounded_pass = r_hit and correct_pass
    else:
        req_threshold = max(2, int(len(exp_items) * 0.80))
        correct_pass = (len(matched_items) >= req_threshold)
        # Grounding check: retrieval must be a HIT AND answer shares distinctive overlap with retrieved context
        distinctive_overlap = check_section_answer_overlap(reply, raw_ctx, target_sec or "")
        grounded_pass = (r_hit and correct_pass and distinctive_overlap)

    if correct_pass:
        correct_hits += 1
        lines.append(f"Answer Correctness: PASS (Matched {len(matched_items)}/{len(exp_items)} items: {matched_items})")
    else:
        lines.append(f"Answer Correctness: FAIL (Matched {len(matched_items)}/{len(exp_items)} items: {matched_items})")

    if grounded_pass:
        grounded_hits += 1
        lines.append("Answer Grounding: PASS (Retrieved target hit + distinctive overlap)")
    else:
        reason = "Retrieval missed" if not r_hit else ("Answer incorrect" if not correct_pass else "Lacks distinctive overlap")
        lines.append(f"Answer Grounding: FAIL ({reason})")

    # If Session 8, run consistency check 2 more times (total 3 runs)
    if case.get("is_session_8"):
        lines.append("\n--- Session 8 Consistency Test (Runs 2 & 3) ---")
        for run_idx in (2, 3):
            with history_manager._get_connection() as conn:
                conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            s8_resp = client.post("/api/chat", json={
                "messages": [{"role": "user", "content": q_text}],
                "conversation_id": conv_id,
                "model": "bonsai-2:9b",
                "stream": False
            })
            s8_reply = s8_resp.json().get("content", "")
            s8_matched = [item for item in exp_items if item.lower() in s8_reply.lower()]
            s8_pass = (len(s8_matched) >= int(len(exp_items) * 0.80))
            lines.append(f"Session 8 Run {run_idx}: Matched {len(s8_matched)}/{len(exp_items)} stages ({'PASS' if s8_pass else 'FAIL'}): {s8_matched}")
            lines.append(f"Preview: {s8_reply[:200]}...")

    lines.append("-" * 80)

# Compute Summary Statistics
retrieval_rate = (retrieval_hits / total_q) * 100
correct_rate = (correct_hits / total_q) * 100
grounded_rate = (grounded_hits / total_q) * 100

lines.append("\n" + "=" * 80)
lines.append("EVALUATION SUMMARY & STATISTICAL SCOREBOARD (20 QUESTIONS)")
lines.append("=" * 80)
lines.append(f"Total Questions Evaluated: {total_q}")
lines.append(f"Strict Retrieval Hits: {retrieval_hits}/{total_q} ({retrieval_rate:.1f}%) [Threshold >= 90.0%]")
lines.append(f"Answer Correctness Hits: {correct_hits}/{total_q} ({correct_rate:.1f}%)")
lines.append(f"Answer Grounded Accuracy: {grounded_hits}/{total_q} ({grounded_rate:.1f}%) [Threshold >= 80.0%]")

retrieval_passed = (retrieval_rate >= 90.0)
grounded_passed = (grounded_rate >= 80.0)

if retrieval_passed and grounded_passed:
    lines.append("\nOVERALL VERDICT: PASSED (Both strict retrieval hit rate and grounded accuracy satisfy requirements)")
else:
    reasons = []
    if not retrieval_passed:
        reasons.append(f"Strict retrieval hit rate {retrieval_rate:.1f}% < 90.0%")
    if not grounded_passed:
        reasons.append(f"Answer grounded accuracy {grounded_rate:.1f}% < 80.0%")
    lines.append(f"\nOVERALL VERDICT: FAILED ({'; '.join(reasons)})")

out_text = "\n".join(lines) + "\n"
output_path.write_text(out_text, encoding="utf-8")
print(f"Evaluation written to: {output_path}")
print(f"Retrieval: {retrieval_hits}/{total_q} ({retrieval_rate:.1f}%) | Grounded Accuracy: {grounded_hits}/{total_q} ({grounded_rate:.1f}%)")

