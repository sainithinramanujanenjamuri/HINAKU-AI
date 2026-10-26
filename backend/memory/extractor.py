import logging
import re
from typing import Any, Dict, List, Optional
from .safety import filter_safe_facts, is_safe_to_store, validate_memory_quality
from .storage import MemoryStorage

logger = logging.getLogger("hinaku.memory.extractor")

EXTRACTION_SYSTEM_PROMPT = """You are HINAKU's memory extraction engine.
Your sole job is to extract durable facts and preferences that the OWNER explicitly stated about themselves.

Strict Rules:
1. Look ONLY at what the OWNER said. Completely ignore the assistant's message.
2. NEVER extract anything from the assistant's reply.
3. Extract ONLY durable, long-term facts and stable preferences about the owner (e.g., hardware specs, favorite tools, skills, location, pets, habits).
4. NEVER store mood, mental-state, or health statements (e.g., "feels low and lost", "has anxiety", "takes medication", "is depressed").
5. NEVER store temporary states or fleeting moods (e.g., "tired after a long coding session", "hungry", "busy today", "sleepy").
6. Anything with a time reference ("today", "this week", "tomorrow", "yesterday", "now", "currently") is NOT a memory.
7. Enforce ONE FACT PER MEMORY with faithful wording. Output each distinct fact on its own separate line (bullet point or line). Never combine multiple distinct facts into a single sentence.
   Example:
   User: "my favorite fruit is mango and I live in Seattle"
   Extraction:
   - Favorite fruit is mango.
   - Lives in Seattle.
8. Write every memory in third person with plain wording, beginning with a verb or attribute (e.g., "Favorite fruit is mango.", "Lives in Seattle.", "Wants to build an LLM.", "Uses a laptop with an RTX 4050."). Every memory must end with a period. Never use first-person pronouns ("I", "my", "me", "myself").
9. Resolve pronouns from the conversation ("it" becomes the named thing). If an entity cannot be resolved, do not output that memory.
10. Do NOT store the owner's message word for word.
11. If the owner did not state any durable facts or preferences about themselves, output exactly: NONE.
12. Multiple values for an attribute from one statement (e.g. multiple colors: "red and blue") MUST be stored as ONE memory with plural wording ("Favorite colors are red and blue"). But distinct attributes (e.g. fruit and city) must ALWAYS be separate lines."""

def split_compound_facts(text: str) -> List[str]:
    """
    Splits compound statements into distinct facts so that each memory contains
    exactly one fact with faithful wording.
    E.g.:
    'Favorite fruit is mango and lives in Seattle'
    -> ['Favorite fruit is mango', 'Lives in Seattle']
    """
    raw_parts = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for part in line.split(";"):
            part = part.strip()
            if part:
                raw_parts.append(part)

    parts = []
    compound_pattern = re.compile(
        r"\s+and\s+(?=(?:i\s+live|i\s+work|i\s+code|i\s+use|i\s+prefer|i\s+like|i\s+want|lives|works|codes|uses|prefers|likes|favorite|favourite|plans|hopes|wants|is|has)\b)",
        re.IGNORECASE
    )
    for part in raw_parts:
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", part)
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            subs = compound_pattern.split(s)
            if len(subs) > 1:
                for sub in subs:
                    sub = sub.strip().rstrip(".")
                    if sub:
                        parts.append(sub + ".")
            else:
                parts.append(s)

    return parts

def extract_attribute_key(text: str) -> Optional[str]:
    """
    Extracts a canonical attribute topic from a fact string.
    Used to locate existing memories when the owner states a new set of values.
    """
    clean = text.lower().strip()
    if re.search(r"\b(?:favorite|favourite|preferred)\s+colou?rs?\b", clean):
        return "favorite_color"
    if re.search(r"\b(?:favorite|favourite|preferred)\s+(?:code\s+)?editors?\b", clean):
        return "favorite_editor"
    if re.search(r"\b(?:laptop|gpu|graphics\s+card|vram|specs)\b", clean):
        return "hardware_specs"
    if re.search(r"\b(?:lives?\s+in|location|city|hometown)\b", clean):
        return "location"
    if re.search(r"\b(?:operating\s+system|os)\b", clean):
        return "operating_system"
    if re.search(r"\b(?:primary\s+)?(?:programming\s+)?languages?\b", clean):
        return "programming_languages"
    if re.search(r"\b(?:drinks?|beverage)\b", clean):
        return "beverage"
    return None

