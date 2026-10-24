import pytest
from backend.models.router import ModelRouter, RouterDecision
from backend.models.ollama_adapter import OllamaAdapter
from backend.models.api_adapter import ApiAdapter
from backend.config import get_settings

@pytest.fixture
def mock_adapters():
    local = OllamaAdapter(default_model="gemma3:4b")
    api = ApiAdapter(provider="openai_compatible", model="test-api-model", api_key="test-key")
    return local, api

def test_detail_mode_routes_to_api_when_auto_and_public(mock_adapters):
    local, api = mock_adapters
    settings = get_settings()
    router = ModelRouter(local_adapter=local, api_adapter=api, mode="auto")

    # When detail_route_to_api is True, a detail request that is not private and not personal should go to API
    decision = router.decide_backend(
        "Explain how gradient descent works in detail",
        is_private=False,
        is_detail=True
    )
    assert decision.target_backend == "api"
    assert decision.target_model == "test-api-model"

def test_detail_mode_stays_local_in_private_chat(mock_adapters):
    local, api = mock_adapters
    router = ModelRouter(local_adapter=local, api_adapter=api, mode="auto")

    # In private chats, MUST stay local
    decision = router.decide_backend(
        "Explain how gradient descent works in detail",
        is_private=True,
        is_detail=True
    )
    assert decision.target_backend == "local"
    assert decision.target_model == "gemma3:4b"

def test_detail_mode_stays_local_for_personal_statement(mock_adapters):
    local, api = mock_adapters
    router = ModelRouter(local_adapter=local, api_adapter=api, mode="auto")

    # For personal statements, MUST stay local
    decision = router.decide_backend(
        "I feel overwhelmed and tired, explain in more detail why I'm burned out",
        is_private=False,
        is_detail=True
    )
    assert decision.target_backend == "local"
    assert decision.target_model == "gemma3:4b"

def test_detail_mode_stays_local_in_local_only_mode(mock_adapters):
    local, api = mock_adapters
    router = ModelRouter(local_adapter=local, api_adapter=api, mode="local_only")

    # In local_only mode, MUST stay local
    decision = router.decide_backend(
        "Explain how gradient descent works in detail",
        is_private=False,
        is_detail=True
    )
    assert decision.target_backend == "local"
    assert decision.target_model == "gemma3:4b"
