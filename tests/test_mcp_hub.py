import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.browser_fetch import snapshot_to_text
from core.mcp_hub import MultiMCPClient, _openai_tool_name, _split_tool_name
from core.mcp_server_config import MCPServerConfig, load_mcp_servers


class MCPServerConfigTest(unittest.TestCase):
    def test_load_mcp_servers_includes_primary_http(self) -> None:
        servers = load_mcp_servers(base_url_override="http://localhost:9000/mcp")
        self.assertEqual(servers[0].id, "automation")
        self.assertEqual(servers[0].url, "http://localhost:9000/mcp")

    def test_openchrome_env_server(self) -> None:
        with patch.dict(
            "os.environ",
            {"MCP_OPENCHROME_ENABLED": "true"},
            clear=False,
        ):
            servers = load_mcp_servers(base_url_override="http://localhost:8000/mcp")
        ids = [server.id for server in servers]
        self.assertIn("openchrome", ids)


class SnapshotTextTest(unittest.TestCase):
    def test_snapshot_to_text_extracts_names(self) -> None:
        snapshot = """
- role: heading
  name: Welcome
- role: button
  name: Login
"""
        text = snapshot_to_text(snapshot)
        self.assertIn("Welcome", text)
        self.assertIn("Login", text)


class MultiMCPClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_routes_prefixed_tool_to_backend(self) -> None:
        automation = MagicMock()
        automation.list_tools = AsyncMock(
            return_value=[{"name": "describe_current_state", "description": "state", "inputSchema": {}}]
        )
        automation.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})

        browser = MagicMock()
        browser.list_tools = AsyncMock(
            return_value=[{"name": "navigate", "description": "go", "inputSchema": {}}]
        )
        browser.call_tool = AsyncMock(
            return_value={"content": [{"type": "text", "text": "navigated"}], "isError": False}
        )

        hub = MultiMCPClient(
            [
                MCPServerConfig(id="automation", transport="http", url="http://localhost:8000/mcp", tool_prefix=False),
                MCPServerConfig(id="openchrome", transport="stdio", command="npx", args=[], tool_prefix=True),
            ]
        )
        hub._backends = {"automation": automation, "openchrome": browser}

        tools = await hub.list_tools()
        names = [tool["name"] for tool in tools]
        self.assertIn("describe_current_state", names)
        self.assertIn("openchrome/navigate", names)

        result = await hub.call_tool("openchrome/navigate", {"url": "https://example.com"})
        browser.call_tool.assert_awaited_once_with("navigate", {"url": "https://example.com"})
        self.assertIn("content", result)

    async def test_has_tool_for_prefixed_name_before_list_tools(self) -> None:
        hub = MultiMCPClient(
            [MCPServerConfig(id="openchrome", transport="stdio", command="npx", args=[])]
        )
        self.assertTrue(hub.has_tool("openchrome/navigate"))

    def test_name_helpers(self) -> None:
        self.assertEqual(
            _openai_tool_name("openchrome", "navigate", use_prefix=True),
            "openchrome/navigate",
        )
        self.assertEqual(_openai_tool_name("automation", "describe_current_state", use_prefix=False), "describe_current_state")
        self.assertEqual(_split_tool_name("openchrome/read_page"), ("openchrome", "read_page"))


if __name__ == "__main__":
    unittest.main()
