from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ReadingQuestion(_Model):
    question: str = Field(min_length=3)
    answer: str = Field(min_length=1)
    rationale: str = ""


class ReadingMaterial(_Model):
    title: str = Field(min_length=1)
    topic: str = ""
    difficulty: int = Field(default=2, ge=1, le=3)
    body: str = Field(min_length=50)
    target_words_used: list[str] = Field(default_factory=list)
    questions: list[ReadingQuestion] = Field(min_length=1)

    @field_validator("questions")
    @classmethod
    def _question_count(cls, value: list[ReadingQuestion]) -> list[ReadingQuestion]:
        if len(value) > 5:
            raise ValueError("题目数量过多")
        return value


class ListeningSentence(_Model):
    text: str = Field(min_length=3)
    translation: str = ""


class ListeningMaterial(_Model):
    topic: str = ""
    sentences: list[ListeningSentence] = Field(min_length=1)
    target_words_used: list[str] = Field(default_factory=list)


class WritingPrompt(_Model):
    level: int = Field(ge=1, le=3)
    prompt: str = Field(min_length=5)
    guidance: str = ""
    suggested_vocabulary: list[str] = Field(default_factory=list)
    reference_points: list[str] = Field(default_factory=list)


class ReadingGrade(_Model):
    understood: bool
    score: float = Field(default=0.0, ge=0, le=1)
    missing: list[str] = Field(default_factory=list)
    misunderstanding: list[str] = Field(default_factory=list)
    vocabulary_notes: list[str] = Field(default_factory=list)
    explanation: str = ""
    reference_answer: str = ""


class ReadingGradeBundle(_Model):
    grades: list[ReadingGrade] = Field(default_factory=list)


class WritingIssue(_Model):
    category: Literal["grammar", "spelling", "meaning", "collocation", "style", "other"]
    excerpt: str = ""
    explanation: str = ""
    correction: str = ""


class TargetWordUse(_Model):
    target_word: str
    used: bool = False
    meaning_correct: bool = True
    collocation_correct: bool = True
    error_type: str = ""
    feedback: str = ""
    corrected_sentence: str = ""
    follow_up_required: bool = False


class WritingGrade(_Model):
    task_completed: bool
    score: float = Field(default=0.0, ge=0, le=1)
    issues: list[WritingIssue] = Field(default_factory=list)
    acceptable_notes: list[str] = Field(default_factory=list)
    target_words: list[TargetWordUse] = Field(default_factory=list)
    minimal_correction: str = ""
    improved_version: str = ""
    follow_up_required: bool = False
    overall_comment: str = ""


class ClozeItem(_Model):
    sentence: str
    answer: str
    translation: str = ""


class ClozeMaterial(_Model):
    items: list[ClozeItem] = Field(min_length=1)


class ReinforcementExercise(_Model):
    word: str
    error_type: str = ""
    exercise: str
    answer_hint: str = ""


class ReinforcementSet(_Model):
    exercises: list[ReinforcementExercise] = Field(min_length=1)


class WordInfo(_Model):
    word: str
    phonetic: str = ""
    pos: str = ""
    translation: str = ""
    definition_en: str = ""
    example: str = ""
    example_translation: str = ""
