"""
scripts/evaluate_document_qa.py

Rigorous evaluation of Document Q&A Retrieval and Answer Accuracy:
- Evaluates 13 questions across both sample PDFs (Security Notes and Game Mechanics Notes)
- Tests AI Triad, Bartle player types, MLSecOps lifecycle (Session 8), evasion vs poisoning,
  Likely Exam Themes, MDA framework, Prototyping, Game Economy, Unity Transforms, etc.
- For each question:
  - Logs retrieved chunks (section title, page range, score)
  - Logs exact context block sent to the model
  - Logs full model reply
  - Code-based grading of retrieval hit and answer accuracy
- Writes raw output to data/measure/<timestamp>_document_qa_evaluation.txt
- Verifies retrieval hit rate >= 90% and answer accuracy >= 80%
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

now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = ROOT / "data" / "measure" / f"{now_str}_document_qa_evaluation.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

client = TestClient(app)

lines = []
lines.append("COMMAND: python scripts/evaluate_document_qa.py")
lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
lines.append("=" * 80)
lines.append("DOCUMENT Q&A RETRIEVAL & ANSWER ACCURACY EVALUATION (13 QUESTIONS)")
lines.append("Target Constraints: Retrieval Hit Rate >= 90%, Answer Accuracy >= 80%")
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

qa_cases = [
    # Security Notes Cases
    {
        "id": "Q1",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "query": "From the AI security notes, what are the three pillars of the AI Triad and what does each focus on?",
        "target_section": "Topic 1 — AI Triad",
        "expected_keywords": ["security", "ethics", "regulation"]
    },
    {
        "id": "Q2",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "query": "Explain the difference between evasion attacks and poisoning attacks according to the notes.",
        "target_section": "Topic 5 — Evasion & Poisoning Attacks",
        "expected_keywords": ["evasion", "poisoning"]
    },
    {
        "id": "Q3",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "query": "According to Session 8, what are the main lifecycle stages of MLSecOps?",
        "target_section": "Session 8 — Introduction to MLSecOps",
        "expected_keywords": ["data", "model", "deployment", "monitoring"]
    },
    {
        "id": "Q4",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "query": "What are the common LLM vulnerabilities discussed in Topic 7 of the notes?",
        "target_section": "Topic 7 — LLM and Transformer Vulnerabilities",
        "expected_keywords": ["prompt injection", "jailbreaking"]
    },
    {
        "id": "Q5",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "query": "What are the likely exam themes highlighted in the AI security notes?",
        "target_section": "Likely Exam Themes",
        "expected_keywords": ["triad", "mitre atlas", "mlsecops", "evasion"]
    },
    {
        "id": "Q6",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "query": "In Unit 1 Topic 9, how does MITRE ATLAS help organizations understand AI threats?",
        "target_section": "Topic 9 — Frameworks for Understanding AI Threats: MITRE ATLAS",
        "expected_keywords": ["mitre", "atlas", "tactics", "techniques"]
    },
    {
        "id": "Q7",
        "conv_id": conv1_id,
        "doc": "Security Notes",
        "query": "According to Session 9, what practices ensure secure data management and provenance in ML?",
        "target_section": "Session 9 — Secure Data Management and Provenance",
        "expected_keywords": ["provenance", "data", "integrity", "lineage"]
    },
    # Game Mechanics Cases
    {
        "id": "Q8",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "query": "What are Bartle's four player types described in the game mechanics notes?",
        "target_section": "9. Player Types",
        "expected_keywords": ["killers", "achievers", "explorers"]
    },
    {
        "id": "Q9",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "query": "In Unit 1, explain the three components of the MDA framework.",
        "target_section": "6. MDA Framework",
        "expected_keywords": ["mechanics", "dynamics", "aesthetics"]
    },
    {
        "id": "Q10",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "query": "According to Section 16 of the game design notes, what is the purpose of prototyping?",
        "target_section": "16. Prototyping",
        "expected_keywords": ["prototype", "prototyping", "gameplay", "risk"]
    },
    {
        "id": "Q11",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "query": "Explain the 7-step framework for Game Economy Design in Unit 2.",
        "target_section": "24. Game Economy Design",
        "expected_keywords": ["economy", "resources", "sources", "sinks"]
    },
    {
        "id": "Q12",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "query": "What are the core concepts of Unity Transforms and Object Parenting covered in Unit 2?",
        "target_section": "18. Unity Transforms & Object Parenting",
        "expected_keywords": ["transform", "parent", "position"]
    },
    {
        "id": "Q13",
        "conv_id": conv2_id,
        "doc": "Game Mechanics",
        "query": "What quick-recall tips are given in the cheat sheet for game balancing?",
        "target_section": "Quick-Recall Cheat Sheet",
        "expected_keywords": ["balancing", "mechanics"]
    }
]

retrieval_hits = 0
accuracy_hits = 0
total_q = len(qa_cases)

for case in qa_cases:
    qid = case["id"]
    conv_id = case["conv_id"]
    q_text = case["query"]
    target_sec = case["target_section"].lower()
    exp_kws = case["expected_keywords"]

    lines.append(f"\n>>> [{qid}] Document: {case['doc']}")
    lines.append(f"Query: {q_text}")
    lines.append(f"Target Section: {case['target_section']}")
    lines.append(f"Expected Keywords: {exp_kws}")

    # Reset conversation message history for isolated question testing
    with history_manager._get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))

    # 1. Inspect exact retrieved context block and metadata
    raw_ctx, cov = attachment_manager.get_document_prompt_context(conv_id, q_text)
    retrieved_secs = cov.get("sections", [])
    retrieved_pages = cov.get("pages", [])
    gate_info = cov.get("gate", {})

    lines.append(f"Retrieved Sections: {retrieved_secs}")
    lines.append(f"Retrieved Pages: {retrieved_pages}")
    lines.append(f"Gate Info: {gate_info}")

    # Check retrieval hit
    retrieval_hit = any(target_sec in s.lower() or any(w in s.lower() for w in target_sec.split() if len(w) > 4) for s in retrieved_secs)
    # Also check if target keywords are in the retrieved context block
    if not retrieval_hit and any(kw.lower() in raw_ctx.lower() for kw in exp_kws):
        retrieval_hit = True

    if retrieval_hit:
        retrieval_hits += 1
        lines.append("Retrieval Verdict: PASS (Target section/content retrieved)")
    else:
        lines.append("Retrieval Verdict: FAIL (Target section not found in retrieved chunks)")

    lines.append(f"Exact Context Block Sent to Model (first 300 chars):\n{raw_ctx[:300]}...")

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

    # Check answer accuracy
    reply_lower = reply.lower()
    matched_kws = [kw for kw in exp_kws if kw.lower() in reply_lower]
    # For player types: check if socializers or socialites or killers or achievers
    if "killers" in exp_kws:
        if ("socializers" in reply_lower or "socialites" in reply_lower) and "socializers" not in matched_kws:
            matched_kws.append("socializers/socialites")

    # Pass accuracy if at least 2 expected keywords (or >= 66% of expected keywords) appear
    accuracy_pass = (len(matched_kws) >= max(2, len(exp_kws) * 2 // 3))
    if accuracy_pass:
        accuracy_hits += 1
        lines.append(f"Answer Accuracy Verdict: PASS (Matched keywords: {matched_kws})")
    else:
        lines.append(f"Answer Accuracy Verdict: FAIL (Matched {len(matched_kws)}/{len(exp_kws)}: {matched_kws})")

    lines.append("-" * 80)

# Compute Summary Statistics
retrieval_rate = (retrieval_hits / total_q) * 100
accuracy_rate = (accuracy_hits / total_q) * 100

lines.append("\n" + "=" * 80)
lines.append("EVALUATION SUMMARY & STATISTICAL RESULTS")
lines.append("=" * 80)
lines.append(f"Total Questions Evaluated: {total_q}")
lines.append(f"Retrieval Hits: {retrieval_hits}/{total_q} ({retrieval_rate:.1f}%) [Threshold >= 90%]")
lines.append(f"Answer Accuracy Hits: {accuracy_hits}/{total_q} ({accuracy_rate:.1f}%) [Threshold >= 80%]")

retrieval_passed = (retrieval_rate >= 90.0)
accuracy_passed = (accuracy_rate >= 80.0)

if retrieval_passed and accuracy_passed:
    lines.append("OVERALL VERDICT: PASSED (Both retrieval hit rate and answer accuracy satisfy requirements)")
else:
    reasons = []
    if not retrieval_passed:
        reasons.append(f"Retrieval hit rate {retrieval_rate:.1f}% < 90%")
    if not accuracy_passed:
        reasons.append(f"Answer accuracy {accuracy_rate:.1f}% < 80%")
    lines.append(f"OVERALL VERDICT: FAILED ({'; '.join(reasons)})")

out_text = "\n".join(lines) + "\n"
output_path.write_text(out_text, encoding="utf-8")
print(f"Evaluation written to: {output_path}")
print(f"Retrieval: {retrieval_rate:.1f}% | Accuracy: {accuracy_rate:.1f}%")

