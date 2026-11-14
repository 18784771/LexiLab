#!/usr/bin/env python3
"""Standalone helper: import ECDICT CSV/SQLite into vocabulary.db."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lexilab.config.settings import load_settings  # noqa: E402
from lexilab.storage.connection import Database  # noqa: E402
from lexilab.storage.schema import ensure_vocabulary_schema  # noqa: E402
from lexilab.storage.vocab_repo import VocabularyRepository  # noqa: E402
from lexilab.vocabulary.ecdict import download_ecdict, import_ecdict_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="LexiLab ECDICT 本地词典导入")
    parser.add_argument("--file", type=Path, help="ecdict.csv 或兼容 stardict.db")
    parser.add_argument("--download", action="store_true", help="下载官方 ECDICT CSV")
    parser.add_argument("--config", type=Path, help="配置文件路径")
    args = parser.parse_args()

    settings = load_settings(args.config)
    settings.ensure_dirs()
    source = args.file
    if source is None:
        source = settings.data_dir / "raw" / "ecdict.csv"
        if args.download or not source.is_file():
            print(f"下载 ECDICT -> {source}")
            download_ecdict(source)
    if not source.is_file():
        print(f"文件不存在: {source}", file=sys.stderr)
        return 1

    db = Database(settings.vocabulary_db)
    ensure_vocabulary_schema(db)
    result = import_ecdict_file(source, VocabularyRepository(db))
    print(f"ECDICT 导入完成: {result['entries']} 条")
    print(f"SHA-256: {result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
