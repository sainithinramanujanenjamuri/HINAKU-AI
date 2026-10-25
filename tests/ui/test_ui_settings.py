import pytest
from backend.api.demo import demo_settings

async def test_demo_settings_endpoint():
    res = await demo_settings()
    assert isinstance(res, dict)
    assert res.get("app_name") == "HINAKU"
    assert "default_local_model" in res
    assert "allowed_local_models" in res
    assert "reduced_motion" in res
    assert "model_options" in res
    assert len(res["allowed_local_models"]) >= 1

def test_shortcuts_and_settings_contract():
    from backend.api.demo import _load_demo_data
    data = _load_demo_data()
    app_info = data.get("app_info", {})
    assert "router" in app_info
    assert app_info["router"].get("mode") in ("auto", "local_only", "api_only")

