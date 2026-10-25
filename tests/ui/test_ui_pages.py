import pytest

def test_context_panel_tabs_and_pages_contract():
    from backend.api.demo import _load_demo_data
    data = _load_demo_data()

    # Verify ratings demo data presence
    assert "ratings" in data or "dataset" in data
    # Verify memory page items render facts without sensitive entries
    mems = data.get("memories", [])
    for m in mems:
        assert "password" not in m["text"].lower()
        assert "pin" not in m["text"].lower()

def test_ratings_by_model_demo_payload():
    import asyncio
    from backend.api.demo import demo_ratings
    res = asyncio.run(demo_ratings())
    assert isinstance(res, list)
    assert len(res) >= 2
    for item in res:
        assert "model" in item
        assert "upvote_pct" in item

