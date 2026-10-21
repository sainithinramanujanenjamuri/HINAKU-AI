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
        If last_self_build_date is None or >= 6 months old, a run is due.
        Hard rule: Never start training automatically on app start; only prompt the owner.
        """
        if not self.last_run:
            return {
                "due": True,
                "last_run": None,
                "months_elapsed": None,
                "interval_months": self.interval_months,
                "message": "No self-build run has been recorded yet. A 6-month cycle is due."
            }

        try:
            last_dt = datetime.datetime.fromisoformat(self.last_run.replace("Z", "+00:00"))
            now = datetime.datetime.now(datetime.timezone.utc)
            elapsed_days = (now - last_dt).total_seconds() / 86400
            elapsed_months = elapsed_days / 30.4375
            due = elapsed_months >= self.interval_months
            return {
                "due": due,
                "last_run": self.last_run,
                "months_elapsed": round(elapsed_months, 1),
                "interval_months": self.interval_months,
                "message": f"6-month self-build cycle is due ({round(elapsed_months, 1)} months since last run)." if due else "Self-build is up to date."
            }
        except Exception as e:
            logger.error(f"Error parsing last_run timestamp: {e}")
            return {"due": True, "last_run": self.last_run, "error": str(e)}

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
