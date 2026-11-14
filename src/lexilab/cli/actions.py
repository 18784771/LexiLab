from __future__ import annotations

import json
import os
import re
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from lexilab.ai.base import AIError
from lexilab.ai.service import AIService
from lexilab.audio.tts import TTSUnavailable
from lexilab.capabilities import ai_message, ai_usable, audio_ready
from lexilab.config.settings import config_summary, save_settings, write_default_config
from lexilab.context import AppContext
from lexilab.learning.screening import ScreeningService
from lexilab.paths import project_root
from lexilab.storage.backup import backup_databases, restore_backup, verify_backup
from lexilab.timeutil import local_time
from lexilab.training.audio_drills import AudioDrillSession
from lexilab.training.listening import ListeningSession
from lexilab.training.reading import ReadingSession
from lexilab.training.vocabulary import DrillSession
from lexilab.training.writing import WritingSession
from lexilab.ui.menu import render_main_menu
from lexilab.ui.screens import (
    books_screen,
    doctor_screen,
    lookup_screen,
    mistakes_screen,
    stats_screen,
)
from lexilab.vocabulary.cet6 import download_cet6, import_cet6
from lexilab.vocabulary.custom import import_custom_csv
from lexilab.vocabulary.ecdict import download_ecdict, import_ecdict_file
from lexilab.vocabulary.normalize import normalize_word


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-")
    return value or "custom"


def _confirm(ctx: AppContext, message: str) -> bool:
    if not ctx.io.interactive:
        return False
    answer = ctx.io.read_line(message + " [y/N]: ")
    return bool(answer and answer.strip().lower().startswith("y"))


def _progress(label: str, console: Console):
    state = {"decile": -1, "last_mb": 0}

    def callback(done: int, total: int) -> None:
        if total:
            decile = int(done * 10 / total)
            if decile != state["decile"]:
                state["decile"] = decile
                console.print(Text(f"{label}: {done * 100 // total}%", style="dim"), end="\r")
        else:
            mb = done // (1024 * 1024)
            if mb >= state["last_mb"] + 5:
                state["last_mb"] = mb
                console.print(Text(f"{label}: {mb} MB", style="dim"), end="\r")

    return callback


# --------------------------------------------------------------------- init
def init_action(
    ctx: AppContext,
    *,
    yes: bool = False,
    skip_vocab: bool = False,
    skip_ecdict: bool = False,
    vocab_file: Path | None = None,
    ecdict_file: Path | None = None,
    force_vocab: bool = False,
) -> int:
    console = ctx.console
    console.print(Text("LexiLab 初始化", style="bold cyan"))
    console.print(Text("学习数据库 learning.db 不会被词库导入覆盖。", style="dim"))
    if force_vocab and ctx.has_learning_data() and not yes:
        if not _confirm(ctx, "词库将重新导入，但学习记录保留。继续？"):
            console.print(Text("已取消。", style="yellow"))
            return 1

    if not skip_vocab:
        existing = ctx.vocab_repo.count_words()
        if existing and not force_vocab:
            console.print(Text(f"六级词库已存在（{existing} 个词条），跳过导入。", style="dim"))
        else:
            source = Path(vocab_file) if vocab_file else ctx.settings.data_dir / "raw" / "cet6.jsonl"
            if not source.is_file():
                if vocab_file:
                    console.print(Text(f"文件不存在: {source}", style="red"))
                    return 1
                console.print(Text("正在下载 KyleBing/english-vocabulary 六级词库…", style="dim"))
                try:
                    download_cet6(source, progress=_progress("六级词库", console))
                except Exception as exc:
                    console.print(Text(f"下载失败: {exc}", style="red"))
                    console.print(Text("可手动下载后运行: lexi init --vocab-file <path>", style="yellow"))
                    return 1
                console.print()
            report = import_cet6(source, ctx.vocab_repo)
            console.print(Text(report.as_text(), style="green"))
            ctx.repo.set_setting("active_book", "cet6")
    else:
        console.print(Text("已跳过六级词库导入。", style="yellow"))

    if not skip_ecdict:
        count = ctx.vocab_repo.count_ecdict()
        if count:
            console.print(Text(f"ECDICT 已存在（{count} 条），跳过导入。", style="dim"))
        else:
            source = Path(ecdict_file) if ecdict_file else ctx.settings.data_dir / "raw" / "ecdict.csv"
            if not source.is_file():
                if ecdict_file:
                    console.print(Text(f"文件不存在: {source}", style="red"))
                    return 1
                console.print(Text("正在下载 ECDICT 完整 CSV（约 66 MB）…", style="dim"))
                try:
                    download_ecdict(source, progress=_progress("ECDICT", console))
                except Exception as exc:
                    console.print(Text(f"ECDICT 下载失败（不影响背单词）: {exc}", style="yellow"))
                    console.print(Text("稍后可运行: lexi import <ecdict.csv> --kind ecdict", style="yellow"))
                    source = None
                console.print()
            if source is not None:
                try:
                    result = import_ecdict_file(source, ctx.vocab_repo)
                    console.print(Text(f"ECDICT 导入完成: {result['entries']} 条", style="green"))
                except Exception as exc:
                    console.print(Text(f"ECDICT 导入失败（不影响背单词）: {exc}", style="yellow"))
    else:
        console.print(Text("已跳过 ECDICT 导入。", style="yellow"))

    if not ctx.repo.get_setting("active_book"):
        ctx.repo.set_setting("active_book", "cet6")
    console.print()
    console.print(Text("初始化完成。下一步:", style="bold"))
    console.print(Text("  lexi doctor"))
    console.print(Text("  lexi"))
    return 0


