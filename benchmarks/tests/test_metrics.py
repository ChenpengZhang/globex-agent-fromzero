from src.metrics import hit_rate_at_k, paired_estimate, recall_at_k


def test_recall_deduplicates_and_respects_k() -> None:
    assert recall_at_k(["a", "a", "b", "c"], ["a", "c"], 2) == 0.5


def test_empty_relevance_is_zero() -> None:
    assert recall_at_k(["a"], [], 100) == 0.0
    assert hit_rate_at_k(["a"], [], 100) == 0.0


def test_paired_estimate_reports_absolute_and_relative_lift() -> None:
    result = paired_estimate([0.0, 1.0], [1.0, 1.0], seed=7, bootstrap_samples=100)
    assert result.baseline == 0.5
    assert result.candidate == 1.0
    assert result.absolute_lift == 0.5
    assert result.relative_lift == 1.0
