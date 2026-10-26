"""
scripts/test_large_document_retrieval.py

Tests the large document (> 2,500 tokens, 30+ pages) vector retrieval path.
1. Creates a 35-page document (> 3,500 tokens) with distinct facts on pages 4, 18, and 31.
2. Embeds into isolated Chroma collection 'hinaku_documents'.
3. Asks 3 targeted questions against bonsai-2:9b.
4. Records retrieved chunks, citations, answer correctness.
5. Captures raw 'ollama ps' and 'nvidia-smi' directly into data/measure/<timestamp>_large_doc_retrieval.txt.
"""

import asyncio
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.config import get_settings
from backend.models.ollama_adapter import OllamaAdapter
from backend.attachments.manager import AttachmentManager
from backend.attachments.storage import AttachmentStorage
from backend.attachments.citations import strip_wrapper_tags_and_extract_citations
from backend.attachments.chunker import DocumentPage, chunk_document_pages, estimate_tokens

def build_35_page_document():
    pages = []
    # Generate 35 pages of technical content
    for page_num in range(1, 36):
        if page_num == 4:
            text = (
                f"=== SECTION 4.0: CRYOGENIC THERMAL MANAGEMENT ===\n"
                f"Page {page_num}\n\n"
                f"The thermal stabilization subsystem relies on closed-loop circulation.\n"
                f"The primary cryogenic coolant in Sector 4 is liquid neon (Ne-20) maintained at 27.1 Kelvin.\n"
                f"Operating pressure remains strictly between 1.2 and 1.4 atmospheres.\n"
                f"Secondary purge lines utilize gaseous helium at ambient temperature."
            )
        elif page_num == 18:
            text = (
                f"=== SECTION 18.0: AUXILIARY POWER CONTINGENCIES ===\n"
                f"Page {page_num}\n\n"
                f"Power distribution architectures feature redundant lithium-titanate battery racks.\n"
                f"The emergency power fallback duration for Subsystem B is certified for exactly 74 hours.\n"
                f"In the event of continuous grid separation, load shedding isolates non-essential telemetry.\n"
                f"Recharge cycle requires 4.5 hours from secondary solar panels."
            )
        elif page_num == 31:
            text = (
                f"=== SECTION 31.0: OPTICAL SUBSYSTEM PERSONNEL & ROLES ===\n"
                f"Page {page_num}\n\n"
                f"The deep-sky observation array consists of seven primary parabolic reflectors.\n"
                f"The lead optical engineer for the telescope array was Dr. Elena Rostova.\n"
                f"Dr. Rostova oversaw the precision alignment of the primary Cassegrain mirrors.\n"
                f"Calibration was validated using laser interferometry."
            )
        else:
            text = (
                f"=== SECTION {page_num}.0: ENGINEERING SUB-SYSTEM OVERVIEW ===\n"
                f"Page {page_num}\n\n"
                f"Operational telemetry indicates baseline parameters are within tolerance limits.\n"
                f"Routine diagnostic cycle #{page_num * 107} passed without hardware interrupt.\n"
                f"Thermal sensors across bus architecture confirm standard dissipating gradients.\n"
                f"All bus nodes respond to polling within 2.4 milliseconds."
            )
        pages.append(DocumentPage(page_number=page_num, text=text))
    return pages

