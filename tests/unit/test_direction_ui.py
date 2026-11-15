from __future__ import annotations

import asyncio

from lexilab.cli.actions import interface_action, learning_plan_action
from lexilab.models.session import ItemType, PlanItem, SessionPlan
from lexilab.ui.effects.presets import preset_for
from lexilab.ui.textual_app import LexiLabSessionApp
from tests.helpers import make_due_card, new_recall_plan
from tests.unit.test_textual_ui import make_context


def _review_app(ctx, word: str = "mitigate"):
    card = make_due_card(ctx.repo, word, "recognition")
    item = PlanItem(ItemType.REVIEW_RECOGNITION, word, direction="recognition", card_row_id=card["id"])
    sid = ctx.repo.create_session("review", SessionPlan(kind="review", items=[item]))
    return LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))


def test_right_arrow_records_easy_and_advances(tmp_path):
    ctx = make_context(tmp_path)
    app = _review_app(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("right")
            await pilot.pause(0.3)
            assert app._mode == "summary"
            await pilot.press("enter")
            await pilot.pause(0.1)
        return app.return_value

    assert asyncio.run(run()) is not None
    assert ctx.repo.db.scalar("SELECT rating FROM review_logs LIMIT 1", (), None) == 4


def test_left_arrow_shows_answer_then_enter_records_again(tmp_path):
    ctx = make_context(tmp_path)
    app = _review_app(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("left")
            await pilot.pause(0.1)
            assert app._stage == "answer"
            assert app._mode.startswith("recognition")
            await pilot.press("enter")
            await pilot.pause(0.3)
            # Again is followed by a short reinforcement item, not a second
            # FSRS review.
            assert app._mode == "reinforcement"
            await pilot.press("enter")
            await pilot.pause(0.1)
            await pilot.press("n")
            await pilot.pause(0.3)
            assert app._mode == "summary"
            await pilot.press("enter")
            await pilot.pause(0.1)

    asyncio.run(run())
    assert ctx.repo.db.scalar("SELECT rating FROM review_logs LIMIT 1", (), None) == 1


def test_up_then_left_is_again_not_hard(tmp_path):
    ctx = make_context(tmp_path)
    app = _review_app(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("up")
            await pilot.pause(0.1)
            assert app._stage == "check"
            await pilot.press("left")
            await pilot.pause(0.3)
            assert app._mode == "reinforcement"
            await pilot.press("enter")
            await pilot.pause(0.1)
            await pilot.press("n")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.1)

    asyncio.run(run())
    assert ctx.repo.db.scalar("SELECT rating FROM review_logs LIMIT 1", (), None) == 1


def test_up_then_right_is_hard(tmp_path):
    ctx = make_context(tmp_path)
    app = _review_app(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("up")
            await pilot.pause(0.1)
            await pilot.press("right")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.1)

    asyncio.run(run())
    assert ctx.repo.db.scalar("SELECT rating FROM review_logs LIMIT 1", (), None) == 2


def test_repeated_direction_does_not_duplicate_review(tmp_path):
    ctx = make_context(tmp_path)
    app = _review_app(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("right")
            await pilot.press("right")
            await pilot.press("right")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.1)

    asyncio.run(run())
    assert ctx.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1


def test_new_intro_right_records_one_review_and_skips_delayed_recall(tmp_path):
    ctx = make_context(tmp_path)
    sid = ctx.repo.create_session("study", SessionPlan(kind="study", items=new_recall_plan("mitigate")))
    app = LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            assert app._mode == "recognition:intro"
            await pilot.press("right")
            await pilot.pause(0.3)
            assert app._mode == "summary"
            await pilot.press("enter")
            await pilot.pause(0.1)
        return app.return_value

    result = asyncio.run(run())
    assert result is not None
    assert ctx.repo.db.scalar("SELECT COUNT(*) FROM cards", (), 0) == 2
    assert ctx.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1
    assert ctx.repo.db.scalar("SELECT rating FROM review_logs LIMIT 1", (), None) == 4


def test_new_intro_up_then_right_records_hard_once(tmp_path):
    ctx = make_context(tmp_path)
    sid = ctx.repo.create_session("study", SessionPlan(kind="study", items=new_recall_plan("mitigate")))
    app = LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("up")
            await pilot.pause(0.1)
            await pilot.press("right")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.1)

    asyncio.run(run())
    assert ctx.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 1
    assert ctx.repo.db.scalar("SELECT rating FROM review_logs LIMIT 1", (), None) == 2


def test_summary_can_request_continued_review(tmp_path):
    ctx = make_context(tmp_path)
    app = _review_app(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("right")
            await pilot.pause(0.3)
            assert app._mode == "summary"
            await pilot.press("r")
            await pilot.pause(0.2)
        return app.return_value

    result = asyncio.run(run())
    assert result is not None
    assert result.details.get("summary_choice") == "review"


def test_text_input_arrows_do_not_trigger_memory_rating(tmp_path):
    ctx = make_context(tmp_path)
    card = make_due_card(ctx.repo, "mitigate", "recall")
    item = PlanItem(ItemType.REVIEW_RECALL, "mitigate", direction="recall", card_row_id=card["id"])
    sid = ctx.repo.create_session("review", SessionPlan(kind="review", items=[item]))
    app = LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("m", "i", "t")
            await pilot.press("left")
            await pilot.press("right")
            await pilot.pause(0.1)
            assert app._mode == "production"
            assert ctx.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 0
            await pilot.press("ctrl+q")
            await pilot.pause(0.2)

    asyncio.run(run())
    assert ctx.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 0


def test_main_menu_has_only_three_options():
    from lexilab.cli.actions import _settings_options, _textual_options

    class Dummy:
        settings = None

    # _textual_options only uses the static menu list.
    assert [key for key, _ in _textual_options(Dummy())] == ["study", "settings", "q"]
    assert [key for key, _ in _settings_options(Dummy())] == [
        "plan",
        "stats",
        "vocab",
        "drill",
        "ai",
        "audio",
        "ui",
        "backup",
        "back",
    ]


def test_learning_plan_can_be_changed_and_saved(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    config = tmp_path / "settings.toml"
    ctx.settings.config_path = config
    answers = iter(["7", "45", "2", "2", "n", "y", "n", "y"])

    monkeypatch.setattr(type(ctx.io), "interactive", property(lambda self: True))
    monkeypatch.setattr(ctx.io, "read_line", lambda prompt: next(answers))
    assert learning_plan_action(ctx) == 0
    assert ctx.settings.learning.new_words_per_day == 7
    assert ctx.settings.learning.daily_minutes == 45
    assert ctx.settings.learning.plan_order == "old_first"
    assert ctx.settings.learning.new_word_order == "frequency"
    assert ctx.settings.learning.adaptive_new_words is False
    assert config.is_file()


def test_planner_does_not_force_screening_verification(context):
    plan = context.planner.build("study", minutes=30, new_count=2)
    assert all(item.item_type != ItemType.VERIFY for item in plan.items)


def test_interface_action_saves_display_and_contrast_settings(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    config = tmp_path / "settings.toml"
    ctx.settings.config_path = config
    answers = iter(["3", "n", "n", "y", "n", "y", "n"])

    monkeypatch.setattr(type(ctx.io), "interactive", property(lambda self: True))
    monkeypatch.setattr(ctx.io, "read_line", lambda prompt: next(answers))
    assert interface_action(ctx) == 0
    assert ctx.settings.ui.display_mode == "large"
    assert ctx.settings.ui.large_word_display is False
    assert ctx.settings.ui.high_contrast is False
    assert ctx.settings.ui.compact_mode is True
    assert ctx.settings.effects.enabled is False
    assert ctx.settings.effects.reduced_motion is True
    assert ctx.settings.ui.textual is False
    assert config.is_file()


def test_large_display_renders_word_without_changing_flow(tmp_path):
    ctx = make_context(tmp_path)
    ctx.settings.ui.display_mode = "large"
    ctx.settings.ui.large_word_display = True
    app = _review_app(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            rendered = app._current_word_plain
            assert "█" in rendered
            assert len(rendered.splitlines()) == 5
            assert app.meta.content.plain == "/ˈtest/"
            await pilot.press("right")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.1)

    asyncio.run(run())


def test_resizing_to_small_switches_to_compact_prompt(tmp_path):
    ctx = make_context(tmp_path)
    app = _review_app(ctx)

    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            assert "\n" in app.prompt.content.plain
            await pilot.resize_terminal(44, 16)
            await pilot.pause(0.2)
            assert "\n" not in app.prompt.content.plain
            assert app._current_word_plain == "mitigate"
            assert "[Esc]" in app.footer.content.plain
            await pilot.press("right")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.1)

    asyncio.run(run())


def test_small_terminal_falls_back_to_plain_word_and_remains_usable(tmp_path):
    ctx = make_context(tmp_path)
    ctx.settings.ui.display_mode = "large"
    app = _review_app(ctx)

    async def run():
        async with app.run_test(size=(44, 16)) as pilot:
            await pilot.pause(0.2)
            assert app._current_word_plain == "mitigate"
            prompt = app.prompt.content.plain
            assert "\n" not in prompt
            assert "不记得" in prompt and "容易" in prompt
            assert app.prompt.region.bottom <= app.size.height
            assert "[Esc]" in app.footer.content.plain
            assert "详情" not in app.footer.content.plain
            await pilot.press("right")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.1)

    asyncio.run(run())
