from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from lexilab.config.settings import Settings

DB_NAMES = ("vocabulary.db", "learning.db")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_version(path: Path) -> int | None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_versions").fetchone()
            return int(row[0]) if row and row[0] is not None else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _snapshot(source: Path, target: Path) -> None:
    """Consistent snapshot using the sqlite backup API (safe with WAL)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def backup_databases(settings: Settings, dest: str | Path | None = None) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(dest) if dest else settings.data_dir / "backups" / timestamp
    target.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"created_at": datetime.now().isoformat(timespec="seconds"), "files": {}}
    for name in DB_NAMES:
        source = settings.data_dir / name
        if not source.exists():
            continue
        out = target / name
        _snapshot(source, out)
        manifest["files"][name] = {
            "size": out.stat().st_size,
            "sha256": _sha256(out),
            "schema_version": _schema_version(out),
        }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def verify_backup(path: str | Path) -> tuple[bool, str, Path]:
    backup = Path(path)
    if backup.is_file():
        if backup.suffix != ".db":
            return False, "备份文件必须是 .db 或包含 manifest.json 的目录", backup
        ok, message = _integrity(backup)
        return ok, message, backup
    manifest_path = backup / "manifest.json"
    if not manifest_path.is_file():
        return False, "目录中没有 manifest.json", backup
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"manifest.json 无法解析: {exc}", backup
    files = manifest.get("files") or {}
    if not files:
        return False, "备份不包含数据库文件", backup
    for name, info in files.items():
        file_path = backup / name
        if not file_path.is_file():
            return False, f"缺少文件: {name}", backup
        if info.get("sha256") and _sha256(file_path) != info["sha256"]:
            return False, f"文件校验失败: {name}", backup
        ok, message = _integrity(file_path)
        if not ok:
            return False, f"{name}: {message}", backup
    return True, "备份校验通过", backup


def _integrity(path: Path) -> tuple[bool, str]:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row and row[0] == "ok":
                return True, "integrity_check ok"
            return False, f"integrity_check 失败: {row[0] if row else 'unknown'}"
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, f"无法打开数据库: {exc}"


def restore_backup(path: str | Path, settings: Settings, *, confirmation: bool) -> tuple[bool, str]:
    if not confirmation:
        return False, "恢复操作需要确认（--yes）"
    ok, message, backup = verify_backup(path)
    if not ok:
        return False, message

    pre_dir = settings.data_dir / "backups" / f"pre-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    for name in DB_NAMES:
        current = settings.data_dir / name
        if current.exists():
            pre_dir.mkdir(parents=True, exist_ok=True)
            _snapshot(current, pre_dir / name)
    if pre_dir.exists():
        (pre_dir / "README.txt").write_text(
            "Restore 前自动备份，如需回滚可再次执行 lexi restore <此目录> --yes\n",
            encoding="utf-8",
        )

    try:
        if backup.is_file():
            filename = "learning.db" if "learning" in backup.name else "vocabulary.db"
            _restore_one(backup, settings.data_dir / filename)
        else:
            for name in DB_NAMES:
                source = backup / name
                if source.is_file():
                    _restore_one(source, settings.data_dir / name)
    except (OSError, sqlite3.Error) as exc:
        return False, f"恢复失败，原数据库保留于 {pre_dir}: {exc}"
    return True, f"恢复完成。恢复前快照: {pre_dir if pre_dir.exists() else '(无)'}"


def _restore_one(source: Path, target: Path) -> None:
    temp = target.with_suffix(target.suffix + ".restore-tmp")
    if temp.exists():
        temp.unlink()
    shutil.copy2(source, temp)
    ok, message = _integrity(temp)
    if not ok:
        temp.unlink(missing_ok=True)
        raise sqlite3.DatabaseError(message)
    temp.replace(target)
