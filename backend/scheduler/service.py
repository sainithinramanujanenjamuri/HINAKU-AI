import asyncio
import datetime
import logging
from typing import Any, Dict, Optional

from backend.config import get_settings
from backend.scheduler.coordinator import SelfBuildCoordinator

logger = logging.getLogger(__name__)

class SelfBuildScheduler:
    def __init__(
        self,
        coordinator: Optional[SelfBuildCoordinator] = None,
        history_manager: Optional[Any] = None
    ):
        settings = get_settings()
        self.coordinator = coordinator or SelfBuildCoordinator()
        from backend.history import ChatHistoryManager
        self.history_manager = history_manager or ChatHistoryManager(settings.sqlite_path)
        self.interval_months = int(settings.training.get("interval_months", 6))
        # 1 month ~ 30.4375 days
        self.interval_seconds = self.interval_months * 30.4375 * 24 * 3600

        # Load persisted last_run from SQLite
        self.last_run: Optional[str] = self.history_manager.get_metadata("last_self_build_date")
        if not self.last_run:
            latest_rep = self.coordinator.get_latest_report()
            if latest_rep and latest_rep.get("timestamp"):
                self.last_run = latest_rep["timestamp"]
                self.history_manager.set_metadata("last_self_build_date", self.last_run)

        self.next_run: Optional[str] = None
        self._is_running: bool = False
        self._task: Optional[asyncio.Task] = None

        self._calc_next_run()

    def _calc_next_run(self):
        if self.last_run:
            try:
                last_dt = datetime.datetime.fromisoformat(self.last_run.replace("Z", "+00:00"))
                next_dt = last_dt + datetime.timedelta(seconds=self.interval_seconds)
                self.next_run = next_dt.isoformat()
                return
            except Exception:
                pass
        now = datetime.datetime.now(datetime.timezone.utc)
        next_dt = now + datetime.timedelta(seconds=self.interval_seconds)
        self.next_run = next_dt.isoformat()

    def check_run_due(self) -> Dict[str, Any]:
        """
        Check if a self-build cycle is due.
        Hard rule: Never start training automatically on app start; only prompt the owner.
        Condition: Show prompt ONLY if a run is due AND the curated dataset has at least
        curation.min_examples_to_train examples, and not currently snoozed.
        Optionally flags show_remind_later if due date is within 7 days.
        """
        from backend.training.curate import DatasetCurator
        settings = get_settings()
        min_examples = settings.curation_min_examples

        curator = DatasetCurator(history_manager=self.history_manager)
        candidates = curator.get_candidate_interactions()
        candidate_count = len(candidates)
        has_enough_examples = candidate_count >= min_examples

        # Check snooze
        now = datetime.datetime.now(datetime.timezone.utc)
        snoozed_until_str = self.history_manager.get_metadata("self_build_snoozed_until")
        is_snoozed = False
        if snoozed_until_str:
            try:
                snoozed_dt = datetime.datetime.fromisoformat(snoozed_until_str.replace("Z", "+00:00"))
                if now < snoozed_dt:
                    is_snoozed = True
            except Exception:
                pass

        if not self.last_run:
            time_due = True
            days_until_due = 0.0
            within_7_days = True
            due_date = now.isoformat()
            elapsed_months = None
        else:
            try:
                last_dt = datetime.datetime.fromisoformat(self.last_run.replace("Z", "+00:00"))
                due_dt = last_dt + datetime.timedelta(seconds=self.interval_seconds)
                due_date = due_dt.isoformat()
                elapsed_days = (now - last_dt).total_seconds() / 86400
                elapsed_months = elapsed_days / 30.4375
                time_due = elapsed_months >= self.interval_months
                days_until_due = (due_dt - now).total_seconds() / 86400
                within_7_days = abs(days_until_due) <= 7 or (0 <= -days_until_due <= 7)
            except Exception as e:
                logger.error(f"Error parsing last_run timestamp: {e}")
                time_due = True
                days_until_due = 0.0
                within_7_days = True
                due_date = now.isoformat()
                elapsed_months = None

        due = time_due and has_enough_examples and not is_snoozed
        show_remind_later = due and within_7_days

        if not time_due:
            msg = "Self-build is up to date."
        elif not has_enough_examples:
            msg = f"Self-build interval reached, but insufficient curated data ({candidate_count}/{min_examples} examples). Prompt deferred."
        elif is_snoozed:
            msg = f"Self-build cycle due, but reminder snoozed until {snoozed_until_str}."
        else:
            msg = f"6-month self-build cycle is due ({candidate_count} curated examples ready)."

        return {
            "due": due,
            "time_due": time_due,
            "has_enough_examples": has_enough_examples,
            "candidate_count": candidate_count,
            "min_examples": min_examples,
            "is_snoozed": is_snoozed,
            "snoozed_until": snoozed_until_str if is_snoozed else None,
            "within_7_days": within_7_days,
            "show_remind_later": show_remind_later,
            "last_run": self.last_run,
            "due_date": due_date,
            "months_elapsed": round(elapsed_months, 1) if elapsed_months is not None else None,
            "interval_months": self.interval_months,
            "message": msg
        }

    def remind_me_later(self, days: int = 7) -> Dict[str, Any]:
        """
        Postpone the self-build reminder prompt by the given number of days.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        snoozed_until = (now + datetime.timedelta(days=days)).isoformat()
        self.history_manager.set_metadata("self_build_snoozed_until", snoozed_until)
        return {
            "status": "snoozed",
            "snoozed_until": snoozed_until,
            "message": f"Self-build prompt snoozed for {days} days."
        }

    def get_status(self) -> Dict[str, Any]:
        due_info = self.check_run_due()
        return {
            "scheduler_active": self._is_running,
            "interval_months": self.interval_months,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "run_due": due_info["due"],
            "due_info": due_info,
            "latest_report": self.coordinator.get_latest_report()
        }

    async def trigger_now(self, force: bool = True, dry_run: bool = True) -> Dict[str, Any]:
        """Manually triggers the self-build cycle."""
        logger.info("Self-build cycle triggered manually...")
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.last_run = now_str
        self.history_manager.set_metadata("last_self_build_date", now_str)
        result = self.coordinator.run_cycle(force=force, dry_run=dry_run)
        self._calc_next_run()
        return result

    async def _loop(self):
        logger.info(f"Self-build 6-month scheduler started (interval: {self.interval_months} months).")
        while self._is_running:
            try:
                # Sleep in increments of 1 hour to check schedule
                await asyncio.sleep(3600)
                now = datetime.datetime.now(datetime.timezone.utc)
                if self.next_run and now.isoformat() >= self.next_run:
                    logger.info("Scheduled 6-month self-build interval reached. Checking schedule...")
                    # Hard rule: never start training automatically without explicit user confirmation.
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in self-build scheduler loop: {e}")

    def start(self):
        if not self._is_running:
            self._is_running = True
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self._loop())
            except RuntimeError:
                pass

    def stop(self):
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
