from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable

from lexilab.ui.effects.presets import EffectsPreset, EffectsRuntime


class EffectEvent(StrEnum):
    KEY_TYPED = "KEY_TYPED"
    ANSWER_CORRECT = "ANSWER_CORRECT"
    ANSWER_INCORRECT = "ANSWER_INCORRECT"
    COMBO_INCREASED = "COMBO_INCREASED"
    CARD_CHANGED = "CARD_CHANGED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    AI_GENERATING = "AI_GENERATING"


COMBO_MILESTONES = (3, 5, 10, 20)


@dataclass
class EffectsState:
    combo: int = 0
    best_combo: int = 0
    last_event: str = ""
    total_correct: int = 0


@dataclass
class EffectsEngine:
    runtime: EffectsRuntime
    sink: Callable[[EffectEvent, dict, EffectsState], None] | None = None
    state: EffectsState = field(default_factory=EffectsState)

    @property
    def enabled(self) -> bool:
        return self.runtime.enabled

    def toggle(self) -> bool:
        self.runtime = EffectsRuntime(
            enabled=not self.runtime.enabled,
            preset=self.runtime.preset if self.runtime.preset != EffectsPreset.OFF else EffectsPreset.NORMAL,
            typing_particles=self.runtime.typing_particles,
            shake_on_error=self.runtime.shake_on_error,
            pulse_on_correct=self.runtime.pulse_on_correct,
            combo=self.runtime.combo,
            startup_animation=self.runtime.startup_animation,
            reduced_motion=self.runtime.reduced_motion,
            max_particles_limit=self.runtime.max_particles_limit,
        )
        return self.runtime.enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self.runtime.enabled:
            self.toggle()

    def emit(self, event: EffectEvent, **payload) -> None:
        if not self.runtime.enabled:
            return
        if event == EffectEvent.ANSWER_CORRECT:
            hinted = bool(payload.get("hinted"))
            independent = bool(payload.get("independent", True))
            if hinted or not independent:
                self.state.combo = 0
            else:
                self.state.combo += 1
                self.state.total_correct += 1
                self.state.best_combo = max(self.state.best_combo, self.state.combo)
                payload["combo"] = self.state.combo
                if self.runtime.combo and self.state.combo in COMBO_MILESTONES:
                    self._send(
                        EffectEvent.COMBO_INCREASED,
                        {"combo": self.state.combo, "milestone": True},
                    )
            payload["hinted"] = hinted
        elif event == EffectEvent.ANSWER_INCORRECT:
            self.state.combo = 0
            payload["combo"] = 0
        self.state.last_event = event.value
        self._send(event, payload)

    def _send(self, event: EffectEvent, payload: dict) -> None:
        if self.sink is not None:
            self.sink(event, payload, self.state)
