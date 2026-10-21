import datetime
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import get_settings, ROOT_DIR

logger = logging.getLogger(__name__)

class ModelPromoter:
    def __init__(self, data_dir: Optional[Path] = None, models_dir: Optional[Path] = None):
        settings = get_settings()
        if data_dir:
            self.promotions_file = Path(data_dir) / "promotions.json"
            self.pending_file = Path(data_dir) / "pending_promotion.json"
        else:
            self.promotions_file = settings.sqlite_path.parent / "promotions.json"
            self.pending_file = settings.sqlite_path.parent / "pending_promotion.json"
        self.models_dir = Path(models_dir) if models_dir else settings.models_dir
        self.keep_versions = settings.training_keep_versions
        self.min_improvement = settings.eval_min_improvement

    def _load_history(self) -> List[Dict[str, Any]]:
        if not self.promotions_file.exists():
            return []
        try:
            with open(self.promotions_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading promotions ledger {self.promotions_file}: {e}")
            return []

    def _save_history(self, history: List[Dict[str, Any]]):
        self.promotions_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.promotions_file, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    def get_history(self) -> List[Dict[str, Any]]:
        return self._load_history()

    def get_active_model(self) -> Optional[Dict[str, Any]]:
        history = self._load_history()
        for item in reversed(history):
            if item.get("status") == "active":
                return item
        return None

    def get_pending_candidate(self) -> Optional[Dict[str, Any]]:
        """Retrieves candidate model awaiting owner confirmation."""
        if not self.pending_file.exists():
            return None
        try:
            with open(self.pending_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading pending promotion {self.pending_file}: {e}")
            return None

    def set_pending_candidate(self, candidate_data: Dict[str, Any]):
        """Saves candidate model details for UI approval gate."""
        self.pending_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.pending_file, "w", encoding="utf-8") as f:
            json.dump(candidate_data, f, indent=2)

    def clear_pending_candidate(self):
        """Clears pending promotion candidate upon promotion or rejection."""
        if self.pending_file.exists():
            try:
                self.pending_file.unlink()
            except Exception as e:
                logger.error(f"Error removing pending promotion file: {e}")

    def can_promote(self, candidate_score: float, current_local_score: float) -> Tuple[bool, str]:
        margin = round(candidate_score - current_local_score, 3)
        if margin >= self.min_improvement:
            return True, f"Candidate model surpassed current local model by {margin:.1%} (required: {self.min_improvement:.1%})."
        else:
            return False, f"Candidate model scored {candidate_score:.1%}, failing to beat current local model ({current_local_score:.1%}) by required margin of {self.min_improvement:.1%}."

    def promote(
        self,
        version: str,
        candidate_score: float,
        current_local_score: float,
        confirmed: bool = False,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        Promotes a candidate model if evaluation condition is satisfied AND explicit owner confirmation is given.
        Hard rule: No trained model may be promoted or activated without explicit confirmation!
        """
        if not confirmed:
            raise ValueError("Approval gate: Model promotion requires explicit owner confirmation in the UI.")

        eligible, reason = self.can_promote(candidate_score, current_local_score)
        if not eligible:
            raise ValueError(f"Promotion rejected: {reason}")

        history = self._load_history()

        # Mark any previously active model as 'superseded'
        for entry in history:
            if entry.get("status") == "active":
                entry["status"] = "superseded"

        ollama_name = f"hinaku-{version}"
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        record = {
            "version": version,
            "ollama_name": ollama_name,
            "candidate_score": candidate_score,
            "previous_local_score": current_local_score,
            "improvement_margin": round(candidate_score - current_local_score, 3),
            "promoted_at": now_str,
            "status": "active",
            "dry_run": dry_run
        }

        history.append(record)
        self._save_history(history)

        # Clear any pending candidate entry once promoted
        self.clear_pending_candidate()

        # Enforce keeping last N versions
        self._prune_old_versions()

        logger.info(f"Successfully promoted model version {version} as {ollama_name} (status=active)")
        return record

    def rollback(self, target_version: Optional[str] = None) -> Dict[str, Any]:
        """
        Rolls back the active model to the previously superseded version or target_version.
        """
        history = self._load_history()
        if not history:
            raise RuntimeError("No promotion history available to rollback to.")

        # Find target record
        target_entry = None
        if target_version:
            for entry in reversed(history):
                if entry.get("version") == target_version:
                    target_entry = entry
                    break
            if not target_entry:
                raise ValueError(f"Target version {target_version} not found in promotion history.")
        else:
            # Find the most recent superseded entry
            for entry in reversed(history):
                if entry.get("status") in ("superseded", "rolled_back"):
                    target_entry = entry
                    break
            if not target_entry:
                raise RuntimeError("No previous version found to rollback to.")

        # Update statuses
        for entry in history:
            if entry.get("status") == "active":
                entry["status"] = "rolled_back"

        target_entry["status"] = "active"
        target_entry["rolled_back_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._save_history(history)

        logger.info(f"Rollback successful: Active model is now {target_entry['version']} ({target_entry['ollama_name']})")
        return target_entry

    def _prune_old_versions(self):
        """Retains last N promoted versions in history and models directory."""
        history = self._load_history()
        if len(history) <= self.keep_versions:
            return

        kept = history[-self.keep_versions:]
        self._save_history(kept)
