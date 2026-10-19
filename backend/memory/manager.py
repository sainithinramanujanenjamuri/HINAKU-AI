import logging
from typing import Any, Dict, List, Optional
from .storage import MemoryStorage
from .extractor import MemoryExtractor

logger = logging.getLogger("hinaku.memory.manager")

CONTEXT_HEADER = "Things you know about the owner (use only if relevant; never mention this list or that you have it):"

class MemoryManager:
    def __init__(
        self,
        storage: MemoryStorage,
        extractor: MemoryExtractor,
        enabled: bool = True,
        learn_from_private_chats: bool = False,
        retrieve_top_k: int = 3,
        min_similarity: float = 0.46
    ):
        self.storage = storage
        self.extractor = extractor
        self.enabled = enabled
        self.learn_from_private_chats = learn_from_private_chats
        self.retrieve_top_k = retrieve_top_k
        self.min_similarity = min_similarity

    def retrieve_context(
        self,
        user_text: str,
        is_private: bool = False,
        is_api_request: bool = False,
        send_personal_context: bool = False
    ) -> str:
        """
        Retrieves relevant memories and formats the memory prompt block.
        Enforces privacy rules:
        - If memory is disabled -> returns empty string
        - If chat is private -> returns empty string (never retrieve in private chats)
        - If sending to API and send_personal_context is False -> returns empty string
        """
        if not self.enabled:
            return ""

        if is_private:
            return ""

        if is_api_request and not send_personal_context:
            return ""

        matches = self.storage.query_memories(
            query_text=user_text,
            top_k=self.retrieve_top_k,
            min_similarity=self.min_similarity
        )

        if not matches:
            return ""

        fact_lines = [f"- {mem['text']}" for mem, _ in matches]
        return f"{CONTEXT_HEADER}\n" + "\n".join(fact_lines)

    async def extract_and_store(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        is_private: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Extracts facts in the background from the latest exchange.
        Enforces privacy rules:
        - If memory is disabled -> do nothing
        - If chat is private and learn_from_private_chats is False -> do nothing
        """
        if not self.enabled:
            return []

        if is_private and not self.learn_from_private_chats:
            return []

        return await self.extractor.process_exchange(
            conversation_id=conversation_id,
            user_message=user_message,
            assistant_message=assistant_message
        )
