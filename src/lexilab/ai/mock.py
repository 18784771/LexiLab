from __future__ import annotations

import json

from lexilab.ai.base import AIRequest, AIResponse
from lexilab.vocabulary.normalize import normalize_answer, tokenize, word_forms

_MOCK_NOTE = "模拟生成（MockProvider）：用于离线演示和自动化测试，不代表真实 AI 质量。"


class MockProvider:
    """Deterministic offline provider used for tests and no-network demos."""

    name = "mock"

    def __init__(self) -> None:
        self.model = "mock-v1"

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def generate(self, request: AIRequest) -> AIResponse:
        purpose = request.purpose
        context = request.context or {}
        if purpose == "reading_generate":
            payload = self._reading(context)
        elif purpose == "reading_grade":
            payload = self._grade_reading(context)
        elif purpose == "listening_generate":
            payload = self._listening(context)
        elif purpose == "writing_generate":
            payload = self._writing_prompt(context)
        elif purpose == "writing_grade":
            payload = self._grade_writing(context)
        elif purpose == "cloze_generate":
            payload = self._cloze(context)
        elif purpose == "error_reinforcement":
            payload = self._reinforcement(context)
        elif purpose == "word_enrich":
            payload = self._word_info(context)
        else:
            payload = {"ok": True, "note": _MOCK_NOTE}
        return AIResponse(
            text=json.dumps(payload, ensure_ascii=False),
            model=self.model,
            provider=self.name,
            finish_reason="stop",
            latency_ms=0,
        )

    # ---------------------------------------------------------------- reading
    def _reading(self, ctx: dict) -> dict:
        targets = [str(w) for w in ctx.get("target_words") or ["mitigate"]]
        topic = str(ctx.get("topic") or "scientific research")
        difficulty = int(ctx.get("difficulty") or 2)
        min_words = int(ctx.get("min_words") or 150)
        max_words = int(ctx.get("max_words") or 250)
        sentences = [
            f"Recent discussions of {topic} often focus on {', '.join(targets[:-1])} and {targets[-1]}.",
            f"Researchers who study {topic} must {targets[0]} the uncertainty that appears in their data.",
            "Careful work begins with a clear question, a small set of observations, and an honest account of what remains unknown.",
        ]
        templates = [
            "A team may {w} an apparent problem before it affects the wider system.",
            "The idea of {w} becomes clearer when it is compared with evidence from more than one source.",
            "In practice, {w} is not a single decision but a process that is reviewed over time.",
            "Teachers and engineers alike need to explain {w} in plain language, because unclear terms hide weak reasoning.",
            "When the evidence is incomplete, the safest approach is to describe {w} carefully and to test the claim again.",
        ]
        for index, word in enumerate(targets):
            sentences.append(templates[index % len(templates)].format(w=word))
        sentences.append(
            "The passage does not claim that one method solves every problem. It suggests that clear definitions, repeated checks, and a willingness to revise an early conclusion are more useful than confident guesses."
        )
        body = " ".join(sentences)
        filler = (
            " This matters because readers need enough context to judge whether a claim is supported."
            " A short example can make the reasoning visible, while a careful conclusion keeps the discussion open to correction."
        )
        while len(body.split()) < min_words:
            body += filler
        words = body.split()
        if len(words) > max_words:
            body = " ".join(words[:max_words])
        return {
            "title": f"Understanding {topic.title()}",
            "topic": topic,
            "difficulty": difficulty,
            "body": body,
            "target_words_used": targets,
            "questions": [
                {
                    "question": "What is the main idea of the passage?",
                    "answer": f"The passage explains how {', '.join(targets[:3])} relate to {topic} and why careful evidence matters.",
                    "rationale": "需要概括全文主旨以及目标词的作用。",
                },
                {
                    "question": f"Why does the passage mention {targets[0]}?",
                    "answer": f"It uses {targets[0]} to illustrate a central concern in {topic}.",
                    "rationale": "需要理解目标词所在的语境。",
                },
                {
                    "question": "What caution does the passage give?",
                    "answer": "It cautions that evidence is often incomplete, so conclusions should be checked and revised.",
                    "rationale": "需要识别作者的限制性说明。",
                },
            ],
            "_mock": True,
        }

    def _grade_reading(self, ctx: dict) -> dict:
        questions = ctx.get("questions") or []
        answers = ctx.get("answers") or []
        grades = []
        for index, question in enumerate(questions):
            answer = str(answers[index] if index < len(answers) else "")
            reference = str(question.get("answer") or "")
            ref_tokens = set(tokenize(reference))
            ans_tokens = set(tokenize(answer))
            overlap = len(ref_tokens & ans_tokens) / max(1, len(ref_tokens))
            understood = bool(answer.strip()) and (overlap >= 0.15 or len(ans_tokens) >= 8)
            grades.append(
                {
                    "understood": understood,
                    "score": 0.7 if understood else (0.0 if not answer.strip() else 0.2),
                    "missing": [] if understood else ["参考答案中的核心信息"],
                    "misunderstanding": [],
                    "vocabulary_notes": [],
                    "explanation": "模拟批改：根据关键词重合度判断，不能替代真实语义批改。"
                    if answer.strip()
                    else "未作答。",
                    "reference_answer": reference,
                }
            )
        return {"grades": grades, "_mock": True}

    # -------------------------------------------------------------- listening
    def _listening(self, ctx: dict) -> dict:
        targets = [str(w) for w in ctx.get("target_words") or ["mitigate"]]
        count = max(1, int(ctx.get("count") or 5))
        templates = [
            "The engineers tried to {w} the risk before the test began.",
            "We need to {w} the effect of noise on the sensor.",
            "The report describes a simple way to {w} the problem.",
            "A careful team will {w} the damage caused by the error.",
            "They discussed how to {w} the impact of the new constraint.",
        ]
        sentences = []
        for index in range(count):
            word = targets[index % len(targets)]
            sentences.append(
                {
                    "text": templates[index % len(templates)].format(w=word),
                    "translation": "（模拟听力材料，本地听写判定）",
                }
            )
        return {"topic": str(ctx.get("topic") or "general"), "sentences": sentences, "target_words_used": targets, "_mock": True}

    # ---------------------------------------------------------------- writing
    def _writing_prompt(self, ctx: dict) -> dict:
        targets = [str(w) for w in ctx.get("target_words") or ["mitigate"]]
        level = int(ctx.get("level") or 1)
        topic = str(ctx.get("topic") or "robotics")
        if level == 1:
            prompt = f"请使用 {targets[0]} 写一个句子，描述如何应对 {topic} 中的一个问题。"
            guidance = "写一个完整句子，注意目标词的搭配。"
        elif level == 2:
            prompt = f"把下面这句话翻译成英文：为了降低 {topic} 中的风险，我们提出了一种新的方法。"
            guidance = "尽量使用目标词，并保持句子结构完整。"
        else:
            prompt = f"写一段短文，说明 {targets[0]} 与 {targets[-1]} 如何影响 {topic} 的可靠性。"
            guidance = "60–120 词，给出理由和一个具体例子。"
        return {
            "level": level,
            "prompt": prompt,
            "guidance": guidance,
            "suggested_vocabulary": targets,
            "reference_points": ["使用目标词", "结构完整", "观点清晰"],
            "_mock": True,
        }

    def _grade_writing(self, ctx: dict) -> dict:
        answer = str(ctx.get("answer") or "")
        targets = [str(w) for w in ctx.get("target_words") or []]
        level = int(ctx.get("level") or 1)
        normalized = normalize_answer(answer)
        issues: list[dict] = []
        target_results: list[dict] = []
        for word in targets:
            forms = word_forms(word)
            used = any(form and form in normalized for form in forms)
            target_results.append(
                {
                    "target_word": word,
                    "used": used,
                    "meaning_correct": used,
                    "collocation_correct": used,
                    "error_type": "" if used else "missing_target",
                    "feedback": "" if used else f"未使用目标词 {word}",
                    "corrected_sentence": "",
                    "follow_up_required": not used,
                }
            )
        if answer and answer[0].islower():
            issues.append(
                {
                    "category": "grammar",
                    "excerpt": answer[:1],
                    "explanation": "句首字母应大写。",
                    "correction": answer[0].upper(),
                }
            )
        if answer and answer.strip()[-1:] not in ".!?":
            issues.append(
                {
                    "category": "grammar",
                    "excerpt": answer[-20:],
                    "explanation": "句子末尾缺少标点。",
                    "correction": answer.strip() + ".",
                }
            )
        min_words = {1: 4, 2: 8, 3: 40}.get(level, 4)
        task_completed = len(answer.split()) >= min_words
        score = 0.4 + (0.2 if task_completed else 0) + (0.2 if any(t["used"] for t in target_results) else 0)
        if issues:
            score -= 0.1
        return {
            "task_completed": task_completed,
            "score": round(max(0.0, min(1.0, score)), 2),
            "issues": issues,
            "acceptable_notes": ["模拟批改不会判断语义是否自然，请以参考表达为参考。"],
            "target_words": target_results,
            "minimal_correction": answer.strip().capitalize() + ("" if answer.strip()[-1:] in ".!?" else "."),
            "improved_version": answer.strip(),
            "follow_up_required": any(t["follow_up_required"] for t in target_results) or not task_completed,
            "overall_comment": _MOCK_NOTE,
            "_mock": True,
        }

    # ------------------------------------------------------------------ cloze
    def _cloze(self, ctx: dict) -> dict:
        targets = [str(w) for w in ctx.get("target_words") or ["mitigate"]]
        items = [
            {
                "sentence": "The team tried to ______ the risk before the test.",
                "answer": targets[0],
                "translation": "团队在测试前尝试降低风险。",
            }
        ]
        for word in targets[1:]:
            items.append(
                {
                    "sentence": "The report explains how to ______ the problem.",
                    "answer": word,
                    "translation": "报告解释了如何处理这个问题。",
                }
            )
        return {"items": items, "_mock": True}

    def _word_info(self, ctx: dict) -> dict:
        word = str(ctx.get("word") or "").strip()
        return {
            "word": word,
            "phonetic": "",
            "pos": "",
            "translation": f"（模拟释义）{word}：请配置真实 AI 或手动补充释义",
            "definition_en": "Mock definition generated offline.",
            "example": f"This is a mock example for {word}.",
            "example_translation": f"这是 {word} 的模拟例句。",
            "_mock": True,
        }

    def _reinforcement(self, ctx: dict) -> dict:
        errors = ctx.get("errors") or []
        exercises = []
        for item in errors:
            word = str(item.get("word") or item.get("word_key") or "")
            if not word:
                continue
            exercises.append(
                {
                    "word": word,
                    "error_type": str(item.get("error_type") or ""),
                    "exercise": f"请用 {word} 写一个新句子，并说明它的宾语或搭配。",
                    "answer_hint": "关注该词的常见搭配，而不是只记中文释义。",
                }
            )
        if not exercises:
            exercises.append(
                {
                    "word": "mitigate",
                    "error_type": "collocation",
                    "exercise": "请用 mitigate the impact of 写一个句子。",
                    "answer_hint": "mitigate 常与 risk / impact / damage 等搭配。",
                }
            )
        return {"exercises": exercises, "_mock": True}
