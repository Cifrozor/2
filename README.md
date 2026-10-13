# doc-critic — агент-критик документов

Агент на Claude, который читает документ и пишет рецензию: оценки по критериям,
сильные стороны, конкретные замечания с цитатами и готовыми исправлениями,
список главных правок и итоговый вердикт.

## Как работает

1. **Критик** (Claude Opus 5.5, adaptive thinking, effort `high`) читает документ и
   возвращает рецензию строго по JSON-схеме (structured outputs).
2. **Проверка цитат.** Каждое замечание обязано опираться на дословную цитату.
   Агент сверяет цитаты с текстом; если какая-то не найдена — возвращает критику
   обратную связь и просит исправить. Замечания, которые так и не удалось
   привязать к тексту, отбрасываются (для PDF этот шаг пропускается).
3. **Второй рецензент** проверяет каждое замечание: оставить, поправить важность
   и предложение или отклонить как ложное/придирчивое.
4. Отчёт в Markdown (или JSON); отклонённые замечания видны в свёрнутом блоке.

При отказе классификатора безопасности включён серверный fallback
(`fallbacks: "default"`); отключается флагом `--no-fallbacks`.

## Установка

```bash
pip install -e .
export ANTHROPIC_API_KEY=...   # или `ant auth login`
```

## Использование

```bash
doc-critic examples/sample.md
doc-critic report.pdf -o review.md \
  --purpose "обоснование бюджета для руководства" \
  --audience "финансовый директор" \
  --focus "цифры и риски"
doc-critic spec.md --format json --criteria "Полнота требований" "Проверяемость" "Однозначность"
doc-critic essay.md --language English --no-verify --effort medium
```

Поддерживаются текстовые форматы (`.md`, `.txt`, `.rst`, …) и `.pdf`.

## Использование из кода

```python
import anthropic
from doc_critic import CriticConfig, Document, DocumentCritic
from doc_critic.report import to_markdown

critic = DocumentCritic(anthropic.Anthropic(), CriticConfig(audience="инвесторы"))
critique = critic.critique(Document.load("pitch.md"))
print(to_markdown(critique, "pitch.md"))
```

## Тесты

Тесты не ходят в сеть — используют фейковый клиент:

```bash
python -m unittest -v
```
