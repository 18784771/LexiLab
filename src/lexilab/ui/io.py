from __future__ import annotations

import sys

from lexilab.ui.keys import KeyReader


class TerminalIO:
    def __init__(self, keys: KeyReader | None = None) -> None:
        self.keys = keys or KeyReader()
        self._session = None

    @property
    def interactive(self) -> bool:
        return self.keys.interactive

    def read_line(self, prompt: str) -> str | None:
        if not self.interactive:
            try:
                return input(prompt)
            except (EOFError, KeyboardInterrupt):
                return None
        try:
            from prompt_toolkit import PromptSession

            if self._session is None:
                self._session = PromptSession()
            return self._session.prompt(prompt)
        except (EOFError, KeyboardInterrupt):
            return None

    def read_multiline(self, prompt: str, *, terminator: str = ".") -> str | None:
        print(prompt)
        print(f"（输入单独一行 {terminator} 或空行结束；Ctrl+C 取消）")
        lines: list[str] = []
        while True:
            line = self.read_line("> ")
            if line is None:
                return None
            if line.strip() in {"", terminator}:
                break
            lines.append(line)
        text = "\n".join(lines).strip()
        return text or None

    def read_char(self) -> str:
        return self.keys.read_key()

    def pause(self, message: str = "按 Enter 继续") -> None:
        try:
            input(message)
        except (EOFError, KeyboardInterrupt):
            pass


def is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False
