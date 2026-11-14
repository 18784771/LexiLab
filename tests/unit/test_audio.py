from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lexilab.audio.tts import AudioService, TTSUnavailable
from lexilab.config.settings import Settings


def audio_settings(tmp_path: Path, **kwargs) -> Settings:
    s = Settings()
    s.data_dir = tmp_path
    s.general.data_dir = str(tmp_path)
    s.ai.enabled = False
    s.audio.enabled = True
    for key, value in kwargs.items():
        setattr(s.audio, key, value)
    s.ensure_dirs()
    return s


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_flite_synthesis_and_cache(tmp_path: Path):
    s = audio_settings(tmp_path, provider="flite", voice="slt", rate=1.0)
    service = AudioService(s)
    status = service.status()
    if not status["provider_available"]:
        pytest.skip(status["provider_reason"])
    path = service.get_audio("We need to mitigate the risk.")
    assert path.is_file()
    assert path.stat().st_size > 1000
    again = service.get_audio("We need to mitigate the risk.")
    assert again == path
    files = list((tmp_path / "audio").glob("*.wav"))
    assert len(files) == 1


def test_cache_key_changes_with_voice_and_rate(tmp_path: Path):
    s = audio_settings(tmp_path, provider="flite", voice="slt", rate=1.0)
    service = AudioService(s)
    key1 = service.cache_key("hello")
    s.audio.voice = "kal"
    key2 = service.cache_key("hello")
    s.audio.rate = 0.8
    key3 = service.cache_key("hello")
    assert len({key1, key2, key3}) == 3


def test_no_provider_raises(tmp_path: Path):
    s = audio_settings(tmp_path, provider="none")
    service = AudioService(s)
    with pytest.raises(TTSUnavailable):
        service.get_audio("hello")


def test_play_without_player_reports_failure(tmp_path: Path):
    s = audio_settings(tmp_path, provider="flite")
    service = AudioService(s)
    service.player = None
    result = service.play(Path("x.wav"))
    assert result.ok is False
    assert result.message


def test_audio_disabled_returns_none_provider(tmp_path: Path):
    s = audio_settings(tmp_path, provider="auto")
    s.audio.enabled = False
    service = AudioService(s)
    assert service.provider.name == "none"
