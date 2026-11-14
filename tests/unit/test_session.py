from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lexilab.learning.session import LearningSession
from lexilab.models.session import ItemType, PlanItem, SessionPlan
from lexilab.ui.base import RatingResult
from tests.helpers import ScriptedUI, make_due_card, new_recall_plan


def run_session(context, items, ui, kind="study"):
    plan = SessionPlan(kind=kind, items=items)
    session_id = context.repo.create_session(kind, plan)
    session = LearningSession(
        context.settings, context.repo, context.memory, context.vocab, ui
    )
    return session_id, session.run(session_id)


def test_new_word_flow_creates_cards_only_after_real_recall(context):
    ui = ScriptedUI(new_actions=[3], recognition=[RatingResult(rating=3, duration_ms=1200)])
    session_id, result = run_session(context, new_recall_plan("mitigate"), ui)
    assert result.quit is False
    assert result.new_words == 1
    assert result.reviewed == 1
    recognition = context.repo.get_card("mitigate", "recognition")
    recall = context.repo.get_card("mitigate", "recall")
    assert recognition is not None
    assert recall is not None
    assert recall["suspended"] == 1
    assert context.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1
    log = context.repo.db.query_one("SELECT * FROM review_logs")
    assert log["rating"] == 3
    assert context.repo.db.query_one("SELECT status FROM sessions WHERE id=?", (session_id,))["status"] == "done"


def test_skip_does_not_write_fsrs_review(context):
    make_due_card(context.repo, "abandon")
    item = PlanItem(ItemType.REVIEW_RECOGNITION, "abandon", direction="recognition")
    item.card_row_id = context.repo.get_card("abandon", "recognition")["id"]
    ui = ScriptedUI(recognition=[RatingResult(skipped=True)])
    _, result = run_session(context, [item], ui, kind="review")
    assert result.skipped == 1
    assert context.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 0
    assert context.repo.db.scalar("SELECT COUNT(*) FROM training_logs WHERE correct IS NULL", (), 0) == 1


def test_again_requeues_reinforcement_without_second_fsrs_review(context):
    make_due_card(context.repo, "abandon")
    item = PlanItem(ItemType.REVIEW_RECOGNITION, "abandon", direction="recognition")
    item.card_row_id = context.repo.get_card("abandon", "recognition")["id"]
    ui = ScriptedUI(
        recognition=[RatingResult(rating=1, duration_ms=900)],
        reinforcement=[True],
    )
    _, result = run_session(context, [item], ui, kind="review")
    assert result.reviewed == 1
    assert context.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1
    rows = context.repo.db.query_all("SELECT detail_json FROM training_logs WHERE skill='recognition'")
    assert any("short_term_reinforcement" in row["detail_json"] for row in rows)


def test_quit_and_resume(context):
    make_due_card(context.repo, "abandon")
    make_due_card(context.repo, "ability")
    items = []
    for word in ("abandon", "ability"):
        item = PlanItem(ItemType.REVIEW_RECOGNITION, word, direction="recognition")
        item.card_row_id = context.repo.get_card(word, "recognition")["id"]
        items.append(item)
    ui = ScriptedUI(
        recognition=[RatingResult(rating=3), RatingResult(quit=True)]
    )
    session_id, result = run_session(context, items, ui, kind="review")
    assert result.quit is True
    assert len(context.repo.pending_items(session_id)) == 1
    assert context.repo.db.query_one("SELECT status FROM sessions WHERE id=?", (session_id,))["status"] == "open"

    ui2 = ScriptedUI(recognition=[RatingResult(rating=3)])
    session = LearningSession(context.settings, context.repo, context.memory, context.vocab, ui2)
    result2 = session.run(session_id)
    assert result2.quit is False
    assert context.repo.pending_items(session_id) == []
    assert context.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 2
    assert context.repo.db.query_one("SELECT status FROM sessions WHERE id=?", (session_id,))["status"] == "done"


def test_production_review_logs_typed_evidence(context):
    card = make_due_card(context.repo, "mitigate", "recall")
    item = PlanItem(ItemType.REVIEW_RECALL, "mitigate", direction="recall", card_row_id=card["id"])
    ui = ScriptedUI(
        production=[RatingResult(answer="mitigated", duration_ms=600)],
        feedback=[3],
    )
    _, result = run_session(context, [item], ui, kind="review")
    assert result.reviewed == 1
    row = context.repo.db.query_one("SELECT * FROM training_logs WHERE skill='recall'")
    assert row["correct"] == 1
    log = context.repo.db.query_one("SELECT * FROM review_logs")
    assert log["direction"] == "recall"
    assert log["rating"] == 3


def test_verification_failure_creates_card_and_records_error(context):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    context.repo.upsert_screening("subtle", past)
    item = PlanItem(ItemType.VERIFY, "subtle")
    ui = ScriptedUI(
        recognition=[RatingResult(rating=1, duration_ms=1000)],
        reinforcement=[True],
    )
    _, result = run_session(context, [item], ui, kind="review")
    assert result.reviewed == 1
    assert context.repo.get_card("subtle", "recognition") is not None
    assert context.repo.screening_for("subtle")["status"] == "failed"
    assert context.repo.db.scalar("SELECT COUNT(*) FROM word_errors", (), 0) == 1


def test_duplicate_submission_is_not_replayed(context):
    make_due_card(context.repo, "abandon")
    item = PlanItem(ItemType.REVIEW_RECOGNITION, "abandon", direction="recognition")
    item.card_row_id = context.repo.get_card("abandon", "recognition")["id"]
    ui = ScriptedUI(recognition=[RatingResult(rating=3)])
    session_id, _ = run_session(context, [item], ui, kind="review")
    # Running the finished session again must not create another review.
    ui2 = ScriptedUI(recognition=[RatingResult(rating=3)])
    session = LearningSession(context.settings, context.repo, context.memory, context.vocab, ui2)
    session.run(session_id)
    assert context.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1
