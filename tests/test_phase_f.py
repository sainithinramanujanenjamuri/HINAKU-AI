import json
import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.training.preflight import run_vram_preflight
from backend.training.train import QLoRATrainer
from backend.training.evaluate import EvaluationHarness
from backend.training.promote import ModelPromoter

client = TestClient(app)

def test_vram_preflight_logic():
    # 1. Sufficient VRAM (e.g. 6 GB on RTX 4050)
    with patch("backend.training.preflight.detect_gpu_vram_gb", return_value=("NVIDIA GeForce RTX 4050 Laptop GPU", 6.0)):
        res = run_vram_preflight(min_gb=5.5)
        assert res["passed"] is True
        assert res["detected_vram_gb"] == 6.0
        assert "passed" in res["message"].lower()

    # 2. Insufficient VRAM (e.g. 4 GB or integrated GPU)
    with patch("backend.training.preflight.detect_gpu_vram_gb", return_value=("Integrated AMD Radeon", 0.5)):
        res_fail = run_vram_preflight(min_gb=5.5)
        assert res_fail["passed"] is False
        assert "refused" in res_fail["message"].lower()
        assert "cloud gpu" in res_fail["message"].lower()

def test_qlora_trainer_dry_run_and_cloud_export_import(tmp_path):
    trainer = QLoRATrainer(models_dir=tmp_path / "models")

    # Create a small valid test dataset
    ds_dir = tmp_path / "datasets" / "2026-10"
    ds_dir.mkdir(parents=True, exist_ok=True)
    dataset_file = ds_dir / "train.jsonl"
    with open(dataset_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"instruction": "Persona prompt", "input": "Hello", "output": "Greetings."}) + "\n")
        f.write(json.dumps({"instruction": "Persona prompt", "input": "Explain void", "output": "Silence."}) + "\n")

    # 1. Dry run training
    res = trainer.train(dataset_path=dataset_file, version="2026-10", dry_run=True)
    assert res["status"] == "dry_run_success"
    assert res["example_count"] == 2
    model_dir = Path(res["model_dir"])
    assert (model_dir / "adapter_config.json").exists()

    # 2. Export cloud bundle
    cloud_zip = trainer.export_cloud_bundle(dataset_file)
    assert cloud_zip.exists()
    assert cloud_zip.suffix == ".zip"

    # Verify bundle contents
    import zipfile
    with zipfile.ZipFile(cloud_zip, "r") as zf:
        namelist = zf.namelist()
        assert "train.jsonl" in namelist
        assert "train_cloud.py" in namelist
        assert "requirements.txt" in namelist

    # 3. Import cloud adapter
    fake_adapter_dir = tmp_path / "fake_cloud_adapter"
    fake_adapter_dir.mkdir(parents=True, exist_ok=True)
    (fake_adapter_dir / "adapter_config.json").write_text(json.dumps({"base_model": "Qwen/Qwen2.5-1.5B-Instruct"}), encoding="utf-8")
    (fake_adapter_dir / "adapter_model.safetensors").write_bytes(b"ADAPTER_WEIGHTS")

    imported_dir = trainer.import_cloud_adapter(fake_adapter_dir, version="2026-11")
    assert imported_dir.exists()
    assert (imported_dir / "adapter_config.json").exists()

def test_evaluation_harness_scoring(tmp_path):
    # Create mini golden set
    golden_path = tmp_path / "golden.jsonl"
    items = [
        {"id": "q1", "category": "persona", "prompt": "Who are you?", "ideal": "HINAKU AI", "must_include": ["HINAKU", "AI"], "must_avoid": ["human"]},
        {"id": "q2", "category": "accuracy", "prompt": "Capital of Australia?", "ideal": "Canberra", "must_include": ["Canberra"], "must_avoid": ["Sydney"]}
    ]
    with open(golden_path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")

    harness = EvaluationHarness(golden_file=golden_path)

    # 1. High-scoring model
    def good_model(prompt, memories=None):
        if "who" in prompt.lower():
            return "I am HINAKU, an AI."
        return "Canberra is the capital."

    res_good = harness.evaluate_model("GoodModel", good_model)
    assert res_good["overall_score"] >= 0.95

    # 2. Flawed model (hits must_avoid)
    def bad_model(prompt, memories=None):
        if "who" in prompt.lower():
            return "I am a human helper! OMG so glad to meet you!!!"
        return "Sydney is the capital of Australia."

    res_bad = harness.evaluate_model("BadModel", bad_model)
    assert res_bad["overall_score"] < 0.50

    # 3. Full comparison
    comp = harness.run_full_comparison(
        candidate_gen=good_model,
        local_gen=bad_model,
        candidate_name="NewCandidate",
        local_name="OldLocal"
    )
    assert comp["promotable"] is True
    assert comp["improvement_margin"] > 0.05

def test_model_promotion_and_rollback(tmp_path):
    promoter = ModelPromoter(data_dir=tmp_path / "data", models_dir=tmp_path / "models")

    # 1. Promoting a model that beats local by >= 0.02
    res_promo = promoter.promote(
        version="2026-10",
        candidate_score=0.92,
        current_local_score=0.85,
        dry_run=True
    )
    assert res_promo["status"] == "active"
    assert res_promo["version"] == "2026-10"

    active = promoter.get_active_model()
    assert active is not None
    assert active["version"] == "2026-10"

    # 2. Promoting a model that DOES NOT beat local -> MUST RAISE ERROR
    with pytest.raises(ValueError, match="Promotion rejected"):
        promoter.promote(
            version="2026-11",
            candidate_score=0.80,
            current_local_score=0.85,
            dry_run=True
        )

    # Active model must still be 2026-10
    assert promoter.get_active_model()["version"] == "2026-10"

    # 3. Promote a second winning version
    promoter.promote(
        version="2027-04",
        candidate_score=0.96,
        current_local_score=0.92,
        dry_run=True
    )
    assert promoter.get_active_model()["version"] == "2027-04"

    # 4. Rollback to previous version
    rb = promoter.rollback()
    assert rb["version"] == "2026-10"
    assert promoter.get_active_model()["version"] == "2026-10"

def test_training_api_endpoints(tmp_path):
    # Test preflight endpoint
    res_pre = client.get("/api/training/preflight")
    assert res_pre.status_code == 200
    assert "passed" in res_pre.json()

    # Test promotions endpoint
    res_promos = client.get("/api/training/promotions")
    assert res_promos.status_code == 200
    assert "history" in res_promos.json()

    # Test promote endpoint via HTTP
    res_promo = client.post("/api/training/promote", json={
        "version": "2026-10",
        "candidate_score": 0.90,
        "current_local_score": 0.85,
        "dry_run": True
    })
    assert res_promo.status_code == 200
    assert res_promo.json()["status"] == "promoted"

    # Test reject via HTTP when score is worse
    res_reject = client.post("/api/training/promote", json={
        "version": "2026-11",
        "candidate_score": 0.82,
        "current_local_score": 0.85,
        "dry_run": True
    })
    assert res_reject.status_code == 400
    assert "Promotion rejected" in res_reject.json()["detail"]
