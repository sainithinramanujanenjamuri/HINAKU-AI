from .ollama_adapter import OllamaAdapter
from .api_adapter import ApiAdapter
from .router import ModelRouter, classify_prompt
from .thinking_filter import ThinkingFilter, strip_thinking, strip_meta_commentary
from .privacy_gate import OutboundPrivacyGate, OutboundPrivacyViolation

__all__ = [
    "OllamaAdapter",
    "ApiAdapter",
    "ModelRouter",
    "classify_prompt",
    "ThinkingFilter",
    "strip_thinking",
    "strip_meta_commentary",
    "OutboundPrivacyGate",
    "OutboundPrivacyViolation",
]
