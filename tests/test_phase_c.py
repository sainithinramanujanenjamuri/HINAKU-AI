import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import get_settings
from backend.memory.storage import MemoryStorage
from run_desktop import create_tray_image

client = TestClient(app)

def test_ui_phase_c_elements_served():
    """Verify index.html includes memory drawer, settings modal, and action buttons."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert "memory-drawer" in html
    assert "What HINAKU remembers" in html
    assert "settings-modal" in html
    assert "private-toggle-btn" in html
    assert "memory-toggle-btn" in html
    assert "settings-toggle-btn" in html

def test_memories_crud_endpoints():
    """Test viewing, editing, and deleting memories via API."""
    from backend.api.chat import memory_storage

    # Add a memory directly
    added = memory_storage.add_memory("Owner enjoys drinking matcha green tea.")
    mem_id = added["id"]

    # 1. View / List
    res = client.get("/api/memories")
    assert res.status_code == 200
    mems = res.json()
    assert any(m["id"] == mem_id for m in mems)

    # 2. Edit (PUT & PATCH)
    res_put = client.put(f"/api/memories/{mem_id}", json={"text": "Owner prefers iced matcha green tea with oat milk."})
    assert res_put.status_code == 200
    assert res_put.json()["text"] == "Owner prefers iced matcha green tea with oat milk."

    # Verify updated in storage
    stored = memory_storage.get_memory(mem_id)
    assert stored["text"] == "Owner prefers iced matcha green tea with oat milk."

    # 3. Delete
    res_del = client.delete(f"/api/memories/{mem_id}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"

    # Verify hard-deleted
    stored_del = memory_storage.get_memory(mem_id)
    assert stored_del is None

def test_settings_endpoints():
    """Test GET and POST /api/settings."""
    # 1. GET settings
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "router_mode" in data
    assert "memory_enabled" in data
    assert "reduced_motion" in data
    assert data["default_local_model"] in ("gemma3:4b", "bonsai-2:9b")

    # 2. Update router mode to local_only
    res_update = client.post("/api/settings", json={
        "router_mode": "local_only",
        "memory_enabled": False,
        "reduced_motion": True
    })
    assert res_update.status_code == 200
    updated_data = res_update.json()
    assert updated_data["router_mode"] == "local_only"
    assert updated_data["memory_enabled"] is False
    assert updated_data["reduced_motion"] is True

    # 3. Test invalid router mode
    res_invalid = client.post("/api/settings", json={"router_mode": "invalid_mode"})
    assert res_invalid.status_code == 400

    # 4. Revert to auto and memory enabled
    client.post("/api/settings", json={
        "router_mode": "auto",
        "memory_enabled": True,
        "reduced_motion": False
    })

def test_export_and_wipe_data():
    """Test export all data and wipe all data with confirmation."""
    from backend.api.chat import history_manager, memory_storage

    # Create dummy conversation & message
    conv = history_manager.create_conversation(title="Export Test Chat")
    history_manager.add_message(conv["id"], "user", "Message for export")
    history_manager.add_message(conv["id"], "assistant", "Response for export")
    memory_storage.add_memory("Memory for export test")

    # 1. Export data
    res_export = client.get("/api/settings/export")
    assert res_export.status_code == 200
    export_json = res_export.json()
    assert export_json["app"] == "HINAKU"
    assert len(export_json["conversations"]) >= 1
    assert len(export_json["messages"]) >= 2
    assert len(export_json["memories"]) >= 1

    # 2. Test wipe without confirmation fails
    res_fail = client.post("/api/settings/wipe-all", json={"confirm": "wrong"})
    assert res_fail.status_code == 400

    # 3. Test wipe with confirmation succeeds
    res_wipe = client.post("/api/settings/wipe-all", json={"confirm": "WIPE_ALL"})
    assert res_wipe.status_code == 200
    assert res_wipe.json()["status"] == "wiped"

    # Verify databases are empty
    convs = history_manager.list_conversations()
    assert len(convs) == 0
    mems = memory_storage.get_memories(include_deleted=False)
    assert len(mems) == 0

def test_self_build_run_endpoint():
    """Test manual self-build run trigger."""
    res = client.post("/api/settings/self-build/run")
    assert res.status_code == 200
    assert res.json()["status"] == "triggered"
    assert "timestamp" in res.json()

def test_tray_image_generation():
    """Test that the system tray icon generation produces a valid PIL image."""
    img = create_tray_image()
    assert img is not None
    assert img.size == (64, 64)

