import logging
import re
from typing import Any, Dict, List, Optional
from .safety import filter_safe_facts, is_safe_to_store
from .storage import MemoryStorage

logger = logging.getLogger("hinaku.memory.extractor")

EXTRACTION_SYSTEM_PROMPT = """You are HINAKU's memory extraction engine.
Your sole job is to extract durable facts and preferences that the OWNER explicitly stated about themselves.

Strict Rules:
1. Look ONLY at what the OWNER said. Completely ignore the assistant's message.
2. NEVER extract anything from the assistant's reply.
3. Extract ONLY durable, long-term facts about the owner (e.g., hardware specs, favorite tools, skills, location, pets, habits).
4. Do NOT infer or guess anything about mood, health, emotions, or personality.
5. Do NOT extract conversational filler, temporary thoughts, or questions.
6. Format: One short fact per line, phrased simply (e.g., "Uses a laptop with an RTX 4050 and 6 GB VRAM", "Favorite code editor is VS Code").
7. If the owner did not state any durable facts or preferences about themselves, output exactly: NONE."""

class MemoryExtractor:
    def __init__(
        self,
        local_adapter: Any,
        storage: MemoryStorage,
        never_store_categories: Optional[List[str]] = None,
        merge_threshold: float = 0.80
    ):
        self.local_adapter = local_adapter
        self.storage = storage
        self.never_store_categories = never_store_categories
        self.merge_threshold = merge_threshold

    async def extract_facts(self, user_message: str, assistant_message: str) -> List[str]:
        """
        Ask the LOCAL model (never API) to extract durable facts and preferences from the exchange.
        """
        clean_user = user_message.strip()
        if not clean_user:
            return []

        prompt = (
            f"The owner said: \"{clean_user}\"\n"
            f"The assistant replied: \"{assistant_message.strip()}\"\n\n"
            f"Extract durable facts stated by the OWNER about themselves (ignore assistant completely, or output NONE):"
        )
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]

        try:
            # Always invoke local adapter
            response_text = ""
            async for chunk in self.local_adapter.stream_chat(messages):
                response_text += chunk
        except Exception as e:
            logger.error(f"Local memory extraction model call failed: {e}")
            return []

        return self.parse_extracted_text(response_text)

    def parse_extracted_text(self, text: str) -> List[str]:
        """
        Parse raw model output into clean, safe fact strings.
        """
        facts = []
        for line in text.splitlines():
            cleaned = line.strip()
            # Strip markdown list markers and quotes
            cleaned = re.sub(r"^(?:[-*+]|\d+\.)\s*", "", cleaned).strip()
            cleaned = cleaned.strip("\"'")
            if not cleaned:
                continue
            if cleaned.upper() == "NONE":
                continue
            if len(cleaned) < 5:
                continue

            # Safety check
            is_safe, reason = is_safe_to_store(cleaned, self.never_store_categories)
            if not is_safe:
                logger.info(f"Dropped unsafe memory candidate: {reason}")
                continue

            facts.append(cleaned)

        return facts

    async def process_exchange(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str
    ) -> List[Dict[str, Any]]:
        """
        Extract facts, deduplicate or merge, and persist to storage.
        """
        facts = await self.extract_facts(user_message, assistant_message)
        saved = []

        for fact in facts:
            # Dedupe & merge check
            similar_match = self.storage.find_similar(fact, threshold=self.merge_threshold)
            if similar_match:
                existing_mem, score = similar_match
                logger.info(f"Merging similar memory '{fact}' into '{existing_mem['text']}' (score: {score:.2f})")
                updated = self.storage.update_memory(existing_mem["id"], fact)
                if updated:
                    saved.append(updated)
            else:
                new_mem = self.storage.add_memory(fact, source_conversation_id=conversation_id)
                saved.append(new_mem)

        return saved
