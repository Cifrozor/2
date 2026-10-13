"""Командная строка: doc-critic путь/к/документу.md"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import DEFAULT_MODEL, CriticConfig, CritiqueError, Document, DocumentCritic
from .report import to_json, to_markdown


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doc-critic",
        description="Агент-критик: рецензирует документ (.md, .txt, .pdf и др.) с помощью Claude.",
    )
    p.add_argument("document", help="путь к документу")
    p.add_argument("-o", "--output", help="куда сохранить отчёт (по умолчанию — stdout)")
    p.add_argument("--format", choices=("md", "json"), default="md", help="формат отчёта")
    p.add_argument("--purpose", help="назначение документа, например «техзадание для подрядчика»")
    p.add_argument("--audience", help="целевая аудитория")
    p.add_argument("--focus", help="на что обратить особое внимание")
    p.add_argument("--criteria", nargs="+", metavar="КРИТЕРИЙ",
                   help="свой список критериев вместо стандартного")
    p.add_argument("--language", default="русский", help="язык рецензии")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--effort", default="high",
                   choices=("low", "medium", "high", "xhigh", "max"))
    p.add_argument("--max-tokens", type=int, default=16000)
    p.add_argument("--no-verify", action="store_true",
                   help="пропустить проверку замечаний вторым рецензентом")
    p.add_argument("--no-fallbacks", action="store_true",
                   help="не включать серверный fallback на другую модель при отказе")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    import anthropic  # импорт здесь, чтобы --help работал без установленного SDK

    config = CriticConfig(
        model=args.model,
        effort=args.effort,
        max_tokens=args.max_tokens,
        language=args.language,
        purpose=args.purpose,
        audience=args.audience,
        focus=args.focus,
        verify=not args.no_verify,
        use_fallbacks=not args.no_fallbacks,
    )
    if args.criteria:
        config.criteria = args.criteria

    def log(msg: str) -> None:
        print(f"· {msg}", file=sys.stderr)

    try:
        document = Document.load(args.document)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Не удалось прочитать документ: {exc}", file=sys.stderr)
        return 2

    critic = DocumentCritic(anthropic.Anthropic(timeout=900), config, log=log)
    try:
        critique = critic.critique(document)
    except CritiqueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except anthropic.AuthenticationError:
        print("Ошибка авторизации: задайте ANTHROPIC_API_KEY.", file=sys.stderr)
        return 1
    except anthropic.RateLimitError:
        print("Превышен лимит запросов, попробуйте позже.", file=sys.stderr)
        return 1
    except anthropic.APIStatusError as exc:
        print(f"Ошибка API ({exc.status_code}): {exc.message}", file=sys.stderr)
        return 1
    except anthropic.APIConnectionError:
        print("Нет соединения с API Anthropic.", file=sys.stderr)
        return 1

    report = to_json(critique) if args.format == "json" else to_markdown(critique, document.name)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        log(f"Отчёт сохранён в {args.output}")
    else:
        print(report)
    return 0
