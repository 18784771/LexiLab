from __future__ import annotations

import json
import math
from dataclasses import dataclass

from lexilab.ai.base import AIError
from lexilab.ai.schemas import (
    ClozeMaterial,
    ListeningMaterial,
    ReadingGradeBundle,
    ReadingMaterial,
    ReinforcementSet,
    WordInfo,
    WritingGrade,
    WritingPrompt,
)
from lexilab.ai.service import AICallMeta, AIService
from lexilab.config.settings import Settings
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.vocabulary.normalize import contains_word, cover_targets, normalize_word
from lexilab.vocabulary.service import VocabularyService

TOPICS = ["科学技术", "人工智能", "机器人", "学术研究", "社会文化", "日常生活", "计算机科学"]


class MaterialValidationError(AIError):
    pass


@dataclass
class MaterialResult:
    material: dict
    meta: AICallMeta
    cached: bool = False
    coverage: dict[str, bool] | None = None


class MaterialService:
    def __init__(
        self,
        settings: Settings,
        repo: LearningRepository,
        vocab: VocabularyRepository,
        ai: AIService,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.vocab = vocab
        self.ai = ai
        self.vocabulary = VocabularyService(vocab, repo)

    # ------------------------------------------------------------- selection
    def active_book(self) -> str:
        return self.repo.get_setting("active_book", "cet6") or "cet6"

    def select_target_words(self, limit: int, *, exclude: set[str] | None = None) -> list[str]:
        exclude = exclude or set()
        rows = self.repo.db.query_all(
            """SELECT c.word_key,
                      COALESCE((SELECT COUNT(*) FROM word_errors e
                                WHERE e.word_key=c.word_key AND e.resolved=0), 0) AS errs,
                      MAX(c.created_at) AS recent
               FROM cards c
               GROUP BY c.word_key
               ORDER BY errs DESC, recent DESC
               LIMIT ?""",
            (limit * 6,),
        )
        targets: list[str] = []
        for row in rows:
            key = row["word_key"]
            if key in exclude or key in targets:
                continue
            targets.append(key)
            if len(targets) >= limit:
                break
        if len(targets) < limit:
            learned = self.repo.learned_keys() | self.repo.screening_known_keys() | exclude
            for key in self.vocab.new_candidates(self.active_book(), limit * 3, learned):
                if key not in targets:
                    targets.append(key)
                if len(targets) >= limit:
                    break
        return targets[:limit]

    def _forms_by_target(self, targets: list[str]) -> dict[str, set[str]]:
        return {target: self.vocabulary.forms_for(target) for target in targets}

    # --------------------------------------------------------------- reading
    def get_reading(
        self,
        *,
        topic: str | None = None,
        difficulty: int = 2,
        target_words: list[str] | None = None,
        force_new: bool = False,
    ) -> MaterialResult:
        targets = target_words or self.select_target_words(
            self.settings.learning.reading_target_max
        )
        if not targets:
            raise MaterialValidationError("没有可用的目标词；请先学习一些单词")
        topic = topic or self._next_topic("reading")
        if not force_new:
            cached = self.repo.find_cached_material("reading", targets, topic, difficulty)
            if cached:
                return MaterialResult(cached, self._meta_from_material(cached), cached=True)
        forms = self._forms_by_target(targets)
        last_error = ""
        for _ in range(2):
            model, meta = self.ai.generate_validated(
                purpose="reading_generate",
                prompt_name="reading_generate",
                schema=ReadingMaterial,
                context={
                    "target_words": targets,
                    "topic": topic,
                    "difficulty": difficulty,
                    "min_words": self.settings.ai.reading_words_min,
                    "max_words": self.settings.ai.reading_words_max,
                },
                target_words=", ".join(targets),
                topic=topic,
                difficulty=difficulty,
                min_words=self.settings.ai.reading_words_min,
                max_words=self.settings.ai.reading_words_max,
                question_count=max(2, min(3, len(targets) - 2)),
            )
            coverage = cover_targets(model.body, targets, forms)
            covered = sum(1 for ok in coverage.values() if ok)
            length = len(model.body.split())
            required = max(1, math.ceil(len(targets) * 0.8))
            if covered < required:
                last_error = f"目标词覆盖率不足（{covered}/{len(targets)}）"
                continue
            if not (
                self.settings.ai.reading_words_min * 0.75
                <= length
                <= self.settings.ai.reading_words_max * 1.4
            ):
                last_error = f"文章长度异常（{length} words）"
                continue
            if len(model.questions) < 2:
                last_error = "理解题少于 2 道"
                continue
            material_id = self.repo.save_material(
                kind="reading",
                target_words=targets,
                topic=topic,
                difficulty=difficulty,
                body=model.body,
                questions=[q.model_dump() for q in model.questions],
                model=meta.model,
                provider=meta.provider,
                prompt_version=meta.prompt_version,
                meta={"title": model.title, "coverage": coverage, "mock": meta.mock},
            )
            material = self.repo.get_material(material_id)
            assert material is not None
            material["title"] = model.title
            material["coverage"] = coverage
            return MaterialResult(material, meta, cached=False, coverage=coverage)
        raise MaterialValidationError(last_error or "AI 材料未通过校验")

    def grade_reading(
        self, material_id: str, answers: list[str], *, hinted: bool = False
    ) -> tuple[list[dict], AICallMeta]:
        material = self.repo.get_material(material_id)
        if material is None:
            raise ValueError("material not found")
        questions = material["questions"]
        if len(answers) != len(questions):
            raise ValueError("answers count does not match questions count")
        model, meta = self.ai.generate_validated(
            purpose="reading_grade",
            prompt_name="reading_grade",
            schema=ReadingGradeBundle,
            context={"questions": questions, "answers": answers},
            article=material["body"],
            questions=json.dumps(questions, ensure_ascii=False, indent=2),
            answers=json.dumps(answers, ensure_ascii=False, indent=2),
        )
        grades = [g.model_dump() for g in model.grades]
        while len(grades) < len(questions):
            grades.append(
                {
                    "understood": None,
                    "score": 0.0,
                    "missing": [],
                    "misunderstanding": [],
                    "vocabulary_notes": [],
                    "explanation": "批改结果缺失，请自行核对参考答案。",
                    "reference_answer": questions[len(grades)].get("answer", ""),
                }
            )
        grades = grades[: len(questions)]
        for index, (answer, grade) in enumerate(zip(answers, grades)):
            correct = grade.get("understood")
            self.repo.record_material_attempt(
                material_id,
                index,
                answer,
                grade,
                bool(correct) if correct is not None else None,
                hinted=hinted,
            )
        self._record_reading_training(material, grades, hinted=hinted)
        self.repo.mark_material_used(material_id)
        return grades, meta

    def _record_reading_training(self, material: dict, grades: list[dict], *, hinted: bool = False) -> None:
        targets = material["target_words"]
        understood_count = sum(1 for g in grades if g.get("understood"))
        overall = understood_count / max(1, len(grades))
        for target in targets:
            self.repo.add_training_log(
                target,
                "context",
                correct=overall >= 0.6,
                hinted=hinted,
                detail={
                    "material_id": material["id"],
                    "attribution": "material_level",
                    "questions": len(grades),
                    "understood": understood_count,
                    "independent": not hinted,
                },
                material_id=material["id"],
            )
        for index, grade in enumerate(grades):
            if grade.get("understood"):
                continue
            question = material["questions"][index] if index < len(material["questions"]) else {}
            reference = question.get("answer", "")
            forms = self._forms_by_target(targets)
            involved = [t for t in targets if contains_word(reference, t, forms.get(t))]
            for target in involved:
                self.repo.add_word_error(
                    target,
                    "context",
                    "reading_misunderstanding",
                    "阅读理解题未答出与目标词相关的信息",
                )

    # ------------------------------------------------------------- listening
    def get_listening(
        self,
        *,
        topic: str | None = None,
        difficulty: int = 2,
        target_words: list[str] | None = None,
        count: int = 5,
        force_new: bool = False,
    ) -> MaterialResult:
        targets = target_words or self.select_target_words(
            min(self.settings.learning.reading_target_max, max(3, count))
        )
        if not targets:
            raise MaterialValidationError("没有可用的目标词")
        topic = topic or self._next_topic("listening")
        if not force_new:
            cached = self.repo.find_cached_material("listening", targets, topic, difficulty)
            if cached:
                return MaterialResult(cached, self._meta_from_material(cached), cached=True)
        forms = self._forms_by_target(targets)
        model, meta = self.ai.generate_validated(
            purpose="listening_generate",
            prompt_name="listening_generate",
            schema=ListeningMaterial,
            context={
                "target_words": targets,
                "topic": topic,
                "count": count,
                "difficulty": difficulty,
            },
            target_words=", ".join(targets),
            topic=topic,
            count=count,
            difficulty=difficulty,
            max_tokens=1200,
        )
        body = "\n".join(s.text for s in model.sentences)
        coverage = cover_targets(body, targets, forms)
        if not any(coverage.values()):
            raise MaterialValidationError("听力材料未包含任何目标词")
        questions = [
            {"question": f"听写第 {index + 1} 句", "answer": sentence.text, "translation": sentence.translation}
            for index, sentence in enumerate(model.sentences)
        ]
        material_id = self.repo.save_material(
            kind="listening",
            target_words=targets,
            topic=topic,
            difficulty=difficulty,
            body=body,
            questions=questions,
            model=meta.model,
            provider=meta.provider,
            prompt_version=meta.prompt_version,
            meta={"coverage": coverage, "mock": meta.mock},
        )
        material = self.repo.get_material(material_id)
        assert material is not None
        material["coverage"] = coverage
        return MaterialResult(material, meta, cached=False, coverage=coverage)

    # --------------------------------------------------------------- writing
    def get_writing(
        self,
        *,
        level: int = 1,
        topic: str | None = None,
        target_words: list[str] | None = None,
        force_new: bool = False,
    ) -> MaterialResult:
        targets = target_words or self.select_target_words(5)
        if not targets:
            raise MaterialValidationError("没有可用的目标词")
        topic = topic or self._next_topic("writing")
        if not force_new:
            cached = self.repo.find_cached_material("writing", targets, topic, level)
            if cached:
                return MaterialResult(cached, self._meta_from_material(cached), cached=True)
        model, meta = self.ai.generate_validated(
            purpose="writing_generate",
            prompt_name="writing_generate",
            schema=WritingPrompt,
            context={"level": level, "target_words": targets, "topic": topic},
            level=level,
            target_words=", ".join(targets),
            topic=topic,
            max_tokens=900,
        )
        material_id = self.repo.save_material(
            kind="writing",
            target_words=targets,
            topic=topic,
            difficulty=level,
            body=model.prompt,
            questions=[model.model_dump()],
            model=meta.model,
            provider=meta.provider,
            prompt_version=meta.prompt_version,
            meta={"guidance": model.guidance, "mock": meta.mock},
        )
        material = self.repo.get_material(material_id)
        assert material is not None
        return MaterialResult(material, meta, cached=False)

    def grade_writing(self, material_id: str, answer: str) -> tuple[WritingGrade, AICallMeta]:
        material = self.repo.get_material(material_id)
        if material is None:
            raise ValueError("material not found")
        level = int(material["difficulty"])
        targets = material["target_words"]
        grade, meta = self.ai.generate_validated(
            purpose="writing_grade",
            prompt_name="writing_grade",
            schema=WritingGrade,
            context={
                "prompt": material["body"],
                "level": level,
                "target_words": targets,
                "answer": answer,
            },
            prompt=material["body"],
            level=level,
            target_words=", ".join(targets),
            answer=answer,
            max_tokens=1800,
        )
        self.repo.record_material_attempt(
            material_id,
            0,
            answer,
            grade.model_dump(),
            bool(grade.task_completed and grade.score >= 0.5),
            hinted=False,
        )
        for item in grade.target_words:
            key = normalize_word(item.target_word)
            if not key:
                continue
            self.repo.add_training_log(
                key,
                "production",
                correct=bool(item.used and item.meaning_correct and item.collocation_correct),
                error_type=item.error_type or None,
                detail={
                    "material_id": material_id,
                    "used": item.used,
                    "meaning_correct": item.meaning_correct,
                    "collocation_correct": item.collocation_correct,
                    "feedback": item.feedback,
                },
                material_id=material_id,
            )
            if item.follow_up_required or not item.collocation_correct or not item.meaning_correct:
                self.repo.add_word_error(
                    key,
                    "production",
                    item.error_type or "collocation",
                    item.feedback or "写作中的目标词使用问题",
                )
        self.repo.mark_material_used(material_id)
        return grade, meta

    # ----------------------------------------------------------------- cloze
    def get_cloze(self, target_words: list[str]) -> list[dict]:
        details = []
        for word in target_words:
            entry = self.vocabulary.lookup(word)
            display = self.vocabulary.display_entry(entry)
            example = display.example_for_cloze() if display else None
            if example:
                details.append({"word": word, "sentence": example.sentence_en, "translation": example.sentence_cn})
        if self.ai.available()[0] and target_words:
            try:
                model, _ = self.ai.generate_validated(
                    purpose="cloze_generate",
                    prompt_name="cloze_generate",
                    schema=ClozeMaterial,
                    context={"target_words": target_words},
                    target_words=", ".join(target_words),
                    examples=json.dumps(details, ensure_ascii=False),
                    max_tokens=900,
                )
                return [item.model_dump() for item in model.items]
            except AIError:
                pass
        return [
            {
                "sentence": item["sentence"].replace(item["word"], "______"),
                "answer": item["word"],
                "translation": item.get("translation", ""),
            }
            for item in details
        ]

    # --------------------------------------------------------- reinforcement
    def get_reinforcement(self, limit: int = 5) -> ReinforcementSet:
        errors = self.repo.list_open_errors(limit)
        if not errors:
            raise MaterialValidationError("没有未解决的错误")
        model, _ = self.ai.generate_validated(
            purpose="error_reinforcement",
            prompt_name="error_reinforcement",
            schema=ReinforcementSet,
            context={"errors": errors},
            errors=json.dumps(errors, ensure_ascii=False, indent=2),
            max_tokens=1200,
        )
        return model

    # ---------------------------------------------------------------- helpers
    def enrich_word(self, word: str) -> tuple[WordInfo, AICallMeta]:
        model, meta = self.ai.generate_validated(
            purpose="word_enrich",
            prompt_name="word_enrich",
            schema=WordInfo,
            context={"word": word},
            word=word,
            max_tokens=700,
        )
        return model, meta

    def _next_topic(self, kind: str) -> str:
        used = {m["topic"] for m in self.repo.recent_materials(kind, limit=3)}
        for topic in TOPICS:
            if topic not in used:
                return topic
        return TOPICS[len(used) % len(TOPICS)]

    @staticmethod
    def _meta_from_material(material: dict) -> AICallMeta:
        meta = material.get("meta") or {}
        return AICallMeta(
            provider=material.get("provider") or "unknown",
            model=material.get("model") or "unknown",
            prompt_version=material.get("prompt_version") or "",
            mock=bool(meta.get("mock")),
        )
