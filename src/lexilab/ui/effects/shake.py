from __future__ import annotations

SHAKE_MILLISECONDS = 200
SHAKE_SEQUENCE = (0, -1, 1, -1, 1, 0)
SHAKE_STEP_MS = SHAKE_MILLISECONDS // (len(SHAKE_SEQUENCE) - 1)


def shake_offsets() -> tuple[tuple[int, int], ...]:
    """Return (delay_ms, horizontal_offset) pairs for a local 200ms shake."""
    return tuple(
        (index * SHAKE_STEP_MS, offset) for index, offset in enumerate(SHAKE_SEQUENCE)
    )
