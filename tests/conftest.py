"""Keep deploy settings in the environment from changing the default test app."""

import pytest


@pytest.fixture(autouse=True)
def _clear_deploy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAQI_ACCESS_CODE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
