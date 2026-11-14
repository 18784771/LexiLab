from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from lexilab.ai.base import AIError
from lexilab.ai.materials import MaterialService
from lexilab.storage.learning_repo import LearningRepository
from lexilab.ui.io import TerminalIO


class WritingSession:
    def __init__(
        self,
        materials: MaterialService,
        repo: LearningRepository,
        console: Console,
        io: TerminalIO,
    ) -> None:
        self.materials = materials
        self.repo = repo
        self.console = console
        self.io = io

    def run(
        self,
        *,
        level: int = 1,
        topic: str | None = None,
        target_words: list[str] | None = None,
        force_new: bool = False,
    ) -> dict:
        ok, reason = self.materials.ai.available()
        if not ok:
            raise AIError(f"写作训练需要 AI：{reason}")
        result = self.materials.get_writing(
            level=level, topic=topic, target_words=target_words, force_new=force_new
        )
        material = result.material
        self.console.print()
        self.console.print(Text(f"WRITING LEVEL {level}", style="bold"))
        self.console.print(Text(material["body"], style="bold"))
        guidance = (material.get("meta") or {}).get("guidance")
        if guidance:
            self.console.print(Text(guidance, style="dim"))
        if material["target_words"]:
            self.console.print(Text("目标词: " + ", ".join(material["target_words"]), style="dim"))
        if result.cached:
            self.console.print(Text("（使用本地缓存题目）", style="dim"))
        answer = self.io.read_multiline("Your answer:")
        if answer is None or not answer.strip():
            self.console.print(Text("未提交作答。", style="yellow"))
            return {"material_id": material["id"], "submitted": False}
        if len(answer.split()) < 4:
            self.console.print(Text("提示: 作答过短，仍将提交批改。", style="yellow"))
        try:
            grade, meta = self.materials.grade_writing(material["id"], answer)
        except AIError as exc:
            self.repo.record_material_attempt(
                material["id"], 0, answer, {"error": str(exc)}, None, hinted=False
            )
            self.console.print(Text(f"批改失败，原文已保存: {exc}", style="red"))
            return {"material_id": material["id"], "submitted": True, "error": str(exc)}

        self.console.print()
        self.console.print(Text("FEEDBACK", style="bold"))
        self.console.print(
            Text(("任务完成" if grade.task_completed else "任务未完成") + f"  score={grade.score:.0%}")
        )
        real_errors = [i for i in grade.issues if i.category != "style"]
        style_notes = [i for i in grade.issues if i.category == "style"]
        if real_errors:
            self.console.print(Text("语言错误", style="bold red"))
            for issue in real_errors:
                self.console.print(
                    Text(f"[{issue.category}] ", style="red")
                    + Text(issue.excerpt or "")
                    + Text(f"  {issue.explanation}", style="dim")
                )
                if issue.correction:
                    self.console.print(Text("  修改: " + issue.correction, style="green"))
        if style_notes:
            self.console.print(Text("风格建议（不是错误）", style="bold yellow"))
            for issue in style_notes:
                self.console.print(Text(f"  {issue.explanation}", style="dim"))
        if grade.acceptable_notes:
            self.console.print(Text("可接受的表达", style="bold green"))
            for note in grade.acceptable_notes:
                self.console.print(Text("  " + note, style="dim"))
        if grade.target_words:
            table = Table(title="目标词使用", show_lines=False)
            table.add_column("单词")
            table.add_column("使用")
            table.add_column("词义")
            table.add_column("搭配")
            table.add_column("反馈")
            for item in grade.target_words:
                table.add_row(
                    item.target_word,
                    "是" if item.used else "否",
                    "正确" if item.meaning_correct else "错误",
                    "正确" if item.collocation_correct else "错误",
                    item.feedback,
                )
            self.console.print(table)
        if grade.minimal_correction:
            self.console.print(Text("最小修改: " + grade.minimal_correction, style="green"))
        if grade.improved_version and grade.improved_version.strip() != grade.minimal_correction.strip():
            self.console.print(Text("改进版本: " + grade.improved_version, style="dim"))
        if grade.overall_comment:
            self.console.print(Text(grade.overall_comment))
        if grade.follow_up_required:
            self.console.print(Text("已记录错误，后续训练会优先安排相关词汇。", style="yellow"))
        self.console.print(Text(f"批改来源: {meta.label}", style="dim"))
        self.console.print(
            Text("[o] 我认为批改有误/应判定为可接受   [Enter] 继续", style="dim")
        )
        key = self.io.read_char()
        if key == "o":
            answer = self.io.read_line("这次作答是否应判定为可接受？[y/N]: ")
            accepted = bool(answer and answer.strip().lower().startswith("y"))
            for target in material["target_words"]:
                self.repo.add_training_log(
                    target,
                    "production",
                    correct=accepted,
                    detail={
                        "manual_override": True,
                        "material_id": material["id"],
                        "raw_answer": answer[:200],
                    },
                    material_id=material["id"],
                )
                if accepted:
                    self.repo.resolve_errors(target, "production")
            self.console.print(Text("已保存人工判断。", style="green"))
        return {
            "material_id": material["id"],
            "submitted": True,
            "score": grade.score,
            "follow_up": grade.follow_up_required,
            "mock": meta.mock,
            "manual_override": key == "o",
        }
