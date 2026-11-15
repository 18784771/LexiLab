from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fsrs import Card

from lexilab.models.word import Definition, Example, WordEntry
from lexilab.relations.model import RelationRecord
from lexilab.relations.spelling import SpellingAnalyzer, forms_from_exchange
from lexilab.relations.wordnet import WordNetAnalyzer, wordnet_data_available


def add_word(repo, word: str, meaning: str, rank: int = 50) -> None:
    book = repo.get_book("cet6")
    assert book is not None
    repo.upsert_word(
        WordEntry(
            word_key=word,
            headword=word,
            pos="v.",
            translation=f"v. {meaning}",
            source="cet6",
            definitions=[Definition(pos="v.", meaning_cn=meaning)],
            examples=[Example(sentence_en=f"They {word} today.", sentence_cn="例句")],
        ),
        book_id=int(book["id"]),
        rank=rank,
        source_id=f"cet6:{word}",
        raw_payload="{}",
    )


def add_ecdict(repo, word: str, *, frq: int = 40000, bnc: int | None = None, collins: int = 0) -> None:
    repo.db.execute(
        """INSERT INTO ecdict(word, phonetic, definition, translation, pos, collins,
                              oxford, tag, bnc, frq, exchange, detail, audio)
           VALUES (?, '', '', '', '', ?, 0, '', ?, ?, '', '', '')
           ON CONFLICT(word) DO UPDATE SET frq=excluded.frq, bnc=excluded.bnc,
             collins=excluded.collins""",
        (word, collins, bnc, frq),
    )


def test_wordnet_relations_are_real_and_multisense():
    if not wordnet_data_available():
        pytest.skip("WordNet data is not installed")
    analyzer = WordNetAnalyzer()
    begin = analyzer.relations("begin")
    assert any(r.relation_type == "synonym" and r.target_word == "start" for r in begin)
    expand = analyzer.relations("expand")
    assert any(r.relation_type == "antonym" and r.target_word == "contract" for r in expand)
    predict = analyzer.relations("predict")
    assert any(r.relation_type == "derivation" and r.target_word == "prediction" for r in predict)
    vehicle = analyzer.relations("vehicle")
    assert any(r.relation_type == "hypernym" for r in vehicle)
    assert all(r.source_word != r.target_word for r in begin)

    bank = [r for r in analyzer.relations("bank") if r.source_word == "bank"]
    assert len({r.source_sense for r in bank}) >= 2
    assert analyzer.relations("zzzznotaword") == []


def test_spelling_similarity_uses_one_normalized_range_and_transposition():
    analyzer = SpellingAnalyzer(max_neighbors=10, similarity_threshold=0.80)
    records = analyzer.neighbours(["adapt", "adopt", "adept", "mitigate"], {})
    pairs = {(r.source_word, r.target_word) for r in records}
    assert ("adapt", "adopt") in pairs
    assert ("adapt", "adept") in pairs
    assert all(0.0 <= float(r.score or 0) <= 1.0 for r in records)
    assert all(r.score is not None and r.score >= 0.80 for r in records)


def test_spelling_excludes_word_forms_and_limits_neighbors():
    analyzer = SpellingAnalyzer(max_neighbors=3, similarity_threshold=0.80)
    forms = {"play": forms_from_exchange("play", "d:played/p:played/i:playing/3:plays/s:plays")}
    assert analyzer.neighbours(["play", "plays", "playing", "played"], forms) == []
    records = analyzer.neighbours(
        ["adapt", "adopt", "adept", "adeptly", "adapter", "adaptive"], {}
    )
    by_source: dict[str, int] = {}
    for record in records:
        by_source[record.source_word] = by_source.get(record.source_word, 0) + 1
    assert max(by_source.values(), default=0) <= 3


def test_relation_store_deduplicates_and_filters(context):
    records = [
        RelationRecord("mitigate", "alleviate", "synonym", "mitigate.v.01", "alleviate.v.01"),
        RelationRecord("mitigate", "alleviate", "synonym", "mitigate.v.01", "alleviate.v.01"),
        RelationRecord("mitigate", "lessen", "synonym", "mitigate.v.02", "lessen.v.01"),
    ]
    assert context.vocab_repo.insert_relations(records) == 2
    assert context.vocab_repo.insert_relations(records) == 0
    views = context.vocab_repo.relation_views("mitigate", "synonym")
    assert {view["target_word"] for view in views} == {"alleviate", "lessen"}
    assert context.relations.groups("mitigate")["synonym"][0].label == "同义词"


