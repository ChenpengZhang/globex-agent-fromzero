from app.infrastructure.settings import (
    PROJECT_ROOT,
    load_settings,
)


def _configure_required_environment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def test_default_database_uses_resolved_data_directory(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv("DATA_DIR", ".test-data")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = load_settings()

    expected_data_dir = PROJECT_ROOT / ".test-data"
    assert settings.data_dir == expected_data_dir
    assert settings.database_url == (
        f"sqlite+aiosqlite:///{expected_data_dir / 'globex.db'}"
    )


def test_explicit_database_url_is_preserved(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _configure_required_environment(monkeypatch)
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'custom.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = load_settings()

    assert settings.database_url == database_url
