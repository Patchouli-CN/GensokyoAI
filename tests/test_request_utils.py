import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from GensokyoAI.utils.request_utils import (
    ModelAPIError,
    is_html_response,
    normalize_openai_api_host_and_path,
    normalize_openai_responses_host_and_path,
    normalize_search_url,
    post_sse,
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
        endpoint = normalize_openai_api_host_and_path("https://api.openai.com/v1/chat/completions")
        self.assertEqual(endpoint.api_host, "https://api.openai.com/v1")
        self.assertEqual(endpoint.api_path, "/chat/completions")

    def test_normalize_openrouter(self):
        for host in ("openrouter.ai", "openrouter.ai/api", "https://openrouter.ai/api/v1"):
            with self.subTest(host=host):
                endpoint = normalize_openai_api_host_and_path(host)
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

    def test_post_sse_reports_invalid_json_with_event_diagnostics(self):
        mock_readline = AsyncMock()
        mock_readline.side_effect = [
            b": keepalive\n",
            b"event: message\n",
            b"data: {bad json}\n",
            b"\n",
            b"",
        ]

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.content.readline = mock_readline
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "GensokyoAI.utils.request_utils.aiohttp.ClientSession", return_value=mock_session
        ):

            async def collect():
                async for _ in post_sse("https://api.example.test/sse", {}, {}, 1):
                    pass

            with self.assertRaises(ModelAPIError) as cm:
                asyncio.run(collect())

        self.assertIn("SSE JSON 解析失败", str(cm.exception))
        self.assertIn("event_index=1", str(cm.exception))
        self.assertIn("ignored_lines=1", str(cm.exception))
        self.assertEqual(cm.exception.response_body, "{bad json}")

    def test_normalize_search_url_dedup_utm_and_trailing_slash(self):
        self.assertEqual(
            normalize_search_url("https://example.test/a?utm_source=x"),
            "https://example.test/a",
        )
        self.assertEqual(
            normalize_search_url("https://example.test/path/"),
            "https://example.test/path",
        )
        self.assertEqual(
            normalize_search_url("https://example.test/a?b=1&utm_source=x"),
            "https://example.test/a?b=1",
        )

    def test_normalize_search_url_handles_html_escaped_chars(self):
        self.assertEqual(
            normalize_search_url("https://example.test/a&amp;b"),
            "https://example.test/a&b",
        )


if __name__ == "__main__":
    unittest.main()
