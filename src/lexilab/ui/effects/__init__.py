"""Presentation-only effects engine. It never touches learning state or the database."""

from lexilab.ui.effects.engine import EffectEvent, EffectsEngine, EffectsState
from lexilab.ui.effects.particles import Particle, ParticleSystem
from lexilab.ui.effects.presets import EffectsPreset, EffectsRuntime, preset_for

__all__ = [
    "EffectEvent",
    "EffectsEngine",
    "EffectsPreset",
    "EffectsRuntime",
    "EffectsState",
    "Particle",
    "ParticleSystem",
    "preset_for",
]
