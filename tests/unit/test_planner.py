from __future__ import annotations

from datetime import datetime, timezone

from fsrs import Card

from lexilab.learning.planner import Planner
from lexilab.memory.engine import MemoryService
from lexilab.models.session import ItemType
from tests.helpers import make_due_card


def planner(context) -> Planner:
    mem = MemoryService(context.repo, context.settings.learning.desired_retention)
    return Planner(context.settings, context.repo, context.vocab_repo, mem)


def test_due_reviews_come_first_and_errors_are_prioritized(context):
    context.settings.learning.plan_order = "old_first"
    for word in ("abandon", "ability", "abstract"):
        make_due_card(context.repo, word)
    context.repo.add_word_error("abstract", "recognition", "forgot", "x")
    plan = planner(context).build("study", minutes=30, new_count=3)
    assert plan.items[0].word_key == "abstract"
    assert plan.items[0].item_type == ItemType.REVIEW_RECOGNITION
    assert plan.due_count == 3


def test_default_plan_starts_with_new_word_then_reviews_then_recall(context):
    make_due_card(context.repo, "abandon", days=-0.1)
    plan = planner(context).build("study", minutes=30, new_count=1)
    assert plan.items[0].item_type == ItemType.NEW_INTRO
    assert any(item.item_type == ItemType.REVIEW_RECOGNITION for item in plan.items)
    assert plan.items[-1].item_type == ItemType.NEW_RECALL


def test_new_words_paused_when_due_load_is_high(context):
    for index in range(61):
        make_due_card(context.repo, f"fake{index}")
    plan = planner(context).build("study", minutes=120)
    assert plan.new_count == 0
    assert any("暂停新词" in note for note in plan.notes)
    assert all(item.item_type != ItemType.NEW_INTRO for item in plan.items)


def test_explicit_learn_is_not_blocked_by_due_load(context):
    for index in range(61):
        make_due_card(context.repo, f"fake{index}")
    plan = planner(context).build("learn", minutes=30, new_count=2)
    assert plan.new_count == 2
    assert plan.items[0].item_type == ItemType.NEW_INTRO


def test_new_word_recall_is_interleaved(context):
    plan = planner(context).build("study", minutes=60, new_count=5)
    types = [item.item_type for item in plan.items]
    assert types.count(ItemType.NEW_INTRO) == 5
    assert types.count(ItemType.NEW_RECALL) == 5
    first_recall = types.index(ItemType.NEW_RECALL)
    intros_before = types[:first_recall].count(ItemType.NEW_INTRO)
    assert intros_before >= context.settings.learning.interleave_gap


def test_time_budget_limits_reviews(context):
    for word in ("abandon", "ability", "abstract", "accelerate", "accurate", "achieve", "acquire", "adapt"):
        make_due_card(context.repo, word)
    plan = planner(context).build("review", minutes=2)
    assert len(plan.items) <= 2 * 60 // context.settings.learning.review_seconds
    assert plan.new_count == 0


def test_daily_new_limit_accounts_for_today(context):
    context.settings.learning.new_words_per_day = 10
    make_due_card(context.repo, "abandon", days=-0.1)
    plan = planner(context).build("study", minutes=120, new_count=None)
    assert plan.new_count == context.settings.learning.new_words_per_day - 1


def test_recall_card_is_unsuspended_after_delay(context):
    context.settings.learning.recall_delay_days = 0
    card = Card().to_dict()
    context.repo.create_card("abandon", "recall", card, suspended=True)
    planner(context).build("study", minutes=30)
    row = context.repo.get_card("abandon", "recall")
    assert row["suspended"] == 0


def test_no_ai_or_audio_tasks_are_planned(context):
    plan = planner(context).build("study", minutes=30, new_count=2)
    assert all(
        item.item_type
        in {
            ItemType.NEW_INTRO,
            ItemType.NEW_RECALL,
            ItemType.REVIEW_RECOGNITION,
            ItemType.REVIEW_RECALL,
            ItemType.VERIFY,
            ItemType.REINFORCE,
        }
        for item in plan.items
    )
    assert datetime.now(timezone.utc)