# ------------------------------------------------------------------- doctor
def doctor_action(ctx: AppContext) -> int:
    import sys

    checks: list[dict] = []
    console = ctx.console
    caps = ctx.capabilities

    base_ready = caps["vocabulary"].ready and caps["fsrs"].ready
    checks.append(
        {
            "name": "基础离线版本",
            "state": "ready" if base_ready else "error",
            "detail": "PASS（词库 + FSRS + 学习数据库可用）" if base_ready else "FAIL（请运行 lexi init）",
        }
    )
    for key, label in (
        ("vocabulary", "词库"),
        ("fsrs", "FSRS"),
        ("ai", "AI（可选）"),
        ("tts", "语音合成（可选）"),
        ("player", "音频播放（可选）"),
        ("cached_materials", "本地材料"),
    ):
        cap = caps[key]
        checks.append(
            {
                "name": label,
                "state": cap.state.value,
                "detail": cap.reason,
            }
        )
    ecdict = ctx.vocab_repo.count_ecdict()
    checks.append(
        {
            "name": "ECDICT",
            "state": "ready" if ecdict else "unconfigured",
            "detail": f"{ecdict} 条" if ecdict else "未导入（可选；lexi import <csv> --kind ecdict）",
        }
    )
    checks.append(
        {
            "name": "学习数据库",
            "state": "ready",
            "detail": f"{ctx.learning_db.path} | cards={ctx.repo.count_cards()}",
        }
    )
    checks.append(
        {
            "name": "Python",
            "state": "ready" if sys.version_info >= (3, 11) else "error",
            "detail": sys.version.split()[0] + " (需要 >=3.11)",
        }
    )
    try:
        ctx.settings.data_dir.mkdir(parents=True, exist_ok=True)
        probe = ctx.settings.data_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append({"name": "数据目录", "state": "ready", "detail": str(ctx.settings.data_dir)})
    except OSError as exc:
        checks.append({"name": "数据目录", "state": "error", "detail": str(exc)})
    checks.append(
        {
            "name": "交互终端",
            "state": "ready" if ctx.io.interactive else "unavailable",
            "detail": "TTY" if ctx.io.interactive else "非 TTY（单键操作将降级为逐行输入）",
        }
    )
    metadata = {}
    for key in ("cet6.sha256", "cet6.imported_at", "ecdict.sha256", "ecdict.imported_at"):
        value = ctx.vocab_repo.get_metadata(key)
        if value:
            metadata[key] = value
    checks.append(
        {
            "name": "词库版本",
            "state": "ready",
            "detail": json.dumps(metadata, ensure_ascii=False),
        }
    )
    doctor_screen(console, checks)
    if caps["ai"].state.value in {"disabled", "unconfigured"}:
        console.print(
            Text("AI 是可选增强功能；当前配置下基础离线学习完整可用。", style="dim")
        )
    return 0


# ------------------------------------------------------------- study/review
def _plan_summary(ctx: AppContext, plan) -> None:
    ctx.console.print(
        Text(
            f"待复习 {plan.due_count} 张卡 | 本次新词 {plan.new_count} | "
            f"预计 {plan.estimated_seconds // 60} min",
            style="bold",
        )
    )
    for note in plan.notes:
        ctx.console.print(Text(f"  · {note}", style="dim"))


def _textual_enabled(ctx: AppContext) -> bool:
    if not ctx.settings.ui.textual or not ctx.io.interactive:
        return False
    if os.environ.get("LEXILAB_NO_TUI"):
        return False
    try:
        import textual  # noqa: F401
    except ImportError:
        return False
    return True


def _execute_session(ctx: AppContext, session_id: str):
    if _textual_enabled(ctx):
        from lexilab.ui.textual_app import run_textual_session

        return run_textual_session(ctx, session_id)
    return ctx.learning_session().run(session_id)


def _run_session(ctx: AppContext, kind: str, *, minutes: int | None, new_count: int | None):
    open_session = ctx.repo.get_open_session(kind=kind)
    if open_session:
        counts = ctx.repo.session_counts(open_session["id"])
        pending = counts.get("pending", 0)
        if pending:
            resume = True
            if ctx.io.interactive:
                ctx.console.print(
                    Text(
                        f"检测到未完成学习会话（{pending} 项）。[Enter] 继续  [n] 新建  [q] 退出",
                        style="yellow",
                    )
                )
                key = ctx.io.read_char()
                if key in {"q", "eof", "esc"}:
                    return None
                resume = key != "n"
            if resume:
                return _execute_session(ctx, open_session["id"])
            ctx.repo.abandon_session(open_session["id"])

    plan = ctx.planner.build(kind, minutes=minutes, new_count=new_count)
    if plan.is_empty:
        ctx.console.print(Text("当前没有需要学习的内容。", style="green"))
        for note in plan.notes:
            ctx.console.print(Text(f"  · {note}", style="dim"))
        return None
    _plan_summary(ctx, plan)
    session_id = ctx.repo.create_session(kind, plan)
    return _execute_session(ctx, session_id)


def study_action(
    ctx: AppContext,
    *,
    minutes: int | None = None,
    new_count: int | None = None,
    offer_training: bool = True,
) -> int:
    result = _run_session(ctx, "study", minutes=minutes, new_count=new_count)
    if result is None or result.quit or not offer_training:
        return 0
    try:
        _offer_training(ctx)
    except KeyboardInterrupt:
        ctx.console.print(Text("已退出。", style="dim"))
    return 0


def review_action(ctx: AppContext, *, minutes: int | None = None) -> int:
    _run_session(ctx, "review", minutes=minutes, new_count=0)
    return 0


def learn_action(ctx: AppContext, *, count: int | None = None, minutes: int | None = None) -> int:
    _run_session(ctx, "learn", minutes=minutes, new_count=count)
    return 0


