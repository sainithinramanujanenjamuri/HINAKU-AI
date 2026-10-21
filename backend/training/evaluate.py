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
        generate_fn: Callable[[str, Optional[List[str]]], str],
        runs: int = 2
    ) -> Dict[str, Any]:
        """
        Runs the golden set against a model generation function.
        Evaluates each model `runs` times (default 2) and uses the average score.
        """
        items = self.load_golden_set()
        question_results = []
        overall_scores = []
        cat_scores_dict: Dict[str, List[float]] = {}

        for item in items:
            prompt = item["prompt"]
            memory_fixture = item.get("memory_fixture")
            category = item.get("category", "general")

            run_scores = []
            run_replies = []
            must_inc_passed_all = True
            must_avoid_passed_all = True

            for _ in range(max(1, runs)):
                try:
                    reply = generate_fn(prompt, memory_fixture)
                except Exception as e:
                    logger.error(f"Error generating response for {item['id']} from {model_name}: {e}")
                    reply = f"[Generation error: {e}]"

                score_data = self.score_response(item, reply)
                run_scores.append(score_data["score"])
                run_replies.append(reply)
                if not score_data["must_include_passed"]:
                    must_inc_passed_all = False
                if not score_data["must_avoid_passed"]:
                    must_avoid_passed_all = False

            avg_score = round(sum(run_scores) / len(run_scores), 3)
            overall_scores.append(avg_score)
            cat_scores_dict.setdefault(category, []).append(avg_score)

            question_results.append({
                "id": item["id"],
                "category": category,
                "prompt": prompt,
                "score": avg_score,
                "run_scores": run_scores,
                "must_include_passed": must_inc_passed_all,
                "must_avoid_passed": must_avoid_passed_all,
                "response": run_replies[0] if run_replies else ""
            })

        mean_score = round(sum(overall_scores) / len(overall_scores), 3) if overall_scores else 0.0
        category_averages = {
            cat: round(sum(scs) / len(scs), 3)
            for cat, scs in cat_scores_dict.items()
        }

        return {
            "model_name": model_name,
            "overall_score": mean_score,
            "total_questions": len(items),
            "category_scores": category_averages,
            "question_results": question_results
        }

    def run_full_comparison(
        self,
        candidate_gen: Callable[[str, Optional[List[str]]], str],
        local_gen: Callable[[str, Optional[List[str]]], str],
        api_gen: Optional[Callable[[str, Optional[List[str]]], str]] = None,
        candidate_name: str = "Candidate (Fine-tuned)",
        local_name: str = "Current Local (gemma3:4b)",
        api_name: str = "API Model",
        runs: int = 2
    ) -> Dict[str, Any]:
        """
        Compares candidate model vs current local model vs API model.
        Evaluates each model twice and uses the average.
        Promotion requires beating current model by at least 3 prompts overall
        with no category getting worse.
        """
        cand_eval = self.evaluate_model(candidate_name, candidate_gen, runs=runs)
        local_eval = self.evaluate_model(local_name, local_gen, runs=runs)
        api_eval = self.evaluate_model(api_name, api_gen, runs=runs) if api_gen else None

        cand_score = cand_eval["overall_score"]
        local_score = local_eval["overall_score"]
        api_score = api_eval["overall_score"] if api_eval else None

        # Prompt-by-prompt win/loss calculation
        cand_q_map = {q["id"]: q for q in cand_eval["question_results"]}
        loc_q_map = {q["id"]: q for q in local_eval["question_results"]}
        api_q_map = {q["id"]: q for q in api_eval["question_results"]} if api_eval else {}

        candidate_wins = 0
        local_wins = 0
        ties = 0
        side_by_side = []

        for q_id, c_q in cand_q_map.items():
            l_q = loc_q_map.get(q_id)
            if not l_q:
                continue

            c_sc = c_q["score"]
            l_sc = l_q["score"]
            a_sc = api_q_map.get(q_id, {}).get("score") if api_eval else None

            if c_sc > l_sc:
                candidate_wins += 1
            elif l_sc > c_sc:
                local_wins += 1
            else:
                ties += 1

            side_by_side.append({
                "id": q_id,
                "category": c_q["category"],
                "prompt": c_q["prompt"],
                "candidate_score": c_sc,
                "local_score": l_sc,
                "api_score": a_sc,
                "candidate_response": c_q["response"],
                "local_response": l_q["response"],
                "api_response": api_q_map.get(q_id, {}).get("response", "") if api_eval else None
            })

        prompts_margin = candidate_wins - local_wins

        # Category level checks (candidate must not be worse in any category)
        cand_cats = cand_eval.get("category_scores", {})
        local_cats = local_eval.get("category_scores", {})
        api_cats = api_eval.get("category_scores", {}) if api_eval else {}

        all_categories = sorted(set(list(cand_cats.keys()) + list(local_cats.keys())))
        category_table = {}
        no_category_worse = True

        for cat in all_categories:
            c_cat = cand_cats.get(cat, 0.0)
            l_cat = local_cats.get(cat, 0.0)
            a_cat = api_cats.get(cat)
            worse = c_cat < (l_cat - 0.001)
            if worse:
                no_category_worse = False

            category_table[cat] = {
                "candidate": c_cat,
                "local": l_cat,
                "api": a_cat,
                "margin": round(c_cat - l_cat, 3),
                "worse": worse
            }

        # Promotion rule: beating current model by at least 3 prompts overall with no category getting worse
        required_advantage = min(3, len(cand_q_map))
        promotable = (prompts_margin >= required_advantage) and no_category_worse
        improvement_margin = round(cand_score - local_score, 3)

        return {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "candidate_name": candidate_name,
            "candidate_score": cand_score,
            "local_name": local_name,
            "local_score": local_score,
            "api_name": api_name if api_eval else None,
            "api_score": api_score,
            "improvement_margin": improvement_margin,
            "prompts_margin": prompts_margin,
            "candidate_wins": candidate_wins,
            "local_wins": local_wins,
            "ties": ties,
            "no_category_worse": no_category_worse,
            "category_table": category_table,
            "side_by_side": side_by_side,
            "promotable": promotable,
            "min_prompts_advantage_required": 3,
            "candidate_eval": cand_eval,
            "local_eval": local_eval,
            "api_eval": api_eval
        }
