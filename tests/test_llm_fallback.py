import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage

from app.agents.base import invoke_with_fallback
from app.llm.models import create_fallback_model


class ModelFallbackTests(unittest.TestCase):
    @patch("app.llm.models.ChatOllama")
    def test_ollama_tools_do_not_receive_groq_only_options(self, chat_ollama):
        model = Mock()
        chat_ollama.return_value = model
        tools = [Mock()]

        create_fallback_model(tools)

        model.bind_tools.assert_called_once_with(tools)

    def test_primary_error_uses_fallback(self):
        primary = Mock()
        primary.invoke.side_effect = RuntimeError("primary failed")
        fallback = Mock()
        fallback.invoke.return_value = AIMessage(content="Fallback response")

        reply = invoke_with_fallback(primary, fallback, [{"role": "user", "content": "hello"}])

        self.assertEqual(reply.content, "Fallback response")

    def test_dual_failure_returns_graceful_message(self):
        primary = Mock()
        primary.invoke.side_effect = RuntimeError("primary failed")
        fallback = Mock()
        fallback.invoke.side_effect = RuntimeError("fallback failed")

        reply = invoke_with_fallback(primary, fallback, [])

        self.assertIn("both reasoning models", reply.content)


if __name__ == "__main__":
    unittest.main()
