"""
OpenChrome(openchrome-mcp)로 URL 본문을 가져오는 헬퍼.

Chrome DevTools Protocol(CDP)로 실제 Chrome을 제어하므로
Browser MCP Chrome 확장 + Connect 없이 동작합니다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core.mcp_result_utils import extract_mcp_text_content, normalize_mcp_tool_result


def extract_browser_tool_text(result: dict[str, Any]) -> str:
    normalized = normalize_mcp_tool_result(result)
    if normalized.get("success") is False:
        return f"[오류] {normalized.get('message', normalized)}"

    if isinstance(normalized.get("text"), str) and normalized["text"].strip():
        return normalized["text"].strip()

    if isinstance(normalized.get("result"), str) and normalized["result"].strip():
        return normalized["result"].strip()

    raw = extract_mcp_text_content(result)
    if not raw:
        return json.dumps(result, ensure_ascii=False, default=str)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    if isinstance(parsed, str):
        return parsed.strip()
    if not isinstance(parsed, dict):
        return raw

    for key in ("content", "markdown", "fit_markdown", "raw_markdown", "text", "body"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return raw


def snapshot_to_text(snapshot: str) -> str:
    """browser_snapshot / AX 스냅샷에서 읽을 수 있는 텍스트를 추출합니다."""
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


async def fetch_url_via_browser(url: str) -> str:
    from core.mcp_client import get_shared_extra_mcp_hub

    hub = await get_shared_extra_mcp_hub()
    if hub is None:
        return (
            "[OpenChrome 미활성화] .env에 MCP_OPENCHROME_ENABLED=true 설정 후 "
            "chatRTD를 재시작하세요. (Node.js + Chrome 필요)"
        )

    if not hub.has_tool("openchrome/navigate"):
        return (
            "[OpenChrome 도구 없음] openchrome MCP 서버가 연결되지 않았습니다. "
            "MCP_OPENCHROME_ENABLED=true 후 chatRTD를 재시작하세요."
        )

    navigate = await hub.call_tool("openchrome/navigate", {"url": url})
    navigate_text = extract_browser_tool_text(navigate)
    if navigate.get("error") or normalize_mcp_tool_result(navigate).get("success") is False:
        return f"[navigate 오류] {navigate_text}"

    read_page = await hub.call_tool(
        "openchrome/read_page",
        {"mode": "markdown", "onlyMainContent": True},
    )
    if read_page.get("error") or normalize_mcp_tool_result(read_page).get("success") is False:
        return f"[read_page 오류] {extract_browser_tool_text(read_page)}"

    text = extract_browser_tool_text(read_page)
    return snapshot_to_text(text) if text.startswith("- role:") else text
