import pytest

from bot.shared import layout


@pytest.fixture(autouse=True)
def _no_remembered_server_settings():
    """Each test starts with no cached server settings (bot/shared/layout.py)."""
    layout.forget_all()
    yield
    layout.forget_all()
