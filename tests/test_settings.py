import pytest

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


def test_preference_settings_use_safe_defaults(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.delenv(
        "PREFERENCE_RELEVANCE_ENABLED",
        raising=False,
    )
    monkeypatch.delenv(
        "PREFERENCE_TOP_K",
        raising=False,
    )
    monkeypatch.delenv(
        "PREFERENCE_SUBAGENT_INJECT",
        raising=False,
    )

    settings = load_settings()

    assert settings.preference_relevance_enabled is False
    assert settings.preference_top_k == 5
    assert settings.preference_subagent_inject is True


def test_preference_settings_accept_explicit_values(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv(
        "PREFERENCE_RELEVANCE_ENABLED",
        "true",
    )
    monkeypatch.setenv("PREFERENCE_TOP_K", "2")
    monkeypatch.setenv(
        "PREFERENCE_SUBAGENT_INJECT",
        "off",
    )

    settings = load_settings()

    assert settings.preference_relevance_enabled is True
    assert settings.preference_top_k == 2
    assert settings.preference_subagent_inject is False


@pytest.mark.parametrize(
    "name",
    [
        "PREFERENCE_RELEVANCE_ENABLED",
        "PREFERENCE_SUBAGENT_INJECT",
    ],
)
def test_preference_settings_reject_invalid_boolean(
    monkeypatch,
    name: str,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv(name, "sometimes")

    with pytest.raises(RuntimeError, match=name):
        load_settings()


def test_preference_settings_reject_negative_top_k(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv("PREFERENCE_TOP_K", "-1")

    with pytest.raises(RuntimeError, match="PREFERENCE_TOP_K"):
        load_settings()
