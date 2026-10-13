"""Рендеринг рецензии в Markdown и JSON."""

from __future__ import annotations

import json
from dataclasses import asdict

from .schema import Critique

VERDICT_LABELS = {
    "ready": "✅ Готов к публикации",
    "minor_revisions": "🟡 Нужны небольшие правки",
    "major_revisions": "🟠 Нужна серьёзная доработка",
    "rewrite": "🔴 Нужно переписать",
}
SEVERITY_LABELS = {
    "critical": "🔴 Критично",
    "major": "🟠 Существенно",
    "minor": "🟢 Мелочь",
}


def to_markdown(critique: Critique, title: str) -> str:
    out = [f"# Рецензия: {title}", ""]
    out += [
        f"**Вердикт:** {VERDICT_LABELS.get(critique.verdict, critique.verdict)}  ",
        f"**Общая оценка:** {critique.overall_score}/10",
        "",
        critique.summary,
        "",
    ]

    if critique.top_priorities:
        out += ["## Главное, что стоит исправить", ""]
        out += [f"{n}. {p}" for n, p in enumerate(critique.top_priorities, 1)]
        out.append("")

    if critique.scores:
        out += ["## Оценки по критериям", "", "| Критерий | Оценка | Комментарий |", "|---|---|---|"]
        for s in critique.scores:
            comment = s.comment.replace("|", "\\|").replace("\n", " ")
            out.append(f"| {s.criterion} | {s.score}/10 | {comment} |")
        out.append("")

    if critique.strengths:
        out += ["## Сильные стороны", ""]
        out += [f"- {s}" for s in critique.strengths]
        out.append("")

    out += [f"## Замечания ({len(critique.issues)})", ""]
    if not critique.issues:
        out += ["Существенных замечаний нет.", ""]
    for n, issue in enumerate(critique.issues, 1):
        label = SEVERITY_LABELS.get(issue.severity, issue.severity)
        out += [
            f"### {n}. {label} · {issue.category}",
            "",
            f"> {issue.quote}",
            "",
            f"**Проблема.** {issue.problem}",
            "",
            f"**Как исправить.** {issue.suggestion}",
            "",
        ]

    if critique.dropped:
        out += [
            "<details><summary>Отклонённые при проверке замечания "
            f"({len(critique.dropped)})</summary>",
            "",
        ]
        out += [f"- «{i.quote}» — {i.problem} _(причина: {i.verifier_note})_" for i in critique.dropped]
        out += ["", "</details>", ""]

    return "\n".join(out)


def to_json(critique: Critique) -> str:
    return json.dumps(asdict(critique), ensure_ascii=False, indent=2)
