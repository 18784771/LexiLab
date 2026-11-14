from __future__ import annotations

import importlib.util
from io import StringIO

import pytest
from rich.console import Console

from lexilab.ai.base import AIUnavailable
from lexilab.ai.schemas import WordInfo
from lexilab.ai.service import AIService
from lexilab.capabilities import CapabilityRegistry, CapabilityState, ai_usable, audio_ready
from lexilab.ui.menu import menu_keys, render_main_menu


class FakeAudio:
    def __init__(self, tts=True, player=True):
        self.tts = tts
        self.player = player

    def status(self):
        return {
            "provider": "fake" if self.tts else "none",
            "provider_available": self.tts,
            "provider_reason": "ok" if self.tts else "no tts",
            "player": "fake" if self.player else None,
            "player_reason": "ok" if self.player else "no player",
            "cache_dir": "/tmp",
        }


def registry(context, *, audio=None):
    return CapabilityRegistry(context.settings, context.repo, context.vocab_repo, audio)


def test_default_ai_is_disabled():
    from lexilab.config.settings import DEFAULT_CONFIG_TEXT, Settings

    assert Settings().ai.enabled is False
    assert "enabled = false" in DEFAULT_CONFIG_TEXT


def test_default_capabilities_hide_ai_and_audio(context):
    context.settings.ai.enabled = False
    context.settings.audio.enabled = False
    caps = registry(context).collect()
    assert caps["ai"].state == CapabilityState.DISABLED
    assert caps["tts"].state == CapabilityState.DISABLED
    assert caps["vocabulary"].state == CapabilityState.READY
    assert not ai_usable(caps)
    assert not audio_ready(caps)
    assert menu_keys(caps) == {"1", "2", "6", "7", "8"}


def test_audio_ready_adds_only_audio_entry(context):
    context.settings.audio.enabled = True
    caps = registry(context, audio=FakeAudio()).collect()
    assert caps["tts"].state == CapabilityState.READY
    assert audio_ready(caps)
    assert "3" in menu_keys(caps)
    assert "4" not in menu_keys(caps)


def test_ai_mock_ready_adds_ai_entries(context):
    context.settings.ai.enabled = True
    context.settings.ai.provider = "mock"
    context.settings.ai.model = "mock-v1"
    caps = registry(context, audio=FakeAudio(False, False)).collect()
    assert caps["ai"].state == CapabilityState.READY
    assert {"4", "5"}.issubset(menu_keys(caps))
    assert "3" not in menu_keys(caps)


def test_ai_unconfigured_without_model(context):
    context.settings.ai.enabled = True
    context.settings.ai.provider = "deepseek"
    context.settings.ai.model = ""
    caps = registry(context).collect()
    assert caps["ai"].state == CapabilityState.UNCONFIGURED
    assert "4" not in menu_keys(caps)


def test_ai_unavailable_without_openai_dependency(context, monkeypatch):
    context.settings.ai.enabled = True
    context.settings.ai.provider = "deepseek"
    context.settings.ai.model = "some-model"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *args, **kwargs: None if name == "openai" else object(),
    )
    caps = registry(context).collect()
    assert caps["ai"].state == CapabilityState.UNAVAILABLE
    assert "4" not in menu_keys(caps)


def test_ai_error_is_retryable_but_still_visible(context):
    context.settings.ai.enabled = True
    context.settings.ai.provider = "mock"
    context.settings.ai.model = "mock-v1"
    context.repo.log_ai_request(
        provider="mock",
        model="mock-v1",
        purpose="reading_generate",
        prompt_version="x",
        status="error",
        error="network down",
    )
    caps = registry(context).collect()
    assert caps["ai"].state == CapabilityState.ERROR
    assert ai_usable(caps)
    assert {"4", "5"}.issubset(menu_keys(caps))


def test_cached_material_adds_offline_entry(context):
    context.repo.save_material(
        kind="reading",
        target_words=["mitigate"],
        topic="test",
        difficulty=1,
        body="body",
        questions=[],
        model="m",
        provider="mock",
        prompt_version="v",
    )
    caps = registry(context).collect()
    assert caps["cached_materials"].ready
    assert "9" in menu_keys(caps)


def test_menu_rendering_hides_unavailable_entries(context):
    context.settings.ai.enabled = False
    context.settings.audio.enabled = False
    caps = registry(context).collect()
    buffer = StringIO()
    console = Console(file=buffer, width=100, force_terminal=False)
    render_main_menu(console, {}, caps)
    output = buffer.getvalue()
    assert "[1] 单词复习" in output
    assert "[c] 配置" in output
    assert "[4] AI 阅读" not in output
    assert "[3] 听音辨义" not in output


def test_narrow_menu_does_not_crash(context):
    caps = registry(context).collect()
    buffer = StringIO()
    console = Console(file=buffer, width=40, force_terminal=False)
    render_main_menu(console, {"due_count": 1}, caps)
    assert "LexiLab" in buffer.getvalue()


def test_disabled_ai_service_makes_no_calls(context):
    calls = {"n": 0}

    class CountingProvider:
        name = "fake"

        def available(self):
            return True, "ok"

        def generate(self, request):
            calls["n"] += 1
            raise AssertionError("must not be called")

    context.settings.ai.enabled = False
    service = AIService(context.settings, context.repo, provider=CountingProvider())
    assert service.available()[0] is False
    with pytest.raises(AIUnavailable):
        service.generate_validated(
            purpose="word_enrich",
            prompt_name="word_enrich",
            schema=WordInfo,
            word="test",
        )
    assert calls["n"] == 0
