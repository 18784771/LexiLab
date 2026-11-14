from __future__ import annotations

PULSE_CORRECT = ("green", "bright_green")
PULSE_INCORRECT = ("red", "bright_red")
PULSE_MS = 260


def pulse_border(color: str) -> tuple[str, str]:
    return ("round", color)
