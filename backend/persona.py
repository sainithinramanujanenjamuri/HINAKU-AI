import logging
from pathlib import Path
from typing import NamedTuple, Optional

logger = logging.getLogger("hinaku.persona")

# Requirement 4: minimal neutral prompt if persona file is missing or empty
DEFAULT_FALLBACK_PROMPT = "You are a helpful, neutral AI assistant."

class PersonaState(NamedTuple):
    content: str
    is_fallback: bool
    notice: Optional[str]

class PersonaManager:
    """
    Manages loading and hot-reloading of HINAKU persona from file.
    Reloads automatically when file modification time changes.
    Falls back to a minimal neutral prompt if missing or empty.
    """
    def __init__(self, file_path: Optional[Path] = None):
        self._file_path = file_path
        self._last_mtime: Optional[float] = None
        self._cached_content: str = DEFAULT_FALLBACK_PROMPT
        self._is_fallback: bool = False
        self._notice: Optional[str] = None

    @property
    def file_path(self) -> Optional[Path]:
        return self._file_path

    def set_file_path(self, path: Path):
        self._file_path = path
        self._last_mtime = None

    def get_persona(self, file_path: Optional[Path] = None) -> PersonaState:
        target_path = file_path or self._file_path
        if not target_path:
            logger.warning("No persona file path configured. Using neutral fallback prompt.")
            return PersonaState(
                content=DEFAULT_FALLBACK_PROMPT,
                is_fallback=True,
                notice="Persona file path not configured. Using neutral fallback prompt."
            )

        if not target_path.exists():
            if not self._is_fallback or self._notice != f"Persona file '{target_path.name}' is missing":
                logger.warning(f"Persona file missing at '{target_path}'. Using neutral fallback prompt.")
            self._is_fallback = True
            self._notice = f"Persona file '{target_path.name}' is missing. Using neutral fallback prompt."
            self._cached_content = DEFAULT_FALLBACK_PROMPT
            self._last_mtime = None
            return PersonaState(self._cached_content, self._is_fallback, self._notice)

        try:
            current_mtime = target_path.stat().st_mtime
            if self._last_mtime != current_mtime:
                text = target_path.read_text(encoding="utf-8").strip()
                self._last_mtime = current_mtime
                if not text:
                    logger.warning(f"Persona file '{target_path.name}' is empty. Using neutral fallback prompt.")
                    self._is_fallback = True
                    self._notice = f"Persona file '{target_path.name}' is empty. Using neutral fallback prompt."
                    self._cached_content = DEFAULT_FALLBACK_PROMPT
                else:
                    self._is_fallback = False
                    self._notice = None
                    self._cached_content = text
        except Exception as e:
            logger.warning(f"Error reading persona file '{target_path}': {e}. Using neutral fallback prompt.")
            self._is_fallback = True
            self._notice = f"Error reading persona file: {e}. Using neutral fallback prompt."
            self._cached_content = DEFAULT_FALLBACK_PROMPT

        return PersonaState(self._cached_content, self._is_fallback, self._notice)