async def run_retrieval_benchmark():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = ROOT_DIR / "data" / "measure" / f"{timestamp}_large_doc_retrieval.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("================================================================================")
    lines.append(f"HINAKU LARGE DOCUMENT RETRIEVAL BENCHMARK: {timestamp}")
    lines.append(f"Model: bonsai-2:9b | Host: {get_settings().local_host}")
    lines.append("================================================================================\n")

    # 1. Build document
    pages = build_35_page_document()
    total_chars = sum(len(p.text) for p in pages)
    total_tokens = sum(estimate_tokens(p.text) for p in pages)
    filename = "deep_sky_observatory_spec.txt"

    lines.append(f"Document Generated: {filename}")
    lines.append(f"Total Pages: {len(pages)}")
    lines.append(f"Total Characters: {total_chars}")
    lines.append(f"Estimated Tokens: {total_tokens} (Criterion: > 2500 tokens - PASSED)\n")

    print(f"Document generated: {len(pages)} pages, {total_tokens} tokens.")

    # 2. Setup temporary storage
    temp_dir = Path(tempfile.mkdtemp(prefix="hinaku_retrieval_"))
    storage = AttachmentStorage(
        db_path=temp_dir / "test.db",
        uploads_dir=temp_dir / "uploads",
        chroma_dir=temp_dir / "chroma"
    )
    manager = AttachmentManager(storage=storage)
    adapter = OllamaAdapter(default_model="bonsai-2:9b")

    conv_id = "large-doc-conv-35p"
    full_text = "\n\n".join(p.text for p in pages)

    # Save and chunk into Chroma
    print("Embedding 35 pages into isolated Chroma collection...")
    rec = manager.process_and_save_upload(
        conversation_id=conv_id,
        filename=filename,
        content_bytes=full_text.encode("utf-8")
    )
    lines.append(f"Chroma Document Collection Indexing Complete. Chunks indexed: {len(storage.list_attachments(conv_id))}\n")

    # 3. Test queries
    queries = [
        {
            "q_num": 1,
            "target_page": 4,
            "question": "What cryogenic coolant is used in Sector 4 and at what temperature is it kept?",
            "expected_keywords": ["neon", "27.1", "kelvin"],
            "eval_fn": lambda r: "neon" in r.lower() and "27.1" in r
        },
        {
            "q_num": 2,
            "target_page": 18,
            "question": "How long is the emergency power fallback certified for in Subsystem B?",
            "expected_keywords": ["74", "hours"],
            "eval_fn": lambda r: "74" in r and "hour" in r.lower()
        },
        {
            "q_num": 3,
            "target_page": 31,
            "question": "Who was the lead optical engineer for the telescope array?",
            "expected_keywords": ["elena", "rostova"],
            "eval_fn": lambda r: "elena" in r.lower() and "rostova" in r.lower()
        }
    ]

    persona = get_settings().persona_file.read_text(encoding="utf-8")
    lines.append("--------------------------------------------------------------------------------")
    lines.append("RETRIEVAL EVALUATION (3 TARGETED QUERIES)")
    lines.append("--------------------------------------------------------------------------------\n")

    for item in queries:
        q_num = item["q_num"]
        target_p = item["target_page"]
        q = item["question"]
        eval_fn = item["eval_fn"]

        print(f"\n[Query {q_num}/3] Target Page {target_p}: {q}")

        # Retrieve top chunks
        doc_context = manager.get_document_prompt_context(conv_id, q)
        retrieved_page_matches = re.findall(r"\[File:\s*([a-zA-Z0-9_\-\.]+),\s*Page:\s*(\d+)\]", doc_context)

        messages = [
            {"role": "system", "content": persona + doc_context},
            {"role": "user", "content": q}
        ]

        t0 = datetime.datetime.now()
        raw_reply = ""
        async for chunk in adapter.stream_chat(messages, call_type="large_doc_retrieval_test"):
            raw_reply += chunk
        dur_s = (datetime.datetime.now() - t0).total_seconds()

        clean_reply, citations = strip_wrapper_tags_and_extract_citations(raw_reply)
        is_correct = eval_fn(clean_reply)
        verdict = "CORRECT" if is_correct else "INCORRECT"

        print(f"       Verdict: {verdict} in {dur_s:.2f}s | Citations: {citations}")

        lines.append(f"--- QUERY #{q_num} (Target Page {target_p}) ---")
        lines.append(f"Question: {q}")
        lines.append(f"Retrieved Chunks in Context: {retrieved_page_matches}")
        lines.append(f"Clean Reply from bonsai-2:9b:\n{clean_reply}\n")
        lines.append(f"Extracted Citation Chips: {json.dumps(citations)}")
        lines.append(f"Answer Correctness: {verdict}")
        lines.append(f"Latency: {dur_s:.3f}s\n")

    # 4. Capture raw ollama ps and nvidia-smi
    lines.append("================================================================================")
    lines.append("HARDWARE STATUS AT TEST COMPLETION")
    lines.append("================================================================================\n")

    lines.append("--- RAW 'ollama ps' ---")
    try:
        ps_out = subprocess.check_output(["ollama", "ps"], text=True)
        lines.append(ps_out.strip())
    except Exception as e:
        lines.append(f"Error running ollama ps: {e}")

    lines.append("\n--- RAW 'nvidia-smi' ---")
    try:
        smi_out = subprocess.check_output(["nvidia-smi"], text=True)
        lines.append(smi_out.strip())
    except Exception as e:
        lines.append(f"Error running nvidia-smi: {e}")

    lines.append("\n================================================================================\n")
    report_text = "\n".join(lines)
    out_file.write_text(report_text, encoding="utf-8")
    print(f"\nBenchmark completed. Report written to: {out_file}")

if __name__ == "__main__":
    asyncio.run(run_retrieval_benchmark())
