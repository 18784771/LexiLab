from __future__ import annotations

from pathlib import Path

from lexilab.config.settings import DEFAULT_CONFIG_TEXT, Settings
from lexilab.context import AppContext
from lexilab.relations.model import RelationRecord
from tests.helpers import make_due_card
from tests.unit.test_relations_engine import add_ecdict, add_word


def test_default_new_word_order_is_smart():
    assert Settings().learning.new_word_order == "smart"
    assert 'new_word_order = "smart"' in DEFAULT_CONFIG_TEXT
    assert "[relations.learning]" in DEFAULT_CONFIG_TEXT


def new_context(tmp_path: Path, words: list[tuple[str, str]]) -> AppContext:
    s = Settings()
    s.data_dir = tmp_path
    s.audio.enabled = False
    s.ensure_dirs()
    ctx = AppContext(s)
    ctx.vocab_repo.upsert_book("cet6", "测试词库", source_url="local://test")
    for index, (word, meaning) in enumerate(words, 1):
        add_word(ctx.vocab_repo, word, meaning, rank=index)
    return ctx


def intros(plan) -> list[str]:
    return [item.word_key for item in plan.items if item.item_type.value == "new_intro"]


def test_frequency_order_uses_lower_ecdict_rank(tmp_path):
    ctx = new_context(
        tmp_path,
        [("abandon", "放弃"), ("ability", "能力"), ("abstract", "抽象的")],
    )
    for word, frq in (("abandon", 100), ("ability", 9000), ("abstract", 5000)):
        add_ecdict(ctx.vocab_repo, word, frq=frq)
    plan = ctx.planner.build("learn", new_count=3, order="frequency")
    assert intros(plan) == ["abandon", "abstract", "ability"]
    assert all(item.payload["recommendation"] for item in plan.items if item.word_key == "abandon")


def test_smart_order_prefers_related_word_after_frequency_is_equal(tmp_path):
    ctx = new_context(
        tmp_path,
        [("predict", "预测"), ("prediction", "预测；预言"), ("ability", "能力")],
    )
    for word in ("predict", "prediction", "ability"):
        add_ecdict(ctx.vocab_repo, word, frq=40000)
    make_due_card(ctx.repo, "predict")
    ctx.vocab_repo.insert_relations(
        [RelationRecord("predict", "prediction", "derivation", source="wordnet")]
    )
    plan = ctx.planner.build("learn", new_count=2, order="smart")
    assert intros(plan)[0] == "prediction"
    assert any("predict" in reason for reason in plan.notes)


def test_smart_order_reduces_adjacent_spelling_interference(tmp_path):
    ctx = new_context(
        tmp_path,
        [
            ("adapt", "适应"),
            ("adopt", "采纳"),
            ("adept", "熟练的"),
            ("mitigate", "缓解"),
            ("robust", "稳健的"),
            ("constraint", "约束"),
            ("subtle", "微妙的"),
        ],
    )
    for word in (
        "adapt",
        "adopt",
        "adept",
        "mitigate",
        "robust",
        "constraint",
        "subtle",
    ):
        add_ecdict(ctx.vocab_repo, word, frq=40000)
    plan = ctx.planner.build("learn", new_count=7, order="smart")
    sequence = intros(plan)
    assert sequence
    similar = {"adapt", "adopt", "adept"}
    adjacent = [
        (left, right)
        for left, right in zip(sequence, sequence[1:])
        if left in similar and right in similar
    ]
    assert not adjacent, sequence


def test_no_word_frequency_degrades_to_source_order_not_alpha(tmp_path):
    ctx = new_context(tmp_path, [("zeta", "最后"), ("alpha", "第一")])
    plan = ctx.planner.build("learn", new_count=2, order="smart")
    assert intros(plan) == ["zeta", "alpha"]


def test_explicit_alphabetical_mode_is_still_available(tmp_path):
    ctx = new_context(tmp_path, [("zeta", "最后"), ("alpha", "第一")])
    plan = ctx.planner.build("learn", new_count=2, order="alphabetical")
    assert intros(plan) == ["alpha", "zeta"]


def test_due_reviews_keep_fsrs_priority_over_smart_ordering(tmp_path):
    ctx = new_context(tmp_path, [("zeta", "最后"), ("alpha", "第一")])
    ctx.settings.learning.plan_order = "old_first"
    add_ecdict(ctx.vocab_repo, "zeta", frq=100)
    add_ecdict(ctx.vocab_repo, "alpha", frq=40000)
    make_due_card(ctx.repo, "zeta")
    plan = ctx.planner.build("study", new_count=1, order="smart")
    assert plan.items[0].item_type.value == "review_recognition"
    assert plan.due_count == 1
    assert intros(plan) == ["alpha"]
