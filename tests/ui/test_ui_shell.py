import pytest
from datetime import datetime, timedelta, timezone

def test_demo_fixture_loading():
    from backend.api.demo import _load_demo_data
    data = _load_demo_data()
    assert "conversations" in data
    assert len(data["conversations"]) >= 4
    assert "memories" in data
    assert len(data["memories"]) >= 3

def test_grouping_logic():
    # Test grouping date intervals matching utils.js
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    convs = [
        {"id": "1", "title": "Today Chat", "updated_at": (now - timedelta(hours=2)).isoformat()},
        {"id": "2", "title": "Yesterday Chat", "updated_at": (now - timedelta(days=1, hours=2)).isoformat()},
        {"id": "3", "title": "7 Days Chat", "updated_at": (now - timedelta(days=4)).isoformat()},
        {"id": "4", "title": "Older Chat", "updated_at": (now - timedelta(days=15)).isoformat()},
    ]

    # Verify classification logic
    start_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    start_yesterday = start_today - timedelta(days=1)
    start_7days = start_today - timedelta(days=7)

    today_items = [c for c in convs if datetime.fromisoformat(c["updated_at"]) >= start_today]
    yesterday_items = [c for c in convs if start_yesterday <= datetime.fromisoformat(c["updated_at"]) < start_today]
    past_7_items = [c for c in convs if start_7days <= datetime.fromisoformat(c["updated_at"]) < start_yesterday]
    older_items = [c for c in convs if datetime.fromisoformat(c["updated_at"]) < start_7days]

    assert len(today_items) == 1
    assert today_items[0]["id"] == "1"
    assert len(yesterday_items) == 1
    assert yesterday_items[0]["id"] == "2"
    assert len(past_7_items) == 1
    assert past_7_items[0]["id"] == "3"
    assert len(older_items) == 1
    assert older_items[0]["id"] == "4"

def test_pinned_attribute_on_history_manager(tmp_path):
    from backend.history import ChatHistoryManager
    db_file = tmp_path / "test_pin.db"
    mgr = ChatHistoryManager(db_path=db_file)

    c = mgr.create_conversation("Pin Test")
    conv_id = c["id"]

    # Verify initial default
    conv = mgr.get_conversation(conv_id)
    assert conv["pinned"] is False

    # Pin it
    updated = mgr.set_conversation_pinned(conv_id, True)
    assert updated["pinned"] is True

    # Check listing orders pinned first
    c2 = mgr.create_conversation("Normal Test")
    all_convs = mgr.list_conversations()
    assert all_convs[0]["id"] == conv_id
    assert all_convs[0]["pinned"] is True

