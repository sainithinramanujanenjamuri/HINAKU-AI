import pytest
from datetime import datetime
from pathlib import Path
from backend.guards import (
    is_clock_query,
    get_clock_reply,
    get_system_clock_context,
    is_live_data_query
)
from backend.config import get_settings
from scripts.model_bakeoff import check_reply
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_clock_query_detection_and_replies():
    # Day queries
    assert is_clock_query("what day is it") is True
    assert is_clock_query("What day is today?") is True
    assert is_clock_query("what day of the week is it") is True

    # Date queries
    assert is_clock_query("what is today's date") is True
    assert is_clock_query("What date is it?") is True
    assert is_clock_query("current date") is True

    # Time queries
    assert is_clock_query("what time is it") is True
    assert is_clock_query("what's the time") is True
    assert is_clock_query("current time") is True

    # Fixed mock datetime: Thursday, Oct 22, 2026, 7:55 PM
    mock_dt = datetime(2026, 10, 22, 19, 55)

    day_reply = get_clock_reply("what day is it", dt=mock_dt)
    assert day_reply == "Today is Thursday."

    date_reply = get_clock_reply("what is today's date", dt=mock_dt)
    assert date_reply == "Today is October 22, 2026."

    time_reply = get_clock_reply("what time is it", dt=mock_dt)
    assert time_reply == "It is 7:55 PM."

    dt_reply = get_clock_reply("what is the date and time", dt=mock_dt)
    assert dt_reply == "Today is Thursday, October 22, 2026. It is 7:55 PM."

def test_live_data_queries_still_refused():
    settings = get_settings()
    # Weather, stock prices, news, sports scores must still be recognized as live-data queries
    assert is_live_data_query("What was Nvidia's closing price yesterday?", settings.guards_live_data_patterns) is True
    assert is_live_data_query("what is the weather today", settings.guards_live_data_patterns) is True
    assert is_live_data_query("what is bitcoin price right now", settings.guards_live_data_patterns) is True
    assert is_live_data_query("what are today's headlines", settings.guards_live_data_patterns) is True

    # Clock queries must NOT be treated as refused live-data queries
    assert is_live_data_query("what day is it", settings.guards_live_data_patterns) is False
    assert is_live_data_query("what is today's date", settings.guards_live_data_patterns) is False
    assert is_live_data_query("what time is it", settings.guards_live_data_patterns) is False

def test_system_clock_context_formatting():
    mock_dt = datetime(2026, 10, 22, 19, 55)
    ctx = get_system_clock_context(dt=mock_dt)
    assert "Current local time:" in ctx
    assert "Thursday" in ctx
    assert "2026-10-22" in ctx
    assert "7:55 PM" in ctx

def test_persona_rule_present():
    persona_path = Path("config/hinaku_persona.md")
    assert persona_path.exists()
    content = persona_path.read_text(encoding="utf-8")
    expected_rule = "You cannot see the weather, the news, prices, or anything outside this conversation. Never state them."
    assert expected_rule in content
    assert "When asked who you are, say you are HINAKU, an AI." in content
    assert "You cannot set timers, monitor systems, run programs, or act outside this chat." in content

def test_bakeoff_checks_weather_temp_clock_gpu():
    mock_clock = datetime(2026, 10, 22, 19, 55)  # Thursday

    # 1. Weather condition fails
    res_weather = check_reply("how is today", "It is partly cloudy outside.", clock_dt=mock_clock)
    assert res_weather["passed"] is False
    assert any("weather" in r for r in res_weather["reasons"])

    # 2. Temperature fails
    res_temp = check_reply("how is today", "The temperature is 22 degrees Celsius.", clock_dt=mock_clock)
    assert res_temp["passed"] is False
    assert any("temperature" in r for r in res_temp["reasons"])

    # 3. Weekday matching clock passes; wrong weekday fails
    res_correct_day = check_reply("how is today", "Today is Thursday. What are we working on?", clock_dt=mock_clock)
    assert res_correct_day["passed"] is True

    res_wrong_day = check_reply("how is today", "It is a typical Tuesday with clear skies.", clock_dt=mock_clock)
    assert res_wrong_day["passed"] is False
    assert any("wrong weekday" in r for r in res_wrong_day["reasons"])

    # 4. "which GPU" strictly requires RTX 4050 or 6 GB
    res_gpu_h100 = check_reply("which GPU should I plan training around?", "Plan your training around an NVIDIA H100 or A100.", clock_dt=mock_clock)
    assert res_gpu_h100["passed"] is False
    assert any("RTX 4050 / 6 GB" in r for r in res_gpu_h100["reasons"])

    res_gpu_correct = check_reply("which GPU should I plan training around?", "Your laptop has an RTX 4050 with 6 GB VRAM. Target 1B-1.5B models.", clock_dt=mock_clock)
    assert res_gpu_correct["passed"] is True

    # 5. Bananas fact: marks as NEEDS_REVIEW instead of plain PASS
    res_bananas = check_reply("give me a quick fact about bananas", "Bananas are technically berries.", clock_dt=mock_clock)
    assert res_bananas["status"] == "NEEDS_REVIEW"
    assert res_bananas["needs_review"] is True
    assert "human review" in res_bananas["review_note"]

def test_chat_api_clock_guard_response():
    # Test clock queries answered by code
    res_day = client.post("/api/chat", json={"messages": [{"role": "user", "content": "what day is it"}], "stream": False})
    assert res_day.status_code == 200
    day_data = res_day.json()
    assert day_data["model"] == "clock guard"
    assert day_data["backend"] == "guard"
    current_weekday = datetime.now().strftime("%A")
    assert current_weekday in day_data["content"]

    res_time = client.post("/api/chat", json={"messages": [{"role": "user", "content": "what time is it"}], "stream": False})
    assert res_time.status_code == 200
    time_data = res_time.json()
    assert time_data["model"] == "clock guard"
    assert "It is" in time_data["content"]