def _offer_training(ctx: AppContext) -> None:
    caps = ctx.capabilities
    options: list[tuple[str, str]] = [("s", "拼写训练"), ("c", "语境填空")]
    if audio_ready(caps):
        options.extend([("v", "听音辨义"), ("d", "单词听写"), ("j", "句子听写")])
    if ai_usable(caps):
        options.extend([("r", "AI 阅读"), ("w", "AI 写作")])
        if audio_ready(caps):
            options.append(("l", "AI 听力"))
        if ctx.repo.list_open_errors(1):
            options.append(("m", "错误强化"))
    line = "   ".join(f"[{key}] {label}" for key, label in options) + "   [Enter] 结束"
    ctx.console.print()
    ctx.console.print(Text(line, style="dim"))
    key = ctx.io.read_char()
    try:
        if key == "s":
            drill_action(ctx, "spelling", count=8)
        elif key == "c":
            drill_action(ctx, "context", count=6)
        elif key == "v":
            audio_drill_action(ctx, "listening", count=8)
        elif key == "d":
            audio_drill_action(ctx, "dictation", count=8)
        elif key == "j":
            audio_drill_action(ctx, "sentence", count=5)
        elif key == "r":
            read_action(ctx)
        elif key == "w":
            write_action(ctx)
        elif key == "l":
            listen_action(ctx)
        elif key == "m":
            ai_reinforcement_action(ctx)
    except (AIError, TTSUnavailable) as exc:
        ctx.console.print(Text(str(exc), style="yellow"))


# ------------------------------------------------------------------ screen
def screen_action(ctx: AppContext, *, limit: int = 50) -> int:
    service = ScreeningService(
        ctx.settings,
        ctx.repo,
        ctx.vocab_repo,
        ctx.vocab,
        ctx.memory,
        ctx.audio,
        ctx.console,
        ctx.io,
    )
    service.run(limit)
    return 0


# ------------------------------------------------------------------ lookup
def lookup_action(ctx: AppContext, word: str) -> int:
    result = ctx.vocab.lookup(word)
    entry = ctx.vocab.display_entry(result)
    if entry is None:
        ctx.console.print(Text(f"未找到: {word}", style="yellow"))
        suggestions = ctx.vocab.search(word, limit=8)
        if suggestions:
            ctx.console.print(Text("相近词条:", style="dim"))
            for key, headword, meaning in suggestions:
                ctx.console.print(Text(f"  {headword}  {meaning}", style="dim"))
        ctx.console.print(Text("可用 lexi add <word> 添加为个人生词。", style="dim"))
        return 1
    lookup_screen(ctx.console, result, entry)
    return 0


def add_action(
    ctx: AppContext,
    word: str,
    *,
    meaning: str = "",
    note: str = "",
    use_ai: bool = False,
) -> int:
    result = ctx.vocab.lookup(word)
    entry = ctx.vocab.display_entry(result)
    if entry is not None:
        ctx.vocab.add_personal(word, translation=meaning, note=note)
        ctx.memory.ensure_cards(
            entry.word_key, recall_suspended=ctx.settings.learning.recall_delay_days > 0
        )
        ctx.console.print(
            Text(f"已加入个人生词与学习队列: {entry.headword}", style="green")
        )
        return 0
    if meaning:
        ctx.vocab.add_personal(word, translation=meaning, note=note, source="manual")
        ctx.memory.ensure_cards(
            normalize_word(word), recall_suspended=ctx.settings.learning.recall_delay_days > 0
        )
        ctx.console.print(Text(f"已手动添加: {word}", style="green"))
        return 0
    ai_ok, ai_reason = ctx.ai.available()
    if use_ai or (ai_ok and ctx.io.interactive):
        if not ai_ok:
            ctx.console.print(Text(f"AI 不可用: {ai_reason}", style="yellow"))
        else:
            if not use_ai and not _confirm(ctx, "本地未找到该词，使用 AI 补充释义？"):
                info = None
            else:
                info, meta = ctx.materials.enrich_word(word)
                if not info.translation.strip():
                    ctx.console.print(Text("AI 未返回有效释义。", style="yellow"))
                    info = None
                else:
                    detail = "\n".join(
                        x
                        for x in (info.definition_en, info.example, info.example_translation)
                        if x
                    )
                    ctx.vocab.add_personal(
                        word,
                        translation=info.translation,
                        phonetic=info.phonetic,
                        note=(note + "\n" + detail).strip(),
                        source="ai",
                    )
                    ctx.memory.ensure_cards(
                        normalize_word(word),
                        recall_suspended=ctx.settings.learning.recall_delay_days > 0,
                    )
                    ctx.console.print(
                        Text(f"已通过 {meta.label} 添加: {info.word} {info.translation}", style="green")
                    )
                    return 0
    if ctx.io.interactive:
        manual = ctx.io.read_line("手动输入中文释义（留空取消）: ")
        if manual and manual.strip():
            ctx.vocab.add_personal(word, translation=manual.strip(), note=note, source="manual")
            ctx.memory.ensure_cards(
                normalize_word(word), recall_suspended=ctx.settings.learning.recall_delay_days > 0
            )
            ctx.console.print(Text(f"已手动添加: {word}", style="green"))
            return 0
    ctx.console.print(Text(f"无法添加 {word}: 未找到释义。可使用 --meaning 指定。", style="yellow"))
    return 1


