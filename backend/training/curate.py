import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import get_settings, ROOT_DIR
from backend.history import ChatHistoryManager
from backend.guards import check_and_redact_sensitive_data
from backend.persona import PersonaManager

logger = logging.getLogger(__name__)

class DatasetCurator:
    def __init__(
        self,
        history_manager: Optional[ChatHistoryManager] = None,
        persona_manager: Optional[PersonaManager] = None,
        datasets_dir: Optional[Path] = None
    ):
        settings = get_settings()
        self.history_manager = history_manager or ChatHistoryManager(settings.sqlite_path)
        self.persona_manager = persona_manager or PersonaManager(settings.persona_file)
        self.datasets_dir = Path(datasets_dir) if datasets_dir else settings.datasets_dir

    def get_candidate_interactions(self) -> List[Dict[str, Any]]:
        """
        Retrieves and filters interactions suitable for instruction-tuning dataset:
        Includes:
          - feedback == 'thumbs_up'
          - owner-edited answers (edited_answer is not null and not empty)
          - accepted API answers (backend == 'api' and feedback != 'thumbs_down')
        Excludes:
          - feedback == 'thumbs_down'
          - marked private (conversation.is_private == 1)
          - deleted conversations or deleted messages
          - guard replies (backend == 'guard')
          - text containing sensitive data (passwords, PINs, card/bank numbers, IDs, API keys)
          - blank prompt or answer
        """
        with self.history_manager._get_connection() as conn:
            query = """
                SELECT i.id, i.conversation_id, i.message_id, i.user_prompt, i.answer,
                       i.model, i.backend, i.feedback, i.edited_answer, i.created_at,
                       c.is_private, c.id AS conv_exists,
                       m.id AS msg_exists
                FROM interactions i
                LEFT JOIN conversations c ON i.conversation_id = c.id
                LEFT JOIN messages m ON i.message_id = m.id
                WHERE (i.backend != 'guard' OR i.backend IS NULL)
                  AND (i.feedback != 'thumbs_down' OR i.feedback IS NULL)
                  AND (c.is_private IS NULL OR c.is_private = 0)
                  AND (
                      i.feedback = 'thumbs_up'
                      OR (i.edited_answer IS NOT NULL AND TRIM(i.edited_answer) != '')
                      OR (i.backend = 'api' AND (i.feedback IS NULL OR i.feedback != 'thumbs_down'))
                  )
                ORDER BY i.created_at ASC
            """
            rows = conn.execute(query).fetchall()

        candidates = []
        for row in rows:
            r = dict(row)

            # Drop if conversation was deleted
            if not r.get("conv_exists"):
                continue

            # Drop if specific message was deleted from conversation
            if r.get("message_id") and not r.get("msg_exists"):
                continue

            user_prompt = (r.get("user_prompt") or "").strip()
            edited = (r.get("edited_answer") or "").strip()
            orig_answer = (r.get("answer") or "").strip()
            final_answer = edited if edited else orig_answer

            if not user_prompt or not final_answer:
                continue

            # Drop anything containing sensitive data (PIN, passwords, card/bank numbers, IDs)
            is_sens_p, _ = check_and_redact_sensitive_data(user_prompt)
            if is_sens_p:
                continue
            is_sens_a, _ = check_and_redact_sensitive_data(final_answer)
            if is_sens_a:
                continue

            # Determine reason for inclusion
            reasons = []
            if r.get("feedback") == "thumbs_up":
                reasons.append("thumbs_up")
            if edited:
                reasons.append("owner_edited")
            if r.get("backend") == "api" and r.get("feedback") != "thumbs_down":
                reasons.append("accepted_api")

            candidates.append({
                "interaction_id": r["id"],
                "conversation_id": r["conversation_id"],
                "message_id": r.get("message_id"),
                "user_prompt": user_prompt,
                "original_answer": orig_answer,
                "final_answer": final_answer,
                "is_edited": bool(edited),
                "feedback": r.get("feedback"),
                "backend": r.get("backend") or "local",
                "model": r.get("model") or "unknown",
                "inclusion_reasons": reasons,
                "created_at": r.get("created_at")
            })

        return candidates

    def get_curation_summary(self) -> Dict[str, Any]:
        settings = get_settings()
        candidates = self.get_candidate_interactions()
        min_required = settings.curation_min_examples

        reasons_count = {"thumbs_up": 0, "owner_edited": 0, "accepted_api": 0}
        for c in candidates:
            for r in c["inclusion_reasons"]:
                if r in reasons_count:
                    reasons_count[r] += 1

        return {
            "total_candidates": len(candidates),
            "min_examples_required": min_required,
            "ready_for_training": len(candidates) >= min_required,
            "breakdown": reasons_count,
            "candidates": candidates
        }

    def exclude_interaction(self, interaction_id: str) -> bool:
        """Excludes an item by marking feedback as thumbs_down."""
        return self.history_manager.update_interaction_feedback(
            interaction_id=interaction_id,
            feedback="thumbs_down"
        )

    def build_dataset(
        self,
        excluded_ids: Optional[List[str]] = None,
        version: Optional[str] = None
    ) -> Tuple[Path, Dict[str, Any]]:
        """
        Builds a versioned dataset in data/datasets/YYYY-MM/train.jsonl
        using instruction-tuning format including the persona prompt.
        """
        excluded_set = set(excluded_ids or [])
        all_candidates = self.get_candidate_interactions()
        filtered = [c for c in all_candidates if c["interaction_id"] not in excluded_set]

        # Version string defaults to current YYYY-MM
        now = datetime.datetime.now(datetime.timezone.utc)
        ver = version or now.strftime("%Y-%m")

        version_dir = self.datasets_dir / ver
        version_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = version_dir / "train.jsonl"
        meta_path = version_dir / "metadata.json"

        persona_state = self.persona_manager.get_persona()
        persona_content = persona_state.content

        # Write train.jsonl in instruction format
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for item in filtered:
                entry = {
                    "instruction": persona_content,
                    "input": item["user_prompt"],
                    "output": item["final_answer"]
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        metadata = {
            "version": ver,
            "created_at": now.isoformat(),
            "example_count": len(filtered),
            "total_candidates_examined": len(all_candidates),
            "excluded_by_user": len(excluded_set),
            "persona_file": str(self.persona_manager.file_path),
            "interaction_ids": [c["interaction_id"] for c in filtered]
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return jsonl_path, metadata

    def list_datasets(self) -> List[Dict[str, Any]]:
        """Lists available versioned datasets in datasets_dir."""
        results = []
        if not self.datasets_dir.exists():
            return results

        for child in sorted(self.datasets_dir.iterdir(), reverse=True):
            if child.is_dir():
                meta_file = child / "metadata.json"
                jsonl_file = child / "train.jsonl"
                if meta_file.exists():
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            data["dataset_path"] = str(jsonl_file)
                            results.append(data)
                    except Exception as e:
                        logger.error(f"Error reading {meta_file}: {e}")
                elif jsonl_file.exists():
                    results.append({
                        "version": child.name,
                        "dataset_path": str(jsonl_file),
                        "example_count": sum(1 for _ in open(jsonl_file, "r", encoding="utf-8"))
                    })
        return results
