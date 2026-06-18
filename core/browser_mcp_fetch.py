"""
Browser MCP(@browsermcp/mcp)로 URL 본문을 가져오는 헬퍼.
"""

from __future__ import annotations

import json
import re
from typing import Any


def extract_mcp_text(result: dict[str, Any]) -> str:
    if result.get("isError"):
        return f"[오류] {result}"
    for block in result.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text", ""))
    if isinstance(result.get("text"), str):
        return result["text"]
    return json.dumps(result, ensure_ascii=False, default=str)


def snapshot_to_text(snapshot: str) -> str:
    """browser_snapshot 접근성 트리에서 읽을 수 있는 텍스트를 추출합니다."""
    if not snapshot.strip():
        return ""

    lines: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        cleaned = " ".join(text.split())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            lines.append(cleaned)

    for raw_line in snapshot.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        inline = re.search(r'\bname:\s*["\']?(.+?)["\']?\s*$', line)
        if inline:
            _add(inline.group(1))
            continue

        text_match = re.search(r'\btext:\s*["\']?(.+?)["\']?\s*$', line)
        if text_match:
            _add(text_match.group(1))
            continue

        quoted = re.findall(r'"([^"]{2,})"', line)
        for item in quoted:
            if not item.startswith("ref:"):
                _add(item)

    return "\n".join(lines) if lines else snapshot.strip()


async def fetch_url_via_browser_mcp(url: str) -> str:
    from core.browser_mcp_connect import ensure_browser_mcp_connected
    from core.mcp_client import get_shared_extra_mcp_hub

    hub = await get_shared_extra_mcp_hub()
    connected, message = await ensure_browser_mcp_connected(hub)
    if not connected:
        return f"[Browser MCP 미연결] {message}"

    navigate = await hub.call_tool("browsermcp/browser_navigate", {"url": url})
    if navigate.get("error"):
        return f"[browser_navigate 오류] {navigate['error']}"

    snapshot = await hub.call_tool("browsermcp/browser_snapshot", {})
    if snapshot.get("error"):
        return f"[browser_snapshot 오류] {snapshot['error']}"

    raw = extract_mcp_text(snapshot)
    return snapshot_to_text(raw)
