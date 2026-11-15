from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from lexilab import __version__
from lexilab.cli import actions
from lexilab.config.settings import load_settings
from lexilab.context import AppContext

app = typer.Typer(
    name="lexi",
    help="LexiLab: 本地化、以词汇为核心的英语学习工具。",
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
    rich_markup_mode="rich",
)
drill_app = typer.Typer(help="词汇专项训练：拼写、主动提取、语境填空、本地听写。", no_args_is_help=True)
relations_app = typer.Typer(help="词汇关系：WordNet/形近词构建、统计与查询。", no_args_is_help=True)
vocab_app = typer.Typer(help="词库管理：查看、切换、暂停、历史。", no_args_is_help=True)
config_app = typer.Typer(
    help="查看配置，或配置可选的 AI / 语音模块。",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(drill_app, name="drill")
app.add_typer(relations_app, name="relations")
app.add_typer(vocab_app, name="vocab")
app.add_typer(config_app, name="config")


def _context(tc: typer.Context) -> AppContext:
    obj = tc.obj
    if not isinstance(obj, AppContext):
        raise typer.Exit(2)
    return obj


@app.callback()
def main(
    tc: typer.Context,
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="配置文件路径"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", help="覆盖数据目录"),
    no_color: bool = typer.Option(False, "--no-color", is_flag=True, help="禁用颜色"),
    no_tui: bool = typer.Option(False, "--no-tui", is_flag=True, help="使用传统行式界面"),
) -> None:
    """启动 LexiLab。无子命令时显示主界面。"""
    try:
        settings = load_settings(config)
    except Exception as exc:
        typer.secho(f"配置读取失败: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    if data_dir is not None:
        settings.data_dir = data_dir.expanduser().resolve()
    if no_color:
        settings.ui.color = False
    if no_tui:
        settings.ui.textual = False
    try:
        tc.obj = AppContext(settings)
    except Exception as exc:
        typer.secho(f"初始化失败: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    if tc.invoked_subcommand is None:
        try:
            code = actions.main_menu_action(tc.obj)
        except KeyboardInterrupt:
            code = 0
        raise typer.Exit(code)


# --------------------------------------------------------------------- setup
@app.command()
def init(
    tc: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="不询问确认"),
    skip_vocab: bool = typer.Option(False, "--skip-vocab", help="跳过六级词库"),
    skip_ecdict: bool = typer.Option(False, "--skip-ecdict", help="跳过 ECDICT"),
    vocab_file: Optional[Path] = typer.Option(None, "--vocab-file", help="本地六级 JSONL"),
    ecdict_file: Optional[Path] = typer.Option(None, "--ecdict-file", help="本地 ECDICT CSV/SQLite"),
    force_vocab: bool = typer.Option(False, "--force-vocab", help="即使已导入也重新导入词库"),
    with_relations: bool = typer.Option(
        False, "--with-relations", help="导入完成后构建 WordNet/形近词关系库"
    ),
) -> None:
    """初始化数据目录，导入真实六级词库与 ECDICT。不会覆盖 learning.db。"""
    raise typer.Exit(
        actions.init_action(
            _context(tc),
            yes=yes,
            skip_vocab=skip_vocab,
            skip_ecdict=skip_ecdict,
            vocab_file=vocab_file,
            ecdict_file=ecdict_file,
            force_vocab=force_vocab,
            with_relations=with_relations,
        )
    )


@app.command()
def doctor(tc: typer.Context) -> None:
    """检查环境、数据库、FSRS、AI 与语音依赖。"""
    raise typer.Exit(actions.doctor_action(_context(tc)))


# -------------------------------------------------------------------- study
@app.command()
def study(
    tc: typer.Context,
    minutes: Optional[int] = typer.Option(None, "--minutes", "-m", help="本次时间预算（分钟）"),
    new: Optional[int] = typer.Option(None, "--new", "-n", help="覆盖今日新词数量"),
    order: Optional[str] = typer.Option(
        None, "--order", help="新词排序: smart|frequency|related|alphabetical"
    ),
    no_training: bool = typer.Option(False, "--no-training", help="结束后不提示AI 训练"),
) -> None:
    """开始今日学习：自动按设置组织新词、到期复习、延迟回忆与错词强化。"""
    raise typer.Exit(
        actions.study_action(
            _context(tc),
            minutes=minutes,
            new_count=new,
            offer_training=not no_training,
            order=order,
        )
    )


@app.command()
def review(
    tc: typer.Context,
    minutes: Optional[int] = typer.Option(None, "--minutes", "-m", help="时间预算（分钟）"),
) -> None:
    """只复习到期卡片。"""
    raise typer.Exit(actions.review_action(_context(tc), minutes=minutes))


@app.command()
def learn(
    tc: typer.Context,
    count: Optional[int] = typer.Option(None, "--count", "-c", help="新词数量"),
    minutes: Optional[int] = typer.Option(None, "--minutes", "-m", help="时间预算（分钟）"),
    order: Optional[str] = typer.Option(
        None, "--order", help="新词排序: smart|frequency|related|alphabetical"
    ),
) -> None:
    """只学习新词；默认 smart 排序，不再按字母顺序。"""
    raise typer.Exit(
        actions.learn_action(_context(tc), count=count, minutes=minutes, order=order)
    )


# ------------------------------------------------------------------- lookup
@app.command()
def lookup(tc: typer.Context, word: str = typer.Argument(..., help="要查询的单词")) -> None:
    """查询本地六级词库、ECDICT 与个人生词。"""
    raise typer.Exit(actions.lookup_action(_context(tc), word))


@app.command()
def related(
    tc: typer.Context,
    word: str = typer.Argument(..., help="要查看关系的单词"),
    relation_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="synonym|antonym|derivation|spelling|confusion"
    ),
    limit: int = typer.Option(30, "--limit", "-l", min=1, max=200),
) -> None:
    """查看同义、反义、派生、上下位、形近与个人易混淆词。"""
    kind = None if relation_type is None else relation_type.strip().lower()
    if kind == "spelling":
        kind = "orthographic_similar"
    elif kind == "confusion":
        kind = "user_confusion"
    raise typer.Exit(
        actions.related_action(_context(tc), word, relation_type=kind, limit=limit)
    )


@app.command()
def add(
    tc: typer.Context,
    word: str = typer.Argument(..., help="要添加的单词"),
    meaning: str = typer.Option("", "--meaning", "-m", help="手动指定中文释义"),
    note: str = typer.Option("", "--note", help="备注"),
    ai: bool = typer.Option(False, "--ai", help="本地未找到时允许 AI 补充释义"),
) -> None:
    """添加个人生词并加入学习队列。"""
    raise typer.Exit(actions.add_action(_context(tc), word, meaning=meaning, note=note, use_ai=ai))


@app.command("import")
def import_cmd(
    tc: typer.Context,
    path: Path = typer.Argument(..., help="词库文件（JSONL/CSV/SQLite）"),
    kind: str = typer.Option("auto", "--kind", help="auto|cet6-jsonl|csv|ecdict"),
    code: Optional[str] = typer.Option(None, "--code", help="词库代码"),
    name: Optional[str] = typer.Option(None, "--name", help="词库名称"),
) -> None:
    """导入自定义词库或 ECDICT。"""
    raise typer.Exit(actions.import_action(_context(tc), path, kind=kind, code=code, name=name))


# -------------------------------------------------------------------- drill
@drill_app.command("spelling")
def drill_spelling(
    tc: typer.Context,
    count: int = typer.Option(10, "--count", "-c", min=1, max=100),
) -> None:
    """根据中文与发音拼写单词。"""
    raise typer.Exit(actions.drill_action(_context(tc), "spelling", count=count))


@drill_app.command("recall")
def drill_recall(
    tc: typer.Context,
    count: int = typer.Option(10, "--count", "-c", min=1, max=100),
) -> None:
    """中译英主动提取训练（不改变 FSRS 状态）。"""
    raise typer.Exit(actions.drill_action(_context(tc), "recall", count=count))


@drill_app.command("synonyms")
def drill_synonyms(
    tc: typer.Context,
    count: int = typer.Option(10, "--count", "-c", min=1, max=50),
) -> None:
    """近义词辨析：结合 ECDICT 释义进行主动提取。"""
    raise typer.Exit(actions.relation_drill_action(_context(tc), "synonym", count=count))


@drill_app.command("similar-spelling")
def drill_similar_spelling(
    tc: typer.Context,
    count: int = typer.Option(10, "--count", "-c", min=1, max=50),
) -> None:
    """形近词辨析：用 Damerau-Levenshtein 发现的形近词对训练。"""
    raise typer.Exit(actions.relation_drill_action(_context(tc), "similar-spelling", count=count))


@drill_app.command("confusion")
def drill_confusion(
    tc: typer.Context,
    count: int = typer.Option(10, "--count", "-c", min=1, max=50),
) -> None:
    """个人易混淆词强化：优先训练真实错误输入产生的词对。"""
    raise typer.Exit(actions.relation_drill_action(_context(tc), "confusion", count=count))


@drill_app.command("context")
def drill_context(
    tc: typer.Context,
    count: int = typer.Option(8, "--count", "-c", min=1, max=50),
) -> None:
    """语境填空训练。"""
    raise typer.Exit(actions.drill_action(_context(tc), "context", count=count))


@drill_app.command("listening")
def drill_listening(
    tc: typer.Context,
    count: int = typer.Option(8, "--count", "-c", min=1, max=100),
) -> None:
    """听音辨义（本地 TTS，无 AI）。"""
    raise typer.Exit(actions.audio_drill_action(_context(tc), "listening", count=count))


@drill_app.command("dictation")
def drill_dictation(
    tc: typer.Context,
    count: int = typer.Option(8, "--count", "-c", min=1, max=100),
) -> None:
    """单词听写（本地 TTS，无 AI）。"""
    raise typer.Exit(actions.audio_drill_action(_context(tc), "dictation", count=count))


@drill_app.command("sentence")
def drill_sentence(
    tc: typer.Context,
    count: int = typer.Option(5, "--count", "-c", min=1, max=50),
) -> None:
    """基于本地例句的句子听写（无 AI）。"""
    raise typer.Exit(actions.audio_drill_action(_context(tc), "sentence", count=count))


@app.command()
def say(tc: typer.Context, word: str = typer.Argument(..., help="要朗读的单词或短语")) -> None:
    """播放本地合成发音（无 AI）。"""
    raise typer.Exit(actions.say_action(_context(tc), word))


# ------------------------------------------------------------------ reading
@app.command()
def read(
    tc: typer.Context,
    topic: Optional[str] = typer.Option(None, "--topic", help="阅读主题"),
    difficulty: int = typer.Option(2, "--difficulty", "-d", min=1, max=3),
    new: bool = typer.Option(False, "--new", help="忽略缓存，重新生成材料"),
    words: Optional[str] = typer.Option(None, "--words", help="逗号分隔的目标词"),
) -> None:
    """AI 阅读训练：生成文章、作答并批改。"""
    target = [w.strip() for w in words.split(",") if w.strip()] if words else None
    raise typer.Exit(
        actions.read_action(_context(tc), topic=topic, difficulty=difficulty, force_new=new, words=target)
    )


@app.command()
def listen(
    tc: typer.Context,
    topic: Optional[str] = typer.Option(None, "--topic"),
    difficulty: int = typer.Option(2, "--difficulty", "-d", min=1, max=3),
    count: int = typer.Option(5, "--count", "-c", min=1, max=20),
    new: bool = typer.Option(False, "--new", help="忽略缓存，重新生成材料"),
    words: Optional[str] = typer.Option(None, "--words", help="逗号分隔的目标词"),
) -> None:
    """听力训练：播放合成语音并听写。"""
    target = [w.strip() for w in words.split(",") if w.strip()] if words else None
    raise typer.Exit(
        actions.listen_action(
            _context(tc), topic=topic, difficulty=difficulty, count=count, force_new=new, words=target
        )
    )


@app.command()
def write(
    tc: typer.Context,
    level: int = typer.Option(1, "--level", "-l", min=1, max=3),
    topic: Optional[str] = typer.Option(None, "--topic"),
    new: bool = typer.Option(False, "--new", help="忽略缓存，重新生成题目"),
    words: Optional[str] = typer.Option(None, "--words", help="逗号分隔的目标词"),
) -> None:
    """写作训练：造句、句子翻译或段落写作，并给出结构化批改。"""
    target = [w.strip() for w in words.split(",") if w.strip()] if words else None
    raise typer.Exit(
        actions.write_action(_context(tc), level=level, topic=topic, force_new=new, words=target)
    )


# ------------------------------------------------------------------ reports
@app.command()
def mistakes(
    tc: typer.Context,
    limit: int = typer.Option(30, "--limit", min=1, max=200),
    drill: bool = typer.Option(False, "--drill", help="立即针对薄弱词训练"),
    ai_drill: bool = typer.Option(False, "--ai-drill", help="使用 AI 生成针对性强化练习"),
) -> None:
    """查看未解决的错误。"""
    raise typer.Exit(
        actions.mistakes_action(_context(tc), limit=limit, drill=drill, ai_drill=ai_drill)
    )


@app.command()
def stats(
    tc: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """真实学习统计。"""
    raise typer.Exit(actions.stats_action(_context(tc), json_output=json_output))


# ------------------------------------------------------------------- data
@app.command()
def backup(
    tc: typer.Context,
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="备份目录"),
) -> None:
    """使用 SQLite 安全备份机制备份两个数据库。"""
    raise typer.Exit(actions.backup_action(_context(tc), dest=out))


@app.command()
def restore(
    tc: typer.Context,
    path: Path = typer.Argument(..., help="备份目录或 .db 文件"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """校验并恢复备份（恢复前自动快照当前数据库）。"""
    raise typer.Exit(actions.restore_action(_context(tc), path, yes=yes))


@config_app.callback()
def config_main(
    tc: typer.Context,
    init: bool = typer.Option(False, "--init", help="写入默认配置"),
    show: bool = typer.Option(True, "--show/--no-show", help="显示当前配置"),
    path: Optional[Path] = typer.Option(None, "--path", help="配置写入路径"),
) -> None:
    """查看当前配置；子命令 ai/audio 用于配置可选模块。"""
    if tc.invoked_subcommand is None:
        raise typer.Exit(actions.config_action(_context(tc), init=init, show=show, path=path))


@config_app.command("show")
def config_show(tc: typer.Context) -> None:
    """显示当前配置与检测到的能力。"""
    raise typer.Exit(actions.config_action(_context(tc), show=True))


@config_app.command("ai")
def config_ai(
    tc: typer.Context,
    enable: bool = typer.Option(False, "--enable", help="启用 AI"),
    disable: bool = typer.Option(False, "--disable", help="禁用 AI"),
    provider: Optional[str] = typer.Option(None, "--provider", help="deepseek|mock|none"),
    model: Optional[str] = typer.Option(None, "--model", help="模型名（从官方文档选择）"),
    base_url: Optional[str] = typer.Option(None, "--base-url"),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="密钥环境变量名"),
    path: Optional[Path] = typer.Option(None, "--path", help="配置文件写入路径"),
) -> None:
    """配置可选 AI 模块。密钥只从环境变量读取，不写入配置文件。"""
    flag = True if enable else (False if disable else None)
    raise typer.Exit(
        actions.config_ai_action(
            _context(tc),
            enable=flag,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            path=path,
        )
    )


@config_app.command("audio")
def config_audio(
    tc: typer.Context,
    enable: bool = typer.Option(False, "--enable"),
    disable: bool = typer.Option(False, "--disable"),
    provider: Optional[str] = typer.Option(None, "--provider", help="auto|flite|espeak|pyttsx3|none"),
    voice: Optional[str] = typer.Option(None, "--voice"),
    rate: Optional[float] = typer.Option(None, "--rate", min=0.5, max=2.0),
    player: Optional[str] = typer.Option(None, "--player", help="auto|ffplay|aplay|paplay|afplay"),
    path: Optional[Path] = typer.Option(None, "--path"),
) -> None:
    """配置可选语音模块，并显示本地检测结果。"""
    flag = True if enable else (False if disable else None)
    raise typer.Exit(
        actions.config_audio_action(
            _context(tc),
            enable=flag,
            provider=provider,
            voice=voice,
            rate=rate,
            player=player,
            path=path,
        )
    )


@app.command()
def materials(
    tc: typer.Context,
    kind: Optional[str] = typer.Option(None, "--kind", help="reading|listening|writing"),
    limit: int = typer.Option(10, "--limit", min=1, max=100),
    show: str = typer.Option("", "--show", help="材料 ID"),
    replay: bool = typer.Option(False, "--replay", help="重播缓存的听力音频（无 AI）"),
) -> None:
    """查看本地缓存的阅读/听力/写作材料（可完全离线使用）。"""
    raise typer.Exit(
        actions.materials_action(
            _context(tc), kind=kind, limit=limit, show=show, replay=replay
        )
    )


# ------------------------------------------------------------------- vocab
@vocab_app.command("list")
def vocab_list(tc: typer.Context) -> None:
    """列出词库。"""
    raise typer.Exit(actions.vocab_list_action(_context(tc)))


@vocab_app.command("use")
def vocab_use(tc: typer.Context, code: str = typer.Argument(...)) -> None:
    """切换当前学习词库。"""
    raise typer.Exit(actions.vocab_use_action(_context(tc), code))


@vocab_app.command("show")
def vocab_show(tc: typer.Context, word: str = typer.Argument(...)) -> None:
    """查看单词详情与卡片状态。"""
    raise typer.Exit(actions.vocab_show_action(_context(tc), word))


@vocab_app.command("pause")
def vocab_pause(
    tc: typer.Context,
    word: str = typer.Argument(...),
    direction: Optional[str] = typer.Option(None, "--direction", help="recognition|recall"),
) -> None:
    """暂停指定单词的学习。"""
    raise typer.Exit(actions.vocab_pause_action(_context(tc), word, direction=direction))


@vocab_app.command("resume")
def vocab_resume(
    tc: typer.Context,
    word: str = typer.Argument(...),
    direction: Optional[str] = typer.Option(None, "--direction", help="recognition|recall"),
) -> None:
    """恢复指定单词的学习。"""
    raise typer.Exit(actions.vocab_resume_action(_context(tc), word, direction=direction))


@vocab_app.command("remove")
def vocab_remove(
    tc: typer.Context,
    word: str = typer.Argument(...),
    cards: bool = typer.Option(False, "--cards", help="同时删除卡片与复习日志"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """移除个人生词；默认只暂停卡片。"""
    raise typer.Exit(actions.vocab_remove_action(_context(tc), word, cards=cards, yes=yes))


@vocab_app.command("history")
def vocab_history(tc: typer.Context, word: str = typer.Argument(...)) -> None:
    """查看单词复习与训练历史。"""
    raise typer.Exit(actions.vocab_history_action(_context(tc), word))


@vocab_app.command("words")
def vocab_words(
    tc: typer.Context,
    limit: int = typer.Option(30, "--limit", min=1, max=200),
    search: str = typer.Option("", "--search", help="按前缀搜索"),
) -> None:
    """预览当前词库或搜索词条。"""
    raise typer.Exit(actions.vocab_words_action(_context(tc), limit=limit, search=search))


@relations_app.command("build")
def relations_build(
    tc: typer.Context,
    force: bool = typer.Option(False, "--force", help="清空后完整重建"),
    wordnet: bool = typer.Option(True, "--wordnet/--no-wordnet", help="构建 WordNet 关系"),
    spelling: bool = typer.Option(True, "--spelling/--no-spelling", help="构建形近词关系"),
    download: bool = typer.Option(False, "--download", help="先显式下载 WordNet 数据"),
) -> None:
    """构建词汇关系库。可重复执行，默认只补齐新词。"""
    raise typer.Exit(
        actions.relations_build_action(
            _context(tc),
            force=force,
            wordnet=wordnet,
            spelling=spelling,
            download=download,
        )
    )


@relations_app.command("stats")
def relations_stats(tc: typer.Context) -> None:
    """查看关系数量、来源、覆盖与个人混淆统计。"""
    raise typer.Exit(actions.relations_stats_action(_context(tc)))


@relations_app.command("download")
def relations_download(tc: typer.Context) -> None:
    """显式下载 NLTK WordNet 数据；正常启动不会自动下载。"""
    try:
        ok = _context(tc).relations.download_wordnet()
    except Exception as exc:
        typer.secho(f"WordNet 下载失败: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    if not ok:
        typer.secho("WordNet 下载未完成。", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1)
    typer.secho("WordNet 数据已就绪。", fg=typer.colors.GREEN)


@app.command()
def version() -> None:
    """显示版本。"""
    typer.echo(f"LexiLab {__version__}")


def main_entry() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main_entry()
