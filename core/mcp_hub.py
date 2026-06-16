"""
여러 MCP 서버를 통합하는 허브 클라이언트.

- automation MCP: HTTP(streamable-http)
- chrome-devtools MCP: stdio(npx) 또는 HTTP(mcp-proxy)
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from core.mcp_server_config import MCPServerConfig, load_extra_mcp_servers, load_mcp_servers

logger = logging.getLogger(__name__)

_SHARED_EXTRA_HUB: Optional["MultiMCPClient"] = None


def _openai_tool_name(server_id: str, tool_name: str, *, use_prefix: bool) -> str:
    if use_prefix and server_id != "automation":
        return f"{server_id}/{tool_name}"
    return tool_name


def _split_tool_name(tool_name: str) -> Tuple[Optional[str], str]:
    if "/" in tool_name:
        server_id, actual = tool_name.split("/", 1)
        if server_id and actual:
            return server_id, actual
    return None, tool_name


@dataclass
class _ToolRoute:
    server_id: str
    tool_name: str
    exposed_name: str


class HttpMCPBackend:
    """HTTP streamable-http MCP 백엔드."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.base_url = str(config.url)
        self._session_id: Optional[str] = None
        self._request_id = 0
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._session_id = None

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _build_headers(self, *, include_session: bool = False) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if include_session and self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    async def _ensure_session(self, client: httpx.AsyncClient) -> None:
        if self._session_id:
            return

        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "chatRTD-mcp-hub", "version": "1.0.0"},
            },
        }
        init_res = await client.post(
            self.base_url,
            json=init_payload,
            headers=self._build_headers(),
            timeout=15.0,
        )
        if init_res.status_code != 200:
            raise RuntimeError(
                f"[{self.config.id}] initialize 실패({init_res.status_code}): {init_res.text}"
            )

        session_id = init_res.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError(f"[{self.config.id}] mcp-session-id 헤더가 없습니다.")
        self._session_id = session_id

        notify_res = await client.post(
            self.base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=self._build_headers(include_session=True),
            timeout=10.0,
        )
        if notify_res.status_code >= 400:
            raise RuntimeError(
                f"[{self.config.id}] notifications/initialized 실패({notify_res.status_code})"
            )

    async def _post_jsonrpc(
        self,
        client: httpx.AsyncClient,
        *,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        await self._ensure_session(client)

        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        parsed: Optional[Dict[str, Any]] = None
        async with client.stream(
            "POST",
            self.base_url,
            json=payload,
            headers=self._build_headers(include_session=True),
            timeout=120.0,
        ) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="ignore")
                raise RuntimeError(
                    f"[{self.config.id}] {method} 실패({response.status_code}): {body}"
                )

            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    parsed = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

        if not parsed:
            raise RuntimeError(f"[{self.config.id}] {method} 응답 파싱 실패")
        if "error" in parsed:
            raise RuntimeError(f"[{self.config.id}] MCP error: {parsed['error']}")
        result = parsed.get("result", {})
        return result if isinstance(result, dict) else {"result": result}

    async def list_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        if self._tools_cache is not None and not refresh:
            return self._tools_cache

        client = await self._get_client()
        try:
            result = await self._post_jsonrpc(client, method="tools/list")
        except Exception:
            self._session_id = None
            result = await self._post_jsonrpc(client, method="tools/list")

        tools = result.get("tools", [])
        self._tools_cache = tools if isinstance(tools, list) else []
        return self._tools_cache

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        client = await self._get_client()
        try:
            return await self._post_jsonrpc(
                client,
                method="tools/call",
                params={"name": tool_name, "arguments": arguments},
            )
        except Exception:
            self._session_id = None
            return await self._post_jsonrpc(
                client,
                method="tools/call",
                params={"name": tool_name, "arguments": arguments},
            )


