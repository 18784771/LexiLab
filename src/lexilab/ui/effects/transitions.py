from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Callable

from rich.text import Text

TTE_EFFECTS = {
    "decrypt": ("effect_decrypt", "Decrypt"),
    "beams": ("effect_beams", "Beams"),
    "spray": ("effect_spray", "Spray"),
    "errorcorrect": ("effect_errorcorrect", "ErrorCorrect"),
    "wipe": ("effect_wipe", "Wipe"),
}


def build_effect(name: str, text: str):
    """Build a TerminalTextEffects iterable without writing to stdout."""
    module_name, class_name = TTE_EFFECTS[name]
    module = importlib.import_module(f"terminaltexteffects.effects.{module_name}")
    return getattr(module, class_name)(text)


@dataclass
class TTEAdapter:
    """Non-blocking frame adapter for Textual.

    TerminalTextEffects yields ANSI frames. This adapter converts them to Rich
    Text and updates a widget from a Textual timer; it never lets TTE clear the
    real terminal or block the event loop.
    """

    app: object
    widget: object
    text: str
    effect: str = "decrypt"
    fps: int = 30
    max_frames: int | None = None
    on_complete: Callable[[], None] | None = None
    _iterator: object | None = field(default=None, init=False, repr=False)
    _timer: object | None = field(default=None, init=False, repr=False)
    _frames: int = field(default=0, init=False, repr=False)
    _done: bool = field(default=False, init=False, repr=False)

    def start(self) -> None:
        if self._timer is not None or self.widget is None:
            return
        try:
            self._iterator = iter(build_effect(self.effect, self.text))
        except Exception:
            self.widget.update(Text(self.text))
            self._done = True
            if self.on_complete:
                self.on_complete()
            return
        self._timer = self.app.set_interval(1 / max(1, self.fps), self._next_frame)

    def _next_frame(self) -> None:
        if self._done:
            return
        try:
            frame = next(self._iterator)  # type: ignore[arg-type]
        except StopIteration:
            self.stop(final=True)
            return
        except Exception:
            self.stop(final=True)
            return
        self._frames += 1
        try:
            self.widget.update(Text.from_ansi(frame).rstrip())
        except Exception:
            self.widget.update(Text(self.text))
            self.stop(final=True)
            return
        if self.max_frames is not None and self._frames >= self.max_frames:
            self.stop(final=True)

    def stop(self, *, final: bool = False) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        if final and not self._done:
            self._done = True
            if self.widget is not None:
                self.widget.update(Text(self.text))
            if self.on_complete:
                self.on_complete()