# ------------------------------------------------------------------ import
def import_action(
    ctx: AppContext,
    path: Path,
    *,
    code: str | None = None,
    name: str | None = None,
    kind: str = "auto",
) -> int:
    source = Path(path)
    if not source.is_file():
        ctx.console.print(Text(f"文件不存在: {source}", style="red"))
        return 1
    lower = source.name.lower()
    if kind == "auto":
        if source.suffix.lower() in {".db", ".sqlite", ".sqlite3"} or "ecdict" in lower:
            kind = "ecdict"
        elif source.suffix.lower() == ".jsonl":
            kind = "cet6-jsonl"
        elif source.suffix.lower() == ".csv":
            kind = "csv"
        else:
            ctx.console.print(Text("无法识别文件格式，请用 --kind 指定", style="red"))
            return 1
    if kind == "ecdict":
        try:
            result = import_ecdict_file(source, ctx.vocab_repo)
        except Exception as exc:
            ctx.console.print(Text(f"ECDICT 导入失败: {exc}", style="red"))
            return 1
        ctx.console.print(Text(f"ECDICT 导入完成: {result['entries']} 条", style="green"))
        return 0
    book_code = code or ("cet6" if "cet6" in lower or "六级" in source.name else _slug(source.stem))
    book_name = name or ("大学英语六级词汇（第三方整理）" if book_code == "cet6" else book_code)
    if kind in {"cet6-jsonl", "jsonl"}:
        report = import_cet6(source, ctx.vocab_repo, book_code=book_code, book_name=book_name)
        ctx.console.print(Text(report.as_text(), style="green"))
    elif kind in {"csv", "custom"}:
        result = import_custom_csv(source, ctx.vocab_repo, code=book_code, name=book_name)
        ctx.console.print(
            Text(f"自定义词库导入完成: {result['words']} 条，跳过 {result['skipped']} 条", style="green")
        )
    else:
        ctx.console.print(Text(f"未知导入类型: {kind}", style="red"))
        return 1
    ctx.console.print(Text(f"词库代码: {book_code}（lexi vocab use {book_code} 可切换）", style="dim"))
    return 0


# ------------------------------------------------------------------- drills
def drill_action(ctx: AppContext, kind: str, *, count: int = 10, words: list[str] | None = None) -> int:
    if _textual_enabled(ctx) and kind in {"spelling", "recall"} and words is None:
        from lexilab.ui.textual_drill import run_textual_drill

        result = run_textual_drill(ctx, kind, count)
        return 0 if result is not None else 1
    session = DrillSession(
        ctx.materials, ctx.repo, ctx.vocab, ctx.audio, ctx.console, ctx.io
    )
    session.run(kind, count=count, words=words)
    return 0


def audio_drill_action(ctx: AppContext, kind: str, *, count: int = 8) -> int:
    caps = ctx.capabilities
    if not audio_ready(caps):
        reason = caps["tts"].reason or caps["player"].reason
        ctx.console.print(Text(f"语音训练当前不可用：{reason}", style="yellow"))
        ctx.console.print(
            Text("可改用本地拼写训练: lexi drill spelling / lexi drill context", style="dim")
        )
        return 1
    session = AudioDrillSession(
        ctx.settings,
        ctx.repo,
        ctx.vocab_repo,
        ctx.vocab,
        ctx.audio,
        ctx.console,
        ctx.io,
    )
    try:
        session.run(kind, count=count)
    except TTSUnavailable as exc:
        ctx.console.print(Text(str(exc), style="yellow"))
        return 1
    return 0


def say_action(ctx: AppContext, word: str) -> int:
    caps = ctx.capabilities
    if not audio_ready(caps):
        reason = caps["tts"].reason or caps["player"].reason
        ctx.console.print(Text(f"发音不可用：{reason}", style="yellow"))
        return 1
    result = ctx.audio.speak(word)
    if not result.ok:
        ctx.console.print(Text(f"播放失败: {result.message}", "yellow"))
        return 1
    ctx.console.print(Text(f"已播放: {word}", style="green"))
    return 0


# ---------------------------------------------------------- AI training
def _ai_failure_fallback(ctx: AppContext, module: str) -> None:
    ctx.console.print(Text(f"{module}失败。可以改用本地训练，或稍后重试。", style="yellow"))
    if not ctx.io.interactive:
        return
    ctx.console.print(Text("[s] 拼写训练   [c] 语境填空   [Enter] 跳过", style="dim"))
    key = ctx.io.read_char()
    if key == "s":
        drill_action(ctx, "spelling", count=6)
    elif key == "c":
        drill_action(ctx, "context", count=5)


def _audio_failure_fallback(ctx: AppContext) -> None:
    if not ctx.io.interactive:
        return
    ctx.console.print(Text("[d] 本地单词听写   [j] 本地句子听写   [Enter] 跳过", style="dim"))
    key = ctx.io.read_char()
    if key == "d":
        audio_drill_action(ctx, "dictation", count=6)
    elif key == "j":
        audio_drill_action(ctx, "sentence", count=4)


def read_action(
    ctx: AppContext,
    *,
    topic: str | None = None,
    difficulty: int = 2,
    force_new: bool = False,
    words: list[str] | None = None,
) -> int:
    caps = ctx.capabilities
    if not ai_usable(caps):
        ctx.console.print(Text(ai_message(caps, "AI 阅读"), style="yellow"))
        return 1
    if _textual_enabled(ctx):
        from lexilab.ui.textual_reading import run_textual_reading

        result = run_textual_reading(
            ctx, topic=topic, difficulty=difficulty, force_new=force_new, words=words
        )
        return 0 if result is not None else 1
    session = ReadingSession(ctx.materials, ctx.repo, ctx.vocab, ctx.console, ctx.io)
    try:
        result = session.run(
            topic=topic, difficulty=difficulty, target_words=words, force_new=force_new
        )
    except (AIError, TTSUnavailable) as exc:
        ctx.console.print(Text(str(exc), style="yellow"))
        _ai_failure_fallback(ctx, "AI 阅读")
        return 1
    if isinstance(result, dict) and result.get("error"):
        _ai_failure_fallback(ctx, "AI 阅读批改")
        return 1
    return 0


