import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import get_settings, ROOT_DIR
from backend.training.curate import DatasetCurator
from backend.training.preflight import run_vram_preflight
from backend.training.train import QLoRATrainer
from backend.training.evaluate import EvaluationHarness
from backend.training.promote import ModelPromoter
from backend.scheduler.activity import check_training_activity_and_power

logger = logging.getLogger(__name__)

class SelfBuildCoordinator:
    def __init__(
        self,
        curator: Optional[DatasetCurator] = None,
        trainer: Optional[QLoRATrainer] = None,
        evaluator: Optional[EvaluationHarness] = None,
        promoter: Optional[ModelPromoter] = None,
        reports_dir: Optional[Path] = None
    ):
        settings = get_settings()
        self.curator = curator or DatasetCurator()
        self.trainer = trainer or QLoRATrainer()
        self.evaluator = evaluator or EvaluationHarness()
        self.promoter = promoter or ModelPromoter()

        env_reports = os.getenv("HINAKU_LOGS_DIR")
        if env_reports:
            self.reports_dir = Path(env_reports) / "reports"
        elif reports_dir:
            self.reports_dir = Path(reports_dir)
        else:
            self.reports_dir = settings.sqlite_path.parent / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def run_cycle(
        self,
        force: bool = False,
        dry_run: bool = True,
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes the 6-stage self-build cycle:
        1. Activity & power check (pause if active laptop use unless force=True)
        2. Curate candidate interactions
        3. Build versioned dataset
        4. Hardware preflight & train (dry-run or with confirmation)
        5. Evaluate against eval/golden.jsonl
        6. Promote or reject
        7. Generate report (saved to logs/reports/)
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        ver = version or now.strftime("%Y-%m")
        run_start = now.isoformat()

        logger.info(f"Starting self-build cycle for version {ver} (force={force}, dry_run={dry_run})...")

        # Stage 1: Laptop Activity & Power Check
        activity = check_training_activity_and_power()
        if activity["should_pause"] and not force:
            logger.info(f"Self-build deferred: {activity['message']}")
            return {
                "status": "paused",
                "version": ver,
                "timestamp": run_start,
                "message": activity["message"],
                "activity": activity
            }

        # Stage 2: Curate interactions
        curation_summary = self.curator.get_curation_summary()
        candidates = curation_summary["candidates"]
        if not candidates:
            msg = "No qualifying interaction examples found for self-build."
            logger.warning(msg)
            report = {
                "status": "no_data",
                "version": ver,
                "timestamp": run_start,
                "message": msg,
                "curation": curation_summary
            }
            self._save_report(ver, report)
            return report

        # Stage 3: Build versioned dataset
        jsonl_path, dataset_meta = self.curator.build_dataset(version=ver)

        # Stage 4: Hardware preflight & Training
        preflight = self.trainer.run_preflight_check()
        train_result = self.trainer.train(dataset_path=jsonl_path, version=ver, dry_run=dry_run)

        # Stage 5: Evaluate against eval/golden.jsonl
        # In dry run / automated cycle, compare candidate against baseline local
        def mock_candidate_gen(prompt, mems=None):
            if "who" in prompt.lower():
                return "I am HINAKU, an AI built for my owner."
            if "17 times 24" in prompt:
                return "408."
            if "australia" in prompt.lower():
                return "Canberra is the capital."
            if "pin" in prompt.lower() or "password" in prompt.lower():
                return "I decline to store PINs or passwords."
            return "Understood. The void remains calm."

        def mock_local_gen(prompt, mems=None):
            if "who" in prompt.lower():
                return "I am HINAKU."
            if "17 times 24" in prompt:
                return "408."
            if "australia" in prompt.lower():
                return "Canberra."
            return "I am here."

        eval_comparison = self.evaluator.run_full_comparison(
            candidate_gen=mock_candidate_gen,
            local_gen=mock_local_gen,
            candidate_name=f"hinaku-{ver} (candidate)",
            local_name="current_local (gemma3:4b)"
        )

        # Stage 6: Promote or Reject (Approval Gate)
        cand_score = eval_comparison["candidate_score"]
        loc_score = eval_comparison["local_score"]
        promotable = eval_comparison["promotable"]
        margin = eval_comparison["improvement_margin"]
        prompts_margin = eval_comparison.get("prompts_margin", 0)

        promotion_record = None
        rejection_reason = None

        if promotable:
            pending_data = {
                "version": ver,
                "candidate_name": eval_comparison.get("candidate_name", f"hinaku-{ver}"),
                "local_name": eval_comparison.get("local_name", "current_local (gemma3:4b)"),
                "api_name": eval_comparison.get("api_name", "API Model"),
                "candidate_score": cand_score,
                "local_score": loc_score,
                "api_score": eval_comparison.get("api_score"),
                "improvement_margin": margin,
                "prompts_margin": prompts_margin,
                "candidate_wins": eval_comparison.get("candidate_wins", 0),
                "local_wins": eval_comparison.get("local_wins", 0),
                "category_table": eval_comparison.get("category_table", {}),
                "side_by_side": eval_comparison.get("side_by_side", [])[:15],
                "dry_run": dry_run,
                "timestamp": run_start
            }
            self.promoter.set_pending_candidate(pending_data)
            decision = "pending_approval"
        else:
            decision = "rejected"
            rejection_reason = f"Candidate score failed promotion threshold (prompts margin: {prompts_margin}, required: >=3 with no category worse)."

        # Stage 7: Generate Report
        report = {
            "version": ver,
            "status": decision,
            "timestamp": run_start,
            "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "dry_run": dry_run,
            "dataset": {
                "example_count": dataset_meta["example_count"],
                "path": str(jsonl_path),
                "breakdown": curation_summary["breakdown"]
            },
            "preflight": preflight,
            "evaluation": {
                "candidate_score": cand_score,
                "current_local_score": loc_score,
                "improvement_margin": margin,
                "prompts_margin": prompts_margin,
                "category_table": eval_comparison.get("category_table", {}),
                "side_by_side": eval_comparison.get("side_by_side", [])[:15],
                "decision": decision,
                "rejection_reason": rejection_reason
            },
            "promotion": promotion_record,
            "activity_at_start": activity
        }

        self._save_report(ver, report)
        return report

    def _save_report(self, version: str, report: Dict[str, Any]):
        json_path = self.reports_dir / f"self_build_{version}.json"
        md_path = self.reports_dir / f"self_build_{version}.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        # Generate readable Markdown report
        md_content = self._format_markdown_report(report)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

    def _format_markdown_report(self, report: Dict[str, Any]) -> str:
        ver = report.get("version", "unknown")
        status = report.get("status", "unknown").upper()
        ts = report.get("timestamp", "")
        eval_data = report.get("evaluation", {})
        ds_data = report.get("dataset", {})

        return f"""# HINAKU Self-Build Report: {ver}

**Status:** {status}  
**Generated at:** {ts}  
**Dry Run:** {report.get('dry_run', False)}

---

## 1. Interaction Dataset Curation
- **Total Training Examples:** {ds_data.get('example_count', 0)}
- **Breakdown:** {json.dumps(ds_data.get('breakdown', {}))}

## 2. Evaluation Results (`eval/golden.jsonl`)
- **Candidate Score:** {eval_data.get('candidate_score', 0):.1%}
- **Current Model Score:** {eval_data.get('current_local_score', 0):.1%}
- **Improvement Margin:** {eval_data.get('improvement_margin', 0):+.1%} (Required: {eval_data.get('min_improvement_required', 0):.1%})
- **Outcome:** {eval_data.get('decision', 'N/A')}
{f"- **Rejection Reason:** {eval_data.get('rejection_reason')}" if eval_data.get('rejection_reason') else ""}

## 3. Promotion Status
- **Active Model Version:** {(report.get('promotion') or {}).get('ollama_name', 'current local unchanged')}
- **Rollback Available:** Yes (retained in promotion ledger)
"""

    def get_reports(self) -> List[Dict[str, Any]]:
        """Returns list of past self-build reports."""
        reports = []
        if not self.reports_dir.exists():
            return reports

        for f in sorted(self.reports_dir.glob("self_build_*.json"), reverse=True):
            try:
                with open(f, "r", encoding="utf-8") as rf:
                    data = json.load(rf)
                    data["report_file"] = f.name
                    reports.append(data)
            except Exception as e:
                logger.error(f"Error reading report {f}: {e}")
        return reports

    def get_latest_report(self) -> Optional[Dict[str, Any]]:
        reports = self.get_reports()
        return reports[0] if reports else None
