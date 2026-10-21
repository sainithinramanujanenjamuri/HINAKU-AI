import json
import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.scheduler.activity import get_system_idle_seconds, check_training_activity_and_power
from backend.scheduler.coordinator import SelfBuildCoordinator
from backend.scheduler.service import SelfBuildScheduler

client = TestClient(app)

def test_laptop_activity_and_pause_logic():
    # 1. User active (e.g. typing, idle for only 10s < 120s)
    with patch("backend.scheduler.activity.get_system_idle_seconds", return_value=10.0), \
         patch("backend.scheduler.activity.check_power_and_battery", return_value={"plugged_in": True, "battery_percent": 90}):
        res_active = check_training_activity_and_power(idle_threshold_seconds=120.0)
        assert res_active["should_pause"] is True
        assert res_active["user_active"] is True
        assert "actively using" in res_active["message"].lower()

    # 2. User idle (idle for 300s > 120s) and on AC power -> safe to train
    with patch("backend.scheduler.activity.get_system_idle_seconds", return_value=300.0), \
         patch("backend.scheduler.activity.check_power_and_battery", return_value={"plugged_in": True, "battery_percent": 100}):
        res_idle = check_training_activity_and_power(idle_threshold_seconds=120.0)
        assert res_idle["should_pause"] is False
        assert res_idle["user_active"] is False
        assert "safe to train" in res_idle["message"].lower()

    # 3. Running on battery power -> should pause
    with patch("backend.scheduler.activity.get_system_idle_seconds", return_value=300.0), \
         patch("backend.scheduler.activity.check_power_and_battery", return_value={"plugged_in": False, "battery_percent": 45}):
        res_batt = check_training_activity_and_power(idle_threshold_seconds=120.0)
        assert res_batt["should_pause"] is True
        assert "battery power" in res_batt["message"].lower()

def test_self_build_coordinator_cycle_and_reports(tmp_path):
    from backend.api.chat import history_manager, persona_manager
    from backend.training.curate import DatasetCurator
    from backend.training.train import QLoRATrainer
    from backend.training.evaluate import EvaluationHarness
    from backend.training.promote import ModelPromoter

    # Seed sample qualifying interaction
    conv = history_manager.create_conversation("Coordinator Test")
    m1 = history_manager.add_message(conv["id"], "user", "Who are you?")
    m2 = history_manager.add_message(conv["id"], "assistant", "I am HINAKU, an AI.", model="test", backend="local")
    history_manager.log_interaction(
        conv_id=conv["id"],
        user_prompt="Who are you?",
        answer="I am HINAKU, an AI.",
        model="test",
        backend="local",
        feedback="thumbs_up",
        message_id=m2["id"]
    )

    reports_dir = tmp_path / "reports"
    coordinator = SelfBuildCoordinator(
        curator=DatasetCurator(history_manager=history_manager, persona_manager=persona_manager),
        trainer=QLoRATrainer(models_dir=tmp_path / "models"),
        evaluator=EvaluationHarness(),
        promoter=ModelPromoter(data_dir=tmp_path / "data", models_dir=tmp_path / "models"),
        reports_dir=reports_dir
    )

    # 1. Paused when user is active and force=False
    with patch("backend.scheduler.coordinator.check_training_activity_and_power", return_value={"should_pause": True, "message": "User is active"}):
        res_paused = coordinator.run_cycle(force=False, dry_run=True, version="2026-10")
        assert res_paused["status"] == "paused"

    # 2. Executed when force=True
    with patch("backend.scheduler.coordinator.check_training_activity_and_power", return_value={"should_pause": False, "message": "Safe"}):
        res_run = coordinator.run_cycle(force=True, dry_run=True, version="2026-10")
        assert res_run["status"] in ("promoted", "rejected")
        assert "evaluation" in res_run
        assert "dataset" in res_run

    # Verify report files were created (JSON and Markdown)
    assert (reports_dir / "self_build_2026-10.json").exists()
    assert (reports_dir / "self_build_2026-10.md").exists()
    md_text = (reports_dir / "self_build_2026-10.md").read_text(encoding="utf-8")
    assert "# HINAKU Self-Build Report" in md_text

    # Verify coordinator retrieval
    latest = coordinator.get_latest_report()
    assert latest is not None
    assert latest["version"] == "2026-10"

def test_self_build_scheduler_service(tmp_path):
    scheduler = SelfBuildScheduler()
    status = scheduler.get_status()
    assert status["interval_months"] == 6
    assert status["next_run"] is not None

def test_self_build_api_endpoints():
    # 1. Status endpoint
    res_status = client.get("/api/self-build/status")
    assert res_status.status_code == 200
    data_status = res_status.json()
    assert data_status["interval_months"] == 6
    assert "activity" in data_status

    # 2. Trigger run endpoint
    with patch("backend.scheduler.activity.get_system_idle_seconds", return_value=300.0), \
         patch("backend.scheduler.activity.check_power_and_battery", return_value={"plugged_in": True}):
        res_run = client.post("/api/self-build/run", json={"force": True, "dry_run": True})
        assert res_run.status_code == 200
        assert res_run.json()["status"] == "success"

    # 3. Reports endpoint
    res_reports = client.get("/api/self-build/reports")
    assert res_reports.status_code == 200
    assert isinstance(res_reports.json(), list)

def test_ui_phase_g_elements_served():
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert "report-modal" in html
    assert "btn-view-report" in html
    assert "report-modal-body" in html
