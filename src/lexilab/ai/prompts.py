from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    text: str
    version: str

    def render(self, **values) -> str:
        try:
            return Template(self.text).substitute(**values)
        except KeyError as exc:
            raise ValueError(f"提示词 {self.name} 缺少变量: {exc.args[0]}") from None


@lru_cache(maxsize=32)
def load_prompt(name: str) -> PromptTemplate:
    path = PROMPT_DIR / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"提示词文件不存在: {path}")
    text = path.read_text(encoding="utf-8")
    version = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return PromptTemplate(name=name, text=text, version=version)


def list_prompts() -> list[PromptTemplate]:
    return [load_prompt(path.stem) for path in sorted(PROMPT_DIR.glob("*.txt"))]
