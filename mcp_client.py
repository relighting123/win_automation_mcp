import asyncio
import httpx
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

class MCPClient:
    """
    HTTP 기반 MCP 서버(단일/멀티 endpoint)와 통신하는 클라이언트
    """
    def __init__(
        self,
        base_url: str = "http://localhost:8000/mcp",
        base_urls: Optional[List[str]] = None,
        server_map: Optional[Dict[str, str]] = None,
    ):
        provided_urls = base_urls[:] if isinstance(base_urls, list) else []
        if base_url:
            provided_urls.insert(0, base_url)

        self.base_urls: List[str] = []
        for url in provided_urls:
            normalized = str(url).strip()
            if normalized and normalized not in self.base_urls:
                self.base_urls.append(normalized)
        if not self.base_urls:
            self.base_urls = ["http://localhost:8000/mcp"]

        self.base_url = self.base_urls[0]  # 기존 단일 서버 코드와의 호환용 기본값
        self.server_map: Dict[str, str] = {}
        if isinstance(server_map, dict):
            for alias, url in server_map.items():
                alias_text = str(alias).strip()
                url_text = str(url).strip()
                if alias_text and url_text:
                    self.server_map[alias_text] = url_text
                    if url_text not in self.base_urls:
                        self.base_urls.append(url_text)

        self._session_ids: Dict[str, Optional[str]] = {url: None for url in self.base_urls}
        self._request_id = 0
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._tool_route: Dict[str, str] = {}
        self._ambiguous_tool_route: Dict[str, List[str]] = {}

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _build_headers(self, session_id: Optional[str]) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if session_id:
            headers["mcp-session-id"] = session_id
        return headers

    async def _ensure_session(self, client: httpx.AsyncClient, base_url: str) -> None:
        """MCP streamable-http 세션을 초기화합니다."""
        current_session_id = self._session_ids.get(base_url)
        if current_session_id:
            return

        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "automation-graph-client", "version": "1.0.0"},
            },
        }
        init_res = await client.post(
            base_url,
            json=init_payload,
            headers=self._build_headers(None),
            timeout=15.0,
        )
        if init_res.status_code != 200:
            raise RuntimeError(
                f"initialize 실패({init_res.status_code}): {init_res.text}"
            )

        session_id = init_res.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("initialize 응답에 mcp-session-id 헤더가 없습니다.")
        self._session_ids[base_url] = session_id

        notify_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        notify_res = await client.post(
            base_url,
            json=notify_payload,
            headers=self._build_headers(session_id),
            timeout=10.0,
        )
        if notify_res.status_code >= 400:
            raise RuntimeError(
                f"notifications/initialized 실패({notify_res.status_code}): {notify_res.text}"
            )

    async def _post_jsonrpc(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """JSON-RPC 호출 후 result payload를 반환합니다."""
        await self._ensure_session(client, base_url)
        session_id = self._session_ids.get(base_url)
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
            base_url,
            json=payload,
            headers=self._build_headers(session_id),
            timeout=60.0,
        ) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="ignore")
                raise RuntimeError(
                    f"{method} 실패({response.status_code}): {body}"
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

            if parsed is None:
                raw_body = (await response.aread()).decode("utf-8", errors="ignore")
                for raw_line in raw_body.splitlines():
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
            raise RuntimeError("MCP 응답에서 JSON payload를 파싱하지 못했습니다.")
        if "error" in parsed:
            raise RuntimeError(f"MCP error: {parsed['error']}")
        result = parsed.get("result", {})
        if isinstance(result, dict):
            return result
        return {"result": result}

    async def _post_jsonrpc_with_retry(
        self,
        *,
        base_url: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            try:
                return await self._post_jsonrpc(
                    client,
                    base_url=base_url,
                    method=method,
                    params=params,
                )
            except Exception:
                # 세션 만료/서버 재기동 시 1회 재시도
                self._session_ids[base_url] = None
                return await self._post_jsonrpc(
                    client,
                    base_url=base_url,
                    method=method,
                    params=params,
                )

    def _alias_for_url(self, base_url: str) -> Optional[str]:
        for alias, mapped_url in self.server_map.items():
            if mapped_url == base_url:
                return alias
        return None

    def _resolve_tool_target(self, tool_name: str) -> Tuple[Optional[str], str, Optional[str]]:
        """
        tool_name을 실제 호출할 endpoint와 raw tool name으로 변환합니다.
        반환값: (base_url, raw_tool_name, error_message)
        """
        # alias.tool_name 형식으로 명시 라우팅 지원
        if "." in tool_name:
            alias, raw_tool_name = tool_name.split(".", 1)
            mapped_url = self.server_map.get(alias)
            if mapped_url:
                return mapped_url, raw_tool_name, None

        routed_url = self._tool_route.get(tool_name)
        if routed_url:
            return routed_url, tool_name, None

        ambiguous_urls = self._ambiguous_tool_route.get(tool_name)
        if ambiguous_urls:
            ambiguous_aliases = [
                alias for alias, url in self.server_map.items() if url in ambiguous_urls
            ]
            hint = ", ".join(f"{alias}.{tool_name}" for alias in ambiguous_aliases) if ambiguous_aliases else ""
            msg = (
                f"도구 '{tool_name}'가 여러 MCP 서버에 중복되어 있습니다. "
                f"대상 서버를 명시하세요.{(' 예: ' + hint) if hint else ''}"
            )
            return None, tool_name, msg

        return None, tool_name, f"도구 '{tool_name}'를 찾을 수 없습니다."

    def _rebuild_tool_routes(self, tools: List[Dict[str, Any]]) -> None:
        route_candidates: Dict[str, List[str]] = {}
        for tool in tools:
            name = str(tool.get("name", "")).strip()
            base_url = str(tool.get("_mcp_base_url", "")).strip()
            if not name or not base_url:
                continue
            route_candidates.setdefault(name, []).append(base_url)

        self._tool_route = {}
        self._ambiguous_tool_route = {}
        for tool_name, urls in route_candidates.items():
            unique_urls = sorted(set(urls))
            if len(unique_urls) == 1:
                self._tool_route[tool_name] = unique_urls[0]
            else:
                self._ambiguous_tool_route[tool_name] = unique_urls

    async def list_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """
        사용 가능한 도구 목록 조회 (멀티 MCP 통합, 캐시 적용)
        """
        if self._tools_cache and not refresh:
            return self._tools_cache

        merged_tools: List[Dict[str, Any]] = []
        for base_url in self.base_urls:
            try:
                result = await self._post_jsonrpc_with_retry(
                    base_url=base_url,
                    method="tools/list",
                )
            except Exception as exc:
                logger.warning("MCP tools/list 실패: %s (%s)", base_url, exc)
                continue

            tools = result.get("tools", [])
            if not isinstance(tools, list):
                continue

            alias = self._alias_for_url(base_url)
            for tool in tools:
                if not isinstance(tool, dict):
                    continue
                name = str(tool.get("name", "")).strip()
                if not name:
                    continue
                enriched = dict(tool)
                enriched["_mcp_base_url"] = base_url
                if alias:
                    enriched["_mcp_server_alias"] = alias
                merged_tools.append(enriched)

        self._rebuild_tool_routes(merged_tools)
        self._tools_cache = merged_tools
        return self._tools_cache

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        특정 도구 실행 (멀티 MCP 자동 라우팅)
        """
        if not self._tools_cache:
            await self.list_tools()

        target_url, raw_tool_name, resolve_error = self._resolve_tool_target(tool_name)
        if target_url is None:
            # 라우팅 정보가 오래되었을 수 있어 1회 refresh 후 재시도
            await self.list_tools(refresh=True)
            target_url, raw_tool_name, resolve_error = self._resolve_tool_target(tool_name)
            if target_url is None:
                return {"error": resolve_error or "tool routing failed"}

        try:
            return await self._post_jsonrpc_with_retry(
                base_url=target_url,
                method="tools/call",
                params={
                    "name": raw_tool_name,
                    "arguments": arguments,
                },
            )
        except Exception as exc:
            return {"error": str(exc)}

    async def _legacy_post_jsonrpc(
        self,
        client: httpx.AsyncClient,
        *,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        기존 단일 endpoint 호출용 private 래퍼 (호환 유지)
        """
        return await self._post_jsonrpc(client, base_url=self.base_url, method=method, params=params)

async def example_usage():
    client = MCPClient(
        base_urls=["http://localhost:8000/mcp", "http://localhost:8900/mcp"],
        server_map={
            "windows": "http://localhost:8000/mcp",
            "filesystem": "http://localhost:8900/mcp",
        },
    )
    # 도구 호출 예시
    tools = await client.list_tools()
    print(f"총 {len(tools)}개 도구 로드")
    result = await client.call_tool("filesystem.list_allowed_directories", {})
    print(result)

if __name__ == "__main__":
    asyncio.run(example_usage())
