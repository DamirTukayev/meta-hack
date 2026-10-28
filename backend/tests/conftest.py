import pytest

import orbitroute.api as api


@pytest.fixture(autouse=True)
def live_mode_unless_a_test_says_otherwise(monkeypatch):
    """Without a MODEL_API_KEY (CI, a fresh clone) the app starts in demo mode. Most tests exercise the live paths with fake
    pipelines and clients, so they run as if a key were set; test_offline_demo.py switches demo mode on itself."""
    monkeypatch.setattr(api, "offline_demo", False)
