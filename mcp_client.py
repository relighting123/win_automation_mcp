import asyncio
import logging
import httpx
import json
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# MCP Streamable HTTP 트랜스포트가 강제하는 Accept 미디어 타입.
# 서버는 둘 다 포함되지 않으면 즉시 406 Not Acceptable을 반환합니다.
_ACCEPT_HEADER = "application/json, text/event-stream"
_PROTOCOL_VERSION = "2024-11-05"


class MCPClient:
    """
    HTTP 기반 FastMCP 서버와 통신하는 클라이언트

    - 세션 ID(`mcp-session-id`)를 인스턴스에 캐싱하여 매 호출마다
      `initialize`를 반복하지 않습니다.
    - 406 Not Acceptable, 401/403/404 등 서버 측 거부에 대해서는
      세션을 폐기한 뒤 1회 재시도합니다.
    - 응답이 SSE 스트림이든 일반 JSON이든 모두 파싱할 수 있게 처리합니다.
    """

    def __init__(self, base_url: str = "http://localhost:8000/mcp"):
        # `/mcp/` 처럼 trailing slash가 붙으면 starlette의 redirect_slashes 로직이
        # 307을 돌려주고 httpx가 POST 리다이렉트를 따라가지 않아 빈 응답이 되어버린다.
        self.base_url = base_url.rstrip("/")
        self._session_id: Optional[str] = None
        self._request_id = 0
        self._tools_cache: Optional[List[Dict[str, Any]]] = None

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _build_headers(self, *, include_session: bool = False) -> Dict[str, str]:
        headers = {
            "Accept": _ACCEPT_HEADER,
            "Content-Type": "application/json",
            "MCP-Protocol-Version": _PROTOCOL_VERSION,
        }
        if include_session and self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    @staticmethod
    def _parse_sse_payload(raw_body: str) -> Optional[Dict[str, Any]]:
        """SSE(`event:`/`data:`) 또는 단일 JSON 본문에서 JSON-RPC payload 추출."""
        if not raw_body:
            return None

        stripped = raw_body.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass

        for raw_line in raw_body.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(":") or line.startswith("event:"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return None

    async def _ensure_session(self, client: httpx.AsyncClient) -> None:
        """MCP streamable-http 세션을 초기화합니다."""
        if self._session_id:
            return

        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "automation-graph-client", "version": "1.0.0"},
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
                self._format_http_error("initialize", init_res.status_code, init_res.text)
            )

        session_id = init_res.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("initialize 응답에 mcp-session-id 헤더가 없습니다.")
        self._session_id = session_id

        notify_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        # notifications/initialized는 서버가 202 Accepted(빈 본문)로 응답한다.
        # 일부 느린 환경에서도 안전하도록 timeout을 충분히 둔다.
        notify_res = await client.post(
            self.base_url,
            json=notify_payload,
            headers=self._build_headers(include_session=True),
            timeout=15.0,
        )
        if notify_res.status_code >= 400:
            # 세션 초기화가 끝나지 않으면 이후 tools/call이 일관되지 않은 상태에서 실행되므로
            # 명시적으로 세션을 폐기하고 예외를 던진다.
            self._session_id = None
            raise RuntimeError(
                self._format_http_error(
                    "notifications/initialized", notify_res.status_code, notify_res.text
                )
            )

    @staticmethod
    def _format_http_error(method: str, status_code: int, body: str) -> str:
        snippet = (body or "").strip()
        if len(snippet) > 500:
            snippet = snippet[:500] + "..."

        hint = ""
        if status_code == 406:
            hint = (
                " (MCP Streamable HTTP는 Accept 헤더에 'application/json'과 "
                "'text/event-stream'을 모두 포함해야 합니다.)"
            )
        elif status_code == 404:
            hint = " (세션이 만료되었거나 잘못된 mcp-session-id 일 수 있습니다.)"
        elif status_code == 415:
            hint = " (Content-Type이 application/json 인지 확인하세요.)"

        return f"{method} 실패({status_code}): {snippet}{hint}"

    async def _post_jsonrpc(
        self,
        client: httpx.AsyncClient,
        *,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """JSON-RPC 호출 후 result payload를 반환합니다."""
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
            timeout=timeout,
        ) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="ignore")
                raise RuntimeError(
                    self._format_http_error(method, response.status_code, body)
                )

            buffer: List[str] = []
            async for raw_line in response.aiter_lines():
                buffer.append(raw_line)
                line = raw_line.strip()
                if not line or line.startswith(":") or line.startswith("event:"):
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
                # 스트리밍 도중 종료되었다면 누적된 본문에서 다시 파싱 시도.
                parsed = self._parse_sse_payload("\n".join(buffer))

        if not parsed:
            raise RuntimeError(f"{method}: MCP 응답에서 JSON payload를 파싱하지 못했습니다.")
        if "error" in parsed:
            raise RuntimeError(f"MCP error ({method}): {parsed['error']}")
        result = parsed.get("result", {})
        if isinstance(result, dict):
            return result
        return {"result": result}

    async def _call_with_retry(
        self,
        client: httpx.AsyncClient,
        *,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """세션/Accept 등 일시적 거부에 대비해 1회 재시도하는 래퍼."""
        try:
            return await self._post_jsonrpc(client, method=method, params=params, timeout=timeout)
        except RuntimeError as exc:
            message = str(exc)
            should_retry = any(token in message for token in ("실패(406)", "실패(404)", "실패(400)"))
            if not should_retry:
                raise
            logger.warning("MCP %s 호출이 거부됨, 세션을 재초기화하여 재시도합니다: %s", method, message)
            self._session_id = None
            return await self._post_jsonrpc(client, method=method, params=params, timeout=timeout)

    async def list_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """
        사용 가능한 도구 목록 조회 (캐시 적용)
        """
        if self._tools_cache and not refresh:
            return self._tools_cache

        async with httpx.AsyncClient() as client:
            result = await self._call_with_retry(client, method="tools/list")

            tools = result.get("tools", [])
            self._tools_cache = tools if isinstance(tools, list) else []
            return self._tools_cache

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        특정 도구 실행
        """
        async with httpx.AsyncClient() as client:
            try:
                return await self._call_with_retry(
                    client,
                    method="tools/call",
                    params={
                        "name": tool_name,
                        "arguments": arguments,
                    },
                )
            except Exception as exc:
                logger.error("MCP tools/call 실패 (%s): %s", tool_name, exc)
                return {"error": str(exc)}

async def example_usage():
    client = MCPClient()
    # 도구 호출 예시
    result = await client.call_tool("launch_program", {"program_name": "notepad"})
    print(result)

if __name__ == "__main__":
    asyncio.run(example_usage())
