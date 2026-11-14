#!/usr/bin/env python3
"""Standalone helper: import the real CET-6 wordbook into vocabulary.db."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lexilab.config.settings import load_settings  # noqa: E402
from lexilab.storage.connection import Database  # noqa: E402
from lexilab.storage.schema import ensure_vocabulary_schema  # noqa: E402
from lexilab.storage.vocab_repo import VocabularyRepository  # noqa: E402
from lexilab.vocabulary.cet6 import download_cet6, import_cet6  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="LexiLab 六级词库初始化")
    parser.add_argument("--file", type=Path, help="本地 full_line_jsonl 六级.jsonl")
    parser.add_argument("--download", action="store_true", help="下载到 data/raw/cet6.jsonl")
    parser.add_argument("--config", type=Path, help="配置文件路径")
    args = parser.parse_args()

    settings = load_settings(args.config)
    settings.ensure_dirs()
    source = args.file
    if source is None:
        source = settings.data_dir / "raw" / "cet6.jsonl"
        if args.download or not source.is_file():
            print(f"下载词库 -> {source}")
            download_cet6(source)
    if not source.is_file():
        print(f"文件不存在: {source}", file=sys.stderr)
        return 1

    db = Database(settings.vocabulary_db)
    ensure_vocabulary_schema(db)
    report = import_cet6(source, VocabularyRepository(db))
    print(report.as_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
