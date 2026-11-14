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
            await pilot.pause(0.2)
            print("paused", flush=True)
            await pilot.press("f1")
            print("hinted flag", app._hinted, "mode", app._mode, flush=True)
            app.answer.value = "mitigate"
            print("after value", app._hinted, flush=True)
            await pilot.press("enter")
            await pilot.pause(0.3)
            print("after enter", app._hinted, "mode", app._mode, flush=True)
            print("mode", app._mode, "combo", app.effects.state.combo, flush=True)
            await pilot.press("ctrl+q")
            print("quit pressed", flush=True)
            await pilot.pause(0.2)
        print("exited", flush=True)


asyncio.run(main())
print("done", flush=True)
