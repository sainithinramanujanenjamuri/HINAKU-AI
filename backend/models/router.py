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

QUESTION_INDICATORS = [
    r"^(?:should|can|could|may|shall|how\s+do|how\s+can|how\s+should|what\s+should|what\s+do|where\s+do|why\s+do)\s+i\b",
]

TASK_REQUEST_PATTERNS = [
    r"(?i)^(?:i\s+want\s+to|i\s+need\s+to|i\s+would\s+like\s+to|can\s+you\s+help\s+me\s+to)\s+(?:learn|build|write|create|debug|understand|solve|implement|code|explain|make|test)\b",
    r"(?i)\b(?:can\s+you\s+help|help\s+me\s+with|how\s+do\s+i|how\s+can\s+i|can\s+you\s+explain)\b",
]

PRIVATE_LIFE_INDICATORS = [
    r"\b(?:feel|feeling|worried|anxious|stressed|sad|depressed|sick|exhausted|tired|overwhelmed)\b",
    r"\b(?:health|doctor|fever|headache|surgery|diagnosis|medication)\b",
    r"\b(?:salary|savings|rent|debt|bank|budget|income|expenses|mortgage)\b",
    r"\b(?:family|mom|mother|dad|father|parents|brother|sister|wife|husband|partner|boyfriend|girlfriend|child|kids|son|daughter)\b",
    r"\b(?:live\s+in|city|hometown|house|apartment|address)\b",
    r"\b(?:boss|coworker|fired|promoted)\b",
]

PERSONAL_STATEMENT_PATTERNS = [
    # Feelings & mental states ("I feel...", "I'm worried...")
    r"(?i)\b(?:i\s+feel|i'?m\s+feeling|i\s+am\s+feeling)\b",
    r"(?i)\b(?:i'?m|i\s+am)\s+(?:worried|anxious|stressed|sad|depressed|happy|scared|upset|hurting|sick|exhausted|tired|burned\s+out|overwhelmed)\b",

    # Health & medical
    r"(?i)\bmy\s+(?:health|doctor|illness|fever|headache|surgery|diagnosis|medication|hospital)\b",
    r"(?i)\bi\s+(?:have|got)\s+(?:a\s+)?(?:fever|headache|cough|cold|infection|disease|pain)\b",

    # Money & Finances ("my salary...", "my savings...")
    r"(?i)\bmy\s+(?:salary|savings|money|rent|debt|bank|budget|income|expenses|mortgage|finances)\b",
    r"(?i)\b(?:i\s+owe|i\s+spent|i\s+invested)\b",

    # Family ("my family...", "my parents...")
    r"(?i)\bmy\s+(?:family|mom|mother|dad|father|parents|brother|sister|wife|husband|partner|boyfriend|girlfriend|child|kids|son|daughter)\b",

    # Location ("I live in...", "my city...")
    r"(?i)\b(?:i\s+live\s+in|my\s+city|my\s+hometown|my\s+home|my\s+house|my\s+apartment|my\s+address|i'?m\s+moving\s+to)\b",

    # School or work ("my job...", "I just got hired...")
    r"(?i)\bmy\s+(?:job|boss|company|coworker|career|workplace|school|college|university|exam|exams|grade|grades|degree)\b",
    r"(?i)\b(?:i\s+just\s+got\s+hired|i\s+just\s+got\s+promoted|i\s+just\s+got\s+fired|i\s+work\s+at)\b",

    # Relationships
    r"(?i)\bmy\s+(?:friend|friends|partner|relationship|ex|breakup)\b",

    # Plans ("I'm planning to...", "my plan is...")
    r"(?i)\b(?:i'?m\s+planning\s+to|i\s+am\s+planning\s+to|my\s+plan\s+is|i\s+plan\s+to|i'?m\s+about\s+to)\b",

    # Personal events & acquisitions ("I just got...")
    r"(?i)\b(?:i\s+just\s+got|i\s+just\s+bought|i\s+just\s+started|i\s+just\s+lost|i\s+just\s+moved)\b",

    # Specs and preferences ("my favorite...", "I use...")
    r"(?i)\bmy\s+(?:project|favorite|favourite|preferred|name|laptop|pc|computer|gpu|specs|cpu|editor|os|setup|hobby|preference|stack|hardware|card|pin|password)\b",
    r"(?i)\bi\s+(?:use|used|using|prefer|preferred|like|liked|love|loved|hate|dislike|have|had|work|worked|live|lived|own|owned|code|program|run|develop)\b",
    r"(?i)\b(?:i\s+am|i'm|im|i\s+was)\b",
    r"(?i)\b(?:i've|ive)\s+(?:been|got|had|used|built|created|configured)\b",
    r"(?i)\bremember\s+(?:that\s+)?(?:i|my)\b",
    r"(?i)\bnote\s+(?:that\s+)?(?:i|my)\b"
]