def listen_action(
    ctx: AppContext,
    *,
    topic: str | None = None,
    difficulty: int = 2,
    count: int = 5,
    force_new: bool = False,
    words: list[str] | None = None,
) -> int:
    caps = ctx.capabilities
    if not ai_usable(caps):
        ctx.console.print(Text(ai_message(caps, "AI 听力"), style="yellow"))
        if audio_ready(caps):
            ctx.console.print(
                Text("可先使用本地听力训练: lexi drill listening / dictation / sentence", style="dim")
            )
        return 1
    if not audio_ready(caps):
        reason = caps["tts"].reason or caps["player"].reason
        ctx.console.print(Text(f"AI 听力需要可用音频模块：{reason}", style="yellow"))
        return 1
    if _textual_enabled(ctx):
        from lexilab.ui.textual_listening import run_textual_listening

        result = run_textual_listening(
            ctx,
            topic=topic,
            difficulty=difficulty,
            count=count,
            force_new=force_new,
            words=words,
        )
        return 0 if result is not None else 1
    session = ListeningSession(
        ctx.materials, ctx.repo, ctx.vocab, ctx.audio, ctx.console, ctx.io
    )
    try:
        session.run(
            topic=topic,
            difficulty=difficulty,
            count=count,
            target_words=words,
            force_new=force_new,
        )
    except (AIError, TTSUnavailable) as exc:
        ctx.console.print(Text(str(exc), style="yellow"))
        if audio_ready(caps):
            _audio_failure_fallback(ctx)
        else:
            _ai_failure_fallback(ctx, "AI 听力")
        return 1
    return 0


def write_action(
    ctx: AppContext,
    *,
    level: int = 1,
    topic: str | None = None,
    force_new: bool = False,
    words: list[str] | None = None,
) -> int:
    caps = ctx.capabilities
    if not ai_usable(caps):
        ctx.console.print(Text(ai_message(caps, "AI 写作"), style="yellow"))
        return 1
    if _textual_enabled(ctx):
        from lexilab.ui.textual_writing import run_textual_writing

        result = run_textual_writing(
            ctx, level=level, topic=topic, force_new=force_new, words=words
        )
        return 0 if result is not None else 1
    session = WritingSession(ctx.materials, ctx.repo, ctx.console, ctx.io)
    try:
        result = session.run(level=level, topic=topic, target_words=words, force_new=force_new)
    except AIError as exc:
        ctx.console.print(Text(str(exc), style="yellow"))
        _ai_failure_fallback(ctx, "AI 写作")
        return 1
    if isinstance(result, dict) and result.get("error"):
        _ai_failure_fallback(ctx, "AI 写作批改")
        return 1
    return 0


# ------------------------------------------------------------------ reports
def mistakes_action(
    ctx: AppContext, *, limit: int = 30, drill: bool = False, ai_drill: bool = False
) -> int:
    errors = ctx.repo.list_open_errors(limit)
    mistakes_screen(ctx.console, errors)
    if ai_drill:
        return ai_reinforcement_action(ctx, limit=min(5, max(1, len(errors))))
    if drill and errors:
        weak = []
        for item in errors:
            if item["word_key"] not in weak:
                weak.append(item["word_key"])
        ctx.console.print(Text("开始针对薄弱词的主动提取训练…", style="cyan"))
        drill_action(ctx, "recall", count=min(10, len(weak)), words=weak)
    elif errors:
        ctx.console.print(
            Text(
                "后续训练建议: lexi drill recall --count 10 / lexi mistakes --ai-drill / lexi write --level 1",
                style="dim",
            )
        )
    return 0


def ai_reinforcement_action(ctx: AppContext, *, limit: int = 5) -> int:
    caps = ctx.capabilities
    if not ai_usable(caps):
        ctx.console.print(Text(ai_message(caps, "AI 错误强化"), style="yellow"))
        return 1
    try:
        exercises = ctx.materials.get_reinforcement(limit)
    except AIError as exc:
        ctx.console.print(Text(str(exc), style="yellow"))
        _ai_failure_fallback(ctx, "AI 错误强化")
        return 1
    for index, item in enumerate(exercises.exercises, 1):
        ctx.console.print()
        ctx.console.print(Text(f"REINFORCE {index}/{len(exercises.exercises)}  {item.word}", style="bold"))
        ctx.console.print(Text(item.exercise))
        if item.answer_hint:
            ctx.console.print(Text("提示: " + item.answer_hint, style="dim"))
        answer = ctx.io.read_line("Your answer（留空跳过）: ")
        if answer is None:
            break
        if not answer.strip():
            continue
        check = ctx.io.read_line("你的答案是否可接受？[y/N]: ")
        accepted = bool(check and check.strip().lower().startswith("y"))
        ctx.repo.add_training_log(
            item.word,
            "production",
            correct=accepted,
            detail={
                "ai_reinforcement": True,
                "error_type": item.error_type,
                "answer": answer.strip(),
            },
        )
        if accepted:
            ctx.repo.resolve_errors(item.word, "production")
        ctx.console.print(Text("已记录强化练习。", style="green"))
    return 0


def stats_action(ctx: AppContext, *, json_output: bool = False) -> int:
    summary = ctx.analytics.summary()
    if json_output:
        ctx.console.print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    else:
        stats_screen(ctx.console, summary)
    return 0


# ------------------------------------------------------------------ backup
def backup_action(ctx: AppContext, *, dest: Path | None = None) -> int:
    try:
        target = backup_databases(ctx.settings, dest)
    except Exception as exc:
        ctx.console.print(Text(f"备份失败: {exc}", style="red"))
        return 1
    ctx.console.print(Text(f"备份完成: {target}", style="green"))
    return 0