class StdioMCPBackend:
    """stdio MCP 백엔드 (chrome-devtools-mcp 등)."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._stack = AsyncExitStack()
        self._session = None
        self._start_lock = asyncio.Lock()
        self._tools_cache: Optional[List[Dict[str, Any]]] = None

    async def ensure_started(self) -> None:
        async with self._start_lock:
            if self._session is not None:
                return

            try:
                from mcp import ClientSession
                from mcp.client.stdio import StdioServerParameters, stdio_client
            except ImportError as exc:
                raise RuntimeError(
                    f"[{self.config.id}] mcp 패키지가 필요합니다: pip install mcp"
                ) from exc

            if not self.config.command:
                raise RuntimeError(f"[{self.config.id}] stdio transport에는 command가 필요합니다.")

            server_params = StdioServerParameters(
                command=self.config.command,
                args=list(self.config.args),
                env=self.config.env or None,
            )
            read, write = await self._stack.enter_async_context(stdio_client(server_params))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
            logger.info("[%s] stdio MCP 세션 시작", self.config.id)

    async def aclose(self) -> None:
        try:
            await self._stack.aclose()
        except RuntimeError as exc:
            logger.debug("[%s] stdio MCP 종료(RuntimeError): %s", self.config.id, exc)
        except Exception as exc:
            logger.debug("[%s] stdio MCP 종료 오류: %s", self.config.id, exc)
        finally:
            self._session = None
            self._tools_cache = None
            self._stack = AsyncExitStack()

    async def list_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        if self._tools_cache is not None and not refresh:
            return self._tools_cache

        await self.ensure_started()
        result = await self._session.list_tools()
        tools: List[Dict[str, Any]] = []
        for tool in result.tools:
            if hasattr(tool, "model_dump"):
                tools.append(tool.model_dump())
            else:
                tools.append(dict(tool))
        self._tools_cache = tools
        return tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        await self.ensure_started()
        result = await self._session.call_tool(
            tool_name,
            arguments,
            read_timeout_seconds=None,
        )
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return dict(result)


class MultiMCPClient:
    """여러 MCP 서버를 하나의 클라이언트처럼 사용합니다."""

    def __init__(self, servers: List[MCPServerConfig]):
        self.servers = servers
        self._backends: Dict[str, Any] = {}
        self._routes: Dict[str, List[_ToolRoute]] = {}
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._openai_tools_cache: Optional[List[Dict[str, Any]]] = None

        for server in servers:
            if server.transport == "http":
                self._backends[server.id] = HttpMCPBackend(server)
            elif server.transport == "stdio":
                self._backends[server.id] = StdioMCPBackend(server)
            else:
                raise ValueError(f"지원하지 않는 MCP transport: {server.transport}")

    @property
    def base_url(self) -> str:
        for server in self.servers:
            if server.transport == "http" and server.url:
                return server.url
        return ""

    async def aclose(self) -> None:
        for backend in self._backends.values():
            await backend.aclose()

    def has_tool(self, tool_name: str) -> bool:
        if tool_name in self._routes:
            return True
        server_id, _actual = _split_tool_name(tool_name)
        if server_id and server_id in self._backends:
            return True
        return False

    def _resolve_route(self, tool_name: str) -> _ToolRoute:
        if tool_name in self._routes:
            routes = self._routes[tool_name]
            if len(routes) == 1:
                return routes[0]
            server_id, actual = _split_tool_name(tool_name)
            if server_id:
                for route in routes:
                    if route.server_id == server_id and route.tool_name == actual:
                        return route
            raise RuntimeError(
                f"도구 이름이 여러 서버에 중복됩니다: {tool_name}. "
                f"'서버id/도구이름' 형식으로 호출하세요."
            )

        server_id, actual = _split_tool_name(tool_name)
        if server_id:
            if server_id not in self._backends:
                raise RuntimeError(f"알 수 없는 MCP 서버: {server_id}")
            return _ToolRoute(server_id=server_id, tool_name=actual, exposed_name=tool_name)

        raise RuntimeError(f"알 수 없는 MCP 도구: {tool_name}")

    async def _rebuild_routes(self, refresh: bool = False) -> None:
        routes: Dict[str, List[_ToolRoute]] = {}
        merged_tools: List[Dict[str, Any]] = []

        for server in self.servers:
            backend = self._backends[server.id]
            try:
                tools = await backend.list_tools(refresh=refresh)
            except Exception as exc:
                logger.warning("[%s] tools/list 실패: %s", server.id, exc)
                continue

            for tool in tools:
                raw_name = str(tool.get("name") or "").strip()
                if not raw_name:
                    continue
                exposed_name = _openai_tool_name(
                    server.id,
                    raw_name,
                    use_prefix=server.tool_prefix,
                )
                route = _ToolRoute(
                    server_id=server.id,
                    tool_name=raw_name,
                    exposed_name=exposed_name,
                )
                routes.setdefault(exposed_name, []).append(route)
                merged_tools.append(
                    {
                        **tool,
                        "name": exposed_name,
                        "description": f"[{server.id}] {tool.get('description', '')}".strip(),
                    }
                )

        self._routes = routes
        self._tools_cache = merged_tools
        self._openai_tools_cache = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {}),
                },
            }
            for tool in merged_tools
        ]

    async def list_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        if self._tools_cache is not None and not refresh:
            return self._tools_cache
        await self._rebuild_routes(refresh=refresh)
        return self._tools_cache or []

    async def list_openai_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        if self._openai_tools_cache is not None and not refresh:
            return self._openai_tools_cache
        await self._rebuild_routes(refresh=refresh)
        return self._openai_tools_cache or []

    async def warmup(self) -> None:
        await self.list_tools()

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self._routes:
            await self._rebuild_routes()

        try:
            route = self._resolve_route(tool_name)
        except RuntimeError as exc:
            return {"error": str(exc)}

        backend = self._backends[route.server_id]
        try:
            return await backend.call_tool(route.tool_name, arguments)
        except Exception as exc:
            logger.exception(
                "[%s] call_tool 실패: %s",
                route.server_id,
                route.tool_name,
            )
            return {"error": str(exc)}


def create_mcp_client(
    config_path: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
) -> MultiMCPClient:
    servers = load_mcp_servers(config_path, base_url_override=base_url)
    return MultiMCPClient(servers)


def create_extra_mcp_client(config_path: Optional[str] = None) -> Optional[MultiMCPClient]:
    servers = load_extra_mcp_servers(config_path)
    if not servers:
        return None
    return MultiMCPClient(servers)


async def get_shared_extra_mcp_hub(config_path: Optional[str] = None) -> Optional[MultiMCPClient]:
    """MCP 서버 프로세스 내부에서 추가 MCP(stdio)를 호출할 때 사용합니다."""
    global _SHARED_EXTRA_HUB
    if _SHARED_EXTRA_HUB is None:
        _SHARED_EXTRA_HUB = create_extra_mcp_client(config_path)
    return _SHARED_EXTRA_HUB
