from __future__ import annotations

import os
import select
import sys
from typing import TextIO


class KeyReader:
    """Read a single key without Enter when the terminal supports it.

    Falls back to line input for pipes/CI. Letters typed into a *text* prompt
    never pass through this class, so p/q/s cannot trigger shortcuts there.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdin
        self._is_windows = os.name == "nt"
        self._tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self._pushed: list[str] = []

    @property
    def interactive(self) -> bool:
        return self._tty

    def read_key(self) -> str:
        if self._pushed:
            return self._pushed.pop(0)
        if not self._tty:
            return self._read_line_key()
        if self._is_windows:
            return self._read_windows()
        return self._read_posix()

    def _read_line_key(self) -> str:
        line = self.stream.readline()
        if line == "":
            return "eof"
        value = line.strip()
        if value == "":
            return "enter"
        lowered = value.lower()
        if lowered in {"enter", "return"}:
            return "enter"
        if lowered in {"left", "right", "up", "down"}:
            return lowered
        if len(value) == 1:
            return lowered
        return "line"

    def _read_windows(self) -> str:
        import msvcrt

        char = msvcrt.getwch()
        if char in {"\x00", "\xe0"}:
            code = msvcrt.getwch()
            return {
                "H": "up",
                "P": "down",
                "M": "right",
                "K": "left",
            }.get(code, "special")
        return self._normalize(char)

    def _read_posix(self) -> str:
        import termios
        import tty

        fd = self.stream.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            char = self.stream.read(1)
            if char == "\x1b":
                ready, _, _ = select.select([fd], [], [], 0.03)
                if ready:
                    extra = self.stream.read(1)
                    if extra in {"[", "O"}:
                        code = ""
                        if select.select([fd], [], [], 0.03)[0]:
                            code = self.stream.read(1)
                        return {
                            "A": "up",
                            "B": "down",
                            "C": "right",
                            "D": "left",
                        }.get(code, "special")
                return "esc"
            return self._normalize(char)
        except (OSError, ValueError):
            return "eof"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    @staticmethod
    def _normalize(char: str) -> str:
        if char in {"\r", "\n"}:
            return "enter"
        if char == "\x03":
            raise KeyboardInterrupt
        if char == "\x04":
            return "eof"
        if char == "\x1b":
            return "esc"
        if char == "\x7f":
            return "backspace"
        return char.lower()
