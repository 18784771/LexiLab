from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lexilab.cli.app import app
from lexilab.config.settings import Settings, load_settings, save_settings
from lexilab.storage.connection import Database
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.schema import ensure_learning_schema, ensure_vocabulary_schema
from lexilab.storage.vocab_repo import VocabularyRepository
from tests.helpers import seed_vocab

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = tmp_path / "settings.toml"
    settings = Settings()
    settings.general.data_dir = str(data_dir)
    settings.ai.enabled = False
    settings.audio.enabled = False
    save_settings(settings, config)
    monkeypatch.setenv("LEXILAB_CONFIG", str(config))
    monkeypatch.setenv("LEXILAB_DATA_DIR", str(data_dir))
    return {"data_dir": data_dir, "config": config}


def seed_cli_vocab(data_dir: Path):
    db = Database(data_dir / "vocabulary.db")
    ensure_vocabulary_schema(db)
    seed_vocab(VocabularyRepository(db))


def test_all_command_help(cli_env):
    runner = CliRunner()
    commands = [
        ["--help"],
        ["init", "--help"],
        ["doctor", "--help"],
        ["study", "--help"],
        ["review", "--help"],
        ["learn", "--help"],
        ["lookup", "--help"],
        ["related", "--help"],
        ["add", "--help"],
        ["import", "--help"],
        ["relations", "--help"],
        ["relations", "build", "--help"],
        ["relations", "stats", "--help"],
        ["relations", "download", "--help"],
        ["drill", "--help"],
        ["drill", "spelling", "--help"],
        ["drill", "recall", "--help"],
        ["drill", "synonyms", "--help"],
        ["drill", "similar-spelling", "--help"],
        ["drill", "confusion", "--help"],
        ["drill", "context", "--help"],
        ["drill", "listening", "--help"],
        ["drill", "dictation", "--help"],
        ["drill", "sentence", "--help"],
        ["say", "--help"],
        ["read", "--help"],
        ["listen", "--help"],
        ["write", "--help"],
        ["mistakes", "--help"],
        ["stats", "--help"],
        ["backup", "--help"],
        ["restore", "--help"],
        ["materials", "--help"],
        ["config", "--help"],
        ["config", "ai", "--help"],
        ["config", "audio", "--help"],
        ["vocab", "--help"],
        ["vocab", "list", "--help"],
        ["vocab", "use", "--help"],
        ["vocab", "show", "--help"],
        ["vocab", "pause", "--help"],
        ["vocab", "resume", "--help"],
        ["vocab", "remove", "--help"],
        ["vocab", "history", "--help"],
        ["vocab", "words", "--help"],
        ["version", "--help"],
    ]
    for args in commands:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output, result.exception)


def test_screen_is_not_exposed_as_user_command(cli_env):
    runner = CliRunner()
    result = runner.invoke(app, ["screen", "--help"])
    assert result.exit_code != 0


def test_relations_stats_and_related_are_available(cli_env):
    seed_cli_vocab(cli_env["data_dir"])
    runner = CliRunner()
    stats = runner.invoke(app, ["relations", "stats"])
    assert stats.exit_code == 0, stats.output
    assert "词汇关系库" in stats.output
    related = runner.invoke(app, ["related", "mitigate"])
    assert related.exit_code == 0, related.output
    assert "mitigate" in related.output


def test_doctor_reports_base_pass_and_ai_off(cli_env):
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "基础离线版本" in result.output
    assert "AI（可选）" in result.output
    assert "OFF" in result.output


def test_ai_commands_are_concise_when_disabled(cli_env):
    runner = CliRunner()
    for command in ("read", "write", "listen"):
        result = runner.invoke(app, [command])
        assert result.exit_code == 1
        assert "尚未启用" in result.output
        assert "Traceback" not in result.output


def test_audio_drill_is_concise_when_disabled(cli_env):
    runner = CliRunner()
    result = runner.invoke(app, ["drill", "listening", "--count", "1"])
    assert result.exit_code == 1
    assert "语音训练当前不可用" in result.output
    assert "Traceback" not in result.output


def test_config_ai_writes_optional_settings(cli_env):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "config",
            "ai",
            "--enable",
            "--provider",
            "mock",
            "--model",
            "mock-v1",
            "--path",
            str(cli_env["config"]),
        ],
    )
    assert result.exit_code == 0, result.output
    loaded = load_settings(cli_env["config"])
    assert loaded.ai.enabled is True
    assert loaded.ai.provider == "mock"
    assert loaded.ai.model == "mock-v1"
    assert "状态" in result.output


def test_config_audio_writes_optional_settings(cli_env):
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["config", "audio", "--disable", "--provider", "flite", "--voice", "slt", "--path", str(cli_env["config"])],
    )
    assert result.exit_code == 0, result.output
    loaded = load_settings(cli_env["config"])
    assert loaded.audio.enabled is False
    assert loaded.audio.provider == "flite"


def test_full_offline_learning_through_cli(cli_env):
    seed_cli_vocab(cli_env["data_dir"])
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["learn", "--count", "1"],
        input="left\n\nright\n",
    )
    assert result.exit_code == 0, result.output
    assert "SESSION SUMMARY" in result.output
    db = Database(cli_env["data_dir"] / "learning.db")
    assert db.scalar("SELECT COUNT(*) FROM cards", (), 0) == 2
    assert db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1


def test_cached_material_can_be_viewed_offline(cli_env):
    db = Database(cli_env["data_dir"] / "learning.db")
    ensure_learning_schema(db)
    repo = LearningRepository(db)
    material_id = repo.save_material(
        kind="reading",
        target_words=["mitigate"],
        topic="offline",
        difficulty=1,
        body="Offline cached reading body with enough text.",
        questions=[{"question": "Q?", "answer": "Reference answer", "rationale": ""}],
        model="mock-v1",
        provider="mock",
        prompt_version="v1",
        meta={"mock": True},
    )
    runner = CliRunner()
    result = runner.invoke(app, ["materials", "--show", material_id])
    assert result.exit_code == 0, result.output
    assert "Offline cached reading body" in result.output
    assert "Reference answer" in result.output


def test_noninteractive_menu_hides_ai_when_disabled(cli_env):
    seed_cli_vocab(cli_env["data_dir"])
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "开始今日学习" in result.output
    assert "设置" in result.output
    assert "单词复习" not in result.output
    assert "AI 阅读" not in result.output
    assert "非交互环境" in result.output


def test_startup_does_not_import_optional_sdks():
    code = (
        "import sys; import lexilab.cli.app; "
        "print('openai' in sys.modules); print('pyttsx3' in sys.modules)"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT / "src")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines == ["False", "False"]
