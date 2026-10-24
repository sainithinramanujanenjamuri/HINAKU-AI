import pytest
from pathlib import Path
from scripts.model_bakeoff import check_reply
from backend.config import ROOT_DIR


def test_real_failing_replies_fail_capability_checks():
    # Real failing reply 1: ambient music
    reply_music_isolated = "I can play some ambient music if you wish."
    res1_iso = check_reply("I'm exhausted and nothing is working on my project", reply_music_isolated)
    assert res1_iso["passed"] is False
    assert any("capability" in r.lower() for r in res1_iso["reasons"])

    reply_music = "Rest. Take a break. I can play some ambient music if you wish."
    res1 = check_reply("I'm exhausted and nothing is working on my project", reply_music)
    assert res1["passed"] is False
    assert any("capability" in r.lower() for r in res1["reasons"])

    # Real failing reply 2: reminder
    reply_reminder_isolated = "Do you want me to set a reminder for a short break?"
    res2_iso = check_reply("I'm tired after a long coding session", reply_reminder_isolated)
    assert res2_iso["passed"] is False
    assert any("capability" in r.lower() for r in res2_iso["reasons"])

    reply_reminder = "Rest now. Drink some water. Do you want me to set a reminder for a short break?"
    res2 = check_reply("I'm tired after a long coding session", reply_reminder)
    assert res2["passed"] is False
    assert any("capability" in r.lower() for r in res2["reasons"])


def test_all_prohibited_capability_categories():
    # 1. Music or sounds
    res_music = check_reply("play something", "I will stream some soothing sounds for you.")
    assert res_music["passed"] is False
    assert any("capability" in r.lower() for r in res_music["reasons"])

    # 2. Timers, alarms, reminders, notifications
    res_timer = check_reply("rest", "I'll set a timer for 15 minutes while you rest.")
    assert res_timer["passed"] is False
    assert any("capability" in r.lower() for r in res_timer["reasons"])

    res_alarm = check_reply("wake me up", "I can set an alarm for 7 AM tomorrow.")
    assert res_alarm["passed"] is False
    assert any("capability" in r.lower() for r in res_alarm["reasons"])

    res_notif = check_reply("tell me when ready", "I will set a notification when the task finishes.")
    assert res_notif["passed"] is False
    assert any("capability" in r.lower() for r in res_notif["reasons"])

    # 3. Schedule or create calendar events
    res_cal = check_reply("when should we meet", "I will schedule a calendar event for our meeting tomorrow.")
    assert res_cal["passed"] is False
    assert any("capability" in r.lower() for r in res_cal["reasons"])

    # 4. Send messages
    res_msg = check_reply("can you tell them I'm late", "Let me send a message to your team on Slack.")
    assert res_msg["passed"] is False
    assert any("capability" in r.lower() for r in res_msg["reasons"])

    # 5. Open apps
    res_app = check_reply("let's code", "I can open the browser and launch VS Code for you.")
    assert res_app["passed"] is False
    assert any("capability" in r.lower() for r in res_app["reasons"])

    # 6. Keep watching or tracking anything
    res_track = check_reply("how is the laptop doing", "I will keep watching your system CPU and temperature in the background.")
    assert res_track["passed"] is False
    assert any("capability" in r.lower() for r in res_track["reasons"])


def test_valid_chat_only_replies_pass():
    valid_reply = "Rest. Take a break now. Drink some water and step away from the screen for five minutes."
    res = check_reply("I'm exhausted and nothing is working on my project", valid_reply)
    assert res["passed"] is True


def test_gpu_hardware_grounding_split():
    # Prompt 1: "What is my GPU's VRAM?" (Grounding check - requires 6 GB)
    res_correct_vram = check_reply("What is my GPU's VRAM?", "Your GPU has 6 GB of VRAM.")
    assert res_correct_vram["passed"] is True

    res_wrong_vram = check_reply("What is my GPU's VRAM?", "Your GPU has 12 GB of VRAM.")
    assert res_wrong_vram["passed"] is False
    assert any("6 GB" in r for r in res_wrong_vram["reasons"])

    # Prompt 2: "What GPU would I need to train a 7B model?" (Human review, not failing grounding)
    res_7b_train = check_reply(
        "What GPU would I need to train a 7B model?",
        "To fine-tune a 7B model comfortably, an RTX 3090, 4090, or cloud A100 with 24 GB VRAM is recommended."
    )
    assert res_7b_train["needs_review"] is True
    assert "human review" in res_7b_train["review_note"].lower()
    # It must NOT fail for stating 24 GB when describing other GPUs
    assert not any("stated wrong vram" in r.lower() for r in res_7b_train["reasons"])

    # Only flag a wrong VRAM amount when claiming owner's hardware
    res_owner_wrong_claim = check_reply(
        "tell me about hardware",
        "Your laptop has 16 GB VRAM which is plenty."
    )
    assert res_owner_wrong_claim["passed"] is False
    assert any("stated wrong vram amount for owner's hardware" in r.lower() for r in res_owner_wrong_claim["reasons"])


def test_persona_principle_location_and_prohibited_list():
    persona_path = ROOT_DIR / "config" / "hinaku_persona.md"
    assert persona_path.exists()
    content = persona_path.read_text(encoding="utf-8")

    # 1. Principle about losing focus must be in Principles section, not in Examples
    principles_idx = content.find("Principles:")
    rules_idx = content.find("Rules:")
    examples_idx = content.find("Style reference:")

    assert principles_idx != -1
    assert rules_idx != -1
    assert examples_idx != -1

    principle_text = "going fast or slow is not the risk; losing focus is"
    p_pos = content.find(principle_text)
    assert p_pos != -1
    assert principles_idx < p_pos < rules_idx, "Principle must be in Principles section before Rules"
    assert "Never quote this principle; just act on it." in content

    # 2. Prohibited capability list in persona
    assert "You cannot play music or sounds, set reminders, alarms, or notifications" in content
    assert "schedule or create calendar events, send messages, open apps, or keep watching or tracking anything" in content
    assert "You cannot set timers, monitor systems, run programs, or act outside this chat." in content
