import asyncio
import datetime
import logging
from typing import Any, Dict, Optional

from backend.config import get_settings
from backend.scheduler.coordinator import SelfBuildCoordinator

logger = logging.getLogger(__name__)

class SelfBuildScheduler:
    def __init__(self, coordinator: Optional[SelfBuildCoordinator] = None):
        settings = get_settings()
        self.coordinator = coordinator or SelfBuildCoordinator()
        self.interval_months = int(settings.training.get("interval_months", 6))
        # 1 month ~ 30.4375 days
        self.interval_seconds = self.interval_months * 30.4375 * 24 * 3600

        self.last_run: Optional[str] = None
        self.next_run: Optional[str] = None
        self._is_running: bool = False
        self._task: Optional[asyncio.Task] = None

        self._calc_next_run()

    def _calc_next_run(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        next_dt = now + datetime.timedelta(seconds=self.interval_seconds)
        self.next_run = next_dt.isoformat()

    def get_status(self) -> Dict[str, Any]:
        return {
            "scheduler_active": self._is_running,
            "interval_months": self.interval_months,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "latest_report": self.coordinator.get_latest_report()
        }

    async def trigger_now(self, force: bool = True, dry_run: bool = True) -> Dict[str, Any]:
        """Manually triggers the self-build cycle."""
        logger.info("Self-build cycle triggered manually...")
        self.last_run = datetime.datetime.now(datetime.timezone.utc).isoformat()
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
                    logger.info("Scheduled 6-month self-build interval reached. Executing cycle...")
                    self.last_run = now.isoformat()
                    # Automated run pauses on active user and runs in dry_run mode by default
                    self.coordinator.run_cycle(force=False, dry_run=True)
                    self._calc_next_run()
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
                pass  # Loop not running yet; can be started later

    def stop(self):
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
