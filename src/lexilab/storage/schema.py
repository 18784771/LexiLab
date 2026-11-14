from __future__ import annotations

from datetime import datetime, timezone

from lexilab.storage.connection import Database

VOCAB_SCHEMA_VERSION = 1
LEARNING_SCHEMA_VERSION = 2


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


_VOCAB_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS word_books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '',
        license TEXT NOT NULL DEFAULT '',
        source_version TEXT NOT NULL DEFAULT '',
        imported_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_key TEXT NOT NULL UNIQUE,
        headword TEXT NOT NULL,
        phonetic_uk TEXT NOT NULL DEFAULT '',
        phonetic_us TEXT NOT NULL DEFAULT '',
        pos TEXT NOT NULL DEFAULT '',
        translation TEXT NOT NULL DEFAULT '',
        definition_en TEXT NOT NULL DEFAULT '',
        frequency INTEGER,
        source TEXT NOT NULL DEFAULT 'cet6',
        source_word_id TEXT NOT NULL DEFAULT '',
        raw_json TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS definitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        pos TEXT NOT NULL DEFAULT '',
        meaning_cn TEXT NOT NULL DEFAULT '',
        meaning_en TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS examples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        sentence_en TEXT NOT NULL,
        sentence_cn TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS phrases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        phrase TEXT NOT NULL,
        translation TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS word_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        rel_type TEXT NOT NULL,
        value TEXT NOT NULL,
        translation TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS word_book_memberships (
        word_book_id INTEGER NOT NULL REFERENCES word_books(id) ON DELETE CASCADE,
        word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        rank INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (word_book_id, word_id)
    )""",
    """CREATE TABLE IF NOT EXISTS raw_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        word_key TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        UNIQUE(source, source_id)
    )""",
    """CREATE TABLE IF NOT EXISTS source_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ecdict (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT NOT NULL UNIQUE COLLATE NOCASE,
        phonetic TEXT NOT NULL DEFAULT '',
        definition TEXT NOT NULL DEFAULT '',
        translation TEXT NOT NULL DEFAULT '',
        pos TEXT NOT NULL DEFAULT '',
        collins INTEGER,
        oxford INTEGER,
        tag TEXT NOT NULL DEFAULT '',
        bnc INTEGER,
        frq INTEGER,
        exchange TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        audio TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_words_headword ON words(headword COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_words_source ON words(source)",
    "CREATE INDEX IF NOT EXISTS idx_definitions_word ON definitions(word_id, sort_order)",
    "CREATE INDEX IF NOT EXISTS idx_examples_word ON examples(word_id, sort_order)",
    "CREATE INDEX IF NOT EXISTS idx_phrases_word ON phrases(word_id, sort_order)",
    "CREATE INDEX IF NOT EXISTS idx_relations_word ON word_relations(word_id, rel_type)",
    "CREATE INDEX IF NOT EXISTS idx_membership_book ON word_book_memberships(word_book_id, rank)",
    "CREATE INDEX IF NOT EXISTS idx_raw_word ON raw_entries(word_key)",
    "CREATE INDEX IF NOT EXISTS idx_ecdict_frq ON ecdict(frq)",
]

_LEARNING_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_key TEXT NOT NULL,
        direction TEXT NOT NULL CHECK (direction IN ('recognition', 'recall')),
        card_id INTEGER,
        state INTEGER NOT NULL DEFAULT 1,
        step INTEGER,
        stability REAL,
        difficulty REAL,
        due TEXT NOT NULL,
        last_review TEXT,
        suspended INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (word_key, direction)
    )""",
    """CREATE TABLE IF NOT EXISTS review_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_row_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
        word_key TEXT NOT NULL,
        direction TEXT NOT NULL,
        rating INTEGER NOT NULL,
        review_datetime TEXT NOT NULL,
        review_duration_ms INTEGER,
        elapsed_days REAL,
        scheduled_days REAL,
        state_before INTEGER,
        state_after INTEGER,
        log_json TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS training_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_key TEXT NOT NULL,
        skill TEXT NOT NULL,
        correct INTEGER,
        hinted INTEGER NOT NULL DEFAULT 0,
        duration_ms INTEGER,
        error_type TEXT,
        detail_json TEXT NOT NULL DEFAULT '',
        material_id TEXT,
        session_id TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS word_errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_key TEXT NOT NULL,
        skill TEXT NOT NULL,
        error_type TEXT NOT NULL DEFAULT 'unknown',
        detail TEXT NOT NULL DEFAULT '',
        resolved INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS personal_words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_key TEXT NOT NULL UNIQUE,
        headword TEXT NOT NULL,
        translation TEXT NOT NULL DEFAULT '',
        phonetic TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'manual',
        added_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS screening (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word_key TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'pending',
        verify_at TEXT NOT NULL,
        step INTEGER NOT NULL DEFAULT 0,
        verified_at TEXT,
        fail_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        plan_json TEXT NOT NULL DEFAULT '{}',
        stats_json TEXT NOT NULL DEFAULT '{}',
        last_seen_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS session_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        item_type TEXT NOT NULL,
        word_key TEXT NOT NULL,
        direction TEXT,
        card_row_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        payload_json TEXT NOT NULL DEFAULT '{}',
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS materials (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        target_words_json TEXT NOT NULL DEFAULT '[]',
        topic TEXT NOT NULL DEFAULT '',
        difficulty INTEGER NOT NULL DEFAULT 2,
        body TEXT NOT NULL DEFAULT '',
        questions_json TEXT NOT NULL DEFAULT '[]',
        model TEXT NOT NULL DEFAULT '',
        provider TEXT NOT NULL DEFAULT '',
        prompt_version TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ready',
        meta_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS material_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
        question_index INTEGER NOT NULL DEFAULT -1,
        user_answer TEXT NOT NULL DEFAULT '',
        grade_json TEXT NOT NULL DEFAULT '{}',
        correct INTEGER,
        hinted INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ai_request_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        model TEXT NOT NULL DEFAULT '',
        purpose TEXT NOT NULL,
        prompt_version TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        latency_ms INTEGER,
        error TEXT NOT NULL DEFAULT '',
        cached INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS schema_versions (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(direction, suspended, due)",
    "CREATE INDEX IF NOT EXISTS idx_cards_word ON cards(word_key)",
    "CREATE INDEX IF NOT EXISTS idx_review_logs_time ON review_logs(review_datetime)",
    "CREATE INDEX IF NOT EXISTS idx_review_logs_word ON review_logs(word_key, direction)",
    "CREATE INDEX IF NOT EXISTS idx_training_logs_word ON training_logs(word_key, skill)",
    "CREATE INDEX IF NOT EXISTS idx_training_logs_time ON training_logs(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_errors_word ON word_errors(word_key, resolved)",
    "CREATE INDEX IF NOT EXISTS idx_screening_verify ON screening(status, verify_at)",
    "CREATE INDEX IF NOT EXISTS idx_session_items_session ON session_items(session_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_materials_kind ON materials(kind, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_attempts_material ON material_attempts(material_id)",
]


def _ensure(db: Database, statements: list[str], version: int) -> None:
    with db.transaction() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        row = conn.execute("SELECT MAX(version) AS v FROM schema_versions").fetchone()
        current = int(row["v"] or 0)
        if current >= version:
            return
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            "INSERT OR REPLACE INTO schema_versions(version, applied_at) VALUES (?, ?)",
            (version, utcnow_iso()),
        )


def ensure_vocabulary_schema(db: Database) -> None:
    _ensure(db, _VOCAB_STATEMENTS, VOCAB_SCHEMA_VERSION)


def ensure_learning_schema(db: Database) -> None:
    # v1: base tables. v2: material_attempts.hinted was added.
    _ensure(db, _LEARNING_STATEMENTS, 1)
    with db.transaction() as conn:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_versions").fetchone()
        current = int(row["v"] or 0)
        if current >= 2:
            return
        columns = {
            r["name"] for r in conn.execute("PRAGMA table_info(material_attempts)").fetchall()
        }
        if "hinted" not in columns:
            conn.execute(
                "ALTER TABLE material_attempts ADD COLUMN hinted INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            "INSERT OR REPLACE INTO schema_versions(version, applied_at) VALUES (?, ?)",
            (2, utcnow_iso()),
        )
