import pytest
from bot.slack.handler import extract_model, strip_bot_mention


def test_extract_model_present():
    model, text = extract_model("model=qwen3 fix the login tests")
    assert model == "qwen3"
    assert text == "fix the login tests"


def test_extract_model_absent():
    model, text = extract_model("fix the login tests")
    assert model is None
    assert text == "fix the login tests"


def test_extract_model_in_middle():
    model, text = extract_model("fix model=opus the login tests")
    assert model == "opus"
    assert text == "fix the login tests"


def test_strip_bot_mention():
    text = strip_bot_mention("<@U12345> fix the login tests")
    assert text == "fix the login tests"


def test_strip_bot_mention_no_mention():
    text = strip_bot_mention("fix the login tests")
    assert text == "fix the login tests"
