from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from lexilab.ai.base import AIResponseFormatError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> dict:
    if not text or not text.strip():
        raise AIResponseFormatError("AI 返回空内容")
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise AIResponseFormatError("AI 返回内容不是 JSON 对象") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIResponseFormatError(f"JSON 解析失败: {exc.msg}") from None
    if not isinstance(data, dict):
        raise AIResponseFormatError("AI 返回的 JSON 顶层不是对象")
    return data


def parse_model(text: str, schema: type[T]) -> T:
    data = extract_json(text)
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(x) for x in first.get("loc", ()))
        raise AIResponseFormatError(f"结构化数据校验失败: {location} {first.get('msg', '')}") from None
