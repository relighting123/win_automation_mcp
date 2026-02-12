import asyncio
import httpx
import json
from typing import Dict, Any, List, Optional

class MCPClient:
    """
    HTTP 기반 FastMCP 서버와 통신하는 클라이언트
    """
    def __init__(self, base_url: str = "http://localhost:8000/mcp"):
        self.base_url = base_url

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        사용 가능한 도구 목록 조회
        """
        async with httpx.AsyncClient() as client:
            # FastMCP의 HTTP 전송 방식에 따라 도구 목록 조회 엔드포인트가 다를 수 있음
            # 기본적으로 FastMCP는 SSE 또는 HTTP Stream을 사용하므로, 
            # 여기서는 간단한 요청/응답 구조를 가정하거나 특정 엔드포인트를 호출
            response = await client.post(f"{self.base_url}/tools/list", json={})
            if response.status_code == 200:
                return response.json().get("tools", [])
            return []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        특정 도구 실행
        """
        async with httpx.AsyncClient() as client:
            payload = {
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            response = await client.post(f"{self.base_url}/tools/call", json=payload)
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Tool call failed with status {response.status_code}", "detail": response.text}

async def example_usage():
    client = MCPClient()
    # 도구 호출 예시
    result = await client.call_tool("launch_program", {"program_name": "notepad"})
    print(result)

if __name__ == "__main__":
    asyncio.run(example_usage())
