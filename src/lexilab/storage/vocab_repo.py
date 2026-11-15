from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from lexilab.models.word import Definition, ECDICTEntry, Example, Phrase, WordEntry
from lexilab.storage.connection import Database
from lexilab.storage.schema import utcnow_iso
from lexilab.vocabulary.normalize import normalize_word


class VocabularyRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ books
    def upsert_book(
        self,
        code: str,
        name: str,
        *,
        description: str = "",
        source_url: str = "",
        license_text: str = "",
        source_version: str = "",
        conn: sqlite3.Connection | None = None,
    ) -> int:
        sql = """INSERT INTO word_books(code, name, description, source_url, license, source_version, imported_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(code) DO UPDATE SET
                   name=excluded.name,
                   description=excluded.description,
                   source_url=excluded.source_url,
                   license=excluded.license,
                   source_version=excluded.source_version,
                   imported_at=excluded.imported_at"""
        params = (code, name, description, source_url, license_text, source_version, utcnow_iso())
        if conn is not None:
            conn.execute(sql, params)
            return int(conn.execute("SELECT id FROM word_books WHERE code=?", (code,)).fetchone()[0])
        with self.db.transaction() as own:
            own.execute(sql, params)
            return int(own.execute("SELECT id FROM word_books WHERE code=?", (code,)).fetchone()[0])

    def get_book(self, code: str) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM word_books WHERE code = ?", (code,))

    def list_books(self) -> list[sqlite3.Row]:
        return self.db.query_all(
            """SELECT b.*, COUNT(m.word_id) AS word_count
               FROM word_books b LEFT JOIN word_book_memberships m ON m.word_book_id = b.id
               GROUP BY b.id ORDER BY b.name"""
        )

    def set_metadata(self, key: str, value: str, conn: sqlite3.Connection | None = None) -> None:
        sql = "INSERT INTO source_metadata(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        if conn is not None:
            conn.execute(sql, (key, value))
        else:
            self.db.execute(sql, (key, value))

    def get_metadata(self, key: str) -> str | None:
        row = self.db.query_one("SELECT value FROM source_metadata WHERE key = ?", (key,))
        return row["value"] if row else None

    # ------------------------------------------------------------------ words
    def upsert_word(
        self,
        entry: WordEntry,
        *,
        book_id: int | None = None,
        rank: int = 0,
        source_id: str = "",
        raw_payload: str = "",
        store_raw: bool = True,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        word_key = normalize_word(entry.word_key or entry.headword)
        if not word_key:
            raise ValueError("empty headword")
        now = utcnow_iso()
        sql = """INSERT INTO words(word_key, headword, phonetic_uk, phonetic_us, pos, translation,
                                   definition_en, frequency, source, source_word_id, raw_json, created_at, updated_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(word_key) DO UPDATE SET
                   phonetic_uk=CASE WHEN excluded.phonetic_uk <> '' THEN excluded.phonetic_uk ELSE words.phonetic_uk END,
                   phonetic_us=CASE WHEN excluded.phonetic_us <> '' THEN excluded.phonetic_us ELSE words.phonetic_us END,
                   pos=CASE WHEN excluded.pos <> '' THEN excluded.pos ELSE words.pos END,
                   translation=CASE WHEN excluded.translation <> '' THEN excluded.translation ELSE words.translation END,
                   definition_en=CASE WHEN excluded.definition_en <> '' THEN excluded.definition_en ELSE words.definition_en END,
                   frequency=COALESCE(excluded.frequency, words.frequency),
                   source_word_id=CASE WHEN excluded.source_word_id <> '' THEN excluded.source_word_id ELSE words.source_word_id END,
                   raw_json=CASE WHEN excluded.raw_json <> '' THEN excluded.raw_json ELSE words.raw_json END,
                   updated_at=excluded.updated_at"""
        params = (
            word_key,
            entry.headword,
            entry.phonetic_uk,
            entry.phonetic_us,
            entry.pos,
            entry.translation,
            entry.definition_en,
            entry.frequency,
            entry.source,
            source_id,
            raw_payload,
            now,
            now,
        )

        def _run(c: sqlite3.Connection) -> int:
            c.execute(sql, params)
            row = c.execute("SELECT id FROM words WHERE word_key = ?", (word_key,)).fetchone()
            word_id = int(row[0])
            self._insert_children(c, word_id, entry)
            if book_id is not None:
                c.execute(
                    """INSERT INTO word_book_memberships(word_book_id, word_id, rank) VALUES (?, ?, ?)
                       ON CONFLICT(word_book_id, word_id) DO UPDATE SET rank=MIN(rank, excluded.rank)""",
                    (book_id, word_id, rank),
                )
            if raw_payload and source_id and store_raw:
                c.execute(
                    """INSERT INTO raw_entries(source, source_id, word_key, payload_json, imported_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(source, source_id) DO UPDATE SET
                         payload_json=excluded.payload_json, imported_at=excluded.imported_at""",
                    (entry.source, source_id, word_key, raw_payload, now),
                )
            return word_id

        if conn is not None:
            return _run(conn)
        with self.db.transaction() as own:
            return _run(own)

    def _insert_children(self, conn: sqlite3.Connection, word_id: int, entry: WordEntry) -> None:
        for index, item in enumerate(entry.definitions):
            conn.execute(
                """INSERT INTO definitions(word_id, pos, meaning_cn, meaning_en, sort_order)
                   SELECT ?, ?, ?, ?, ? WHERE NOT EXISTS (
                     SELECT 1 FROM definitions WHERE word_id=? AND pos=? AND meaning_cn=? AND meaning_en=?)""",
                (
                    word_id,
                    item.pos,
                    item.meaning_cn,
                    item.meaning_en,
                    index,
                    word_id,
                    item.pos,
                    item.meaning_cn,
                    item.meaning_en,
                ),
            )
        for index, example in enumerate(entry.examples):
            conn.execute(
                """INSERT INTO examples(word_id, sentence_en, sentence_cn, source, sort_order)
                   SELECT ?, ?, ?, ?, ? WHERE NOT EXISTS (
                     SELECT 1 FROM examples WHERE word_id=? AND sentence_en=?)""",
                (
                    word_id,
                    example.sentence_en,
                    example.sentence_cn,
                    example.source,
                    index,
                    word_id,
                    example.sentence_en,
                ),
            )
        for index, phrase in enumerate(entry.phrases):
            conn.execute(
                """INSERT INTO phrases(word_id, phrase, translation, source, sort_order)
                   SELECT ?, ?, ?, ?, ? WHERE NOT EXISTS (
                     SELECT 1 FROM phrases WHERE word_id=? AND phrase=?)""",
                (word_id, phrase.phrase, phrase.translation, "cet6", index, word_id, phrase.phrase),
            )
        for value in entry.synonyms:
            conn.execute(
                """INSERT INTO word_relations(word_id, rel_type, value)
                   SELECT ?, 'synonym', ? WHERE NOT EXISTS (
                     SELECT 1 FROM word_relations WHERE word_id=? AND rel_type='synonym' AND value=?)""",
                (word_id, value, word_id, value),
            )
        for value in entry.derivatives:
            conn.execute(
                """INSERT INTO word_relations(word_id, rel_type, value)
                   SELECT ?, 'derivative', ? WHERE NOT EXISTS (
                     SELECT 1 FROM word_relations WHERE word_id=? AND rel_type='derivative' AND value=?)""",
                (word_id, value, word_id, value),
            )

    def get_entry(self, word_key: str) -> WordEntry | None:
        key = normalize_word(word_key)
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM words WHERE word_key = ?", (key,)).fetchone()
            if row is None:
                return None
            word_id = int(row["id"])
            definitions = [
                Definition(pos=r["pos"], meaning_cn=r["meaning_cn"], meaning_en=r["meaning_en"])
                for r in conn.execute(
                    "SELECT * FROM definitions WHERE word_id=? ORDER BY sort_order, id", (word_id,)
                )
            ]
            examples = [
                Example(sentence_en=r["sentence_en"], sentence_cn=r["sentence_cn"], source=r["source"])
                for r in conn.execute(
                    "SELECT * FROM examples WHERE word_id=? ORDER BY sort_order, id LIMIT 12", (word_id,)
                )
            ]
            phrases = [
                Phrase(phrase=r["phrase"], translation=r["translation"])
                for r in conn.execute(
                    "SELECT * FROM phrases WHERE word_id=? ORDER BY sort_order, id LIMIT 12", (word_id,)
                )
            ]
            synonyms = [
                r["value"]
                for r in conn.execute(
                    "SELECT value FROM word_relations WHERE word_id=? AND rel_type='synonym' ORDER BY id",
                    (word_id,),
                )
            ]
            derivatives = [
                r["value"]
                for r in conn.execute(
                    "SELECT value FROM word_relations WHERE word_id=? AND rel_type='derivative' ORDER BY id",
                    (word_id,),
                )
            ]
        return WordEntry(
            word_key=row["word_key"],
            headword=row["headword"],
            phonetic_uk=row["phonetic_uk"],
            phonetic_us=row["phonetic_us"],
            pos=row["pos"],
            translation=row["translation"],
            definition_en=row["definition_en"],
            frequency=row["frequency"],
            source=row["source"],
            definitions=definitions,
            examples=examples,
            phrases=phrases,
            synonyms=synonyms,
            derivatives=derivatives,
        )

    def find_by_headword(self, word: str) -> sqlite3.Row | None:
        key = normalize_word(word)
        return self.db.query_one("SELECT * FROM words WHERE word_key = ?", (key,))

    def search(self, term: str, limit: int = 20) -> list[sqlite3.Row]:
        key = normalize_word(term)
        if not key:
            return []
        return self.db.query_all(
            """SELECT word_key, headword, translation, pos FROM words
               WHERE word_key LIKE ? OR headword LIKE ? COLLATE NOCASE
               ORDER BY CASE WHEN word_key = ? THEN 0 WHEN word_key LIKE ? THEN 1 ELSE 2 END, word_key
               LIMIT ?""",
            (f"{key}%", f"%{term.strip()}%", key, f"{key}%", limit),
        )

    def count_words(self, book_code: str | None = None) -> int:
        if book_code:
            return int(
                self.db.scalar(
                    """SELECT COUNT(*) FROM word_book_memberships m
                       JOIN word_books b ON b.id=m.word_book_id WHERE b.code=?""",
                    (book_code,),
                    0,
                )
            )
        return int(self.db.scalar("SELECT COUNT(*) FROM words", (), 0))

    def count_ecdict(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM ecdict", (), 0))

    def new_candidates(self, book_code: str | None, limit: int, exclude: set[str]) -> list[str]:
        if limit <= 0:
            return []
        if book_code:
            rows = self.db.query_all(
                """SELECT w.word_key FROM word_book_memberships m
                   JOIN words w ON w.id=m.word_id JOIN word_books b ON b.id=m.word_book_id
                   WHERE b.code=? ORDER BY m.rank, w.word_key""",
                (book_code,),
            )
        else:
            rows = self.db.query_all("SELECT word_key FROM words ORDER BY id")
        result: list[str] = []
        for row in rows:
            key = row["word_key"]
            if key in exclude:
                continue
            result.append(key)
            if len(result) >= limit:
                break
        return result

    def all_word_keys(self) -> list[str]:
        return [r["word_key"] for r in self.db.query_all("SELECT word_key FROM words ORDER BY id")]

    def book_word_keys(self, book_code: str | None = None) -> list[str]:
        if book_code:
            rows = self.db.query_all(
                """SELECT w.word_key FROM word_book_memberships m
                   JOIN words w ON w.id=m.word_id JOIN word_books b ON b.id=m.word_book_id
                   WHERE b.code=? ORDER BY w.id""",
                (book_code,),
            )
        else:
            rows = self.db.query_all("SELECT word_key FROM words ORDER BY id")
        return [row["word_key"] for row in rows]

    def new_word_rows(self, book_code: str | None = None) -> list[dict]:
        """Return candidate rows with ECDICT frequency metadata and source rank.

        ECDICT is fetched in indexed batches instead of a 770k-row LEFT JOIN;
        this keeps smart ordering responsive on the full dictionary.
        """
        self.ensure_word_metrics()
        if book_code:
            rows = self.db.query_all(
                """SELECT w.word_key, m.rank, e.frq, e.bnc, e.collins, e.oxford
                   FROM word_book_memberships m
                   JOIN words w INDEXED BY idx_words_id_key ON w.id=m.word_id
                   JOIN word_books b ON b.id=m.word_book_id
                   LEFT JOIN word_metrics e ON e.word_key=w.word_key
                   WHERE b.code=? ORDER BY w.id""",
                (book_code,),
            )
        else:
            rows = self.db.query_all(
                """SELECT w.word_key, NULL AS rank, e.frq, e.bnc, e.collins, e.oxford
                   FROM words w LEFT JOIN word_metrics e ON e.word_key=w.word_key
                   ORDER BY w.id"""
            )
        return [dict(row) for row in rows]

    def ensure_word_metrics(self) -> int:
        """Populate the compact ECDICT metrics cache once per vocabulary import."""
        metrics = int(self.db.scalar("SELECT COUNT(*) FROM word_metrics", (), 0) or 0)
        words = int(self.db.scalar("SELECT COUNT(*) FROM words", (), 0) or 0)
        if words <= 0 or metrics > 0 or self.get_metadata("metrics.built_at"):
            return metrics
        return self.refresh_word_metrics()

    def refresh_word_metrics(self) -> int:
        now = utcnow_iso()
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM word_metrics")
            conn.execute(
                """INSERT INTO word_metrics(word_key, frq, bnc, collins, oxford, updated_at)
                   SELECT w.word_key, e.frq, e.bnc, e.collins, e.oxford, ?
                   FROM words w JOIN ecdict e ON e.word=w.word_key COLLATE NOCASE""",
                (now,),
            )
            count = int(conn.execute("SELECT COUNT(*) FROM word_metrics").fetchone()[0])
        self.set_metadata("metrics.built_at", now)
        return count

    def ecdict_metadata(self, word_keys: list[str]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        keys = [normalize_word(k) for k in word_keys if normalize_word(k)]
        for start in range(0, len(keys), 400):
            batch = keys[start : start + 400]
            placeholders = ",".join("?" for _ in batch)
            rows = self.db.query_all(
                f"""SELECT word, frq, bnc, collins, oxford FROM ecdict
                    WHERE word IN ({placeholders}) COLLATE NOCASE""",
                tuple(batch),
            )
            for row in rows:
                result[normalize_word(row["word"])] = dict(row)
        return result

    def word_metadata(self, word_key: str) -> dict | None:
        row = self.db.query_one(
            """SELECT w.word_key, w.headword, w.translation, w.pos,
                      e.frq, e.bnc, e.collins, e.oxford
               FROM words w LEFT JOIN ecdict e ON e.word=w.word_key COLLATE NOCASE
               WHERE w.word_key=?""",
            (normalize_word(word_key),),
        )
        return dict(row) if row else None

    def ecdict_exchanges(self, word_keys: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        keys = [normalize_word(k) for k in word_keys if normalize_word(k)]
        for start in range(0, len(keys), 400):
            batch = keys[start : start + 400]
            placeholders = ",".join("?" for _ in batch)
            rows = self.db.query_all(
                f"SELECT word, exchange FROM ecdict WHERE word IN ({placeholders}) COLLATE NOCASE",
                tuple(batch),
            )
            for row in rows:
                result[normalize_word(row["word"])] = row["exchange"] or ""
        return result

    # -------------------------------------------------------------- relations
    def insert_relations(self, records: list) -> int:
        """Insert static relation records with deduplication."""
        if not records:
            return 0
        now = utcnow_iso()
        rows = [
            (
                r.source_word,
                r.target_word,
                r.relation_type,
                r.source_sense,
                r.target_sense,
                r.part_of_speech,
                r.score,
                r.source,
                now,
            )
            for r in records
            if r.source_word and r.target_word and r.source_word != r.target_word
        ]
        with self.db.transaction() as conn:
            before = int(conn.execute("SELECT COUNT(*) FROM vocab_relations").fetchone()[0])
            conn.executemany(
                """INSERT OR IGNORE INTO vocab_relations(
                       source_word, target_word, relation_type, source_sense,
                       target_sense, part_of_speech, score, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            after = int(conn.execute("SELECT COUNT(*) FROM vocab_relations").fetchone()[0])
        return after - before

    def relation_views(
        self,
        word_key: str,
        relation_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        params: list = [normalize_word(word_key)]
        type_sql = ""
        if relation_type:
            type_sql = " AND r.relation_type=?"
            params.append(relation_type)
        params.append(limit)
        rows = self.db.query_all(
            f"""SELECT r.source_word, r.target_word, r.relation_type, r.source_sense,
                       r.target_sense, r.part_of_speech, r.score, r.source,
                       COALESCE(w.headword, e.word, r.target_word) AS headword,
                       COALESCE(w.translation, e.translation, '') AS translation,
                       COALESCE(w.pos, e.pos, r.part_of_speech, '') AS display_pos
                FROM vocab_relations r
                LEFT JOIN words w ON w.word_key=r.target_word
                LEFT JOIN ecdict e ON e.word=r.target_word COLLATE NOCASE
                WHERE r.source_word=?{type_sql}
                ORDER BY r.score DESC, r.relation_type, r.target_word
                LIMIT ?""",
            tuple(params),
        )
        return [dict(row) for row in rows]

    def relations_for_sources(self, source_words: set[str]) -> list[dict]:
        rows: list[dict] = []
        keys = list(source_words)
        for start in range(0, len(keys), 300):
            batch = keys[start : start + 300]
            placeholders = ",".join("?" for _ in batch)
            result = self.db.query_all(
                f"""SELECT source_word, target_word, relation_type, score
                    FROM vocab_relations WHERE source_word IN ({placeholders})""",
                tuple(batch),
            )
            rows.extend(dict(row) for row in result)
        return rows

    def relation_pairs(self, relation_type: str, limit: int = 200) -> list[dict]:
        rows = self.db.query_all(
            """SELECT source_word, target_word, relation_type, score
               FROM vocab_relations WHERE relation_type=?
               ORDER BY score DESC, source_word, target_word LIMIT ?""",
            (relation_type, limit),
        )
        return [dict(row) for row in rows]

    def has_relation(self, source: str, target: str, relation_types: tuple[str, ...]) -> bool:
        if not relation_types:
            return False
        placeholders = ",".join("?" for _ in relation_types)
        row = self.db.query_one(
            f"""SELECT 1 FROM vocab_relations
                WHERE source_word=? AND target_word=? AND relation_type IN ({placeholders})
                LIMIT 1""",
            (normalize_word(source), normalize_word(target), *relation_types),
        )
        return row is not None

    def relation_stats(self) -> dict:
        rows = self.db.query_all(
            "SELECT relation_type, source, COUNT(*) AS n FROM vocab_relations GROUP BY relation_type, source"
        )
        by_type: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for row in rows:
            by_type[row["relation_type"]] = by_type.get(row["relation_type"], 0) + int(row["n"])
            by_source[row["source"]] = by_source.get(row["source"], 0) + int(row["n"])
        return {
            "relations": sum(by_type.values()),
            "by_type": by_type,
            "by_source": by_source,
            "source_words": int(
                self.db.scalar("SELECT COUNT(DISTINCT source_word) FROM vocab_relations", (), 0) or 0
            ),
            "target_words": int(
                self.db.scalar("SELECT COUNT(DISTINCT target_word) FROM vocab_relations", (), 0) or 0
            ),
        }

    def clear_relations(self) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM vocab_relations")
            conn.execute("DELETE FROM relation_build_state")

    def clear_relations_by_source(self, source: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM vocab_relations WHERE source=?", (source,))
            if source == "wordnet":
                conn.execute("UPDATE relation_build_state SET wordnet_built_at=NULL")
            elif source == "rapidfuzz":
                conn.execute("UPDATE relation_build_state SET spelling_built_at=NULL")

    def relation_built_words(self, source: str) -> set[str]:
        column = "wordnet_built_at" if source == "wordnet" else "spelling_built_at"
        rows = self.db.query_all(
            f"SELECT word_key FROM relation_build_state WHERE {column} IS NOT NULL"
        )
        return {row["word_key"] for row in rows}

    def mark_relation_built(self, word_keys: list[str], source: str) -> None:
        if not word_keys:
            return
        column = "wordnet_built_at" if source == "wordnet" else "spelling_built_at"
        now = utcnow_iso()
        with self.db.transaction() as conn:
            for key in word_keys:
                conn.execute(
                    f"""INSERT INTO relation_build_state(word_key, {column}, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(word_key) DO UPDATE SET {column}=excluded.{column},
                          updated_at=excluded.updated_at""",
                    (normalize_word(key), now, now),
                )


    # ------------------------------------------------------------------ ecdict
    def import_ecdict_csv(self, path: str | Path, batch_size: int = 4000) -> int:
        source = Path(path)
        sql = """INSERT INTO ecdict(word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio)
                 VALUES (:word, :phonetic, :definition, :translation, :pos, :collins, :oxford, :tag, :bnc, :frq, :exchange, :detail, :audio)
                 ON CONFLICT(word) DO UPDATE SET
                   phonetic=excluded.phonetic, definition=excluded.definition, translation=excluded.translation,
                   pos=excluded.pos, collins=excluded.collins, oxford=excluded.oxford, tag=excluded.tag,
                   bnc=excluded.bnc, frq=excluded.frq, exchange=excluded.exchange,
                   detail=excluded.detail, audio=excluded.audio"""
        count = 0
        with source.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            expected = {"word", "phonetic", "definition", "translation", "pos", "collins", "oxford", "tag", "bnc", "frq", "exchange", "detail", "audio"}
            if not expected.issubset(set(reader.fieldnames or [])):
                missing = expected - set(reader.fieldnames or [])
                raise ValueError(f"ECDICT CSV 缺少字段: {sorted(missing)}")
            with self.db.transaction() as conn:
                batch: list[dict] = []
                for raw in reader:
                    word = (raw.get("word") or "").strip()
                    if not word:
                        continue
                    batch.append(
                        {
                            "word": word,
                            "phonetic": raw.get("phonetic") or "",
                            "definition": _ecdict_text(raw.get("definition")),
                            "translation": _ecdict_text(raw.get("translation")),
                            "pos": raw.get("pos") or "",
                            "collins": _int_or_none(raw.get("collins")),
                            "oxford": _int_or_none(raw.get("oxford")),
                            "tag": raw.get("tag") or "",
                            "bnc": _int_or_none(raw.get("bnc")),
                            "frq": _int_or_none(raw.get("frq")),
                            "exchange": raw.get("exchange") or "",
                            "detail": _ecdict_text(raw.get("detail")),
                            "audio": raw.get("audio") or "",
                        }
                    )
                    if len(batch) >= batch_size:
                        conn.executemany(sql, batch)
                        count += len(batch)
                        batch.clear()
                if batch:
                    conn.executemany(sql, batch)
                    count += len(batch)
        return count

    def import_ecdict_sqlite(self, path: str | Path) -> int:
        source = sqlite3.connect(path)
        source.row_factory = sqlite3.Row
        try:
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            table = "stardict" if "stardict" in tables else ("ecdict" if "ecdict" in tables else None)
            if table is None:
                raise ValueError("未找到 stardict/ecdict 表")
            select = "SELECT word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio FROM " + table
            sql = """INSERT INTO ecdict(word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                     ON CONFLICT(word) DO UPDATE SET
                       phonetic=excluded.phonetic, definition=excluded.definition, translation=excluded.translation,
                       pos=excluded.pos, collins=excluded.collins, oxford=excluded.oxford, tag=excluded.tag,
                       bnc=excluded.bnc, frq=excluded.frq, exchange=excluded.exchange,
                       detail=excluded.detail, audio=excluded.audio"""
            count = 0
            with self.db.transaction() as conn:
                for row in source.execute(select):
                    values = list(row)
                    values[2] = _ecdict_text(values[2])
                    values[3] = _ecdict_text(values[3])
                    values[11] = _ecdict_text(values[11])
                    conn.execute(sql, tuple(values))
                    count += 1
            return count
        finally:
            source.close()

    def ecdict_lookup(self, word: str) -> ECDICTEntry | None:
        key = normalize_word(word)
        if not key or self._table_missing("ecdict"):
            return None
        row = self.db.query_one("SELECT * FROM ecdict WHERE word = ? COLLATE NOCASE", (key,))
        if row is None:
            return None
        return ECDICTEntry(
            word=row["word"],
            phonetic=row["phonetic"],
            definition=_ecdict_text(row["definition"]),
            translation=_ecdict_text(row["translation"]),
            pos=row["pos"],
            collins=row["collins"],
            oxford=row["oxford"],
            tag=row["tag"],
            bnc=row["bnc"],
            frq=row["frq"],
            exchange=row["exchange"],
            detail=_ecdict_text(row["detail"]),
            audio=row["audio"],
        )

    def _table_missing(self, table: str) -> bool:
        row = self.db.query_one(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return row is None

    def ecdict_search(self, term: str, limit: int = 20) -> list[sqlite3.Row]:
        key = normalize_word(term)
        if not key or self._table_missing("ecdict"):
            return []
        return self.db.query_all(
            """SELECT word, phonetic, translation, tag, frq FROM ecdict
               WHERE word LIKE ? COLLATE NOCASE ORDER BY CASE WHEN word = ? THEN 0 ELSE 1 END, frq IS NULL, frq
               LIMIT ?""",
            (f"{key}%", key, limit),
        )

    def count_members(self, book_code: str) -> int:
        return self.count_words(book_code)

    def export_raw(self, output: str | Path) -> int:
        rows = self.db.query_all("SELECT source, source_id, word_key, payload_json FROM raw_entries ORDER BY id")
        target = Path(output)
        with target.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
        return len(rows)


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _ecdict_text(value: str | None) -> str:
    """ECDICT stores newlines as the two characters backslash + n."""
    if not value:
        return ""
    return value.replace("\\r", "").replace("\\n", "\n")
