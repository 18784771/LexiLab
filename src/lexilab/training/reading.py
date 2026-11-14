from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from lexilab.ai.base import AIError
from lexilab.ai.materials import MaterialService
from lexilab.ui.io import TerminalIO
from lexilab.ui.screens import lookup_screen
from lexilab.vocabulary.service import VocabularyService


class ReadingSession:
    def __init__(
        self,
        materials: MaterialService,
        repo,
        vocab: VocabularyService,
        console: Console,
        io: TerminalIO,
    ) -> None:
        self.materials = materials
        self.repo = repo
        self.vocab = vocab
        self.console = console
        self.io = io

    def run(
        self,
        *,
        topic: str | None = None,
        difficulty: int = 2,
        target_words: list[str] | None = None,
        force_new: bool = False,
    ) -> dict:
        ok, reason = self.materials.ai.available()
        if not ok:
            raise AIError(f"阅读训练需要 AI：{reason}")
        result = self.materials.get_reading(
            topic=topic, difficulty=difficulty, target_words=target_words, force_new=force_new
        )
        material = result.material
        title = material.get("title") or material.get("topic") or "Reading"
        self.console.print()
        self.console.print(
            Panel(
                Text(material["body"]),
                title=f"{title}  |  {material['topic']}  |  {result.meta.label}",
                border_style="cyan",
            )
        )
        self.console.print(
            Text("目标词: " + ", ".join(material["target_words"]), style="bold"),
        )
        if result.cached:
            self.console.print(Text("（使用本地缓存材料）", style="dim"))

        answers: list[str] = []
        hinted = False
        skipped_all = True
        questions = material["questions"]
        for index, question in enumerate(questions, 1):
            self.console.print()
            self.console.print(Text(f"Question {index}/{len(questions)}", style="bold"))
            self.console.print(Text(question["question"]))
            self.console.print(
                Text("[Enter] 作答   [l] 查词   [a] 添加生词   [s] 跳过   [q] 退出", style="dim")
            )
            while True:
                key = self.io.read_char()
                if key in {"q", "eof", "esc"}:
                    self.console.print(Text("已退出阅读会话（本次作答未批改）", style="yellow"))
                    return {"material_id": material["id"], "answered": 0, "quit": True}
                if key == "l":
                    word = self.io.read_line("查词: ")
                    if word:
                        lookup = self.vocab.lookup(word)
                        lookup_screen(self.console, lookup, self.vocab.display_entry(lookup))
                        hinted = True
                    continue
                if key == "a":
                    word = self.io.read_line("添加生词: ")
                    if word:
                        added = self.vocab.add_personal(word)
                        entry = self.vocab.display_entry(added)
                        if entry:
                            self.console.print(Text(f"已添加: {entry.headword}", style="green"))
                        else:
                            self.console.print(Text("未找到该词，请用 lexi add 手动补充释义", style="yellow"))
                        hinted = True
                    continue
                if key == "s":
                    answers.append("")
                    break
                if key == "enter":
                    answer = self.io.read_line("Your answer: ")
                    if answer is None:
                        return {"material_id": material["id"], "answered": 0, "quit": True}
                    answers.append(answer.strip())
                    skipped_all = False
                    break
        if skipped_all:
            self.console.print(Text("所有题目均已跳过，未调用 AI 批改。", style="dim"))
            return {"material_id": material["id"], "answered": 0, "quit": False}

        try:
            grades, meta = self.materials.grade_reading(material["id"], answers, hinted=hinted)
        except AIError as exc:
            for index, answer in enumerate(answers):
                self.repo.record_material_attempt(
                    material["id"], index, answer, {"error": str(exc)}, None, hinted=hinted
                )
            self.console.print(Text(f"批改失败，作答已保存: {exc}", style="red"))
            return {"material_id": material["id"], "answered": len(answers), "error": str(exc)}

        self.console.print()
        understood = 0
        for index, (question, grade) in enumerate(zip(questions, grades), 1):
            if grade.get("understood"):
                understood += 1
            status = Text("理解正确", style="green") if grade.get("understood") else Text("未完全理解", style="yellow")
            self.console.print(Text(f"Q{index}: ", style="bold") + status)
            if grade.get("missing"):
                self.console.print(Text("遗漏: " + "；".join(grade["missing"]), style="dim"))
            if grade.get("misunderstanding"):
                self.console.print(Text("误解: " + "；".join(grade["misunderstanding"]), style="yellow"))
            if grade.get("vocabulary_notes"):
                self.console.print(Text("词汇: " + "；".join(grade["vocabulary_notes"]), style="dim"))
            if grade.get("explanation"):
                self.console.print(Text(grade["explanation"]))
            if grade.get("reference_answer"):
                self.console.print(Text("参考: " + grade["reference_answer"], style="dim"))
        self.console.print(
            Text(
                f"\n结果: {understood}/{len(grades)} 题理解正确"
                + ("（本次使用了查词/添词辅助）" if hinted else ""),
                style="bold",
            )
        )
        self.console.print(Text(f"批改来源: {meta.label}", style="dim"))
        self.console.print(
            Text("[o] 我认为批改有误/应判定为可接受   [Enter] 继续", style="dim")
        )
        key = self.io.read_char()
        manual = False
        if key == "o":
            answer = self.io.read_line("这次作答是否应判定为可接受？[y/N]: ")
            accepted = bool(answer and answer.strip().lower().startswith("y"))
            for target in material["target_words"]:
                self.repo.add_training_log(
                    target,
                    "context",
                    correct=accepted,
                    detail={
                        "manual_override": True,
                        "material_id": material["id"],
                        "attribution": "material_level",
                    },
                    material_id=material["id"],
                )
                if accepted:
                    self.repo.resolve_errors(target, "context")
            manual = True
            self.console.print(Text("已保存人工判断。", style="green"))
        return {
            "material_id": material["id"],
            "answered": len(answers),
            "understood": understood,
            "hinted": hinted,
            "mock": meta.mock,
            "manual_override": manual,
        }
