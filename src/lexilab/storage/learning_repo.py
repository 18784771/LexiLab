from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from lexilab.models.session import SessionPlan
from lexilab.storage.connection import Database
from lexilab.storage.schema import utcnow, utcnow_iso
from lexilab.vocabulary.normalize import normalize_word


class LearningRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute(
            """INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, utcnow_iso()),
        )

    # ------------------------------------------------------------------- cards
    def create_card(
        self,
        word_key: str,
        direction: str,
        card_dict: dict,
        *,
        suspended: bool = False,
        now: datetime | None = None,
    ) -> dict:
        key = normalize_word(word_key)
        now_iso = (now or utcnow()).astimezone(timezone.utc).isoformat()
        existing = self.get_card(key, direction)
        if existing:
            return dict(existing)
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO cards(word_key, direction, card_id, state, step, stability, difficulty,
                                     due, last_review, suspended, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    direction,
                    card_dict.get("card_id"),
                    int(card_dict.get("state", 1)),
                    card_dict.get("step"),
                    card_dict.get("stability"),
                    card_dict.get("difficulty"),
                    card_dict.get("due") or now_iso,
                    card_dict.get("last_review"),
                    1 if suspended else 0,
                    now_iso,
                    now_iso,
                ),
            )
            row = conn.execute(
                "SELECT * FROM cards WHERE word_key=? AND direction=?", (key, direction)
            ).fetchone()
        return dict(row)

    def get_card(self, word_key: str, direction: str):
        return self.db.query_one(
            "SELECT * FROM cards WHERE word_key=? AND direction=?", (normalize_word(word_key), direction)
        )

    def get_card_by_id(self, card_row_id: int):
        return self.db.query_one("SELECT * FROM cards WHERE id=?", (card_row_id,))

    def card_exists(self, word_key: str) -> bool:
        row = self.db.query_one("SELECT 1 FROM cards WHERE word_key=?", (normalize_word(word_key),))
        return row is not None

    def learned_keys(self) -> set[str]:
        return {r["word_key"] for r in self.db.query_all("SELECT DISTINCT word_key FROM cards")}

    def count_due(self, now: datetime | None = None) -> int:
        now_iso = (now or utcnow()).astimezone(timezone.utc).isoformat()
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM cards WHERE suspended=0 AND due <= ?", (now_iso,), 0
            )
        )

    def due_cards(self, limit: int = 200, now: datetime | None = None) -> list[dict]:
        now_iso = (now or utcnow()).astimezone(timezone.utc).isoformat()
        rows = self.db.query_all(
            """SELECT c.*, COALESCE(e.n, 0) AS error_count
               FROM cards c
               LEFT JOIN (
                   SELECT word_key, COUNT(*) AS n FROM word_errors
                   WHERE resolved=0 AND created_at >= datetime('now', '-14 days')
                   GROUP BY word_key
               ) e ON e.word_key = c.word_key
               WHERE c.suspended=0 AND c.due <= ?
               ORDER BY error_count DESC, c.due ASC, c.id ASC
               LIMIT ?""",
            (now_iso, limit),
        )
        return [dict(r) for r in rows]

    def count_cards(self, direction: str | None = None) -> int:
        if direction:
            return int(self.db.scalar("SELECT COUNT(*) FROM cards WHERE direction=?", (direction,), 0))
        return int(self.db.scalar("SELECT COUNT(*) FROM cards", (), 0))

    def suspend_card(self, word_key: str, direction: str | None = None) -> int:
        with self.db.transaction() as conn:
            if direction:
                cur = conn.execute(
                    "UPDATE cards SET suspended=1, updated_at=? WHERE word_key=? AND direction=?",
                    (utcnow_iso(), normalize_word(word_key), direction),
                )
            else:
                cur = conn.execute(
                    "UPDATE cards SET suspended=1, updated_at=? WHERE word_key=?",
                    (utcnow_iso(), normalize_word(word_key)),
                )
            return cur.rowcount

    def resume_card(self, word_key: str, direction: str | None = None) -> int:
        with self.db.transaction() as conn:
            if direction:
                cur = conn.execute(
                    "UPDATE cards SET suspended=0, due=?, updated_at=? WHERE word_key=? AND direction=?",
                    (utcnow_iso(), utcnow_iso(), normalize_word(word_key), direction),
                )
            else:
                cur = conn.execute(
                    "UPDATE cards SET suspended=0, due=?, updated_at=? WHERE word_key=?",
                    (utcnow_iso(), utcnow_iso(), normalize_word(word_key)),
                )
            return cur.rowcount

    def unsuspend_due_recall_cards(self, delay_days: int) -> int:
        if delay_days <= 0:
            cutoff = utcnow_iso()
        else:
            cutoff = (utcnow() - timedelta(days=delay_days)).isoformat()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """UPDATE cards SET suspended=0, updated_at=?
                   WHERE direction='recall' AND suspended=1 AND created_at <= ?""",
                (utcnow_iso(), cutoff),
            )
            return cur.rowcount

    def save_review(
        self,
        card_row_id: int,
        card_dict: dict,
        log_dict: dict,
        *,
        rating: int,
        duration_ms: int | None,
        elapsed_days: float,
        scheduled_days: float,
        state_before: int | None,
        now: datetime | None = None,
    ) -> None:
        """Update a card and append its review log in one transaction."""
        now_iso = (now or utcnow()).astimezone(timezone.utc).isoformat()
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM cards WHERE id=?", (card_row_id,)).fetchone()
            if row is None:
                raise ValueError(f"card {card_row_id} not found")
            conn.execute(
                """UPDATE cards SET card_id=?, state=?, step=?, stability=?, difficulty=?,
                                    due=?, last_review=?, updated_at=? WHERE id=?""",
                (
                    card_dict.get("card_id"),
                    int(card_dict.get("state", 1)),
                    card_dict.get("step"),
                    card_dict.get("stability"),
                    card_dict.get("difficulty"),
                    card_dict.get("due"),
                    card_dict.get("last_review"),
                    now_iso,
                    card_row_id,
                ),
            )
            conn.execute(
                """INSERT INTO review_logs(card_row_id, word_key, direction, rating, review_datetime,
                                           review_duration_ms, elapsed_days, scheduled_days,
                                           state_before, state_after, log_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    card_row_id,
                    row["word_key"],
                    row["direction"],
                    rating,
                    log_dict.get("review_datetime") or now_iso,
                    duration_ms,
                    elapsed_days,
                    scheduled_days,
                    state_before,
                    int(card_dict.get("state", 1)),
                    json.dumps(log_dict, ensure_ascii=False),
                ),
            )

    # ------------------------------------------------------------------- logs
    def add_training_log(
        self,
        word_key: str,
        skill: str,
        *,
        correct: bool | None = None,
        hinted: bool = False,
        duration_ms: int | None = None,
        error_type: str | None = None,
        detail: dict | str | None = None,
        material_id: str | None = None,
        session_id: str | None = None,
    ) -> int:
        if isinstance(detail, dict):
            detail_json = json.dumps(detail, ensure_ascii=False)
        else:
            detail_json = detail or ""
        return self.db.execute(
            """INSERT INTO training_logs(word_key, skill, correct, hinted, duration_ms, error_type,
                                         detail_json, material_id, session_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                normalize_word(word_key),
                skill,
                None if correct is None else int(correct),
                1 if hinted else 0,
                duration_ms,
                error_type,
                detail_json,
                material_id,
                session_id,
                utcnow_iso(),
            ),
        )

    def add_word_error(
        self,
        word_key: str,
        skill: str,
        error_type: str,
        detail: str = "",
    ) -> int:
        return self.db.execute(
            """INSERT INTO word_errors(word_key, skill, error_type, detail, resolved, created_at)
               VALUES (?, ?, ?, ?, 0, ?)""",
            (normalize_word(word_key), skill, error_type, detail, utcnow_iso()),
        )

    def list_open_errors(self, limit: int = 50) -> list[dict]:
        rows = self.db.query_all(
            """SELECT word_key, skill, error_type, detail, COUNT(*) AS n, MAX(created_at) AS last_at
               FROM word_errors WHERE resolved=0
               GROUP BY word_key, skill, error_type
               ORDER BY n DESC, last_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]

    def resolve_errors(self, word_key: str, skill: str | None = None) -> int:
        with self.db.transaction() as conn:
            if skill:
                cur = conn.execute(
                    "UPDATE word_errors SET resolved=1, resolved_at=? WHERE word_key=? AND skill=? AND resolved=0",
                    (utcnow_iso(), normalize_word(word_key), skill),
                )
            else:
                cur = conn.execute(
                    "UPDATE word_errors SET resolved=1, resolved_at=? WHERE word_key=? AND resolved=0",
                    (utcnow_iso(), normalize_word(word_key)),
                )
            return cur.rowcount

    def weak_words(self, limit: int = 10) -> list[str]:
        rows = self.db.query_all(
            """SELECT word_key, COUNT(*) AS n FROM word_errors WHERE resolved=0
               GROUP BY word_key ORDER BY n DESC, MAX(created_at) DESC LIMIT ?""",
            (limit,),
        )
        return [r["word_key"] for r in rows]

    # --------------------------------------------------------------- personal
    def add_personal(
        self,
        word_key: str,
        headword: str,
        translation: str = "",
        phonetic: str = "",
        note: str = "",
        source: str = "manual",
    ) -> None:
        self.db.execute(
            """INSERT INTO personal_words(word_key, headword, translation, phonetic, note, source, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(word_key) DO UPDATE SET
                 translation=CASE WHEN excluded.translation <> '' THEN excluded.translation ELSE personal_words.translation END,
                 phonetic=CASE WHEN excluded.phonetic <> '' THEN excluded.phonetic ELSE personal_words.phonetic END,
                 note=CASE WHEN excluded.note <> '' THEN excluded.note ELSE personal_words.note END""",
            (normalize_word(word_key), headword, translation, phonetic, note, source, utcnow_iso()),
        )

    def get_personal(self, word_key: str):
        return self.db.query_one(
            "SELECT * FROM personal_words WHERE word_key=?", (normalize_word(word_key),)
        )

    def remove_personal(self, word_key: str) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute("DELETE FROM personal_words WHERE word_key=?", (normalize_word(word_key),))
            return cur.rowcount

    def list_personal(self) -> list[dict]:
        return [dict(r) for r in self.db.query_all("SELECT * FROM personal_words ORDER BY added_at DESC")]

    # --------------------------------------------------------------- screening
    def upsert_screening(self, word_key: str, verify_at: datetime) -> None:
        self.db.execute(
            """INSERT INTO screening(word_key, status, verify_at, step, created_at)
               VALUES (?, 'pending', ?, 0, ?)
               ON CONFLICT(word_key) DO UPDATE SET status='pending', verify_at=excluded.verify_at""",
            (normalize_word(word_key), verify_at.astimezone(timezone.utc).isoformat(), utcnow_iso()),
        )

    def due_screenings(self, now: datetime | None = None, limit: int = 50) -> list[dict]:
        now_iso = (now or utcnow()).astimezone(timezone.utc).isoformat()
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM screening WHERE status='pending' AND verify_at <= ? ORDER BY verify_at LIMIT ?",
                (now_iso, limit),
            )
        ]

    def screening_for(self, word_key: str):
        return self.db.query_one("SELECT * FROM screening WHERE word_key=?", (normalize_word(word_key),))

    def mark_screening(self, word_key: str, *, passed: bool, next_verify_days: list[int]) -> None:
        row = self.screening_for(word_key)
        if row is None:
            return
        if passed:
            step = int(row["step"]) + 1
            if step >= len(next_verify_days):
                self.db.execute(
                    "UPDATE screening SET status='verified', step=?, verified_at=? WHERE word_key=?",
                    (step, utcnow_iso(), normalize_word(word_key)),
                )
            else:
                nxt = utcnow() + timedelta(days=next_verify_days[step])
                self.db.execute(
                    "UPDATE screening SET status='pending', step=?, verify_at=?, verified_at=? WHERE word_key=?",
                    (step, nxt.astimezone(timezone.utc).isoformat(), utcnow_iso(), normalize_word(word_key)),
                )
        else:
            self.db.execute(
                "UPDATE screening SET status='failed', fail_count=fail_count+1 WHERE word_key=?",
                (normalize_word(word_key),),
            )

    def screening_known_keys(self) -> set[str]:
        return {
            r["word_key"]
            for r in self.db.query_all("SELECT word_key FROM screening WHERE status IN ('pending', 'verified')")
        }

    def delete_cards(self, word_key: str) -> int:
        key = normalize_word(word_key)
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM review_logs WHERE card_row_id IN (SELECT id FROM cards WHERE word_key=?)",
                (key,),
            )
            cur = conn.execute("DELETE FROM cards WHERE word_key=?", (key,))
            conn.execute("DELETE FROM screening WHERE word_key=?", (key,))
            return cur.rowcount

    def review_history(self, word_key: str, limit: int = 20) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                """SELECT rating, review_datetime, review_duration_ms, elapsed_days, scheduled_days,
                          state_before, state_after, direction
                   FROM review_logs WHERE word_key=? ORDER BY review_datetime DESC LIMIT ?""",
                (normalize_word(word_key), limit),
            )
        ]

    def training_history(self, word_key: str, limit: int = 20) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                """SELECT skill, correct, hinted, duration_ms, error_type, created_at
                   FROM training_logs WHERE word_key=? ORDER BY created_at DESC LIMIT ?""",
                (normalize_word(word_key), limit),
            )
        ]

    def word_cards(self, word_key: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM cards WHERE word_key=? ORDER BY direction",
                (normalize_word(word_key),),
            )
        ]

    # ---------------------------------------------------------------- sessions
    def create_session(self, kind: str, plan: SessionPlan) -> str:
        session_id = uuid.uuid4().hex[:12]
        now = utcnow_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO sessions(id, kind, started_at, status, plan_json, stats_json, last_seen_at)
                   VALUES (?, ?, ?, 'open', ?, '{}', ?)""",
                (
                    session_id,
                    kind,
                    now,
                    json.dumps(
                        {
                            "due_count": plan.due_count,
                            "new_count": plan.new_count,
                            "estimated_seconds": plan.estimated_seconds,
                        }
                    ),
                    now,
                ),
            )
            for seq, item in enumerate(plan.items):
                conn.execute(
                    """INSERT INTO session_items(session_id, seq, item_type, word_key, direction,
                                                 card_row_id, status, payload_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                    (
                        session_id,
                        seq,
                        item.item_type.value,
                        item.word_key,
                        item.direction,
                        item.card_row_id,
                        json.dumps(item.payload, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        return session_id

    def get_open_session(self, kind: str | None = None, max_age_hours: int = 36):
        cutoff = (utcnow() - timedelta(hours=max_age_hours)).isoformat()
        sql = "SELECT * FROM sessions WHERE status='open' AND last_seen_at >= ?"
        params: list = [cutoff]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY started_at DESC LIMIT 1"
        return self.db.query_one(sql, tuple(params))

    def pending_items(self, session_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM session_items WHERE session_id=? AND status='pending' ORDER BY seq",
                (session_id,),
            )
        ]

    def session_items(self, session_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM session_items WHERE session_id=? ORDER BY seq", (session_id,)
            )
        ]

    def mark_item(
        self,
        item_id: int,
        status: str,
        *,
        payload: dict | None = None,
        attempts_delta: int = 1,
    ) -> None:
        now = utcnow_iso()
        with self.db.transaction() as conn:
            if payload is None:
                conn.execute(
                    "UPDATE session_items SET status=?, attempts=attempts+?, updated_at=? WHERE id=?",
                    (status, attempts_delta, now, item_id),
                )
            else:
                conn.execute(
                    "UPDATE session_items SET status=?, attempts=attempts+?, payload_json=?, updated_at=? WHERE id=?",
                    (status, attempts_delta, json.dumps(payload, ensure_ascii=False), now, item_id),
                )
            row = conn.execute("SELECT session_id FROM session_items WHERE id=?", (item_id,)).fetchone()
            if row:
                conn.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (now, row["session_id"]))

    def touch_session(self, session_id: str) -> None:
        self.db.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (utcnow_iso(), session_id))

    def finish_session(self, session_id: str, stats: dict | None = None) -> None:
        self.db.execute(
            "UPDATE sessions SET status='done', ended_at=?, stats_json=? WHERE id=?",
            (utcnow_iso(), json.dumps(stats or {}, ensure_ascii=False), session_id),
        )

    def abandon_session(self, session_id: str) -> None:
        self.db.execute("UPDATE sessions SET status='abandoned', ended_at=? WHERE id=?", (utcnow_iso(), session_id))

    def session_counts(self, session_id: str) -> dict[str, int]:
        rows = self.db.query_all(
            "SELECT status, COUNT(*) AS n FROM session_items WHERE session_id=? GROUP BY status",
            (session_id,),
        )
        return {r["status"]: int(r["n"]) for r in rows}

    # --------------------------------------------------------------- materials
    def save_material(
        self,
        *,
        kind: str,
        target_words: list[str],
        topic: str,
        difficulty: int,
        body: str,
        questions: list[dict],
        model: str,
        provider: str,
        prompt_version: str,
        meta: dict | None = None,
    ) -> str:
        material_id = uuid.uuid4().hex[:12]
        self.db.execute(
            """INSERT INTO materials(id, kind, target_words_json, topic, difficulty, body, questions_json,
                                     model, provider, prompt_version, created_at, status, meta_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?)""",
            (
                material_id,
                kind,
                json.dumps(target_words, ensure_ascii=False),
                topic,
                difficulty,
                body,
                json.dumps(questions, ensure_ascii=False),
                model,
                provider,
                prompt_version,
                utcnow_iso(),
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        return material_id

    def get_material(self, material_id: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM materials WHERE id=?", (material_id,))
        return _material_dict(row) if row else None

    def find_cached_material(
        self,
        kind: str,
        target_words: list[str],
        topic: str,
        difficulty: int,
        *,
        max_age_days: int = 30,
    ) -> dict | None:
        cutoff = (utcnow() - timedelta(days=max_age_days)).isoformat()
        rows = self.db.query_all(
            """SELECT * FROM materials WHERE kind=? AND topic=? AND difficulty=? AND created_at >= ?
               ORDER BY created_at DESC LIMIT 30""",
            (kind, topic, difficulty, cutoff),
        )
        wanted = {normalize_word(w) for w in target_words}
        for row in rows:
            saved = {normalize_word(w) for w in json.loads(row["target_words_json"])}
            if not saved or not wanted:
                continue
            overlap = len(saved & wanted) / len(wanted | saved)
            if overlap >= 0.8:
                return _material_dict(row)
        return None

    def recent_materials(self, kind: str | None = None, limit: int = 10) -> list[dict]:
        if kind:
            rows = self.db.query_all(
                "SELECT * FROM materials WHERE kind=? ORDER BY created_at DESC LIMIT ?", (kind, limit)
            )
        else:
            rows = self.db.query_all("SELECT * FROM materials ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_material_dict(r) for r in rows]

    def record_material_attempt(
        self,
        material_id: str,
        question_index: int,
        user_answer: str,
        grade: dict,
        correct: bool | None,
        *,
        hinted: bool = False,
    ) -> int:
        return self.db.execute(
            """INSERT INTO material_attempts(material_id, question_index, user_answer, grade_json, correct, hinted, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                material_id,
                question_index,
                user_answer,
                json.dumps(grade, ensure_ascii=False),
                None if correct is None else int(correct),
                int(hinted),
                utcnow_iso(),
            ),
        )

    def mark_material_used(self, material_id: str) -> None:
        self.db.execute("UPDATE materials SET status='used' WHERE id=?", (material_id,))

    # ---------------------------------------------------------------- AI logs
    def log_ai_request(
        self,
        *,
        provider: str,
        model: str,
        purpose: str,
        prompt_version: str,
        status: str,
        latency_ms: int | None = None,
        error: str = "",
        cached: bool = False,
    ) -> None:
        self.db.execute(
            """INSERT INTO ai_request_logs(provider, model, purpose, prompt_version, status, latency_ms,
                                           error, cached, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (provider, model, purpose, prompt_version, status, latency_ms, error[:500], int(cached), utcnow_iso()),
        )

    def ai_requests_today(self) -> int:
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM ai_request_logs WHERE status='ok' AND cached=0 AND date(created_at)=date('now')",
                (),
                0,
            )
        )


def _material_dict(row) -> dict:
    data = dict(row)
    data["target_words"] = json.loads(data.pop("target_words_json") or "[]")
    data["questions"] = json.loads(data.pop("questions_json") or "[]")
    data["meta"] = json.loads(data.pop("meta_json") or "{}")
    return data
