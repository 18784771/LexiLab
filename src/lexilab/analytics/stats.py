from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.vocab_repo import VocabularyRepository


def _local_day_bounds(day_offset: int = 0) -> tuple[str, str]:
    local_now = datetime.now().astimezone()
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).isoformat()
    end_utc = end_local.astimezone(timezone.utc).isoformat()
    return start_utc, end_utc


class AnalyticsService:
    def __init__(self, repo: LearningRepository, vocab: VocabularyRepository | None = None) -> None:
        self.repo = repo
        self.vocab = vocab

    def summary(self) -> dict:
        start, end = _local_day_bounds()
        db = self.repo.db
        due_count = self.repo.count_due()
        learned_total = int(db.scalar("SELECT COUNT(DISTINCT word_key) FROM cards", (), 0))
        today_new = int(
            db.scalar(
                """SELECT COUNT(DISTINCT word_key) FROM cards
                   WHERE direction='recognition' AND created_at >= ? AND created_at < ?""",
                (start, end),
                0,
            )
        )
        today_reviews = int(
            db.scalar(
                "SELECT COUNT(*) FROM review_logs WHERE review_datetime >= ? AND review_datetime < ?",
                (start, end),
                0,
            )
        )
        today_minutes = int(
            db.scalar(
                """SELECT COALESCE(SUM((julianday(COALESCE(ended_at, last_seen_at)) - julianday(started_at)) * 1440), 0)
                   FROM sessions WHERE started_at >= ? AND started_at < ?""",
                (start, end),
                0,
            )
            or 0
        )
        personal_count = int(db.scalar("SELECT COUNT(*) FROM personal_words", (), 0))
        return {
            "due_count": due_count,
            "learned_total": learned_total,
            "today_new": today_new,
            "today_reviews": today_reviews,
            "today_minutes": today_minutes,
            "personal_count": personal_count,
            "skills": self.skill_accuracy(),
            "delayed_7d": self.delayed_recall(7),
            "delayed_30d": self.delayed_recall(30),
            "weak_words": self.repo.weak_words(10),
            "open_errors": self.repo.list_open_errors(10),
            "avg_response_ms": self.avg_response_ms(),
            "upcoming": self.upcoming_burden(7),
            "new_per_day": self.new_words_last_days(7),
        }

    def skill_accuracy(self) -> dict[str, dict]:
        db = self.repo.db
        result: dict[str, dict] = {}
        for direction, skill in (("recognition", "recognition"), ("recall", "recall")):
            row = db.query_one(
                """SELECT COUNT(*) AS n, SUM(CASE WHEN rating >= 3 THEN 1 ELSE 0 END) AS ok
                   FROM review_logs WHERE direction=?""",
                (direction,),
            )
            n = int(row["n"] or 0)
            ok = int(row["ok"] or 0)
            result[skill] = {"sample": n, "correct": ok, "accuracy": (ok / n) if n else None}
        for skill in ("spelling", "listening", "context", "production"):
            row = db.query_one(
                """SELECT COUNT(*) AS n, SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS ok
                   FROM training_logs WHERE skill=? AND correct IS NOT NULL""",
                (skill,),
            )
            n = int(row["n"] or 0)
            ok = int(row["ok"] or 0)
            result[skill] = {"sample": n, "correct": ok, "accuracy": (ok / n) if n else None}
        typed_recall = db.query_one(
            """SELECT COUNT(*) AS n, SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS ok
               FROM training_logs WHERE skill='recall' AND correct IS NOT NULL""",
        )
        n = int(typed_recall["n"] or 0)
        if n:
            previous = result["recall"]
            total = n + previous["sample"]
            correct = int(typed_recall["ok"] or 0) + previous["correct"]
            result["recall"] = {
                "sample": total,
                "correct": correct,
                "accuracy": (correct / total) if total else None,
            }
        return result

    def delayed_recall(self, days: int, minimum_sample: int = 5) -> dict:
        row = self.repo.db.query_one(
            """SELECT COUNT(*) AS n, SUM(CASE WHEN rating >= 3 THEN 1 ELSE 0 END) AS ok
               FROM review_logs WHERE elapsed_days >= ?""",
            (float(days),),
        )
        n = int(row["n"] or 0)
        ok = int(row["ok"] or 0)
        return {
            "days": days,
            "sample": n,
            "correct": ok,
            "accuracy": (ok / n) if n else None,
            "sufficient": n >= minimum_sample,
        }

    def avg_response_ms(self) -> int | None:
        value = self.repo.db.scalar(
            """SELECT AVG(x) FROM (
                 SELECT review_duration_ms AS x FROM review_logs WHERE review_duration_ms IS NOT NULL
                 UNION ALL
                 SELECT duration_ms AS x FROM training_logs WHERE duration_ms IS NOT NULL
               )""",
            (),
            None,
        )
        return int(value) if value else None

    def upcoming_burden(self, days: int = 7) -> list[dict]:
        today_start, _ = _local_day_bounds()
        rows = self.repo.db.query_all(
            "SELECT due FROM cards WHERE suspended=0 AND due < ?",
            (_local_day_bounds(days)[0],),
        )
        buckets = [0] * days
        today_local = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        for row in rows:
            try:
                due = datetime.fromisoformat(row["due"])
            except (ValueError, TypeError):
                continue
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            local_due = due.astimezone()
            index = (local_due.date() - today_local.date()).days
            index = max(0, min(days - 1, index))
            buckets[index] += 1
        return [
            {"date": (today_local + timedelta(days=i)).date().isoformat(), "count": buckets[i]}
            for i in range(days)
        ]

    def new_words_last_days(self, days: int = 7) -> list[dict]:
        result = []
        for offset in range(days - 1, -1, -1):
            start, end = _local_day_bounds(-offset)
            count = int(
                self.repo.db.scalar(
                    """SELECT COUNT(DISTINCT word_key) FROM cards
                       WHERE direction='recognition' AND created_at >= ? AND created_at < ?""",
                    (start, end),
                    0,
                )
            )
            day = (datetime.now().astimezone() - timedelta(days=offset)).date().isoformat()
            result.append({"date": day, "count": count})
        return result
