import logging
import re
from typing import Any, AsyncGenerator, Dict, List, NamedTuple, Optional
from .ollama_adapter import OllamaAdapter
from .api_adapter import ApiAdapter

logger = logging.getLogger("hinaku.router")

GREETINGS = {
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "howdy", "sup", "yo", "greetings"
}

SMALL_TALK = {
    "how are you", "who are you", "how are things", "how is today",
    "what's up", "whats up", "how's it going", "hows it going",
    "what is your name", "what are you"
}

FOLLOW_UPS = {
    "yes", "no", "ok", "okay", "thanks", "thank you", "sure", "got it",
    "cool", "nice", "yep", "nope", "alright", "perfect", "continue", "go on"
}

API_KEYWORDS = [
    r"\b(?:what is|what are|explain|why|how does|how do|how to|define|describe)\b",
    r"\b(?:compare|difference between|versus|\bvs\b)\b",
    r"\b(?:calculate|solve|equation|integral|derivative|formula)\b",
    r"\b(?:code|function|class|import|def|python|javascript|typescript|c\+\+|rust|sql|bug|regex|algorithm|api|git)\b",
]

def classify_prompt(text: str, is_private: bool = False, max_local_tokens: int = 1500) -> str:
    """
    Classify whether a prompt should go to 'local' or 'api' in auto mode.
    """
    if is_private:
        return "local"

    clean = text.strip().lower()
    est_tokens = len(text) // 4
    if est_tokens > max_local_tokens:
        return "api"

    clean_stripped = re.sub(r"[^\w\s]", "", clean).strip()
    if clean_stripped in GREETINGS or clean_stripped in SMALL_TALK or clean_stripped in FOLLOW_UPS:
        return "local"

    # API patterns (factual, code, math, comparisons)
    for pat in API_KEYWORDS:
        if re.search(pat, clean):
            return "api"

    words = clean.split()
    if len(words) <= 4:
        return "local"

    return "api"

class RouterDecision(NamedTuple):
    target_backend: str   # 'local' or 'api'
    target_model: str
    fallback_allowed: bool
    notice: Optional[str]

class ModelRouter:
    def __init__(
        self,
        local_adapter: OllamaAdapter,
        api_adapter: ApiAdapter,
        mode: str = "auto",
        fallback_on_failure: bool = True,
        max_prompt_tokens: int = 1500,
        max_daily_api_requests: int = 100,
        history_manager: Optional[Any] = None
    ):
        self.local_adapter = local_adapter
        self.api_adapter = api_adapter
        self.mode = mode.lower()
        self.fallback_on_failure = fallback_on_failure
        self.max_prompt_tokens = max_prompt_tokens
        self.max_daily_api_requests = max_daily_api_requests
        self.history_manager = history_manager

    def decide_backend(
        self,
        user_prompt: str,
        is_private: bool = False
    ) -> RouterDecision:
        # Private chats NEVER use API
        if is_private:
            return RouterDecision(
                target_backend="local",
                target_model=self.local_adapter.default_model,
                fallback_allowed=False,
                notice=None
            )

        if self.mode == "local_only":
            return RouterDecision(
                target_backend="local",
                target_model=self.local_adapter.default_model,
                fallback_allowed=False,
                notice=None
            )

        if self.mode == "api_only":
            # Check API key presence
            if not self.api_adapter.api_key:
                return RouterDecision(
                    target_backend="local",
                    target_model=self.local_adapter.default_model,
                    fallback_allowed=False,
                    notice="API key missing while mode is api_only. Using local model."
                )
            return RouterDecision(
                target_backend="api",
                target_model=self.api_adapter.model,
                fallback_allowed=self.fallback_on_failure,
                notice=None
            )

        # Mode is 'auto'
        classified = classify_prompt(
            user_prompt,
            is_private=is_private,
            max_local_tokens=self.max_prompt_tokens
        )

        if classified == "api":
            # Check safety limit for daily requests
            if self.history_manager:
                daily_count = self.history_manager.get_daily_api_request_count()
                if daily_count >= self.max_daily_api_requests:
                    logger.warning(f"Daily API request limit ({self.max_daily_api_requests}) reached. Falling back to local.")
                    return RouterDecision(
                        target_backend="local",
                        target_model=self.local_adapter.default_model,
                        fallback_allowed=False,
                        notice=f"Daily API request limit ({self.max_daily_api_requests}) reached. Using local model."
                    )

            # Check if API key is present
            if not self.api_adapter.api_key:
                logger.info("API key missing in auto mode. Falling back to local model.")
                return RouterDecision(
                    target_backend="local",
                    target_model=self.local_adapter.default_model,
                    fallback_allowed=False,
                    notice="API key not configured. Using local model."
                )

            return RouterDecision(
                target_backend="api",
                target_model=self.api_adapter.model,
                fallback_allowed=self.fallback_on_failure,
                notice=None
            )
        else:
            return RouterDecision(
                target_backend="local",
                target_model=self.local_adapter.default_model,
                fallback_allowed=self.fallback_on_failure,
                notice=None
            )

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        user_prompt: str,
        is_private: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        decision = self.decide_backend(user_prompt, is_private=is_private)
        active_backend = decision.target_backend
        active_model = decision.target_model
        notice = decision.notice

        if active_backend == "api":
            try:
                # Attempt primary API streaming
                started = False
                async for chunk in self.api_adapter.stream_chat(messages, model=active_model):
                    started = True
                    yield {
                        "chunk": chunk,
                        "backend": "api",
                        "model": active_model,
                        "notice": notice
                    }
                return
            except Exception as e:
                logger.error(f"API backend failed: {e}")
                if not decision.fallback_allowed or is_private:
                    yield {
                        "chunk": f"[Error: API failed - {str(e)}]",
                        "backend": "api",
                        "model": active_model,
                        "notice": f"API error: {str(e)}"
                    }
                    return

                # Fallback to local
                fallback_msg = f"API error: {str(e)}. Fell back to local model."
                logger.warning(fallback_msg)
                active_backend = "local"
                active_model = self.local_adapter.default_model
                notice = fallback_msg

        # Local execution (primary or fallback)
        try:
            async for chunk in self.local_adapter.stream_chat(messages, model=active_model):
                yield {
                    "chunk": chunk,
                    "backend": "local",
                    "model": active_model,
                    "notice": notice
                }
        except Exception as e:
            logger.error(f"Local backend failed: {e}")
            if active_backend == "local" and decision.fallback_allowed and not is_private and self.api_adapter.api_key:
                # Fallback to API if local is down
                fallback_msg = f"Local model offline: {str(e)}. Fell back to API."
                logger.warning(fallback_msg)
                try:
                    async for chunk in self.api_adapter.stream_chat(messages, model=self.api_adapter.model):
                        yield {
                            "chunk": chunk,
                            "backend": "api",
                            "model": self.api_adapter.model,
                            "notice": fallback_msg
                        }
                    return
                except Exception as api_err:
                    yield {
                        "chunk": f"[Error: Both backends failed - Local: {str(e)} | API: {str(api_err)}]",
                        "backend": "local",
                        "model": active_model,
                        "notice": "Both local and API backends failed."
                    }
            else:
                yield {
                    "chunk": f"[Error: Local model failed - {str(e)}]",
                    "backend": "local",
                    "model": active_model,
                    "notice": f"Local model error: {str(e)}"
                }

