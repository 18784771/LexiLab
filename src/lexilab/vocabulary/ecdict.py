from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Callable

from lexilab.storage.schema import utcnow_iso
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.vocabulary.cet6 import sha256_file

ECDICT_CSV_URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv"
ECDICT_SQLITE_URL = "https://github.com/skywind3000/ECDICT/releases/download/1.0.28/ecdict-sqlite-28.zip"
ECDICT_SOURCE_URL = "https://github.com/skywind3000/ECDICT"
ECDICT_LICENSE = "MIT (skywind3000/ECDICT)"


def download_ecdict(target: Path, *, progress: Callable[[int, int], None] | None = None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(ECDICT_CSV_URL, headers={"User-Agent": "LexiLab/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as fh:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    tmp.replace(target)
    return target


def import_ecdict_file(path: str | Path, repo: VocabularyRepository, *, progress: Callable[[int], None] | None = None) -> dict:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        count = repo.import_ecdict_sqlite(source)
    elif suffix == ".csv":
        count = repo.import_ecdict_csv(source)
    else:
        raise ValueError("ECDICT 数据必须是 .csv 或 .db/.sqlite 文件")
    if progress:
        progress(count)
    digest = sha256_file(source)
    repo.set_metadata("ecdict.source_url", ECDICT_SOURCE_URL)
    repo.set_metadata("ecdict.path", str(source))
    repo.set_metadata("ecdict.sha256", digest)
    repo.set_metadata("ecdict.license", ECDICT_LICENSE)
    repo.set_metadata("ecdict.imported_at", utcnow_iso())
    return {"entries": count, "sha256": digest, "path": str(source)}
