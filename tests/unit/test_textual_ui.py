from __future__ import annotations

import asyncio
from pathlib import Path


from lexilab.config.settings import Settings
from lexilab.context import AppContext
from lexilab.models.session import ItemType, PlanItem, SessionPlan
from lexilab.ui.effects.presets import preset_for
from lexilab.ui.effects.transitions import build_effect
from lexilab.ui.textual_app import LexiLabMenuApp, LexiLabSessionApp
from tests.helpers import make_due_card, new_recall_plan, seed_vocab


def make_context(tmp_path: Path, **effects) -> AppContext:
    s = Settings()
    s.data_dir = tmp_path
    s.audio.enabled = False
    s.effects.startup_animation = False
    for key, value in effects.items():
        setattr(s.effects, key, value)
    s.ensure_dirs()
    ctx = AppContext(s)
    seed_vocab(ctx.vocab_repo)
    return ctx


def test_textual_new_word_session_is_keyboard_only(tmp_path):
    ctx = make_context(tmp_path)
    sid = ctx.repo.create_session("study", SessionPlan(kind="study", items=new_recall_plan("mitigate")))
    app = LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            # Intro: unknown -> show answer -> Enter; delayed recall: easy -> next.
            await pilot.press("left")
            await pilot.pause(0.1)
            await pilot.press("enter")
            await pilot.pause(0.2)
            await pilot.press("right")
            await pilot.pause(0.3)
            assert app._mode == "summary"
            await pilot.press("enter")
            await pilot.pause(0.2)
        return app.return_value

    result = asyncio.run(run())
    assert result is not None
    assert result.new_words == 1
    assert ctx.repo.count_cards() == 2
    assert ctx.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1


def test_textual_production_typing_does_not_trigger_shortcuts(tmp_path):
    ctx = make_context(tmp_path)
    card = make_due_card(ctx.repo, "mitigate", "recall")
    item = PlanItem(ItemType.REVIEW_RECALL, "mitigate", direction="recall", card_row_id=card["id"])
    sid = ctx.repo.create_session("review", SessionPlan(kind="review", items=[item]))
    app = LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("q", "u", "i", "t")
            await pilot.pause(0.1)
            assert app._mode == "production"
            assert app.answer.value == "quit"
            app.answer.value = "mitigate"
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert app._mode == "feedback"
            assert app.effects.state.combo == 1
            await pilot.press("enter")
            await pilot.pause(0.2)
            if app._mode == "summary":
                await pilot.press("enter")
                await pilot.pause(0.2)

    asyncio.run(run())
    assert ctx.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1


def test_particles_can_be_disabled_and_session_still_works(tmp_path):
    ctx = make_context(tmp_path, enabled=False)
    card = make_due_card(ctx.repo, "mitigate", "recall")
    item = PlanItem(ItemType.REVIEW_RECALL, "mitigate", direction="recall", card_row_id=card["id"])
    sid = ctx.repo.create_session("review", SessionPlan(kind="review", items=[item]))
    app = LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("m", "i", "t", "i", "g", "a", "t", "e")
            await pilot.pause(0.1)
            assert app._canvas.system.active == 0
            await pilot.press("enter")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.2)
            if app._mode == "summary":
                await pilot.press("enter")
                await pilot.pause(0.1)

    asyncio.run(run())
    assert ctx.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1


def test_ctrl_q_keeps_pending_item(tmp_path):
    ctx = make_context(tmp_path)
    card = make_due_card(ctx.repo, "mitigate", "recall")
    item = PlanItem(ItemType.REVIEW_RECALL, "mitigate", direction="recall", card_row_id=card["id"])
    sid = ctx.repo.create_session("review", SessionPlan(kind="review", items=[item]))
    app = LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("ctrl+q")
            await pilot.pause(0.2)

    asyncio.run(run())
    assert ctx.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 0
    assert len(ctx.repo.pending_items(sid)) == 1


def test_textual_menu_default_focus_starts_today_lesson(tmp_path):
    ctx = make_context(tmp_path)
    app = LexiLabMenuApp(ctx, [("study", "开始今日学习"), ("settings", "设置"), ("q", "退出")])

    async def run():
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("enter")
            await pilot.pause(0.1)
        return app.return_value

    assert asyncio.run(run()) == "study"


def test_textual_menu_uses_arrows_and_digits(tmp_path):
    ctx = make_context(tmp_path)
    options = [("study", "开始今日学习"), ("review", "单词复习"), ("learn", "新词学习"), ("q", "退出")]
    app = LexiLabMenuApp(ctx, options)

    async def run():
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("down", "enter")
            await pilot.pause(0.1)
        return app.return_value

    assert asyncio.run(run()) == "review"


def test_tte_frames_are_data_not_terminal_writes():
    effect = build_effect("decrypt", "LexiLab")
    frames = []
    iterator = iter(effect)
    for _ in range(20):
        frames.append(next(iterator))
    assert any("\x1b[" in frame for frame in frames)
    from rich.text import Text

    text = Text.from_ansi(frames[-1])
    assert text.plain.strip()
