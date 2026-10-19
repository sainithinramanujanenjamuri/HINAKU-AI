import json
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx
from .thinking_filter import ThinkingFilter, strip_thinking

class ApiAdapter:
    """
    Unified API adapter supporting:
    1. Anthropic Messages API (provider='anthropic')
    2. OpenAI-compatible Chat Completions (provider='openai_compatible' / 'openai' / 'openrouter' / etc.)
    """
    def __init__(
        self,
        provider: str = "openai_compatible",
        model: str = "",
        base_url: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
        timeout: float = 60.0,
        max_tokens: int = 1024
    ):
        self.provider = provider.lower()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens

    @property
    def is_anthropic(self) -> bool:
        return "anthropic" in self.provider

    def check_ready(self) -> Dict[str, Any]:
        return {
            "has_key": bool(self.api_key),
            "provider": self.provider,
            "model": self.model,
            "configured": bool(self.api_key and self.model and self.model != "SET_ME")
        }

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        if not self.api_key:
            raise ValueError("API key is missing or not configured in environment (HINAKU_API_KEY).")

        target_model = model or self.model
        if not target_model or target_model == "SET_ME":
            raise ValueError("API model name is not configured in settings.yaml.")

        thinking_filter = ThinkingFilter()

        if self.is_anthropic:
            async for chunk in self._stream_anthropic(messages, target_model, thinking_filter):
                yield chunk
        else:
            async for chunk in self._stream_openai_compatible(messages, target_model, thinking_filter):
                yield chunk

        final_chunk = thinking_filter.flush()
        if final_chunk:
            yield final_chunk

    async def _stream_openai_compatible(
        self,
        messages: List[Dict[str, str]],
        target_model: str,
        thinking_filter: ThinkingFilter
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/sainithinramanujanenjamuri/HINAKU-AI",
            "X-Title": "HINAKU"
        }
        payload = {
            "model": target_model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "stream": True
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        err_bytes = await response.aread()
                        err_str = err_bytes.decode("utf-8", errors="ignore")
                        raise RuntimeError(f"API Error ({response.status_code}): {err_str}")

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        trimmed = line.strip()
                        if not trimmed.startswith("data:"):
                            continue
                        data_part = trimmed[5:].strip()
                        if data_part == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data_part)
                            choices = parsed.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                text = delta.get("content", "")
                                if text:
                                    filtered = thinking_filter.process_chunk(text)
                                    if filtered:
                                        yield filtered
                        except json.JSONDecodeError:
                            continue
            except httpx.TimeoutException:
                raise TimeoutError(f"API request timed out after {self.timeout}s.")
            except Exception as e:
                if isinstance(e, (RuntimeError, TimeoutError, ValueError)):
                    raise
                raise RuntimeError(f"API connection failed: {str(e)}")

    async def _stream_anthropic(
        self,
        messages: List[Dict[str, str]],
        target_model: str,
        thinking_filter: ThinkingFilter
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        system_prompt = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        non_system = [
            {"role": m["role"], "content": m["content"]}
            for m in messages if m["role"] in ("user", "assistant")
        ]

        payload = {
            "model": target_model,
            "max_tokens": self.max_tokens,
            "messages": non_system,
            "stream": True
        }
        if system_prompt:
            payload["system"] = system_prompt

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        err_bytes = await response.aread()
                        err_str = err_bytes.decode("utf-8", errors="ignore")
                        raise RuntimeError(f"Anthropic API Error ({response.status_code}): {err_str}")

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        trimmed = line.strip()
                        if trimmed.startswith("data:"):
                            data_part = trimmed[5:].strip()
                            try:
                                parsed = json.loads(data_part)
                                event_type = parsed.get("type")
                                if event_type == "content_block_delta":
                                    delta = parsed.get("delta", {})
                                    text = delta.get("text", "")
                                    if text:
                                        filtered = thinking_filter.process_chunk(text)
                                        if filtered:
                                            yield filtered
                                elif event_type == "message_stop":
                                    break
                                elif event_type == "error":
                                    err_msg = parsed.get("error", {}).get("message", "Unknown error")
                                    raise RuntimeError(f"Anthropic streaming error: {err_msg}")
                            except json.JSONDecodeError:
                                continue
            except httpx.TimeoutException:
                raise TimeoutError(f"Anthropic API request timed out after {self.timeout}s.")
            except Exception as e:
                if isinstance(e, (RuntimeError, TimeoutError, ValueError)):
                    raise
                raise RuntimeError(f"Anthropic API connection failed: {str(e)}")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None
    ) -> str:
        parts = []
        async for chunk in self.stream_chat(messages, model=model):
            parts.append(chunk)
        return strip_thinking("".join(parts))

