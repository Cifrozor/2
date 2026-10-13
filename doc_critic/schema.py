"""Модель данных критики и JSON-схемы для structured outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITIES = ("critical", "major", "minor")
VERDICTS = ("ready", "minor_revisions", "major_revisions", "rewrite")
DECISIONS = ("keep", "revise", "drop")

DEFAULT_CRITERIA = (
    "Ясность изложения",
    "Структура и логика",
    "Аргументация и доказательность",
    "Фактическая точность и непротиворечивость",
    "Полнота",
    "Соответствие цели и аудитории",
    "Стиль, грамматика, оформление",
)


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_INT = {"type": "integer"}

CRITIQUE_SCHEMA = _obj(
    {
        "summary": _STR,
        "overall_score": _INT,
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "scores": {
            "type": "array",
            "items": _obj({"criterion": _STR, "score": _INT, "comment": _STR}),
        },
        "strengths": {"type": "array", "items": _STR},
        "issues": {
            "type": "array",
            "items": _obj(
                {
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "category": _STR,
                    "quote": _STR,
                    "problem": _STR,
                    "suggestion": _STR,
                }
            ),
        },
        "top_priorities": {"type": "array", "items": _STR},
    }
)

VERIFY_SCHEMA = _obj(
    {
        "reviews": {
            "type": "array",
            "items": _obj(
                {
                    "index": _INT,
                    "decision": {"type": "string", "enum": list(DECISIONS)},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "reason": _STR,
                    "suggestion": _STR,
                }
            ),
        }
    }
)


@dataclass
class Score:
    criterion: str
    score: int
    comment: str


@dataclass
class Issue:
    severity: str
    category: str
    quote: str
    problem: str
    suggestion: str
    # None — цитату нельзя проверить локально (например, PDF).
    grounded: bool | None = None
    verifier_note: str = ""


@dataclass
class Critique:
    summary: str
    overall_score: int
    verdict: str
    scores: list[Score]
    strengths: list[str]
    issues: list[Issue]
    top_priorities: list[str]
    dropped: list[Issue] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Critique":
        return cls(
            summary=data["summary"],
            overall_score=_clamp(data["overall_score"]),
            verdict=data["verdict"],
            scores=[
                Score(s["criterion"], _clamp(s["score"]), s["comment"])
                for s in data["scores"]
            ],
            strengths=list(data["strengths"]),
            issues=[Issue(**i) for i in data["issues"]],
            top_priorities=list(data["top_priorities"]),
        )

    def sort_issues(self) -> None:
        order = {s: n for n, s in enumerate(SEVERITIES)}
        self.issues.sort(key=lambda i: order.get(i.severity, len(order)))


def _clamp(value: int, low: int = 1, high: int = 10) -> int:
    return max(low, min(high, int(value)))
