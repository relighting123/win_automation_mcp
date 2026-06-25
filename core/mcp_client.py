"""
MCP 클라이언트 팩토리 및 하위 호환 래퍼.
"""

from __future__ import annotations

from typing import Optional

from core.mcp_hub import (
    HttpMCPBackend,
    MultiMCPClient,
    create_extra_mcp_client,
    create_mcp_client,
    get_shared_extra_mcp_hub,
    reset_shared_extra_mcp_hub,
)
from core.mcp_server_config import load_mcp_servers


class MCPClient(MultiMCPClient):
    """하위 호환 래퍼. base_url 하나만 넘기던 기존 코드를 지원합니다."""

    def __init__(self, base_url: Optional[str] = None):
        from core.llm_config import DEFAULT_MCP_BASE_URL

        super().__init__(load_mcp_servers(base_url_override=base_url or DEFAULT_MCP_BASE_URL))


async def example_usage():
    client = create_mcp_client()
    result = await client.call_tool("get_connection_status", {})
    print(result)
    await client.aclose()


__all__ = [
    "HttpMCPBackend",
    "MCPClient",
    "MultiMCPClient",
    "create_extra_mcp_client",
    "create_mcp_client",
    "get_shared_extra_mcp_hub",
    "reset_shared_extra_mcp_hub",
    "example_usage",
]
