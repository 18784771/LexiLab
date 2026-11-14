"""Power Mode / Textual 交互补充测试。"""

from __future__ import annotations

import asyncio

from lexilab.context import AppContext
from lexilab.config.settings import Settings
from tests.unit.test_textual_ui import make_context
from lexilab.models.session import ItemType, PlanItem, SessionPlan
from lexilab.ui.effects.presets import preset_for
from lexilab.ui.textual_app import LexiLabSessionApp
from lexilab.ui.textual_writing import LexiLabWritingApp
from tests.helpers import make_due_card, seed_vocab


def make_mock_context(tmp_path) -> AppContext:
    s = Settings()
    s.data_dir = tmp_path
    s.audio.enabled = False
    s.ai.enabled = True
    s.ai.provider = "mock"
    s.ai.model = "mock-v1"
    s.effects.startup_animation = False
    s.ensure_dirs()
    ctx = AppContext(s)
    seed_vocab(ctx.vocab_repo)
    return ctx


def _recall_session(ctx, word: str = "mitigate"):
    card = make_due_card(ctx.repo, word, "recall")
    item = PlanItem(ItemType.REVIEW_RECALL, word, direction="recall", card_row_id=card["id"])
    sid = ctx.repo.create_session("review", SessionPlan(kind="review", items=[item]))
    return LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))


def test_ctrl_t_toggles_particles_without_changing_input(tmp_path):
    ctx = make_context(tmp_path)
    app = _recall_session(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("ctrl+t")
            await pilot.press("m", "i", "t")
            await pilot.pause(0.1)
            assert not app.effects.runtime.enabled
            assert app._canvas.system.active == 0
            assert app.answer.value == "mit"
            await pilot.press("ctrl+t")
            await pilot.press("i", "g")
            await pilot.pause(0.1)
            assert app.effects.runtime.enabled
            assert app._canvas.system.active > 0
            assert app.answer.value == "mitig"
            await pilot.press("ctrl+q")
            await pilot.pause(0.2)

    asyncio.run(run())


def test_hinted_answer_does_not_extend_combo(tmp_path):
    ctx = make_context(tmp_path)
    app = _recall_session(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("f1")
            app.answer.value = "mitigate"
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert app._mode == "feedback"
            assert app.effects.state.combo == 0
            await pilot.press("ctrl+q")
            await pilot.pause(0.2)

    asyncio.run(run())


def test_textual_writing_uses_ctrl_enter_and_particles(tmp_path):
    ctx = make_mock_context(tmp_path)
    app = LexiLabWritingApp(ctx, level=1, topic=None, force_new=True, words=["mitigate"])

    async def run():
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause(0.6)
            assert app._mode == "writing"
            await pilot.press("m", "i", "t", "i", "g", "a", "t", "e", "space", "r", "i", "s", "k")
            assert app._textarea.text.startswith("mitigate")
            assert app._canvas.system.active > 0
            await pilot.press("ctrl+enter")
            await pilot.pause(0.6)
            assert app._mode == "feedback"
            await pilot.press("enter")
            await pilot.pause(0.2)
        return app.return_value

    result = asyncio.run(run())
    assert result is not None and result["submitted"] is True
