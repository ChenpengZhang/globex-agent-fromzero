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
        "SEMANTIC_CACHE_ENABLED",
        "QUEUE_ENABLED",
        "QUEUE_PRIORITY_ENABLED",
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


def test_redis_is_disabled_when_url_is_missing(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.delenv("REDIS_URL", raising=False)

    settings = load_settings()

    assert settings.redis_url == ""


def test_redis_url_is_trimmed_and_preserved(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv(
        "REDIS_URL",
        "  redis://localhost:6379/3  ",
    )

    settings = load_settings()

    assert settings.redis_url == "redis://localhost:6379/3"


def test_queue_settings_use_safe_defaults(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.delenv("QUEUE_ENABLED", raising=False)
    monkeypatch.delenv("WORKER_CONCURRENCY", raising=False)
    monkeypatch.delenv("QUEUE_MAX_DELIVERIES", raising=False)
    monkeypatch.delenv("QUEUE_PRIORITY_ENABLED", raising=False)
    monkeypatch.delenv("QUEUE_LARGE_REQUEST_TURNS", raising=False)

    settings = load_settings()

    assert settings.queue_enabled is False
    assert settings.worker_concurrency == 1
    assert settings.queue_max_deliveries == 3
    assert settings.queue_priority_enabled is True
    assert settings.queue_large_request_turns == 30


def test_queue_settings_accept_explicit_values(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv(
        "REDIS_URL",
        "redis://localhost:6379/0",
    )
    monkeypatch.setenv("QUEUE_ENABLED", "true")
    monkeypatch.setenv("WORKER_CONCURRENCY", "4")
    monkeypatch.setenv("QUEUE_MAX_DELIVERIES", "5")
    monkeypatch.setenv("QUEUE_PRIORITY_ENABLED", "off")
    monkeypatch.setenv("QUEUE_LARGE_REQUEST_TURNS", "12")

    settings = load_settings()

    assert settings.queue_enabled is True
    assert settings.worker_concurrency == 4
    assert settings.queue_max_deliveries == 5
    assert settings.queue_priority_enabled is False
    assert settings.queue_large_request_turns == 12


def test_enabled_queue_requires_redis_url(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("QUEUE_ENABLED", "true")

    with pytest.raises(RuntimeError, match="requires REDIS_URL"):
        load_settings()


@pytest.mark.parametrize(
    "name",
    [
        "WORKER_CONCURRENCY",
        "QUEUE_MAX_DELIVERIES",
        "QUEUE_LARGE_REQUEST_TURNS",
    ],
)
def test_queue_counts_must_be_positive(
    monkeypatch,
    name: str,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv(name, "0")

    with pytest.raises(RuntimeError, match=name):
        load_settings()


def test_semantic_cache_settings_use_safe_defaults(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.delenv(
        "SEMANTIC_CACHE_ENABLED",
        raising=False,
    )
    monkeypatch.delenv(
        "SEMANTIC_CACHE_THRESHOLD",
        raising=False,
    )

    settings = load_settings()

    assert settings.semantic_cache_enabled is True
    assert settings.semantic_cache_threshold == 0.95


def test_semantic_cache_settings_accept_explicit_values(
    monkeypatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv("SEMANTIC_CACHE_ENABLED", "off")
    monkeypatch.setenv("SEMANTIC_CACHE_THRESHOLD", "0.99")

    settings = load_settings()

    assert settings.semantic_cache_enabled is False
    assert settings.semantic_cache_threshold == 0.99


@pytest.mark.parametrize(
    "threshold",
    ["0", "-0.1", "1.01"],
)
def test_semantic_cache_rejects_out_of_range_threshold(
    monkeypatch,
    threshold: str,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv(
        "SEMANTIC_CACHE_THRESHOLD",
        threshold,
    )

    with pytest.raises(
        RuntimeError,
        match="SEMANTIC_CACHE_THRESHOLD",
    ):
        load_settings()
