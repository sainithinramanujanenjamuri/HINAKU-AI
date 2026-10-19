import json
from typing import AsyncGenerator, Dict, List, Optional
import httpx

class OllamaAdapter:
    def __init__(self, host: str = "http://localhost:11434", default_model: str = "qwen3.5:4b"):
        self.host = host.rstrip("/")
        self.default_model = default_model

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
        model: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        target_model = model or self.default_model
        url = f"{self.host}/api/chat"
        payload = {
            "model": target_model,
            "messages": messages,
            "stream": True,
        }

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
                                yield content
                            if chunk.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
            except httpx.ConnectError:
                yield "[Error: Unable to connect to local Ollama service at " + self.host + ". Is Ollama running?]"
            except Exception as e:
                yield f"[Error streaming from Ollama: {str(e)}]"

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None
    ) -> str:
        parts = []
        async for chunk in self.stream_chat(messages, model=model):
            parts.append(chunk)
        return "".join(parts)

