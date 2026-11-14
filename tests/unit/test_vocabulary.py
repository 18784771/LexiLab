from __future__ import annotations

import json
from pathlib import Path

import pytest

from lexilab.storage.connection import Database
from lexilab.storage.schema import ensure_vocabulary_schema
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.vocabulary.cet6 import import_cet6, parse_entry
from lexilab.vocabulary.ecdict import import_ecdict_file
from lexilab.vocabulary.normalize import (
    cover_targets,
    describe_misspelling,
    normalize_answer,
    normalize_word,
    word_forms,
)
from lexilab.vocabulary.service import VocabularyService

PROJECT = Path(__file__).resolve().parents[2]


def _entry_json(word: str, sense: str, example: str = "") -> dict:
    content = {
        "trans": [{"pos": "v", "tranCn": sense, "descCn": "中释", "tranOther": f"to {sense}"}],
        "ukphone": "ˈtest",
        "usphone": "ˈtest",
        "phrase": {"phrases": [{"pContent": f"{word} risk", "pCn": "降低风险"}]},
        "syno": {"synos": [{"pos": "v", "tran": "同义", "hwds": [{"w": f"{word}-syn"}]}]},
        "relWord": {"rels": [{"pos": "n", "words": [{"hwd": f"{word}-noun", "tran": "同根"}]}]},
    }
    if example:
        content["sentence"] = {"sentences": [{"sContent": example, "sCn": "例句翻译"}]}
    return {
        "wordRank": 1,
        "headWord": word,
        "content": {
            "word": {
                "wordHead": word,
                "wordId": f"CET6_1_{word}",
                "content": content,
            }
        },
        "bookId": "CET6_1",
    }


@pytest.fixture
def vocab_repo(tmp_path: Path) -> VocabularyRepository:
    db = Database(tmp_path / "vocabulary.db")
    ensure_vocabulary_schema(db)
    return VocabularyRepository(db)


def test_parse_entry_structure():
    entry = parse_entry(_entry_json("mitigate", "减轻", "We must mitigate the risk."))
    assert entry is not None
    assert entry.word_key == "mitigate"
    assert entry.definitions[0].meaning_cn == "减轻"
    assert entry.examples[0].sentence_en == "We must mitigate the risk."
    assert entry.phrases[0].phrase == "mitigate risk"
    assert "mitigate-syn" in entry.synonyms
    assert "mitigate-noun 同根" in entry.derivatives


def test_import_merges_duplicate_senses_and_is_idempotent(tmp_path: Path, vocab_repo: VocabularyRepository):
    path = tmp_path / "six.jsonl"
    lines = [
        _entry_json("abstract", "抽象的", "The idea is abstract."),
        _entry_json("abstract", "摘要"),
        _entry_json("ability", "能力"),
        {"headWord": ""},
    ]
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    report = import_cet6(path, vocab_repo)
    assert report.total_lines == 4
    assert report.unique_words == 2
    assert report.duplicate_senses == 1
    assert report.skipped == 1
    entry = vocab_repo.get_entry("abstract")
    assert entry is not None
    assert len(entry.definitions) == 2
    assert vocab_repo.count_words("cet6") == 2
    import_cet6(path, vocab_repo)
    assert vocab_repo.count_words("cet6") == 2
    assert len(vocab_repo.get_entry("abstract").definitions) == 2
    raw = vocab_repo.db.scalar("SELECT COUNT(*) FROM raw_entries", (), 0)
    assert raw == 3


def test_ecdict_csv_import_unescapes_newlines(tmp_path: Path, vocab_repo: VocabularyRepository):
    csv_path = tmp_path / "ecdict.csv"
    header = [
        "word", "phonetic", "definition", "translation", "pos", "collins", "oxford",
        "tag", "bnc", "frq", "exchange", "detail", "audio",
    ]
    rows = [
        ["perceive", "pəˈsiːv", "to notice", "v. 察觉\\n感知", "v", "3", "1", "cet6", "100", "90",
         "p:perceived/d:perceived/3:perceives/i:perceiving/0:perceive", "", ""],
        ["mitigate", "", "to make less severe", "vt. 减轻\\n缓和", "vt", "2", "0", "cet6", "200", "150",
         "d:mitigated", "", ""],
    ]
    import csv

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    result = import_ecdict_file(csv_path, vocab_repo)
    assert result["entries"] == 2
    ec = vocab_repo.ecdict_lookup("perceive")
    assert ec is not None
    assert "\n" in ec.translation
    assert ec.lemma() == "perceive"
    assert "perceives" in ec.forms()
    assert vocab_repo.count_ecdict() == 2
    # idempotent
    import_ecdict_file(csv_path, vocab_repo)
    assert vocab_repo.count_ecdict() == 2


def test_lookup_falls_back_to_lemma(vocab_repo: VocabularyRepository):
    csv_path = vocab_repo.db.path.parent / "ecdict.csv"
    import csv

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["word", "phonetic", "definition", "translation", "pos", "collins", "oxford",
             "tag", "bnc", "frq", "exchange", "detail", "audio"]
        )
        writer.writerow(
            ["perceive", "", "to notice", "v. 察觉", "v", "", "", "cet6", "", "", "p:perceived/0:perceive", "", ""]
        )
    import_ecdict_file(csv_path, vocab_repo)
    service = VocabularyService(vocab_repo)
    result = service.lookup("perceived")
    assert result.found
    assert result.word_key == "perceive"
    assert "lemma" in result.found_in


def test_word_forms_and_coverage():
    assert "mitigated" in word_forms("mitigate")
    assert "studies" in word_forms("study")
    covered = cover_targets("The team mitigated the risk.", ["mitigate", "constraint"])
    assert covered["mitigate"] is True
    assert covered["constraint"] is False


def test_misspelling_diagnosis_and_normalization():
    assert normalize_word("  Mitigate! ") == "mitigate"
    assert normalize_answer("  Mitigate.  ") == "mitigate"
    message = describe_misspelling("mitigate", "mitigete")
    assert "a" in message and "e" in message


@pytest.mark.skipif(
    not (PROJECT / "data" / "raw" / "cet6.jsonl").is_file(),
    reason="真实六级词库尚未下载",
)
def test_real_cet6_import(tmp_path: Path):
    db = Database(tmp_path / "real.db")
    ensure_vocabulary_schema(db)
    repo = VocabularyRepository(db)
    report = import_cet6(PROJECT / "data" / "raw" / "cet6.jsonl", repo)
    assert report.total_lines == 5651
    assert report.unique_words >= 3900
    assert report.skipped == 0
    assert repo.count_words("cet6") == report.unique_words
    assert repo.get_entry("abandonment") is not None
    assert repo.get_metadata("cet6.sha256")
