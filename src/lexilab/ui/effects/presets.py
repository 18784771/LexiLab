from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EffectsPreset(StrEnum):
    OFF = "off"
    MINIMAL = "minimal"
    NORMAL = "normal"
    POWER = "power"


@dataclass(frozen=True)
class EffectsRuntime:
    enabled: bool
    preset: EffectsPreset
    typing_particles: bool
    shake_on_error: bool
    pulse_on_correct: bool
    combo: bool
    startup_animation: bool
    reduced_motion: bool
    max_particles_limit: int = 0

    @property
    def max_particles(self) -> int:
        if not self.enabled or self.preset == EffectsPreset.OFF:
            return 0
        base = {
            EffectsPreset.MINIMAL: 16,
            EffectsPreset.NORMAL: 96,
            EffectsPreset.POWER: 220,
        }[self.preset]
        if self.max_particles_limit > 0:
            return min(base, self.max_particles_limit)
        return base

    @property
    def particles_per_key(self) -> int:
        if not self.enabled or self.reduced_motion or not self.typing_particles:
            return 0
        return {
            EffectsPreset.MINIMAL: 1,
            EffectsPreset.NORMAL: 2,
            EffectsPreset.POWER: 4,
        }[self.preset]

    @property
    def burst_particles(self) -> int:
        if not self.enabled or self.reduced_motion:
            return 0
        return {
            EffectsPreset.MINIMAL: 6,
            EffectsPreset.NORMAL: 18,
            EffectsPreset.POWER: 36,
        }[self.preset]

    @property
    def animations(self) -> bool:
        return self.enabled and self.preset != EffectsPreset.OFF and not self.reduced_motion

    @property
    def decorative_animations(self) -> bool:
        return self.animations and self.startup_animation


def preset_for(settings) -> EffectsRuntime:
    cfg = settings.effects
    preset = EffectsPreset(cfg.intensity)
    enabled = cfg.enabled and preset != EffectsPreset.OFF
    minimal = preset == EffectsPreset.MINIMAL
    return EffectsRuntime(
        enabled=enabled,
        preset=preset,
        typing_particles=cfg.typing_particles and not minimal,
        shake_on_error=cfg.shake_on_error,
        pulse_on_correct=cfg.pulse_on_correct,
        combo=cfg.combo,
        startup_animation=cfg.startup_animation and not minimal,
        reduced_motion=cfg.reduced_motion,
        max_particles_limit=cfg.max_particles,
    )
