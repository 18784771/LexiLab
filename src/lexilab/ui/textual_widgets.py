from __future__ import annotations

import time

from rich.text import Text
from textual.widgets import Input, Static, TextArea

from lexilab.ui.effects.engine import EffectEvent, EffectsEngine
from lexilab.ui.effects.particles import ParticleSystem


class ParticleCanvas(Static):
    """Bounded, non-blocking character-particle feedback area."""

    def __init__(self, engine: EffectsEngine, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.engine = engine
        self.system = ParticleSystem(max_particles=engine.runtime.max_particles)
        self._timer = None

    def on_mount(self) -> None:
        self.styles.height = 3
        self.update(Text(""))

    def on_unmount(self) -> None:
        self._stop_timer()

    def refresh_limit(self) -> None:
        self.system.max_particles = self.engine.runtime.max_particles

    def burst(self, count: int | None = None, *, color: str = "bright_green") -> None:
        self.refresh_limit()
        amount = self.engine.runtime.burst_particles if count is None else count
        if amount <= 0 or self.system.max_particles <= 0:
            return
        width = max(8, self.size.width or 40)
        self.system.spawn(
            min(amount, self.system.max_particles),
            width=width,
            height=3,
            color=color,
        )
        self._start_timer()

    def emit_key(self, count: int = 1) -> None:
        self.refresh_limit()
        amount = self.engine.runtime.particles_per_key * max(1, min(count, 8))
        if amount <= 0:
            return
        self.system.spawn(
            min(amount, self.system.max_particles),
            width=max(8, self.size.width or 40),
            height=3,
            color="bright_green",
        )
        self._start_timer()

    def clear(self) -> None:
        self.system.clear()
        self.update(Text(""))
        self._stop_timer()

    def _start_timer(self) -> None:
        if self._timer is None and self.is_mounted:
            self._timer = self.set_interval(0.05, self._tick)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None

    def _tick(self) -> None:
        if not self.system.active:
            self.update(Text(""))
            self._stop_timer()
            return
        self.system.tick(0.05)
        self.update(self.system.render(max(8, self.size.width or 40), 3))
        if not self.system.active:
            self._stop_timer()


class PowerInput(Input):
    """A normal Textual Input that only observes typing for particle feedback."""

    def __init__(self, canvas: ParticleCanvas, engine: EffectsEngine, **kwargs) -> None:
        super().__init__(**kwargs)
        self.canvas = canvas
        self.engine = engine
        self._previous = ""
        self._suppress = False
        self._last_typed_at = 0.0

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._suppress:
            return
        delta = len(event.value) - len(self._previous)
        if delta > 0:
            now = time.monotonic()
            rapid = (now - self._last_typed_at) < 0.18
            self._last_typed_at = now
            self.canvas.emit_key(delta * (2 if rapid else 1))
            self.engine.emit(EffectEvent.KEY_TYPED, count=delta)
        self._previous = event.value

    def reset_text(self) -> None:
        self._suppress = True
        try:
            self.value = ""
            self._previous = ""
        finally:
            self._suppress = False


class PowerTextArea(TextArea):
    """Multiline writing input with the same particle feedback (Ctrl+Enter submits)."""

    def __init__(self, canvas: ParticleCanvas, engine: EffectsEngine, **kwargs) -> None:
        super().__init__(**kwargs)
        self.canvas = canvas
        self.engine = engine
        self._previous_length = 0
        self._suppress = False
        self._last_typed_at = 0.0

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if self._suppress:
            return
        text = event.text_area.text
        delta = len(text) - self._previous_length
        if delta > 0:
            now = time.monotonic()
            rapid = (now - self._last_typed_at) < 0.18
            self._last_typed_at = now
            self.canvas.emit_key(delta * (2 if rapid else 1))
            self.engine.emit(EffectEvent.KEY_TYPED, count=delta)
        self._previous_length = len(text)

    def reset_text(self) -> None:
        self._suppress = True
        try:
            self.text = ""
            self._previous_length = 0
        finally:
            self._suppress = False


class ComboBadge(Static):
    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._timer = None

    def show(self, combo: int, *, milestone: bool = False) -> None:
        if combo < 3:
            self.update(Text(""))
            return
        style = "bold bright_yellow" if milestone else "bold yellow"
        self.update(Text(f"COMBO × {combo}", style=style))
        if milestone:
            self.styles.background = "dark_goldenrod"
            if self._timer is not None:
                self._timer.stop()
            self._timer = self.set_timer(0.35, self._restore)

    def _restore(self) -> None:
        self.styles.background = None
        self._timer = None

    def reset(self) -> None:
        self.update(Text(""))
