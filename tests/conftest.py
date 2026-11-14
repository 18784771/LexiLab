from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexilab.config.settings import Settings  # noqa: E402
from lexilab.context import AppContext  # noqa: E402
from tests.helpers import seed_vocab  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.data_dir = tmp_path
    s.general.data_dir = str(tmp_path)
    s.ai.enabled = False
    s.audio.enabled = False
    s.ensure_dirs()
    return s


@pytest.fixture
def context(settings: Settings) -> AppContext:
    ctx = AppContext(settings)
    seed_vocab(ctx.vocab_repo)
    return ctx


@pytest.fixture
def mock_context(settings: Settings) -> AppContext:
    settings.ai.enabled = True
    settings.ai.provider = "mock"
    settings.ai.model = "mock-v1"
    ctx = AppContext(settings)
    seed_vocab(ctx.vocab_repo)
    return ctx
