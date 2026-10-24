from pathlib import Path
from typing import Any, Dict, List, Optional
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
        self.guards = raw.get("guards", {})

    @property
    def app_name(self) -> str:
        return self.app.get("name", "HINAKU")

    @property
    def local_host(self) -> str:
        return self.local.get("host", "http://localhost:11434")

    @property
    def default_local_model(self) -> str:
        return self.local.get("default_model", "gemma3:4b")

    @property
    def local_keep_alive(self) -> str:
        return str(self.local.get("keep_alive", "30m"))

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
            "presence_penalty": 0.0,
            "num_predict": 300
        })

    @property
    def bakeoff_models(self) -> List[str]:
        return self.raw.get("bakeoff", {}).get("models", [
            "qwen3.5:4b",
            "qwen3:4b",
            "llama3.2:3b",
            "qwen2.5:3b",
            "gemma3:4b"
        ])

    @property
    def local_think(self) -> bool:
        return self.local.get("think", False)

    @property
    def quality_mode(self) -> bool:
        return bool(self.local.get("quality_mode", False))

    @property
    def think_harder_num_predict(self) -> int:
        return int(self.local.get("think_harder_num_predict", 3000))

    @property
    def think_num_predict(self) -> int:
        return int(self.local.get("think_num_predict", self.local.get("think_harder_num_predict", 3000)))

    @property
    def detail_num_predict(self) -> int:
        return int(self.local.get("detail_num_predict", 900))

    @property
    def think_harder_timeout_seconds(self) -> float:
        return float(self.local.get("think_harder_timeout_seconds", 60.0))

    @property
    def hard_timeout_seconds(self) -> float:
        return float(self.local.get("hard_timeout_seconds", 120.0))

    @property
    def supports_think_models(self) -> list:
        return self.local.get("supports_think", [
            "qwen3.5:4b",
            "qwen3:4b",
            "bonsai-2:9b",
            "bonsai-2:27b",
            "qwen3.5:9b"
        ])

    @property
    def model_options(self) -> Dict[str, Dict[str, Any]]:
        return self.local.get("model_options", {})

    def get_model_options(self, model_name: str) -> Dict[str, Any]:
        """Return merged generation options for a specific model."""
        base = dict(self.local_options)
        if model_name in self.model_options:
            base.update(self.model_options[model_name])
        return base

    @property
    def max_context_tokens(self) -> int:
        return int(self.local.get("max_context_tokens", 2500))

    @property
    def local_num_ctx(self) -> int:
        return int(self.local_options.get("num_ctx", 4096))

    @property
    def sqlite_path(self) -> Path:
        import os, tempfile
        env_override = os.getenv("HINAKU_DB_PATH")
        if env_override:
            return Path(env_override)
        if os.getenv("HINAKU_USE_REAL_DATA") == "1":
            p = self.memory.get("sqlite_path", "data/hinaku.db")
            path = Path(p)
            return path if path.is_absolute() else ROOT_DIR / path
        # By default, any process without HINAKU_USE_REAL_DATA=1 uses an isolated temp directory
        temp_dir = Path(tempfile.gettempdir()) / "hinaku_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir / "hinaku.db"

    @property
    def router_mode(self) -> str:
        return self.router.get("mode", "auto").lower()

    @property
    def fallback_on_failure(self) -> bool:
        return self.router.get("fallback_on_failure", True)

    @property
    def detail_route_to_api(self) -> bool:
        return bool(self.router.get("detail_route_to_api", True))

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

    @property
    def api_logged_by_provider(self) -> bool:
        return self.api.get("logged_by_provider", False)

    @property
    def api_send_personal_context(self) -> bool:
        return self.api.get("send_personal_context", False)

    @property
    def chroma_path(self) -> Path:
        import os, tempfile
        env_override = os.getenv("HINAKU_CHROMA_PATH")
        if env_override:
            return Path(env_override)
        if os.getenv("HINAKU_USE_REAL_DATA") == "1":
            p = self.memory.get("chroma_path", "data/chroma")
            path = Path(p)
            return path if path.is_absolute() else ROOT_DIR / path
        # By default, any process without HINAKU_USE_REAL_DATA=1 uses an isolated temp directory
        temp_dir = Path(tempfile.gettempdir()) / "hinaku_temp" / "chroma"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    @property
    def memory_enabled(self) -> bool:
        return self.memory.get("enabled", True)

    @property
    def memory_extract_after_each_turn(self) -> bool:
        return self.memory.get("extract_after_each_turn", True)

    @property
    def memory_learn_from_private_chats(self) -> bool:
        return self.memory.get("learn_from_private_chats", False)

    @property
    def memory_retrieve_top_k(self) -> int:
        return self.memory.get("retrieve_top_k", 3)

    @property
    def memory_min_similarity(self) -> float:
        return float(self.memory.get("min_similarity", 0.46))

    @property
    def memory_embedding_model(self) -> str:
        return self.memory.get("embedding_model", "qwen3-embedding:0.6b")

    @property
    def memory_embedding_dims(self) -> int:
        return self.memory.get("embedding_dims", 1024)

    @property
    def memory_query_prefix(self) -> str:
        return self.memory.get("query_prefix", "Instruct: Given the owner's message, retrieve stored facts about the owner that help answer it\nQuery: ")

    @property
    def memory_document_prefix(self) -> str:
        return self.memory.get("document_prefix", "")

    @property
    def memory_merge_similar(self) -> bool:
        return self.memory.get("merge_similar", True)

    @property
    def memory_merge_threshold(self) -> float:
        return float(self.memory.get("merge_threshold", 0.80))

    @property
    def memory_never_store(self) -> List[str]:
        return self.memory.get("never_store", [
            "passwords",
            "api_keys",
            "government_id_numbers",
            "bank_or_card_numbers"
        ])

    @property
    def guards_sensitive_data_enabled(self) -> bool:
        return self.guards.get("sensitive_data", {}).get("enabled", True)

    @property
    def guards_sensitive_data_reply(self) -> str:
        return self.guards.get("sensitive_data", {}).get(
            "reply",
            "I won't store PINs, passwords, or card numbers. A password manager is the right place for them."
        )

    @property
    def guards_live_data_enabled(self) -> bool:
        return self.guards.get("live_data", {}).get("enabled", True)

    @property
    def guards_live_data_reply(self) -> str:
        return self.guards.get("live_data", {}).get(
            "reply",
            "I don't have access to live data like real-time prices, current weather, or today's news. A search engine or dedicated tracker is the right place for that."
        )

    @property
    def guards_live_data_patterns(self) -> List[str]:
        return self.guards.get("live_data", {}).get("patterns", [
            r"(?i)\b(?:current|latest|today'?s?|yesterday'?s?|live)\b.*\b(?:stock|share|crypto|bitcoin|btc|eth|market|price|quote|close|closing)\b",
            r"(?i)\b(?:what\s+is|what's|how\s+much\s+is)\b.*\b(?:stock|share|crypto|bitcoin|btc|eth|market)\s+(?:price|value|worth)\b",
            r"(?i)\b(?:what\s+was)\b.*\b(?:closing\s+price|market\s+close)\b",
            r"(?i)\b(?:nvidia'?s?|apple'?s?|tesla'?s?|google'?s?|microsoft'?s?)\s+(?:closing\s+price|stock\s+price|current\s+price)\b",
            r"(?i)\b(?:what\s+is\s+the\s+weather|current\s+weather|weather\s+today|weather\s+forecast|is\s+it\s+raining\s+outside|temperature\s+outside)\b",
            r"(?i)\b(?:today'?s?|current|breaking|latest)\s+(?:news|headlines)\b",
            r"(?i)\b(?:score\s+of|who\s+won)\b.*\b(?:game|match|today|yesterday|super\s*bowl|world\s*cup|nba|ipl)\b",
            r"(?i)\b(?:what\s+(?:time|day|date)\s+is\s+it|what\s+is\s+today'?s?\s+date|current\s+time)\b",
            r"(?i)\blatest\b\s+(?:news|headlines|score|stock\s+price)\b"
        ])

    @property
    def datasets_dir(self) -> Path:
        import os, tempfile
        env_override = os.getenv("HINAKU_DATASETS_DIR")
        if env_override:
            return Path(env_override)
        if os.getenv("HINAKU_USE_REAL_DATA") == "1":
            p = self.training.get("datasets_dir", "data/datasets")
            path = Path(p)
            return path if path.is_absolute() else ROOT_DIR / path
        temp_dir = Path(tempfile.gettempdir()) / "hinaku_temp" / "datasets"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    @property
    def curation_min_examples(self) -> int:
        return int(self.curation.get("min_examples_to_train", 200))

    @property
    def models_dir(self) -> Path:
        import os, tempfile
        env_override = os.getenv("HINAKU_MODELS_DIR")
        if env_override:
            return Path(env_override)
        if os.getenv("HINAKU_USE_REAL_DATA") == "1":
            p = self.training.get("models_dir", "models")
            path = Path(p)
            return path if path.is_absolute() else ROOT_DIR / path
        temp_dir = Path(tempfile.gettempdir()) / "hinaku_temp" / "models"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    @property
    def training_temp_dir(self) -> Path:
        raw = self.training.get("training_temp_dir", r"D:\hinaku-tmp")
        p = Path(raw)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def hf_cache_dir(self) -> Path:
        raw = self.training.get("hf_cache_dir", r"D:\hf-cache")
        p = Path(raw)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def training_min_vram_gb(self) -> float:
        return float(self.training.get("min_vram_gb", 5.5))

    @property
    def training_base_model(self) -> str:
        return str(self.training.get("base_model", "Qwen/Qwen2.5-1.5B-Instruct"))

    @property
    def eval_golden_file(self) -> Path:
        p = self.evaluation.get("golden_file", "eval/golden.jsonl")
        path = Path(p)
        return path if path.is_absolute() else ROOT_DIR / path

    @property
    def eval_min_improvement(self) -> float:
        return float(self.evaluation.get("min_improvement", 0.02))


    @property
    def helpline_numbers(self) -> List[Dict[str, str]]:
        return self.raw.get("safety", {}).get("helpline_numbers", [])

    @property
    def training_keep_versions(self) -> int:
        return int(self.training.get("keep_versions", 3))


    @property
    def memory_embedding_keep_alive(self) -> str:
        return str(self.memory.get("embedding_keep_alive", "5m"))

    @property
    def memory_embedding_num_ctx(self) -> int:
        return int(self.memory.get("embedding_num_ctx", 512))

    @property
    def curation_min_examples_to_train(self) -> int:
        return self.curation_min_examples

    @property
    def curation_api_answers_require_thumbs_up(self) -> bool:
        return bool(self.curation.get("api_answers_require_thumbs_up", True))

    @property
    def curation_exclude_api_answers(self) -> bool:
        return bool(self.curation.get("exclude_api_answers", False))

    @property
    def router_personal_statement_patterns(self) -> List[str]:
        return self.router.get("personal_statement_patterns", [])

    @property
    def router_task_request_patterns(self) -> List[str]:
        return self.router.get("task_request_patterns", [])

    def get_api_key(self) -> Optional[str]:
        import os
        from dotenv import load_dotenv
        load_dotenv(ROOT_DIR / ".env")
        key = os.getenv(self.api_key_env)
        return key.strip() if key and key.strip() else None




_settings_instance: Optional[Settings] = None

def get_settings(reload: bool = False) -> Settings:
    global _settings_instance
    if _settings_instance is None or reload:
        _settings_instance = Settings(load_settings())
    return _settings_instance

