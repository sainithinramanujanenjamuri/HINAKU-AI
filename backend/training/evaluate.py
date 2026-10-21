import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.config import get_settings, ROOT_DIR

logger = logging.getLogger(__name__)

class EvaluationHarness:
    def __init__(self, golden_file: Optional[Path] = None):
        settings = get_settings()
        self.golden_file = Path(golden_file) if golden_file else settings.eval_golden_file
        self.min_improvement = settings.eval_min_improvement

    def load_golden_set(self) -> List[Dict[str, Any]]:
        if not self.golden_file.exists():
            raise FileNotFoundError(f"Golden evaluation file not found: {self.golden_file}")

        items = []
        with open(self.golden_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
        return items

    def score_response(self, item: Dict[str, Any], response: str) -> Dict[str, Any]:
        """
        Scores a single response against golden item requirements:
        - must_include substrings (40% weight)
        - must_avoid substrings (30% weight)
        - persona style and length (30% weight)
        """
        text = response.strip()
        text_lower = text.lower()
        must_include = item.get("must_include", [])
        must_avoid = item.get("must_avoid", [])

        # 1. must_include check
        if must_include:
            inc_hits = sum(1 for inc in must_include if inc.lower() in text_lower)
            inc_score = inc_hits / len(must_include)
        else:
            inc_score = 1.0

        # 2. must_avoid check
        if must_avoid:
            avoid_violations = sum(1 for av in must_avoid if av.lower() in text_lower)
            avoid_score = 0.0 if avoid_violations > 0 else 1.0
        else:
            avoid_score = 1.0

        # 3. persona tone and concise style
        style_score = 1.0
        # Check for excessive exclamation marks or gushing
        if text.count("!") > 2 or "omg" in text_lower:
            style_score -= 0.3
        # Check for empty response
        if not text:
            style_score = 0.0
        # Check for extreme wordiness on concise prompt requests
        word_count = len(text.split())
        if "concise" in item.get("ideal", "").lower() and word_count > 60:
            style_score -= 0.3

        style_score = max(0.0, style_score)

        final_score = round((inc_score * 0.4) + (avoid_score * 0.3) + (style_score * 0.3), 3)

        return {
            "score": final_score,
            "must_include_passed": inc_score == 1.0,
            "must_avoid_passed": avoid_score == 1.0,
            "style_score": round(style_score, 2),
            "response": text
        }

    def evaluate_model(
        self,
        model_name: str,
        generate_fn: Callable[[str, Optional[List[str]]], str]
    ) -> Dict[str, Any]:
        """Runs the golden set against a model generation function."""
        items = self.load_golden_set()
        question_results = []
        scores = []

        for item in items:
            prompt = item["prompt"]
            memory_fixture = item.get("memory_fixture")
            try:
                reply = generate_fn(prompt, memory_fixture)
            except Exception as e:
                logger.error(f"Error generating response for {item['id']} from {model_name}: {e}")
                reply = f"[Generation error: {e}]"

            score_data = self.score_response(item, reply)
            scores.append(score_data["score"])
            question_results.append({
                "id": item["id"],
                "category": item.get("category", "general"),
                "prompt": prompt,
                "score": score_data["score"],
                "must_include_passed": score_data["must_include_passed"],
                "must_avoid_passed": score_data["must_avoid_passed"],
                "response": reply
            })

        mean_score = round(sum(scores) / len(scores), 3) if scores else 0.0
        return {
            "model_name": model_name,
            "overall_score": mean_score,
            "total_questions": len(items),
            "question_results": question_results
        }

    def run_full_comparison(
        self,
        candidate_gen: Callable[[str, Optional[List[str]]], str],
        local_gen: Callable[[str, Optional[List[str]]], str],
        api_gen: Optional[Callable[[str, Optional[List[str]]], str]] = None,
        candidate_name: str = "Candidate (Fine-tuned)",
        local_name: str = "Current Local (gemma3:4b)",
        api_name: str = "API Model"
    ) -> Dict[str, Any]:
        """
        Compares candidate model vs current local model vs API model.
        Promotable only if candidate_score - local_score >= min_improvement.
        """
        cand_eval = self.evaluate_model(candidate_name, candidate_gen)
        local_eval = self.evaluate_model(local_name, local_gen)
        api_eval = self.evaluate_model(api_name, api_gen) if api_gen else None

        cand_score = cand_eval["overall_score"]
        local_score = local_eval["overall_score"]
        api_score = api_eval["overall_score"] if api_eval else None

        margin = round(cand_score - local_score, 3)
        promotable = margin >= self.min_improvement

        return {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "candidate_name": candidate_name,
            "candidate_score": cand_score,
            "local_name": local_name,
            "local_score": local_score,
            "api_name": api_name if api_eval else None,
            "api_score": api_score,
            "improvement_margin": margin,
            "min_improvement_required": self.min_improvement,
            "promotable": promotable,
            "candidate_eval": cand_eval,
            "local_eval": local_eval,
            "api_eval": api_eval
        }
