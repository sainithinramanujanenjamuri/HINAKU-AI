import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tempfile
from pathlib import Path
import chromadb
from chromadb.config import Settings as ChromaSettings

temp_chroma = Path(tempfile.gettempdir()) / "hinaku_temp" / "chroma"
client = chromadb.PersistentClient(path=str(temp_chroma), settings=ChromaSettings(anonymized_telemetry=False))
coll = client.get_collection("hinaku_documents")

print(f"Total count in hinaku_documents: {coll.count()}")
res = coll.get(include=["metadatas", "documents"])
for idx, (doc, meta) in enumerate(zip(res["documents"], res["metadatas"])):
    if "Game Mechanics" in meta.get("filename", "") or meta.get("page_number") == 3:
        print(f"[{idx}] Page: {meta.get('page_number')}, Section: {meta.get('section_title')}")
        print(f"Text preview: {doc[:200]}...\n")