def restore_action(ctx: AppContext, path: Path, *, yes: bool = False) -> int:
    ok, message, backup = verify_backup(path)
    if not ok:
        ctx.console.print(Text(f"备份校验失败: {message}", style="red"))
        return 1
    ctx.console.print(Text(f"备份校验通过: {backup}", style="green"))
    if not yes:
        if not _confirm(ctx, "恢复会替换当前数据库（恢复前会自动快照）。继续？"):
            ctx.console.print(Text("已取消。", style="yellow"))
            return 1
    success, message = restore_backup(backup, ctx.settings, confirmation=True)
    ctx.console.print(Text(message, style="green" if success else "red"))
    return 0 if success else 1


# ------------------------------------------------------------------ config
def _config_target(ctx: AppContext, path: Path | None = None) -> Path:
    if path:
        return path.expanduser()
    if ctx.settings.config_path:
        return ctx.settings.config_path
    return project_root() / "configs" / "settings.toml"


def _reload_optional_services(ctx: AppContext) -> None:
    ctx.ai = AIService(ctx.settings, ctx.repo)
    ctx.materials.ai = ctx.ai
    ctx._audio = None  # type: ignore[attr-defined]
    ctx._capabilities = None  # type: ignore[attr-defined]
    ctx._ui = None  # type: ignore[attr-defined]


def config_action(
    ctx: AppContext,
    *,
    init: bool = False,
    show: bool = True,
    path: Path | None = None,
) -> int:
    if init:
        target = _config_target(ctx, path)
        try:
            written = write_default_config(target)
            ctx.console.print(Text(f"已写入默认配置: {written}", style="green"))
        except FileExistsError as exc:
            ctx.console.print(Text(str(exc), style="yellow"))
    if show:
        table = Table(title="CONFIG", show_header=False)
        table.add_column("key")
        table.add_column("value")
        for key, value in config_summary(ctx.settings).items():
            table.add_row(key, str(value))
        ctx.console.print(table)
        if ctx.settings.config_path:
            ctx.console.print(Text(f"配置文件: {ctx.settings.config_path}", style="dim"))
        else:
            ctx.console.print(Text("正在使用内置默认配置。运行 lexi config --init 创建配置文件。", style="dim"))
        ctx.console.print(
            Text("可选模块: lexi config ai / lexi config audio / lexi doctor", style="dim")
        )
    return 0


def config_ai_action(
    ctx: AppContext,
    *,
    enable: bool | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    path: Path | None = None,
) -> int:
    cfg = ctx.settings.ai
    if enable is None and ctx.io.interactive:
        current = "已启用" if cfg.enabled else "已关闭"
        answer = ctx.io.read_line(f"启用 AI 模块？当前{current} [y/N]: ")
        if answer is not None and answer.strip():
            enable = answer.strip().lower().startswith("y")
    if enable is not None:
        cfg.enabled = enable
    if provider is not None:
        cfg.provider = provider
    if base_url is not None:
        cfg.base_url = base_url
    if api_key_env is not None:
        cfg.api_key_env = api_key_env
    if ctx.io.interactive and cfg.enabled:
        if model is None:
            answer = ctx.io.read_line(
                f"模型名（当前 {cfg.model or '空'}；直接回车保留，需查阅 DeepSeek 官方文档）: "
            )
            if answer and answer.strip():
                model = answer.strip()
    if model is not None:
        cfg.model = model.strip()
    target = _config_target(ctx, path)
    save_settings(ctx.settings, target)
    _reload_optional_services(ctx)
    cap = ctx.capabilities["ai"]
    table = Table(title="AI CONFIG", show_header=False)
    table.add_column("key")
    table.add_column("value")
    table.add_row("enabled", str(cfg.enabled))
    table.add_row("provider", cfg.provider)
    table.add_row("base_url", cfg.base_url)
    table.add_row("model", cfg.model or "(未配置)")
    table.add_row("api_key_env", cfg.api_key_env)
    table.add_row("状态", cap.state.value)
    table.add_row("说明", cap.reason)
    ctx.console.print(table)
    ctx.console.print(Text(f"已保存: {target}", style="green"))
    if cfg.enabled:
        if cfg.provider.lower() == "deepseek":
            ctx.console.print(
                Text(
                    f"请在环境变量中设置密钥（不会写入配置文件）: export {cfg.api_key_env}=<your-key>",
                    style="dim",
                )
            )
        if not cfg.model:
            ctx.console.print(
                Text(
                    "model 仍为空，请从 DeepSeek 官方文档选择当前模型名后再次运行 lexi config ai。",
                    style="yellow",
                )
            )
    return 0


def config_audio_action(
    ctx: AppContext,
    *,
    enable: bool | None = None,
    provider: str | None = None,
    voice: str | None = None,
    rate: float | None = None,
    player: str | None = None,
    path: Path | None = None,
) -> int:
    cfg = ctx.settings.audio
    if enable is None and ctx.io.interactive:
        current = "已启用" if cfg.enabled else "已关闭"
        answer = ctx.io.read_line(f"启用语音模块？当前{current} [y/N]: ")
        if answer is not None and answer.strip():
            enable = answer.strip().lower().startswith("y")
    if enable is not None:
        cfg.enabled = enable
    if provider:
        cfg.provider = provider
    if voice:
        cfg.voice = voice
    if rate is not None:
        cfg.rate = max(0.5, min(2.0, float(rate)))
    if player:
        cfg.player = player
    target = _config_target(ctx, path)
    save_settings(ctx.settings, target)
    _reload_optional_services(ctx)
    status = ctx.audio.status()
    table = Table(title="AUDIO CONFIG", show_header=False)
    table.add_column("key")
    table.add_column("value")
    table.add_row("enabled", str(cfg.enabled))
    table.add_row("provider", cfg.provider)
    table.add_row("detected", status["provider"])
    table.add_row("tts", f"{status['provider_available']} {status['provider_reason']}")
    table.add_row("player", f"{status['player']} {status['player_reason']}")
    table.add_row("voice", cfg.voice)
    table.add_row("rate", str(cfg.rate))
    ctx.console.print(table)
    ctx.console.print(Text(f"已保存: {target}", style="green"))
    if not ctx.capabilities["tts"].ready:
        ctx.console.print(
            Text("未检测到可用本地语音；依赖语音的训练入口会自动隐藏。", style="dim")
        )
    return 0


