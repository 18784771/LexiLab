from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fsrs import Card

from lexilab.memory.engine import MemoryService


def test_create_cards_and_review_all_ratings(context):
    mem = MemoryService(context.repo, 0.9)
    cards = mem.ensure_cards("mitigate")
    assert cards["recognition"]["suspended"] == 0
    assert cards["recall"]["suspended"] == 1
    assert context.repo.count_cards() == 2

    row = context.repo.get_card("mitigate", "recognition")
    for rating in (1, 2, 3, 4):
        row = context.repo.get_card("mitigate", "recognition")
        outcome = mem.review(row, rating, duration_ms=1234)
        assert outcome.rating == rating
        assert outcome.card["due"]
    logs = context.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0)
    assert logs == 4


def test_card_serialization_roundtrip(context):
    mem = MemoryService(context.repo, 0.9)
    row = context.repo.create_card("ability", "recognition", Card().to_dict())
    original = mem._row_to_card(context.repo.get_card("ability", "recognition"))
    assert original.card_id == row["card_id"]
    import json

    data = json.loads(original.to_json())
    restored = Card.from_dict(data)
    assert restored.card_id == original.card_id
    assert restored.state == original.state


def test_due_queue_excludes_suspended_and_orders_errors(context):
    now = datetime.now(timezone.utc)
    for word in ("abandon", "ability", "abstract"):
        card = Card().to_dict()
        card["due"] = (now - timedelta(days=2)).isoformat()
        context.repo.create_card(word, "recognition", card)
    context.repo.create_card("accelerate", "recognition", Card().to_dict(), suspended=True)
    context.repo.add_word_error("ability", "recognition", "forgot", "x")
    context.repo.add_word_error("ability", "recognition", "forgot", "x")
    due = context.repo.due_cards()
    assert due[0]["word_key"] == "ability"
    assert all(item["suspended"] == 0 for item in due)
    assert "accelerate" not in {item["word_key"] for item in due}


def test_review_and_log_are_atomic(context, monkeypatch):
    repo = context.repo
    mem = MemoryService(repo, 0.9)
    repo.create_card("abandon", "recognition", Card().to_dict())
    row = repo.get_card("abandon", "recognition")

    original_save = repo.save_review

    def failing_save(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(repo, "save_review", failing_save)
    with pytest.raises(RuntimeError):
        mem.review(row, 3)
    assert repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 0
    monkeypatch.setattr(repo, "save_review", original_save)


def test_elapsed_days_and_scheduled_days(context):
    mem = MemoryService(context.repo, 0.9)
    repo = context.repo
    past = datetime.now(timezone.utc) - timedelta(days=10)
    card = Card().to_dict()
    card["due"] = past.isoformat()
    card["last_review"] = past.isoformat()
    repo.create_card("abandon", "recognition", card)
    row = repo.get_card("abandon", "recognition")
    outcome = mem.review(row, 3)
    assert outcome.elapsed_days >= 9.9
    log = repo.db.query_one("SELECT * FROM review_logs ORDER BY id DESC LIMIT 1")
    assert log["elapsed_days"] >= 9.9
    assert log["scheduled_days"] >= 0
