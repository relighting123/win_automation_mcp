import asyncio
import sys
import unittest
from inspect import Parameter
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from mcp.server.fastmcp import FastMCP

from tools.skill_tool import (
    _make_skill_func,
    extract_skill_ai_param_specs,
    register_skill_tools,
)


class ExtractSkillAiParamSpecsTest(unittest.TestCase):
    def test_fetch_url_info_requires_url(self) -> None:
        steps = [
            {
                "tool": "fetch_url_content",
                "args": {"url": {"mode": "ai"}},
            }
        ]
        specs = extract_skill_ai_param_specs(steps)
        self.assertEqual(list(specs.keys()), ["url"])
        self.assertTrue(specs["url"]["required"])

    def test_optional_ai_param_uses_default(self) -> None:
        steps = [
            {
                "tool": "query_oracle_db",
                "args": {
                    "sql": {"mode": "ai"},
                    "max_rows": {"mode": "ai", "value": 100},
                },
            }
        ]
        specs = extract_skill_ai_param_specs(steps)
        self.assertTrue(specs["sql"]["required"])
        self.assertFalse(specs["max_rows"]["required"])
        self.assertEqual(specs["max_rows"]["default"], 100)


class SkillToolSchemaTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_url_info_schema_uses_url_not_kwargs(self) -> None:
        mcp = FastMCP("test")
        tool_func = _make_skill_func(
            "fetch_url_info",
            "fetch url",
            {"url": {"required": True, "default": Parameter.empty}},
            "config/skills.yaml",
        )
        mcp.tool()(tool_func)

        tools = await mcp.list_tools()
        schema = tools[0].inputSchema
        self.assertIn("url", schema["properties"])
        self.assertIn("url", schema["required"])
        self.assertNotIn("kwargs", schema["properties"])

    async def test_register_fetch_url_info_skill_from_yaml(self) -> None:
        mcp = FastMCP("test")
        register_skill_tools(mcp)

        tools = await mcp.list_tools()
        fetch_tool = next((t for t in tools if t.name == "fetch_url_info"), None)
        self.assertIsNotNone(fetch_tool)
        assert fetch_tool is not None
        schema = fetch_tool.inputSchema
        self.assertIn("url", schema["properties"])
        self.assertIn("url", schema["required"])
        self.assertNotIn("kwargs", schema["properties"])


if __name__ == "__main__":
    unittest.main()
