from __future__ import annotations

import csv
from pathlib import Path

from lexilab.models.word import Definition, Example, WordEntry
from lexilab.storage.schema import utcnow_iso
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.vocabulary.normalize import normalize_word


def import_custom_csv(
    path: str | Path,
    repo: VocabularyRepository,
    *,
    code: str,
    name: str,
    description: str = "",
    source_url: str = "",
) -> dict:
    """Import a simple wordbook CSV: word,translation[,phonetic,pos,example,example_cn]."""
    source = Path(path)
    book_id = repo.upsert_book(code, name, description=description, source_url=source_url)
    imported = 0
    skipped = 0
    with source.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = {field.strip().lower() for field in (reader.fieldnames or [])}
        if "word" not in fields:
            raise ValueError("自定义词库 CSV 必须包含 word 列")
        with repo.db.transaction() as conn:
            for rank, row in enumerate(reader, 1):
                raw_word = (row.get("word") or row.get("Word") or "").strip()
                if not raw_word:
                    skipped += 1
                    continue
                translation = (row.get("translation") or row.get("meaning") or "").strip()
                if not translation:
                    skipped += 1
                    continue
                pos = (row.get("pos") or "").strip()
                entry = WordEntry(
                    word_key=normalize_word(raw_word),
                    headword=raw_word,
                    phonetic_uk=(row.get("phonetic") or "").strip(),
                    pos=pos,
                    translation=translation,
                    definition_en=(row.get("definition") or "").strip(),
                    source=code,
                    definitions=[Definition(pos=pos, meaning_cn=translation)],
                )
                example = (row.get("example") or "").strip()
                if example:
                    entry.examples.append(
                        Example(
                            sentence_en=example,
                            sentence_cn=(row.get("example_cn") or "").strip(),
                            source=code,
                        )
                    )
                repo.upsert_word(
                    entry,
                    book_id=book_id,
                    rank=rank,
                    source_id=f"{code}:{entry.word_key}",
                    raw_payload="",
                    conn=conn,
                )
                imported += 1
        repo.set_metadata(f"{code}.imported_at", utcnow_iso(), conn=None)
        repo.set_metadata(f"{code}.path", str(source), conn=None)
    return {"words": imported, "skipped": skipped, "book": code}
