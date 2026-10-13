import json
import unittest
from types import SimpleNamespace

from doc_critic import CriticConfig, CritiqueError, Document, DocumentCritic
from doc_critic.agent import quote_in_document
from doc_critic.report import to_json, to_markdown

DOC = Document(
    name="plan.md",
    text="# План\n\nМы  запустим продукт в «третьем» квартале.\nБюджет — 10 млн рублей.\n",
)


def issue(quote, severity="major"):
    return {
        "severity": severity,
        "category": "Логика",
        "quote": quote,
        "problem": "проблема",
        "suggestion": "исправление",
    }


def critique(*issues):
    return {
        "summary": "Кратко.",
        "overall_score": 6,
        "verdict": "minor_revisions",
        "scores": [{"criterion": "Ясность", "score": 7, "comment": "ok | норм"}],
        "strengths": ["Коротко"],
        "issues": list(issues),
        "top_priorities": ["Уточнить сроки"],
    }


class FakeClient:
    """Возвращает заранее заданные JSON-ответы и запоминает запросы."""

    def __init__(self, *payloads, stop_reason="end_turn"):
        self.payloads = list(payloads)
        self.calls = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.calls.append(params)
        payload = self.payloads.pop(0)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            stop_details=SimpleNamespace(category="cyber"),
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False)),
            ],
        )


class QuoteTests(unittest.TestCase):
    def test_normalizes_whitespace_quotes_and_dashes(self):
        self.assertTrue(quote_in_document('Мы запустим продукт в "третьем" квартале', DOC.text))
        self.assertTrue(quote_in_document("Бюджет - 10 млн", DOC.text))

    def test_rejects_missing_or_empty_quote(self):
        self.assertFalse(quote_in_document("четвёртом квартале", DOC.text))
        self.assertFalse(quote_in_document("  ", DOC.text))


class CriticTests(unittest.TestCase):
    def test_happy_path_with_verification(self):
        client = FakeClient(
            critique(issue("Бюджет — 10 млн рублей", "minor"), issue("# План", "critical")),
            {"reviews": [
                {"index": 0, "decision": "revise", "severity": "major",
                 "reason": "важно", "suggestion": "Расписать бюджет"},
                {"index": 1, "decision": "drop", "severity": "critical",
                 "reason": "придирка", "suggestion": ""},
            ]},
        )
        result = DocumentCritic(client).critique(DOC)

        self.assertEqual(len(client.calls), 2)
        first = client.calls[0]
        self.assertEqual(first["model"], "claude-opus-5-5")
        self.assertEqual(first["fallbacks"], "default")
        self.assertEqual(first["output_config"]["format"]["type"], "json_schema")
        self.assertEqual([i.severity for i in result.issues], ["major"])
        self.assertEqual(result.issues[0].suggestion, "Расписать бюджет")
        self.assertEqual(len(result.dropped), 1)

    def test_regrounds_hallucinated_quote(self):
        client = FakeClient(
            critique(issue("выдуманная цитата")),
            critique(issue("в «третьем» квартале")),
        )
        result = DocumentCritic(client, CriticConfig(verify=False)).critique(DOC)

        self.assertEqual(len(client.calls), 2)
        followup = client.calls[1]["messages"]
        self.assertEqual([m["role"] for m in followup], ["user", "assistant", "user"])
        self.assertIn("выдуманная цитата", followup[-1]["content"])
        self.assertEqual(len(result.issues), 1)
        self.assertTrue(result.issues[0].grounded)

    def test_drops_quote_that_stays_ungrounded(self):
        client = FakeClient(critique(issue("нет такого")), critique(issue("и такого нет")))
        result = DocumentCritic(client, CriticConfig(verify=False)).critique(DOC)
        self.assertEqual(result.issues, [])
        self.assertEqual(result.dropped[0].verifier_note, "цитата не найдена в документе")

    def test_pdf_skips_local_grounding(self):
        pdf = Document(name="a.pdf", pdf_base64="AAAA")
        client = FakeClient(critique(issue("что угодно")))
        result = DocumentCritic(client, CriticConfig(verify=False)).critique(pdf)
        self.assertEqual(len(client.calls), 1)
        self.assertIsNone(result.issues[0].grounded)
        block = client.calls[0]["messages"][0]["content"][0]
        self.assertEqual(block["type"], "document")

    def test_refusal_raises(self):
        client = FakeClient(critique(), stop_reason="refusal")
        with self.assertRaises(CritiqueError):
            DocumentCritic(client).critique(DOC)

    def test_no_fallbacks_option(self):
        client = FakeClient(critique())
        DocumentCritic(client, CriticConfig(use_fallbacks=False)).critique(DOC)
        self.assertNotIn("fallbacks", client.calls[0])
        self.assertNotIn("betas", client.calls[0])


class ReportTests(unittest.TestCase):
    def test_markdown_and_json(self):
        client = FakeClient(critique(issue("Бюджет — 10 млн рублей")))
        result = DocumentCritic(client, CriticConfig(verify=False)).critique(DOC)
        md = to_markdown(result, "plan.md")
        self.assertIn("# Рецензия: plan.md", md)
        self.assertIn("ok \\| норм", md)
        self.assertIn("> Бюджет — 10 млн рублей", md)
        self.assertEqual(json.loads(to_json(result))["overall_score"], 6)


if __name__ == "__main__":
    unittest.main()