# ---------------------------------------------------------------- materials
def materials_action(
    ctx: AppContext,
    *,
    kind: str | None = None,
    limit: int = 10,
    show: str = "",
    replay: bool = False,
) -> int:
    if show:
        material = ctx.repo.get_material(show)
        if material is None:
            ctx.console.print(Text(f"材料不存在: {show}", style="yellow"))
            return 1
        meta = material.get("meta") or {}
        header = (
            f"{material['kind']} | {material['topic']} | "
            f"{material.get('provider') or 'unknown'}/{material.get('model') or 'unknown'}"
            + ("（模拟）" if meta.get("mock") else "")
        )
        ctx.console.print(Text(header, style="bold"))
        ctx.console.print(Text("目标词: " + ", ".join(material["target_words"]), style="dim"))
        ctx.console.print(Text("生成时间: " + local_time(material["created_at"]), style="dim"))
        if material["kind"] == "reading":
            ctx.console.print(Text(material["body"]))
            for index, question in enumerate(material["questions"], 1):
                ctx.console.print()
                ctx.console.print(Text(f"Q{index}. {question.get('question', '')}", style="bold"))
                if question.get("answer"):
                    ctx.console.print(Text("参考答案: " + str(question["answer"]), style="dim"))
        elif material["kind"] == "listening":
            for index, question in enumerate(material["questions"], 1):
                ctx.console.print(Text(f"{index}. {question.get('answer', '')}"))
                if question.get("translation"):
                    ctx.console.print(Text(question["translation"], style="dim"))
            if replay:
                if not audio_ready(ctx.capabilities):
                    ctx.console.print(Text("音频模块不可用，无法重播。", style="yellow"))
                else:
                    for question in material["questions"]:
                        ctx.audio.speak(str(question.get("answer", "")))
        else:
            ctx.console.print(Text(material["body"], style="bold"))
            if meta.get("guidance"):
                ctx.console.print(Text(meta["guidance"], style="dim"))
            ctx.console.print(
                Text("（离线查看模式：此材料的历史批改记录保存在 material_attempts）", style="dim")
            )
        return 0

    rows = ctx.repo.recent_materials(kind, limit=max(1, limit))
    if not rows:
        ctx.console.print(Text("暂无本地缓存材料。", style="dim"))
        return 0
    table = Table(title="本地材料")
    table.add_column("ID")
    table.add_column("类型")
    table.add_column("主题")
    table.add_column("目标词")
    table.add_column("来源")
    table.add_column("时间")
    for item in rows:
        meta = item.get("meta") or {}
        table.add_row(
            item["id"],
            item["kind"],
            item["topic"],
            ", ".join(item["target_words"][:5]),
            f"{item.get('provider')}/{item.get('model')}" + (" (mock)" if meta.get("mock") else ""),
            local_time(item["created_at"]),
        )
    ctx.console.print(table)
    ctx.console.print(Text("离线查看: lexi materials --show <ID>   （听力可用 --replay）", style="dim"))
    return 0


# ------------------------------------------------------------------- vocab
def vocab_list_action(ctx: AppContext) -> int:
    books = ctx.vocab_repo.list_books()
    books_screen(ctx.console, books, ctx.active_book())
    ctx.console.print(Text("使用 lexi vocab use <code> 切换当前词库。", style="dim"))
    return 0


def vocab_use_action(ctx: AppContext, code: str) -> int:
    if ctx.vocab_repo.get_book(code) is None:
        ctx.console.print(Text(f"词库不存在: {code}", style="red"))
        return 1
    ctx.repo.set_setting("active_book", code)
    ctx.console.print(Text(f"当前词库: {code}", style="green"))
    return 0


def vocab_show_action(ctx: AppContext, word: str) -> int:
    lookup_action(ctx, word)
    cards = ctx.repo.word_cards(word)
    if cards:
        table = Table(title="记忆卡片")
        table.add_column("方向")
        table.add_column("状态")
        table.add_column("到期（本地时间）")
        table.add_column("暂停")
        for card in cards:
            table.add_row(
                card["direction"],
                str(card["state"]),
                local_time(card["due"]),
                "是" if card["suspended"] else "否",
            )
        ctx.console.print(table)
    else:
        ctx.console.print(Text("尚无记忆卡片。", style="dim"))
    screening = ctx.repo.screening_for(word)
    if screening:
        ctx.console.print(
            Text(
                f"筛选状态: {screening['status']}  下次抽查: {local_time(screening['verify_at'])}",
                style="dim",
            )
        )
    return 0


def vocab_pause_action(ctx: AppContext, word: str, *, direction: str | None = None) -> int:
    count = ctx.repo.suspend_card(word, direction)
    ctx.console.print(Text(f"已暂停 {count} 张卡片: {word}", style="green" if count else "yellow"))
    return 0 if count else 1


def vocab_resume_action(ctx: AppContext, word: str, *, direction: str | None = None) -> int:
    count = ctx.repo.resume_card(word, direction)
    ctx.console.print(Text(f"已恢复 {count} 张卡片: {word}", style="green" if count else "yellow"))
    return 0 if count else 1


def vocab_remove_action(ctx: AppContext, word: str, *, cards: bool = False, yes: bool = False) -> int:
    removed = ctx.vocab.remove_personal(word)
    ctx.console.print(Text(f"个人生词记录删除: {removed}", style="green" if removed else "dim"))
    if cards:
        if not yes and not _confirm(ctx, "同时删除该词的全部卡片和复习日志？此操作不可撤销"):
            ctx.console.print(Text("已保留卡片。", style="yellow"))
            return 0
        count = ctx.repo.delete_cards(word)
        ctx.console.print(Text(f"已删除卡片: {count}", style="yellow"))
    elif removed:
        ctx.repo.suspend_card(word)
        ctx.console.print(Text("卡片已暂停；如需彻底删除请加 --cards --yes。", style="dim"))
    return 0


