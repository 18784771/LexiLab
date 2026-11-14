from __future__ import annotations

from lexilab.storage.connection import Database
from lexilab.storage.schema import ensure_learning_schema


def test_learning_schema_upgrade_adds_hinted(tmp_path):
    db = Database(tmp_path / "learning.db")
    ensure_learning_schema(db)
    with db.transaction() as conn:
        conn.execute("DELETE FROM schema_versions WHERE version=2")
        conn.execute("ALTER TABLE material_attempts DROP COLUMN hinted")
    with db.read() as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(material_attempts)")}
    assert "hinted" not in columns
    ensure_learning_schema(db)
    with db.read() as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(material_attempts)")}
        version = conn.execute("SELECT MAX(version) FROM schema_versions").fetchone()[0]
    assert "hinted" in columns
    assert version == 2
