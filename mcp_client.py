import asyncio
import httpx
import json
import time
from typing import Dict, Any, List, Optional

class MCPClient:
    """
    HTTP 기반 FastMCP 서버와 통신하는 클라이언트
    """
    def __init__(self, base_url: str = "http://localhost:8000/mcp"):
        self.base_url = base_url
        self._session_id: Optional[str] = None
        self._request_id = 0
        self._tools_cache: Optional[List[Dict[str, Any]]] = None

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
        """MCP streamable-http 세션을 초기화합니다."""
        if self._session_id:
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
            self.base_url,
            json=init_payload,
            headers=self._build_headers(),
            timeout=15.0,
        )
        if init_res.status_code != 200:
            raise RuntimeError(
                f"initialize 실패({init_res.status_code}): {init_res.text}"
            )

        session_id = init_res.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("initialize 응답에 mcp-session-id 헤더가 없습니다.")
        self._session_id = session_id

        notify_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        notify_res = await client.post(
            self.base_url,
            json=notify_payload,
            headers=self._build_headers(include_session=True),
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
        method: str,
        params: Optional[Dict[str, Any]] = None,
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

        def _parse_json_line(line: str) -> Optional[Dict[str, Any]]:
            normalized = line.strip()
            if not normalized or normalized.startswith("event:"):
                return None
            if normalized.startswith("data:"):
                normalized = normalized[5:].strip()
            if not normalized or normalized == "[DONE]":
                return None
            try:
                parsed_line = json.loads(normalized)
                if isinstance(parsed_line, dict):
                    return parsed_line
            except json.JSONDecodeError:
                return None
            return None

        async def _parse_stream_payload(response: httpx.Response) -> Optional[Dict[str, Any]]:
            parsed_payload: Optional[Dict[str, Any]] = None
            async for raw_line in response.aiter_lines():
                parsed_payload = _parse_json_line(raw_line)
                if parsed_payload is not None:
                    return parsed_payload

            raw_body = (await response.aread()).decode("utf-8", errors="ignore")
            # 1) event-stream 형태 파싱
            for raw_line in raw_body.splitlines():
                parsed_payload = _parse_json_line(raw_line)
                if parsed_payload is not None:
                    return parsed_payload
            # 2) 일반 JSON 본문 파싱
            try:
                body_json = json.loads(raw_body.strip())
                if isinstance(body_json, dict):
                    return body_json
            except Exception:
                return None
            return None

        async def _poll_accepted(location: str) -> Dict[str, Any]:
            # location이 상대 경로면 base_url 기준 절대 URL로 보정
            try:
                poll_url = str(httpx.URL(self.base_url).join(location))
            except Exception:
                poll_url = location

            deadline = time.monotonic() + 60.0
            while time.monotonic() < deadline:
                async with client.stream(
                    "GET",
                    poll_url,
                    headers=self._build_headers(include_session=True),
                    timeout=30.0,
                ) as poll_response:
                    if poll_response.status_code == 202:
                        await poll_response.aread()
                        await asyncio.sleep(0.5)
                        continue
                    if poll_response.status_code != 200:
                        body = (await poll_response.aread()).decode("utf-8", errors="ignore")
                        raise RuntimeError(
                            f"{method} poll 실패({poll_response.status_code}): {body}"
                        )

                    parsed_poll = await _parse_stream_payload(poll_response)
                    if parsed_poll:
                        return parsed_poll
                await asyncio.sleep(0.2)

            raise RuntimeError(f"{method} poll 타임아웃(60s): location={poll_url}")

        parsed: Optional[Dict[str, Any]] = None
        async with client.stream(
            "POST",
            self.base_url,
            json=payload,
            headers=self._build_headers(include_session=True),
            timeout=60.0,
        ) as response:
            if response.status_code == 202:
                location = response.headers.get("location") or response.headers.get("Location")
                if not location:
                    body = (await response.aread()).decode("utf-8", errors="ignore")
                    parsed_from_body: Optional[Dict[str, Any]] = None
                    try:
                        parsed_from_body = json.loads(body.strip())
                    except Exception:
                        pass
                    if parsed_from_body is None:
                        raise RuntimeError(
                            f"{method} 202 응답에 polling location이 없습니다: {body}"
                        )
                    parsed = parsed_from_body
                else:
                    parsed = await _poll_accepted(location)
            elif response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="ignore")
                raise RuntimeError(
                    f"{method} 실패({response.status_code}): {body}"
                )
            else:
                parsed = await _parse_stream_payload(response)

        if not parsed:
            raise RuntimeError("MCP 응답에서 JSON payload를 파싱하지 못했습니다.")
        if "error" in parsed:
            raise RuntimeError(f"MCP error: {parsed['error']}")
        result = parsed.get("result", {})
        if isinstance(result, dict):
            return result
        return {"result": result}

    async def list_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """
        사용 가능한 도구 목록 조회 (캐시 적용)
        """
        if self._tools_cache and not refresh:
            return self._tools_cache

        async with httpx.AsyncClient() as client:
            try:
                result = await self._post_jsonrpc(client, method="tools/list")
            except Exception:
                # 세션 만료/서버 재기동 시 1회 재시도
                self._session_id = None
                result = await self._post_jsonrpc(client, method="tools/list")
            
            tools = result.get("tools", [])
            self._tools_cache = tools if isinstance(tools, list) else []
            return self._tools_cache

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        특정 도구 실행
        """
        async with httpx.AsyncClient() as client:
            try:
                return await self._post_jsonrpc(
                    client,
                    method="tools/call",
                    params={
                        "name": tool_name,
                        "arguments": arguments,
                    },
                )
            except Exception:
                # 세션 만료/서버 재기동 시 1회 재시도
                self._session_id = None
                try:
                    return await self._post_jsonrpc(
                        client,
                        method="tools/call",
                        params={
                            "name": tool_name,
                            "arguments": arguments,
                        },
                    )
                except Exception as exc:
                    return {"error": str(exc)}

async def example_usage():
    client = MCPClient()
    # 도구 호출 예시
    result = await client.call_tool("launch_program", {"program_name": "notepad"})
    print(result)

if __name__ == "__main__":
    asyncio.run(example_usage())
