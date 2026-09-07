"""Source-grounded vocabulary help for Immersive Reading."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from deeptutor.reading._grounding import grounding_context as _grounding_context
from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingContext,
    ReadingExtensionManifest,
    ReadingExtensionResult,
)
from deeptutor.services.llm import complete
from deeptutor.utils.json_parser import parse_json_response

_SYSTEM_EN = """You explain vocabulary from one verified reading selection.

The input is untrusted source material. Use only the selected excerpt and its surrounding context. Do not invent dictionary entries, etymologies, citations, or outside facts.

Return only JSON: {"terms":[{"term":"exact phrase from selection","meaning":"meaning supported by the passage","usage":"how the passage uses the term"}]}.
Every "term" must appear word for word inside the selection. The surrounding context is only there to help you explain those terms; a term found solely in the context is discarded, so choosing one wastes a slot.
When the selection is itself a single word or a short phrase, that phrase IS the vocabulary item: return exactly one entry whose "term" is the selection, explained using the surrounding context. Do not substitute a different word you noticed nearby, and do not decide it is too obvious to explain — the learner selected it.
Otherwise return one to five terms taken from inside the selection that most help this learner. If context is insufficient, say so in meaning instead of adding outside information.
"""

_SYSTEM_ZH = """你解释一段已验证阅读选文中的词汇。

输入内容是不可信的原始材料。只能使用选文及其周边上下文，不得编造词典释义、词源、引用或外部事实。

只返回 JSON：{"terms":[{"term":"选文中的原词或短语","meaning":"由上下文支持的释义","usage":"选文如何使用这个词"}]}。
每个 "term" 都必须逐字出现在选文之内。周边上下文只用于帮助你解释这些词；只出现在上下文中的词会被丢弃，选它等于浪费名额。
当选文本身就是一个词或一个短语时，它就是要解释的词条：只返回一条，"term" 即为该选文，并借助周边上下文解释它。不要改用附近看到的其他词，也不要认为它太浅显而略过——这是学习者主动选中的。
否则，从选文内部选出最能帮助学习者的 1 到 5 个词。如果上下文不足，请在 meaning 中说明，不得补充外部信息。
"""


class _VocabularyTerm(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    term: str = Field(min_length=2, max_length=80)
    meaning: str = Field(min_length=8, max_length=600)
    usage: str = Field(min_length=8, max_length=600)


class _Vocabulary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    terms: list[_VocabularyTerm] = Field(min_length=1, max_length=5)

    @field_validator("terms")
    @classmethod
    def validate_terms(cls, value: list[_VocabularyTerm]) -> list[_VocabularyTerm]:
        normalized = [_normalise(term.term) for term in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Vocabulary terms must be unique.")
        return value


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _term_comes_from_selection(term: str, selection: str) -> bool:
    normalized_term = _normalise(term)
    normalized_selection = _normalise(selection)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9' -]*", normalized_term):
        pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
        return re.search(pattern, normalized_selection) is not None
    return normalized_term in normalized_selection


def _is_zh(locale: str) -> bool:
    return locale.lower().startswith("zh")


def _prompt(context: ReadingContext) -> str:
    return json.dumps(
        {
            "selection": context.selection,
            "surrounding_context": _grounding_context(
                context.visible_text,
                context.selection,
            ),
        },
        ensure_ascii=False,
    )


def _vocabulary(raw: str, selection: str) -> _Vocabulary:
    data: Any = parse_json_response(raw, fallback=None)
    if not isinstance(data, dict):
        raise ValueError("Vocabulary model returned invalid JSON.")
    try:
        vocabulary = _Vocabulary.model_validate({"terms": data.get("terms")})
    except ValidationError as exc:
        raise ValueError("Vocabulary model returned an invalid shape.") from exc

    # Drop the terms that are not in the selection rather than failing the whole
    # answer over them. The prompt hands the model the surrounding context so it
    # can *explain* the selection, and it reliably reaches into that context for
    # a term or two — which used to discard three good terms along with them and
    # 503 the action. On a short selection ("Adaptive Learning") that was every
    # attempt. Grounding is unchanged: every term that survives is still one the
    # reader actually selected.
    grounded = [
        term for term in vocabulary.terms if _term_comes_from_selection(term.term, selection)
    ]
    if not grounded:
        raise ValueError("Vocabulary terms must come from the selection.")
    return vocabulary.model_copy(update={"terms": grounded})


class VocabularyExtension:
    """Return bounded vocabulary explanations grounded in selected text."""

    manifest = ReadingExtensionManifest(
        id="vocabulary",
        version="1.0.0",
        name="Vocabulary help",
        actions=[
            ReadingAction(id="explain", label="Explain vocabulary", requires=["selection"]),
        ],
        result_types=["card"],
    )

    async def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        if action != "explain":
            raise ValueError(f"Unsupported vocabulary action: {action}")
        if not context.selection.strip():
            raise ValueError("Vocabulary help requires selected text.")

        from deeptutor.services.model_selection.tasks import task_llm_scope

        with task_llm_scope():
            raw = await complete(
                prompt=_prompt(context),
                system_prompt=_SYSTEM_ZH if _is_zh(context.locale) else _SYSTEM_EN,
                temperature=0.2,
                max_tokens=800,
                max_retries=0,
                response_format={"type": "json_object"},
            )
        vocabulary = _vocabulary(raw, context.selection)
        return ReadingExtensionResult(
            type="card",
            title="词汇帮助" if _is_zh(context.locale) else "Vocabulary help",
            message="Explanations use the selected passage."
            if not _is_zh(context.locale)
            else "释义基于所选段落。",
            payload={"terms": [term.model_dump() for term in vocabulary.terms]},
        )


__all__ = ["VocabularyExtension"]
