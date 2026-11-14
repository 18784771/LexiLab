from __future__ import annotations

import json
from pathlib import Path


from lexilab.config.settings import Settings
from lexilab.storage.backup import backup_databases, restore_backup, verify_backup
from lexilab.storage.connection import Database
from lexilab.vocabulary.cet6 import import_cet6
from tests.helpers import make_due_card


def test_backup_verify_and_restore_roundtrip(context, tmp_path: Path):
    make_due_card(context.repo, "mitigate")
    context.repo.add_training_log("mitigate", "spelling", correct=True)
    target = backup_databases(context.settings, tmp_path / "bk")
    ok, message, _ = verify_backup(target)
    assert ok, message
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert "learning.db" in manifest["files"]
    assert manifest["files"]["learning.db"]["sha256"]

    new_settings = Settings()
    new_settings.data_dir = tmp_path / "restored"
    new_settings.ensure_dirs()
    success, message = restore_backup(target, new_settings, confirmation=True)
    assert success, message
    restored = Database(new_settings.learning_db)
    assert restored.scalar("SELECT COUNT(*) FROM cards", (), 0) == 1
    assert restored.scalar("SELECT COUNT(*) FROM training_logs", (), 0) == 1


def test_restore_requires_confirmation(context, tmp_path: Path):
    target = backup_databases(context.settings, tmp_path / "bk2")
    success, message = restore_backup(target, context.settings, confirmation=False)
    assert success is False
    assert "确认" in message


def test_tampered_backup_is_rejected(context, tmp_path: Path):
    target = backup_databases(context.settings, tmp_path / "bk3")
    db = target / "learning.db"
    data = db.read_bytes()
    db.write_bytes(data + b"tamper")
    ok, message, _ = verify_backup(target)
    assert ok is False
    assert "校验" in message or "integrity" in message


def test_vocabulary_reimport_does_not_touch_learning_data(context, tmp_path: Path):
    make_due_card(context.repo, "mitigate")
    learning_count = context.repo.count_cards()
    raw = Path(__file__).resolve().parents[2] / "data" / "raw" / "cet6.jsonl"
    if not raw.is_file():
        return
    import_cet6(raw, context.vocab_repo)
    assert context.repo.count_cards() == learning_count
    assert context.repo.get_card("mitigate", "recognition") is not None
