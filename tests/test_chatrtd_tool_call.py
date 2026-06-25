import unittest

from core.tool_call_utils import parse_kv_args, parse_text_tool_calls


class ParseTextToolCallsTest(unittest.TestCase):
    def test_parse_tool_call_block(self) -> None:
        content = (
            "요청을 처리합니다.\n"
            '<tool_call>{"name": "query_oracle_db", "arguments": {"sql": "SELECT 1 FROM DUAL"}}</tool_call>'
        )
        calls = parse_text_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "query_oracle_db")
        self.assertEqual(calls[0].arguments["sql"], "SELECT 1 FROM DUAL")

    def test_parse_tool_call_with_string_arguments(self) -> None:
        content = (
            '<tool_call>{"name": "query_oracle_db", '
            '"arguments": "{\\"sql\\": \\"SELECT 1 FROM DUAL\\"}"}</tool_call>'
        )
        calls = parse_text_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].arguments["sql"], "SELECT 1 FROM DUAL")

    def test_parse_kv_args(self) -> None:
        self.assertEqual(
            parse_kv_args(["sql=SELECT 1", "db=prd"]),
            {"sql": "SELECT 1", "db": "prd"},
        )


if __name__ == "__main__":
    unittest.main()
