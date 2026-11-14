from __future__ import annotations

from lexilab.analytics.stats import AnalyticsService


def test_stats_marks_unevaluated_as_none(context):
    summary = AnalyticsService(context.repo, context.vocab_repo).summary()
    assert summary["skills"]["spelling"]["accuracy"] is None
    assert summary["skills"]["listening"]["accuracy"] is None
    assert summary["delayed_7d"]["sufficient"] is False


def test_typed_recall_drill_is_included(context):
    context.repo.add_training_log("mitigate", "recall", correct=True)
    context.repo.add_training_log("mitigate", "recall", correct=False)
    summary = AnalyticsService(context.repo, context.vocab_repo).summary()
    recall = summary["skills"]["recall"]
    assert recall["sample"] == 2
    assert recall["accuracy"] == 0.5


def test_delayed_recall_requires_samples(context):
    context.repo.db.execute(
        "INSERT INTO cards(word_key, direction, due, created_at, updated_at) VALUES ('x','recognition',?,?,?)",
        ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00"),
    )
    card = context.repo.get_card("x", "recognition")
    context.repo.db.execute(
        """INSERT INTO review_logs(card_row_id, word_key, direction, rating, review_datetime,
                                   elapsed_days, scheduled_days, log_json)
           VALUES (?, 'x', 'recognition', 3, ?, 8.0, 10.0, '{}')""",
        (card["id"], "2026-01-01T00:00:00+00:00"),
    )
    summary = AnalyticsService(context.repo, context.vocab_repo).summary()
    assert summary["delayed_7d"]["sample"] == 1
    assert summary["delayed_7d"]["sufficient"] is False
