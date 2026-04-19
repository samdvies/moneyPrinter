import pytest
from algobet_common.config import Settings


def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.example")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "testdb")
    monkeypatch.setenv("POSTGRES_USER", "tester")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("REDIS_HOST", "redis.example")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("SERVICE_NAME", "unit-test")

    settings = Settings()

    assert settings.postgres_dsn == "postgresql://tester:secret@db.example:5433/testdb"
    assert settings.redis_url == "redis://redis.example:6380/0"
    assert settings.service_name == "unit-test"


def test_settings_requires_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_settings_ingestion_mode_defaults_to_betfair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "unit-test")
    monkeypatch.delenv("INGESTION_MODE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.ingestion_mode == "betfair"
