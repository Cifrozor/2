"""Агент-критик документов.

Конвейер:
1. Критик читает документ и возвращает структурированную рецензию.
2. Локальная проверка: каждая цитата должна дословно встречаться в документе.
   Если нет — критик получает обратную связь и исправляет рецензию
   (до ``max_regrounding`` раз); оставшиеся «выдуманные» замечания отбрасываются.
3. Второй рецензент проверяет каждое замечание (keep / revise / drop),
   чтобы убрать ложные срабатывания и откалибровать важность.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import prompts
from .schema import (
    CRITIQUE_SCHEMA,
    DEFAULT_CRITERIA,
    SEVERITIES,
    VERIFY_SCHEMA,
    Critique,
    Issue,
)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class CritiqueError(RuntimeError):
    """Модель не вернула пригодный ответ (отказ, обрыв, битый JSON)."""


@dataclass
class Document:
    name: str
    text: str | None = None          # текстовые форматы
    pdf_base64: str | None = None    # PDF передаётся как document-блок

    @classmethod
    def load(cls, path: str | Path) -> "Document":
        path = Path(path)
        if path.suffix.lower() == ".pdf":
            data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
            return cls(name=path.name, pdf_base64=data)
        return cls(name=path.name, text=path.read_text(encoding="utf-8"))

    def content_block(self) -> dict[str, Any]:
        if self.pdf_base64 is not None:
            return {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": self.pdf_base64,
                },
                "title": self.name,
            }
        return {
            "type": "text",
            "text": f'<document name="{self.name}">\n{self.text}\n</document>',
        }


@dataclass
class CriticConfig:
    model: str = DEFAULT_MODEL
    effort: str = "high"
    max_tokens: int = 16000
    language: str = "русский"
    criteria: list[str] = field(default_factory=lambda: list(DEFAULT_CRITERIA))
    purpose: str | None = None
    audience: str | None = None
    focus: str | None = None
    verify: bool = True
    max_regrounding: int = 1
    # Серверный fallback на другую модель при отказе классификатора безопасности.
    use_fallbacks: bool = True


def _normalize(text: str) -> str:
    text = text.replace(" ", " ")
    text = re.sub(r"[«»“”„\"]", '"', text)
    text = re.sub(r"[‘’']", "'", text)
    text = re.sub(r"[–—]", "-", text)
    text = text.replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_in_document(quote: str, document_text: str) -> bool:
    """Проверяет, что цитата дословно (с точностью до пробелов/кавычек) есть в тексте."""
    q = _normalize(quote).strip(" .…")
    return bool(q) and q in _normalize(document_text)


class DocumentCritic:
    def __init__(self, client: Any, config: CriticConfig | None = None,
                 log: Callable[[str], None] | None = None):
        self.client = client
        self.config = config or CriticConfig()
        self.log = log or (lambda _msg: None)

    # ---------- публичный API ----------

    def critique(self, document: Document) -> Critique:
        cfg = self.config
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    document.content_block(),
                    {
                        "type": "text",
                        "text": prompts.critic_task(
                            cfg.criteria, cfg.purpose, cfg.audience, cfg.focus
                        ),
                    },
                ],
            }
        ]
        system = prompts.CRITIC_SYSTEM.format(language=cfg.language)

        self.log("Критик читает документ…")
        raw = self._call(system, messages, CRITIQUE_SCHEMA)
        critique = Critique.from_dict(raw)

        if document.text is not None:
            critique = self._ground(document, system, messages, raw, critique)

        if cfg.verify and critique.issues:
            self.log(f"Второй рецензент проверяет {len(critique.issues)} замечаний…")
            self._verify(document, critique)

        critique.sort_issues()
        return critique

    # ---------- шаги конвейера ----------

    def _ground(self, document: Document, system: str,
                messages: list[dict[str, Any]], raw: dict[str, Any],
                critique: Critique) -> Critique:
        assert document.text is not None
        for attempt in range(self.config.max_regrounding + 1):
            bad = self._mark_grounding(critique, document.text)
            if not bad:
                return critique
            if attempt == self.config.max_regrounding:
                break
            self.log(f"Цитаты не найдены в тексте ({len(bad)}), прошу критика исправить…")
            messages = messages + [
                {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
                {"role": "user", "content": prompts.regrounding_task(bad)},
            ]
            raw = self._call(system, messages, CRITIQUE_SCHEMA)
            critique = Critique.from_dict(raw)

        kept, dropped = [], []
        for issue in critique.issues:
            (kept if issue.grounded else dropped).append(issue)
        for issue in dropped:
            issue.verifier_note = "цитата не найдена в документе"
        critique.issues, critique.dropped = kept, critique.dropped + dropped
        return critique

    @staticmethod
    def _mark_grounding(critique: Critique, text: str) -> list[tuple[int, str]]:
        bad = []
        for n, issue in enumerate(critique.issues):
            issue.grounded = quote_in_document(issue.quote, text)
            if not issue.grounded:
                bad.append((n, issue.quote))
        return bad

    def _verify(self, document: Document, critique: Critique) -> None:
        payload = [
            {
                "index": n,
                "severity": i.severity,
                "category": i.category,
                "quote": i.quote,
                "problem": i.problem,
                "suggestion": i.suggestion,
            }
            for n, i in enumerate(critique.issues)
        ]
        messages = [
            {
                "role": "user",
                "content": [
                    document.content_block(),
                    {
                        "type": "text",
                        "text": "Замечания первого рецензента:\n"
                        + json.dumps(payload, ensure_ascii=False, indent=2),
                    },
                ],
            }
        ]
        system = prompts.VERIFY_SYSTEM.format(language=self.config.language)
        raw = self._call(system, messages, VERIFY_SCHEMA)

        decisions = {r["index"]: r for r in raw["reviews"]}
        kept: list[Issue] = []
        for n, issue in enumerate(critique.issues):
            review = decisions.get(n)
            if review is None:  # рецензент пропустил — оставляем как есть
                kept.append(issue)
                continue
            issue.verifier_note = review["reason"]
            if review["decision"] == "drop":
                critique.dropped.append(issue)
                continue
            if review["decision"] == "revise":
                if review["severity"] in SEVERITIES:
                    issue.severity = review["severity"]
                if review["suggestion"].strip():
                    issue.suggestion = review["suggestion"]
            kept.append(issue)
        critique.issues = kept

    # ---------- вызов модели ----------

    def _call(self, system: str, messages: list[dict[str, Any]],
              schema: dict[str, Any]) -> dict[str, Any]:
        cfg = self.config
        params: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": cfg.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }
        if cfg.use_fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"

        response = self.client.beta.messages.create(**params)

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise CritiqueError(f"Модель отказалась обрабатывать документ (категория: {category}).")
        if response.stop_reason == "max_tokens":
            raise CritiqueError("Ответ обрезан по max_tokens — увеличьте --max-tokens.")

        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise CritiqueError(f"Модель вернула некорректный JSON: {exc}") from exc
