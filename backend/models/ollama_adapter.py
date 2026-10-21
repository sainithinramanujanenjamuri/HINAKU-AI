import json
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx
from .thinking_filter import ThinkingFilter, strip_thinking

class OllamaAdapter:
    def __init__(
        self,
        host: str = "http://localhost:11434",
        default_model: str = "gemma3:4b",
        default_options: Optional[Dict[str, Any]] = None,
        default_think: Optional[bool] = False,
        default_keep_alive: Optional[str] = "30m",
    ):
        self.host = host.rstrip("/")
        self.default_model = default_model
        self.default_options = default_options or {}
        self.default_think = default_think
        self.default_keep_alive = default_keep_alive

    async def check_health(self) -> Dict[str, bool]:
        url = f"{self.host}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    return {
                        "online": True,
                        "has_default_model": any(self.default_model in m for m in models),
                        "models": models
                    }
        except Exception:
            pass
        return {"online": False, "has_default_model": False, "models": []}

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        think: Optional[bool] = None,
        keep_alive: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        target_model = model or self.default_model
        url = f"{self.host}/api/chat"
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "stream": True,
        }

        # Apply keep_alive
        use_keep_alive = self.default_keep_alive if keep_alive is None else keep_alive
        if use_keep_alive is not None:
            payload["keep_alive"] = use_keep_alive

        # Apply configurable options
        merged_options = dict(self.default_options)
        if options:
            merged_options.update(options)
        if merged_options:
            payload["options"] = merged_options

        # Apply think parameter
        use_think = self.default_think if think is None else think
        if use_think is not None:
            payload["think"] = use_think

        thinking_filter = ThinkingFilter()

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        err_text = await response.aread()
                        yield f"[Ollama Error: Status {response.status_code} - {err_text.decode('utf-8', errors='ignore')}]"
                        return

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            msg = chunk.get("message", {})
                            content = msg.get("content", "")
                            if content:
                                filtered = thinking_filter.process_chunk(content)
                                if filtered:
                                    yield filtered
                            if chunk.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue

                    # Flush any remaining buffer from the filter
                    final_chunk = thinking_filter.flush()
                    if final_chunk:
                        yield final_chunk

            except httpx.ConnectError:
                yield "[Error: Unable to connect to local Ollama service at " + self.host + ". Is Ollama running?]"
            except Exception as e:
                yield f"[Error streaming from Ollama: {str(e)}]"

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        think: Optional[bool] = None,
        keep_alive: Optional[str] = None,
    ) -> str:
        parts = []
        async for chunk in self.stream_chat(messages, model=model, options=options, think=think, keep_alive=keep_alive):
            parts.append(chunk)
        return strip_thinking("".join(parts))

