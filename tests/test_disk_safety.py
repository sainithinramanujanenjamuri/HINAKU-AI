import os
import shutil
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from backend.config import get_settings
from backend.training.disk_safety import (
    check_disk_space,
    check_training_disk_safety,
    get_large_file_locations,
    setup_training_environment
)

def test_settings_properties_training_temp_and_hf_cache():
    settings = get_settings()
    assert str(settings.training_temp_dir).endswith("hinaku-tmp")
    assert str(settings.hf_cache_dir).endswith("hf-cache")

def test_check_disk_space_sufficient():
    # Mock disk_usage returning 20 GB free
    mock_usage = MagicMock(total=100 * (1024**3), used=80 * (1024**3), free=20 * (1024**3))
    with patch("shutil.disk_usage", return_value=mock_usage):
        is_safe, free_gb, msg = check_disk_space("D:/hinaku-tmp", required_gb=3.0, margin_gb=2.0)
        assert is_safe is True
        assert free_gb == 20.0
        assert "Disk space OK" in msg

def test_check_disk_space_insufficient_refuses():
    # Mock disk_usage returning 4 GB free when 3 GB + 2 GB margin (5 GB) is required
    mock_usage = MagicMock(total=100 * (1024**3), used=96 * (1024**3), free=4 * (1024**3))
    with patch("shutil.disk_usage", return_value=mock_usage):
        is_safe, free_gb, msg = check_disk_space("D:/hinaku-tmp", required_gb=3.0, margin_gb=2.0)
        assert is_safe is False
        assert free_gb == 4.0
        assert "Refusing to start: Insufficient disk space" in msg
        assert "2.00 GB safety margin" in msg

def test_check_training_disk_safety_temp_insufficient():
    # Temp has 3 GB free (insufficient for 2+2=4 GB), cache has 20 GB free
    def fake_usage(path):
        p_str = str(path)
        if "tmp" in p_str:
            return MagicMock(total=100 * (1024**3), used=97 * (1024**3), free=3 * (1024**3))
        return MagicMock(total=100 * (1024**3), used=80 * (1024**3), free=20 * (1024**3))

    with patch("shutil.disk_usage", side_effect=fake_usage):
        is_safe, msg, details = check_training_disk_safety(
            temp_dir=Path("D:/hinaku-tmp"),
            cache_dir=Path("D:/hf-cache"),
            required_temp_gb=2.0,
            required_cache_gb=2.0,
            margin_gb=2.0
        )
        assert is_safe is False
        assert "Insufficient disk space" in msg
        assert details["temp_safe"] is False
        assert details["cache_safe"] is True

def test_setup_training_environment(tmp_path):
    temp_dir = tmp_path / "custom_temp"
    cache_dir = tmp_path / "custom_cache"
    env_vars = setup_training_environment(cache_dir=cache_dir, temp_dir=temp_dir)

    assert os.environ["HF_HOME"] == str(cache_dir)
    assert os.environ["TRANSFORMERS_CACHE"] == str(cache_dir)
    assert os.environ["TEMP"] == str(temp_dir)
    assert env_vars["HF_HOME"] == str(cache_dir)

def test_large_file_locations():
    settings = get_settings()
    locations = get_large_file_locations()
    assert "huggingface_cache" in locations
    assert "training_temp" in locations
    assert "promoted_models" in locations
    assert locations["huggingface_cache"] == str(settings.hf_cache_dir)
    assert locations["training_temp"] == str(settings.training_temp_dir)
