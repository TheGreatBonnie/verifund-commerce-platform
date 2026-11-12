from gateway.settings import Settings


def test_defaults(monkeypatch) -> None:
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.host == "0.0.0.0"
    assert settings.port == 10000


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8080")
    settings = Settings(_env_file=None)
    assert settings.host == "127.0.0.1"
    assert settings.port == 8080
