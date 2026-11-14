from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from tests.unit.test_textual_power import _recall_session
from tests.unit.test_textual_ui import make_context


async def main():
    with tempfile.TemporaryDirectory() as d:
        ctx = make_context(Path(d))
        app = _recall_session(ctx)
        print("created", flush=True)
        async with app.run_test(size=(100, 30)) as pilot:
            print("mounted", flush=True)
            await pilot.pause(0.2)
            print("paused", flush=True)
            await pilot.press("ctrl+t")
            print("toggled", app.effects.runtime.enabled, flush=True)
            await pilot.press("ctrl+q")
            print("quit pressed", flush=True)
        print("exited", flush=True)


asyncio.run(main())
print("done", flush=True)
