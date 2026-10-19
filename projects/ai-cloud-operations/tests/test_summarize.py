from __future__ import annotations

import unittest
from datetime import timedelta

from helpers import EPOCH, alert, deploy

from aiops.correlation import correlate
from aiops.llm import NoOpLLMProvider
from aiops.models import Anomaly
from aiops.summarize import SummaryConfig, summarize, template_summary


def _correlation(with_deploy=False, with_alert=False):
    a = Anomaly(
        service="checkout-api", metric="error_rate", window_start=EPOCH,
        window_end=EPOCH + timedelta(minutes=5), observed_value=0.4, baseline_mean=0.02,
        baseline_stddev=0.01, z_score=38.0, sample_size=50,
    )
    deploys = [deploy("checkout-api", EPOCH - timedelta(minutes=3))] if with_deploy else []
    alerts = [alert("checkout-api", a.window_end + timedelta(minutes=1))] if with_alert else []
    return correlate([a], deploys, alerts)[0]


class TemplateSummaryTests(unittest.TestCase):
    def test_mentions_service_and_zscore(self):
        text = template_summary(_correlation())
        self.assertIn("checkout-api", text)
        self.assertIn("z=38.00", text)

    def test_mentions_deploy_when_correlated(self):
        text = template_summary(_correlation(with_deploy=True))
        self.assertIn("Correlated with deploy", text)

    def test_mentions_no_correlation_when_none(self):
        text = template_summary(_correlation())
        self.assertIn("No deploy or alert correlated", text)


class SummarizeTests(unittest.TestCase):
    def test_default_config_never_uses_llm(self):
        result = summarize(_correlation(), raw_log_excerpt="anything")
        self.assertEqual(result.source, "template")
        self.assertFalse(result.redacted_input)

    def test_noop_provider_falls_back_to_template_but_marks_redacted(self):
        config = SummaryConfig(use_llm=True, provider=NoOpLLMProvider())
        result = summarize(_correlation(), raw_log_excerpt="user alice@example.com failed", config=config)
        self.assertEqual(result.source, "template")
        self.assertTrue(result.redacted_input)

    def test_custom_provider_output_is_used(self):
        class FakeProvider:
            name = "fake"

            def summarize(self, prompt, max_tokens):
                self.last_prompt = prompt
                return "a concise incident summary"

        provider = FakeProvider()
        config = SummaryConfig(use_llm=True, provider=provider)
        result = summarize(_correlation(), raw_log_excerpt="irrelevant", config=config)
        self.assertEqual(result.text, "a concise incident summary")
        self.assertEqual(result.source, "llm:fake")

    def test_llm_prompt_never_contains_raw_secret(self):
        captured = {}

        class CapturingProvider:
            name = "capture"

            def summarize(self, prompt, max_tokens):
                captured["prompt"] = prompt
                return "ok"

        config = SummaryConfig(use_llm=True, provider=CapturingProvider())
        summarize(_correlation(), raw_log_excerpt="token=supersecretvalue123 from alice@example.com",
                  config=config)
        self.assertNotIn("supersecretvalue123", captured["prompt"])
        self.assertNotIn("alice@example.com", captured["prompt"])

    def test_prompt_char_budget_truncates_excerpt(self):
        captured = {}

        class CapturingProvider:
            name = "capture"

            def summarize(self, prompt, max_tokens):
                captured["prompt"] = prompt
                return "ok"

        config = SummaryConfig(use_llm=True, provider=CapturingProvider(), prompt_char_budget=120)
        long_excerpt = "x" * 5000
        summarize(_correlation(), raw_log_excerpt=long_excerpt, config=config)
        self.assertLess(len(captured["prompt"]), 400)


if __name__ == "__main__":
    unittest.main()
