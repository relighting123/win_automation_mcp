import unittest

from core.tool_call_utils import parse_kv_args, parse_text_tool_calls


class ParseTextToolCallsTest(unittest.TestCase):
    def test_parse_tool_call_block(self) -> None:
        content = (
            "요청을 처리합니다.\n"
            '<tool_call>{"name": "fetch_url_info", "arguments": {"url": "https://example.com"}}</tool_call>'
        )
        calls = parse_text_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "fetch_url_info")
        self.assertEqual(calls[0].arguments["url"], "https://example.com")

    def test_parse_tool_call_with_string_arguments(self) -> None:
        content = (
            '<tool_call>{"name": "fetch_url_info", '
            '"arguments": "{\\"url\\": \\"https://example.com\\"}"}</tool_call>'
        )
        calls = parse_text_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].arguments["url"], "https://example.com")

    def test_parse_kv_args(self) -> None:
        self.assertEqual(
            parse_kv_args(["url=https://example.com", "wait_seconds=30"]),
            {"url": "https://example.com", "wait_seconds": "30"},
        )


if __name__ == "__main__":
    unittest.main()
