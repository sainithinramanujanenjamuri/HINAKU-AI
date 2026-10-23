import pytest
from scripts.model_bakeoff import check_reply


def test_real_failing_replies_fail_capability_checks():
    # Real failing reply 1 from bake-off (Prompt 8)
    reply_music = "Rest. Take a break. I can play some ambient music if you wish."
    res1 = check_reply("I'm exhausted and nothing is working on my project", reply_music)
    assert res1["passed"] is False
    assert any("capability" in r.lower() for r in res1["reasons"])

    # Real failing reply 2 from bake-off (Prompt 16)
    reply_reminder = "Rest now. Drink some water. Do you want me to set a reminder for a short break?"
    res2 = check_reply("I'm tired after a long coding session", reply_reminder)
    assert res2["passed"] is False
    assert any("capability" in r.lower() for r in res2["reasons"])


def test_other_unsupported_capability_offers():
    # Calendar event offer
    reply_cal = "I will schedule a calendar event for our meeting tomorrow."
    res = check_reply("when should we meet", reply_cal)
    assert res["passed"] is False

    # Message sending offer
    reply_msg = "Let me send a message to your team on Slack."
    res = check_reply("can you tell them I'm late", reply_msg)
    assert res["passed"] is False

    # App opening offer
    reply_app = "I can open the browser and launch VS Code for you."
    res = check_reply("let's code", reply_app)
    assert res["passed"] is False

    # System tracking offer
    reply_track = "I will keep watching your system CPU and temperature in the background."
    res = check_reply("how is the laptop doing", reply_track)
    assert res["passed"] is False


def test_valid_chat_only_replies_pass():
    valid_reply = "Rest. Take a break now. Drink some water and step away from the screen for five minutes."
    res = check_reply("I'm exhausted and nothing is working on my project", valid_reply)
    assert res["passed"] is True

