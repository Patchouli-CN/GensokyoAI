import unittest

from GensokyoAI.core.agent.providers.request_utils import (
    is_html_response,
    normalize_openai_api_host_and_path,
    normalize_openai_responses_host_and_path,
    sanitize_response_body,
)


class RequestUtilsTests(unittest.TestCase):
    def test_sanitize_html_gateway_error(self):
        body = "<!doctype html><html><body>bad gateway</body></html>"
        self.assertTrue(is_html_response(body))
        self.assertEqual(
            sanitize_response_body(502, body),
            "Bad Gateway - 服务端返回了 HTML 错误页，而不是有效的 API 响应。",
        )

    def test_normalize_openai_defaults(self):
        endpoint = normalize_openai_api_host_and_path(None)
        self.assertEqual(endpoint.api_host, "https://api.openai.com/v1")
        self.assertEqual(endpoint.api_path, "/chat/completions")

    def test_normalize_openai_full_endpoint(self):
        endpoint = normalize_openai_api_host_and_path(
            "https://api.openai.com/v1/chat/completions"
        )
        self.assertEqual(endpoint.api_host, "https://api.openai.com/v1")
        self.assertEqual(endpoint.api_path, "/chat/completions")

    def test_normalize_openrouter(self):
        endpoint = normalize_openai_api_host_and_path("openrouter.ai/api")
        self.assertEqual(endpoint.api_host, "https://openrouter.ai/api/v1")
        self.assertEqual(endpoint.api_path, "/chat/completions")

    def test_normalize_custom_api_path(self):
        endpoint = normalize_openai_api_host_and_path("proxy.example.com", "custom/path")
        self.assertEqual(endpoint.api_host, "https://proxy.example.com")
        self.assertEqual(endpoint.api_path, "/custom/path")

    def test_normalize_responses(self):
        endpoint = normalize_openai_responses_host_and_path("https://api.openai.com")
        self.assertEqual(endpoint.api_host, "https://api.openai.com/v1")
        self.assertEqual(endpoint.api_path, "/responses")


if __name__ == "__main__":
    unittest.main()