def is_personal_statement(
    text: str,
    custom_personal_patterns: Optional[List[str]] = None,
    custom_task_patterns: Optional[List[str]] = None
) -> bool:
    """
    Check if a user prompt is a first-person statement about the owner
    (e.g., feelings, health, money, family, location, school/work, relationships, plans, hardware).
    Plain task requests ('I want to learn Python, can you help?') return False so they may use the API.
    """
    clean = text.strip().lower()

    # If it is an inquiry asking for advice/instructions ("Should I...", "Can I...", "How do I..."), it is not a statement of fact/preference
    for q_pat in QUESTION_INDICATORS:
        if re.search(q_pat, clean):
            return False

    from backend.config import get_settings
    settings = get_settings()

    pats = custom_personal_patterns or settings.router_personal_statement_patterns or PERSONAL_STATEMENT_PATTERNS
    t_pats = custom_task_patterns or settings.router_task_request_patterns or TASK_REQUEST_PATTERNS

    # Check if prompt is a plain task request
    is_task = False
    for t_pat in t_pats:
        if re.search(t_pat, clean):
            is_task = True
            break

    if is_task:
        has_private_life = any(re.search(p, clean) for p in PRIVATE_LIFE_INDICATORS)
        if not has_private_life:
            return False

    for pat in pats:
        if re.search(pat, clean):
            return True

    return False

def is_short_followup(text: str) -> bool:
    """
    Check if a user prompt is a short follow-up (under 12 words, no new topic).
    """
    words = text.strip().split()
    if not (1 <= len(words) < 12):
        return False

    clean = text.strip().lower()
    clean_stripped = re.sub(r"[^\w\s]", "", clean).strip()

    # Greetings are conversational resets, not topic follow-ups
    if clean_stripped in GREETINGS:
        return False

    # Personal statements stay local, not topic follow-ups
    if is_personal_statement(clean):
        return False

    # Explicit new topic or new question indicators
    new_topic_patterns = [
        r"\b(?:new topic|new question|switch topic|different question|by the way|unrelated)\b",
        r"\b(?:what is|what are|who is|who was|tell me about|define)\s+(?!it\b|this\b|that\b|the\b|these\b|those\b)"
    ]
    for pat in new_topic_patterns:
        if re.search(pat, clean):
            return False

    if clean_stripped in FOLLOW_UPS:
        return True

    followup_indicators = [
        r"\b(?:it|this|that|them|these|those|again|more|else|example|shorter|longer|simpler|faster|further)\b",
        r"\b(?:continue|go on|elaborate|expand|summarize|clarify|rephrase|rewrite)\b",
        r"\b(?:why|how so|what about|and\b|but\b|so\b|tell me more|tell me)\b"
    ]
    for pat in followup_indicators:
        if re.search(pat, clean):
            return True

    return False

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

    # Personal statements about the owner stay local (safe, private, extracted locally)
    if is_personal_statement(clean):
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
        is_private: bool = False,
        last_backend: Optional[str] = None
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
        # Stickiness: a short follow-up (under 12 words, no new topic) uses the same backend
        # as the previous assistant reply in that conversation
        if last_backend in ("local", "api") and is_short_followup(user_prompt):
            if last_backend == "api":
                if self.history_manager:
                    daily_count = self.history_manager.get_daily_api_request_count()
                    if daily_count >= self.max_daily_api_requests:
                        logger.warning(f"Daily API request limit reached. Sticky fallback to local.")
                        return RouterDecision(
                            target_backend="local",
                            target_model=self.local_adapter.default_model,
                            fallback_allowed=False,
                            notice=f"Daily API request limit ({self.max_daily_api_requests}) reached. Using local model."
                        )
                if not self.api_adapter.api_key:
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
        is_private: bool = False,
        last_backend: Optional[str] = None,
        override_model: Optional[str] = None,
        think: Optional[bool] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        decision = self.decide_backend(user_prompt, is_private=is_private, last_backend=last_backend)
        active_backend = decision.target_backend
        active_model = override_model if (override_model and active_backend == "local") else decision.target_model
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
                active_model = override_model or self.local_adapter.default_model
                notice = fallback_msg

        # Local execution (primary or fallback)
        try:
            try:
                kwargs = {}
                if options is not None:
                    kwargs["options"] = options
                if think is not None:
                    kwargs["think"] = think
                async for chunk in self.local_adapter.stream_chat(messages, model=active_model, **kwargs):
                    yield {
                        "chunk": chunk,
                        "backend": "local",
                        "model": active_model,
                        "notice": notice
                    }
            except TypeError as te:
                if "unexpected keyword argument" in str(te):
                    async for chunk in self.local_adapter.stream_chat(messages, model=active_model):
                        yield {
                            "chunk": chunk,
                            "backend": "local",
                            "model": active_model,
                            "notice": notice
                        }
                else:
                    raise
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

