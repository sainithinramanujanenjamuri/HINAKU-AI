from pathlib import Path
from typing import Any, Dict, Optional
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"

def load_settings(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}

class Settings:
    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.app = raw.get("app", {})
        self.router = raw.get("router", {})
        self.local = raw.get("local", {})
        self.api = raw.get("api", {})
        self.memory = raw.get("memory", {})
        self.training = raw.get("training", {})
        self.curation = raw.get("curation", {})
        self.evaluation = raw.get("evaluation", {})
        self.paths = raw.get("paths", {})

    @property
    def app_name(self) -> str:
        return self.app.get("name", "HINAKU")

    @property
    def local_host(self) -> str:
        return self.local.get("host", "http://localhost:11434")

    @property
    def default_local_model(self) -> str:
        return self.local.get("default_model", "qwen3.5:4b")

    @property
    def allowed_local_models(self) -> list:
        return self.local.get("allowed_models", [self.default_local_model])

    @property
    def persona_file(self) -> Path:
        rel_or_abs = self.app.get("persona_file", "config/hinaku_persona.md")
        p = Path(rel_or_abs)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def local_options(self) -> Dict[str, Any]:
        return self.local.get("options", {
            "temperature": 0.6,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "num_predict": 300
        })

    @property
    def local_think(self) -> bool:
        return self.local.get("think", False)

    @property
    def max_context_tokens(self) -> int:
        return self.local.get("max_context_tokens", 2000)

    @property
    def sqlite_path(self) -> Path:
        import os
        env_override = os.getenv("HINAKU_DB_PATH")
        if env_override:
            return Path(env_override)
        p = self.memory.get("sqlite_path", "data/hinaku.db")
        path = Path(p)
        return path if path.is_absolute() else ROOT_DIR / path

    @property
    def router_mode(self) -> str:
        return self.router.get("mode", "auto").lower()

    @property
    def fallback_on_failure(self) -> bool:
        return self.router.get("fallback_on_failure", True)

    @property
    def local_max_prompt_tokens(self) -> int:
        return self.router.get("local_max_prompt_tokens", 1500)

    @property
    def api_provider(self) -> str:
        return self.api.get("provider", "openai_compatible").lower()

    @property
    def api_base_url(self) -> str:
        default_url = "https://api.anthropic.com/v1" if "anthropic" in self.api_provider else "https://api.openai.com/v1"
        return self.api.get("base_url", default_url).rstrip("/")

    @property
    def api_model(self) -> str:
        return self.api.get("model", "")

    @property
    def api_key_env(self) -> str:
        return self.api.get("api_key_env", "HINAKU_API_KEY")

    @property
    def api_max_tokens(self) -> int:
        return self.api.get("max_tokens", 1024)

    @property
    def api_timeout_seconds(self) -> int:
        return self.api.get("timeout_seconds", 60)

    @property
    def api_max_requests_per_day(self) -> int:
        return self.api.get("max_requests_per_day", 100)

    def get_api_key(self) -> Optional[str]:
        import os
        from dotenv import load_dotenv
        load_dotenv(ROOT_DIR / ".env")
        key = os.getenv(self.api_key_env)
        return key.strip() if key and key.strip() else None




def get_settings() -> Settings:
    return Settings(load_settings())

