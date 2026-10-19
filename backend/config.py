from pathlib import Path
from typing import Any, Dict
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

def get_settings() -> Settings:
    return Settings(load_settings())