def consolidate_multi_value_facts(facts: List[str]) -> List[str]:
    """
    Consolidates facts with multiple values from one statement into ONE memory with plural wording.
    Never splits multiple values into separate memories.
    E.g.:
    ['Favorite color is black', 'Favorite color is red', 'Favorite color is blue']
    -> ['Favorite colors are black, red, and blue']
    """
    if not facts:
        return []

    color_values = []
    other_facts = []

    for f in facts:
        # Match single or plural color fact
        m = re.match(r"(?i)^favorite\s+colou?rs?\s+(?:is|are|include)\s+(.+)$", f.strip())
        if m:
            raw_vals = m.group(1).rstrip(".")
            # Split by comma or 'and'
            parts = [p.strip() for p in re.split(r",\s*|\s+and\s+", raw_vals) if p.strip()]
            for p in parts:
                if p.lower() not in [c.lower() for c in color_values]:
                    color_values.append(p)
        else:
            other_facts.append(f)

    result = []
    if color_values:
        if len(color_values) == 1:
            result.append(f"Favorite color is {color_values[0]}")
        elif len(color_values) == 2:
            result.append(f"Favorite colors are {color_values[0]} and {color_values[1]}")
        else:
            joined = ", ".join(color_values[:-1])
            result.append(f"Favorite colors are {joined}, and {color_values[-1]}")

    result.extend(other_facts)
    return result

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
            # Always invoke local adapter with memory extraction call type
            response_text = ""
            async for chunk in self.local_adapter.stream_chat(messages, call_type="memory_extraction"):
                response_text += chunk
        except Exception as e:
            logger.error(f"Local memory extraction model call failed: {e}")
            return []

        return self.parse_extracted_text(
            response_text,
            user_message=clean_user,
            context=assistant_message.strip()
        )

    def parse_extracted_text(
        self,
        text: str,
        user_message: str = "",
        context: str = ""
    ) -> List[str]:
        """
        Parse raw model output into clean, safe fact strings, applying quality validation
        and consolidating multi-value facts.
        """
        facts = []
        raw_items = split_compound_facts(text)
        for raw in raw_items:
            cleaned = raw.strip()
            # Strip markdown list markers and quotes
            cleaned = re.sub(r"^(?:[-*+]|\d+\.)\s*", "", cleaned).strip()
            cleaned = cleaned.strip("\"'")
            if not cleaned:
                continue
            if cleaned.upper() == "NONE":
                continue
            if len(cleaned) < 4:
                continue

            # Safety check (confidential numbers, keys, passwords)
            is_safe, reason = is_safe_to_store(cleaned, self.never_store_categories)
            if not is_safe:
                logger.info(f"Dropped unsafe memory candidate: {reason}")
                continue

            # Quality validation (mood, health, temporary state, time ref, third-person, pronouns)
            is_valid, processed_fact, rej_reason = validate_memory_quality(
                cleaned,
                user_message=user_message,
                context=context
            )
            if not is_valid:
                logger.info(f"Dropped invalid memory candidate '{cleaned}': {rej_reason}")
                continue

            processed_fact = processed_fact[0].upper() + processed_fact[1:]
            facts.append(processed_fact)

        # Consolidate multiple values into one memory with plural wording
        return consolidate_multi_value_facts(facts)

    def find_existing_matching_memory(self, fact: str) -> Optional[Dict[str, Any]]:
        """
        Locates an existing memory that covers the same attribute/fact for updating.
        Checks attribute key matching and semantic similarity.
        """
        attr_key = extract_attribute_key(fact)
        all_memories = self.storage.get_memories(include_deleted=False)

        if attr_key:
            for mem in all_memories:
                if extract_attribute_key(mem["text"]) == attr_key:
                    return mem

        similar_match = self.storage.find_similar(fact, threshold=0.60)
        if similar_match:
            existing_mem, _ = similar_match
            return existing_mem

        return None

    async def process_exchange(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str
    ) -> List[Dict[str, Any]]:
        """
        Extract facts, deduplicate or update existing memories, and persist to storage.
        """
        facts = await self.extract_facts(user_message, assistant_message)
        saved = []

        for fact in facts:
            # Check if an existing memory exists for this fact/attribute
            existing_mem = self.find_existing_matching_memory(fact)
            if existing_mem:
                logger.info(f"Updating existing memory '{existing_mem['text']}' with new values '{fact}'")
                updated = self.storage.update_memory(existing_mem["id"], fact)
                if updated:
                    saved.append(updated)
            else:
                new_mem = self.storage.add_memory(fact, source_conversation_id=conversation_id)
                saved.append(new_mem)

        return saved
