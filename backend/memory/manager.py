import asyncio
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
        min_similarity: float = 0.46,
        idle_delay_seconds: float = 5.0
    ):
        self.storage = storage
        self.extractor = extractor
        self.enabled = enabled
        self.learn_from_private_chats = learn_from_private_chats
        self.retrieve_top_k = retrieve_top_k
        self.min_similarity = min_similarity
        self.idle_delay_seconds = idle_delay_seconds

        # 5-second idle debounce queue
        self._pending_extractions: List[Dict[str, Any]] = []
        self._idle_task: Optional[asyncio.Task] = None
        self._chat_active: bool = False

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

    def notify_user_message_received(self):
        """
        Called when a new chat turn arrives.
        Cancels any pending idle timer and re-queues any unextracted turns so extraction
        never runs while the user is actively interacting.
        """
        self._chat_active = True
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None
            logger.info("New message arrived; paused pending memory extraction and re-queued.")

    def notify_chat_completed(self):
        """
        Called when an assistant reply finishes streaming or generating.
        Marks chat inactive and restarts the 5-second idle countdown.
        """
        self._chat_active = False
        self._restart_idle_timer()

    def schedule_extraction(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        is_private: bool = False
    ):
        """
        Enqueues an exchange for memory extraction and (re)starts the 5-second idle timer.
        """
        if not self.enabled:
            return
        if is_private and not self.learn_from_private_chats:
            return

        item = {
            "conversation_id": conversation_id,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "is_private": is_private
        }
        self._pending_extractions.append(item)
        self._restart_idle_timer()

    def _restart_idle_timer(self):
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        if self._pending_extractions and not self._chat_active:
            try:
                loop = asyncio.get_running_loop()
                self._idle_task = loop.create_task(self._idle_worker())
            except RuntimeError:
                pass

    async def _idle_worker(self):
        try:
            await asyncio.sleep(self.idle_delay_seconds)
            if self._chat_active:
                return

            while self._pending_extractions and not self._chat_active:
                item = self._pending_extractions.pop(0)
                try:
                    await self.extract_and_store(
                        conversation_id=item["conversation_id"],
                        user_message=item["user_message"],
                        assistant_message=item["assistant_message"],
                        is_private=item["is_private"]
                    )
                except Exception as e:
                    logger.error(f"Error in deferred memory extraction: {e}")
        except asyncio.CancelledError:
            pass

    async def extract_and_store(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        is_private: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Extracts facts from the exchange using the LOCAL model.
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
