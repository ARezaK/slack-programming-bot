import pytest


def test_app_module_imports():
    from bot.app import create_app
    assert callable(create_app)
