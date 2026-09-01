"""Shared model gateway retry behavior."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agents.runtime import model_gateway


class ModelGatewayTests(unittest.TestCase):
    def test_rate_limit_retries_then_returns_response(self):
        response = SimpleNamespace(choices=[])
        create = Mock(side_effect=[Exception("429 Too Many Requests"), response])
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))

        with patch.object(model_gateway.openai_client, "get_client",
                          return_value=client), \
                patch.object(model_gateway.config,
                             "OPENAI_GATEWAY_MAX_ATTEMPTS", 2), \
                patch.object(model_gateway.config,
                             "OPENAI_GATEWAY_BASE_BACKOFF_SECONDS", 0), \
                patch.object(model_gateway.time, "sleep") as sleep:
            result = model_gateway.chat_completion(model="m", messages=[])

        self.assertIs(response, result)
        self.assertEqual(2, create.call_count)
        sleep.assert_called_once()

    def test_non_retriable_error_raises_typed_gateway_error(self):
        create = Mock(side_effect=ValueError("bad request"))
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))

        with patch.object(model_gateway.openai_client, "get_client",
                          return_value=client):
            with self.assertRaises(model_gateway.ModelGatewayError) as raised:
                model_gateway.chat_completion(model="m", messages=[])

        self.assertEqual("model_error", raised.exception.kind)
        self.assertEqual(1, create.call_count)


if __name__ == "__main__":
    unittest.main()
