from __future__ import annotations

import unittest

from aiops.llm import LLMProvider, NoOpLLMProvider


class NoOpLLMProviderTests(unittest.TestCase):
    def test_summarize_returns_none(self):
        provider = NoOpLLMProvider()
        self.assertIsNone(provider.summarize("any prompt", 100))

    def test_has_a_name(self):
        self.assertEqual(NoOpLLMProvider().name, "noop")

    def test_satisfies_llm_provider_protocol(self):
        provider = NoOpLLMProvider()
        self.assertIsInstance(provider, LLMProvider)


if __name__ == "__main__":
    unittest.main()
