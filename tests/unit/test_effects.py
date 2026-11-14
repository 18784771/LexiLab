from __future__ import annotations

from lexilab.config.settings import Settings
from lexilab.ui.effects.engine import COMBO_MILESTONES, EffectEvent, EffectsEngine
from lexilab.ui.effects.particles import ParticleSystem
from lexilab.ui.effects.presets import preset_for
from lexilab.ui.effects.shake import SHAKE_SEQUENCE, shake_offsets


def engine(settings, sink=None):
    return EffectsEngine(preset_for(settings), sink=sink)


def test_combo_only_increases_for_independent_correct(settings):
    events = []
    e = engine(settings, sink=lambda event, payload, state: events.append((event, payload, state.combo)))
    for _ in range(3):
        e.emit(EffectEvent.ANSWER_CORRECT, hinted=False)
    assert e.state.combo == 3
    assert any(event == EffectEvent.COMBO_INCREASED for event, _, _ in events)
    e.emit(EffectEvent.ANSWER_CORRECT, hinted=True)
    assert e.state.combo == 0
    e.emit(EffectEvent.ANSWER_CORRECT, hinted=False)
    e.emit(EffectEvent.ANSWER_INCORRECT, hinted=False)
    assert e.state.combo == 0


def test_combo_milestones_are_configured(settings):
    assert COMBO_MILESTONES == (3, 5, 10, 20)
    e = engine(settings)
    for _ in range(5):
        e.emit(EffectEvent.ANSWER_CORRECT, hinted=False)
    assert e.state.best_combo == 5


def test_effects_disabled_emit_nothing(settings):
    settings.effects.enabled = False
    events = []
    e = engine(settings, sink=lambda *args: events.append(args))
    e.emit(EffectEvent.ANSWER_CORRECT)
    assert events == []
    assert not e.runtime.enabled


def test_particles_are_bounded_and_expire():
    system = ParticleSystem(max_particles=10, seed=1)
    for _ in range(100):
        system.spawn(20, width=20, height=3)
    assert 0 < system.active <= 10
    for _ in range(50):
        system.tick(0.05)
    assert system.active == 0
    assert system.render(20, 3).plain.strip() == ""


def test_particles_render_symbols():
    system = ParticleSystem(max_particles=10, seed=2)
    system.spawn(5, width=20, height=3)
    rendered = system.render(20, 3).plain
    assert any(char in rendered for char in ("✦", "·", "✧", "+"))


def test_shake_sequence_is_local_and_200ms():
    assert SHAKE_SEQUENCE == (0, -1, 1, -1, 1, 0)
    offsets = shake_offsets()
    assert offsets[0][1] == 0
    assert offsets[-1][1] == 0
    assert offsets[-1][0] <= 200
    assert len({offset for _, offset in offsets}) >= 3


def test_presets():
    s = Settings()
    s.effects.intensity = "off"
    assert not preset_for(s).enabled
    s.effects.intensity = "minimal"
    runtime = preset_for(s)
    assert runtime.enabled and not runtime.typing_particles
    s.effects.intensity = "power"
    power = preset_for(s)
    s.effects.intensity = "normal"
    normal = preset_for(s)
    assert power.max_particles > normal.max_particles
    s.effects.reduced_motion = True
    assert preset_for(s).particles_per_key == 0