def test_relation_build_is_incremental_and_does_not_touch_fsrs(context):
    add_word(context.vocab_repo, "adapt", "适应")
    add_word(context.vocab_repo, "adopt", "采纳")
    add_word(context.vocab_repo, "adept", "熟练的")
    card = Card().to_dict()
    card["due"] = datetime.now(timezone.utc).isoformat()
    context.repo.create_card("adapt", "recognition", card)
    before = dict(context.repo.get_card("adapt", "recognition"))

    first = context.relations.build(force=True, wordnet=False, spelling=True)
    assert first["spelling"]["relations"] > 0
    count = context.vocab_repo.relation_stats()["relations"]
    second = context.relations.build(wordnet=False, spelling=True)
    assert second["spelling"]["built"] == 0
    assert context.vocab_repo.relation_stats()["relations"] == count
    after = dict(context.repo.get_card("adapt", "recognition"))
    assert after["due"] == before["due"]
    assert after["stability"] == before["stability"]


def test_confusion_requires_real_word_and_survives_relation_rebuild(context):
    add_word(context.vocab_repo, "adopt", "采纳")
    assert context.relations.record_confusion_from_answer("adapt", "adopt") is True
    assert context.relations.record_confusion_from_answer("adapt", "adoptt") is False
    assert context.repo.confusion_count() == 1
    assert context.relations.drill_pairs("confusion") == [("adapt", "adopt")]

    context.relations.build(force=True, wordnet=False, spelling=False)
    assert context.repo.confusion_count() == 1


def test_synonym_and_spelling_drill_pairs_use_relations(context):
    add_word(context.vocab_repo, "adapt", "适应")
    add_word(context.vocab_repo, "adopt", "采纳")
    add_word(context.vocab_repo, "adept", "熟练的")
    context.vocab_repo.insert_relations(
        [
            RelationRecord("adapt", "adjust", "synonym", source="wordnet"),
            RelationRecord("adapt", "adopt", "orthographic_similar", source="rapidfuzz"),
        ]
    )
    add_word(context.vocab_repo, "adjust", "调整")
    assert context.relations.drill_pairs("synonym")
    spelling = context.relations.drill_pairs("similar-spelling")
    assert spelling and spelling[0] == ("adapt", "adopt")


def test_relation_query_and_keyboard_navigation(context):
    import asyncio

    from lexilab.ui.textual_relations import LexiLabRelationsApp

    context.vocab_repo.insert_relations(
        [
            RelationRecord("mitigate", "alleviate", "synonym", source="wordnet"),
            RelationRecord("mitigate", "lessen", "synonym", source="wordnet"),
        ]
    )
    app = LexiLabRelationsApp(context, "mitigate")

    async def run():
        async with app.run_test(size=(90, 24)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("1")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause(0.1)
        return app.return_value

    assert asyncio.run(run()) == "alleviate"


def test_disabling_relations_removes_queries_and_confusion_writes(context):
    context.vocab_repo.insert_relations(
        [RelationRecord("mitigate", "alleviate", "synonym", source="wordnet")]
    )
    context.settings.relations.enabled = False
    assert context.relations.groups("mitigate") == {}
    assert context.relations.drill_pairs("synonym") == []
    assert context.relations.record_confusion_from_answer("adapt", "adopt") is False
    assert context.repo.confusion_count() == 0


def test_tiny_vocabulary_still_produces_spelling_relations(context):
    add_word(context.vocab_repo, "adapt", "适应")
    add_word(context.vocab_repo, "adopt", "采纳")
    add_word(context.vocab_repo, "adept", "熟练的")
    context.relations.build(force=True, wordnet=False, spelling=True)
    groups = context.relations.groups("adapt")
    assert "orthographic_similar" in groups
    assert {view.headword for view in groups["orthographic_similar"]} >= {"adopt", "adept"}