def vocab_history_action(ctx: AppContext, word: str) -> int:
    reviews = ctx.repo.review_history(word, limit=15)
    trainings = ctx.repo.training_history(word, limit=15)
    if reviews:
        table = Table(title=f"复习历史: {word}")
        table.add_column("时间（本地）")
        table.add_column("方向")
        table.add_column("评分")
        table.add_column("间隔(天)")
        table.add_column("耗时(ms)")
        for row in reviews:
            table.add_row(
                local_time(row["review_datetime"]),
                row["direction"],
                str(row["rating"]),
                f"{row['elapsed_days']:.1f}" if row["elapsed_days"] is not None else "-",
                str(row["review_duration_ms"] or "-"),
            )
        ctx.console.print(table)
    else:
        ctx.console.print(Text("无复习历史。", style="dim"))
    if trainings:
        table = Table(title=f"训练历史: {word}")
        table.add_column("时间（本地）")
        table.add_column("能力")
        table.add_column("正确")
        table.add_column("提示")
        table.add_column("错误类型")
        for row in trainings:
            table.add_row(
                local_time(row["created_at"]),
                row["skill"],
                "-" if row["correct"] is None else ("是" if row["correct"] else "否"),
                "是" if row["hinted"] else "否",
                row["error_type"] or "",
            )
        ctx.console.print(table)
    return 0


def vocab_words_action(ctx: AppContext, *, limit: int = 30, search: str = "") -> int:
    if search:
        rows = ctx.vocab_repo.search(search, limit=limit)
        table = Table(title=f"词库搜索: {search}")
        table.add_column("单词")
        table.add_column("释义")
        for row in rows:
            table.add_row(row["headword"], row["translation"].split("\n")[0])
        ctx.console.print(table)
        return 0
    words = ctx.vocab_repo.new_candidates(ctx.active_book(), limit, set())
    table = Table(title=f"词库预览: {ctx.active_book()}")
    table.add_column("单词")
    table.add_column("词性")
    table.add_column("释义")
    for key in words:
        entry = ctx.vocab_repo.get_entry(key)
        if entry:
            table.add_row(entry.headword, entry.primary_pos, entry.short_meaning)
    ctx.console.print(table)
    return 0


# ---------------------------------------------------------------- main menu
def _textual_options(ctx: AppContext) -> list[tuple[str, str]]:
    caps = ctx.capabilities
    options: list[tuple[str, str]] = [
        ("study", "开始今日学习"),
        ("review", "单词复习"),
        ("learn", "新词学习"),
    ]
    if audio_ready(caps):
        options.append(("audio", "听音辨义 / 听写"))
    if ai_usable(caps):
        options.extend([("read", "AI 阅读"), ("write", "AI 写作")])
    options.extend(
        [
            ("stats", "学习统计"),
            ("vocab", "词库管理"),
            ("screen", "快速筛选"),
        ]
    )
    if caps["cached_materials"].ready:
        options.append(("materials", "本地材料"))
    options.extend([("config", "配置"), ("q", "退出")])
    return options


def _dispatch_menu_key(ctx: AppContext, key: str) -> bool:
    if key in {"study", "enter"}:
        study_action(ctx)
    elif key in {"review", "1"}:
        review_action(ctx)
    elif key in {"learn", "2"}:
        learn_action(ctx)
    elif key in {"audio", "3"}:
        audio_drill_action(ctx, "listening")
    elif key in {"read", "4"}:
        read_action(ctx)
    elif key in {"write", "5"}:
        write_action(ctx)
    elif key in {"stats", "6"}:
        stats_action(ctx)
    elif key in {"vocab", "7"}:
        vocab_list_action(ctx)
    elif key in {"screen", "8"}:
        screen_action(ctx)
    elif key in {"materials", "9"}:
        materials_action(ctx)
    elif key in {"config", "c"}:
        config_action(ctx)
    elif key in {"q", "eof", "esc"}:
        return False
    return True


def main_menu_action(ctx: AppContext) -> int:
    if not ctx.has_vocabulary():
        ctx.console.print(Text("尚未初始化词库。请先运行: lexi init", style="yellow"))
        return 1
    if not ctx.io.interactive:
        summary = ctx.analytics.summary()
        render_main_menu(ctx.console, summary, ctx.capabilities)
        ctx.console.print(Text("非交互环境：请使用 lexi --help 查看命令。", style="dim"))
        return 0
    if _textual_enabled(ctx):
        from lexilab.ui.textual_app import run_textual_menu

        while True:
            key = run_textual_menu(ctx, _textual_options(ctx))
            if not key:
                break
            try:
                if not _dispatch_menu_key(ctx, key):
                    break
            except (AIError, TTSUnavailable) as exc:
                ctx.console.print(Text(str(exc), style="yellow"))
            except KeyboardInterrupt:
                ctx.console.print(Text("已退出。", style="dim"))
                break
        return 0
    while True:
        summary = ctx.analytics.summary()
        ctx.console.print()
        render_main_menu(ctx.console, summary, ctx.capabilities)
        ctx.console.print()
        ctx.console.print(Text("选择操作: ", style="dim"), end="")
        key = ctx.io.read_char()
        ctx.console.print()
        try:
            if not _dispatch_menu_key(ctx, key):
                break
        except (AIError, TTSUnavailable) as exc:
            ctx.console.print(Text(str(exc), style="yellow"))
        except KeyboardInterrupt:
            ctx.console.print(Text("已退出。", style="dim"))
            break
    return 0
