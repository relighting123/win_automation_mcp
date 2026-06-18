"""
OpenChrome(openchrome-mcp)로 URL 본문을 가져오는 헬퍼.

Chrome DevTools Protocol(CDP)로 실제 Chrome을 제어하므로
Browser MCP Chrome 확장 + Connect 없이 동작합니다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

from core.mcp_result_utils import extract_mcp_text_content, normalize_mcp_tool_result

logger = logging.getLogger(__name__)

_READ_PAGE_WAIT_SECONDS = 2.0
_OPENCHROME_OWNER_CONFLICT_MARKERS = (
    "already owns",
    "owner_conflict",
    "duplicate controller",
    "refusing to start",
    "pid ",
)
_OPENCHROME_STALE_SESSION_MARKERS = (
    "broken pipe",
    "connection reset",
    "connection closed",
    "not connected",
    "eof",
    "stream closed",
    "session is closed",
)


def _openchrome_remediation(message: str) -> str:
    lowered = (message or "").lower()
    if any(marker in lowered for marker in _OPENCHROME_OWNER_CONFLICT_MARKERS):
        return (
            f"{message}\n\n"
            "[해결 방법]\n"
            "1. chatRTD 터미널/프로세스를 모두 종료합니다.\n"
            "2. 작업 관리자에서 chrome.exe, node.exe(openchrome)를 종료합니다.\n"
            "3. 잠금 파일을 삭제합니다:\n"
            "   - Windows: %TEMP%\\openchrome-9222.pid, %USERPROFILE%\\.openchrome\\locks\\\n"
            "   - Linux/macOS: /tmp/openchrome-9222.pid, ~/.openchrome/locks/\n"
            "4. chatRTD만 다시 실행합니다. (Chrome은 OpenChrome이 자동 실행)\n"
            "   ※ OpenChrome/node만 kill하고 chatRTD는 그대로 두면 연결이 끊긴 채로 남습니다."
        )
    if any(marker in lowered for marker in _OPENCHROME_STALE_SESSION_MARKERS):
        return (
            f"{message}\n\n"
            "[해결 방법] OpenChrome 프로세스만 종료했다면 chatRTD도 반드시 재시작하세요. "
            "내부 MCP stdio 연결이 끊긴 상태로 남아 있을 수 있습니다."
        )
    return message


def extract_browser_tool_text(result: dict[str, Any]) -> str:
    normalized = normalize_mcp_tool_result(result)
    if normalized.get("success") is False:
        message = normalized.get("message")
        if isinstance(message, str) and message.strip():
            return f"[오류] {message.strip()}"
        text = extract_mcp_text_content(result)
        if text.strip():
            return f"[오류] {text.strip()}"
        return f"[오류] OpenChrome 도구 호출 실패: {normalized}"

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


def extract_openchrome_tab_id(result: dict[str, Any]) -> Optional[str]:
    normalized = normalize_mcp_tool_result(result)
    if isinstance(normalized.get("tabId"), str) and normalized["tabId"].strip():
        return normalized["tabId"].strip()

    raw = extract_mcp_text_content(result)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        tab_id = parsed.get("tabId")
        if isinstance(tab_id, str) and tab_id.strip():
            return tab_id.strip()
    return None


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


def _tool_failure_message(result: dict[str, Any], *, step: str) -> Optional[str]:
    if result.get("error"):
        return f"[{step} 오류] {_openchrome_remediation(str(result['error']))}"

    normalized = normalize_mcp_tool_result(result)
    if normalized.get("success") is False:
        message = normalized.get("message") or extract_browser_tool_text(result)
        return f"[{step} 오류] {_openchrome_remediation(str(message))}"

    text = extract_browser_tool_text(result)
    if text.startswith("Error:") or text.startswith("[오류]"):
        body = text.removeprefix("[오류]").strip() or text
        return f"[{step} 오류] {_openchrome_remediation(body)}"
    return None


async def _fetch_url_via_browser_once(url: str, hub: Any) -> str:
    navigate = await hub.call_tool("openchrome/navigate", {"url": url})
    navigate_error = _tool_failure_message(navigate, step="navigate")
    if navigate_error:
        return navigate_error

    tab_id = extract_openchrome_tab_id(navigate)
    if tab_id and hub.has_tool("openchrome/wait_for"):
        wait_result = await hub.call_tool(
            "openchrome/wait_for",
            {
                "tabId": tab_id,
                "type": "navigation",
                "timeout": 30000,
            },
        )
        wait_error = _tool_failure_message(wait_result, step="wait_for")
        if wait_error:
            logger.warning("OpenChrome wait_for 실패, 짧은 대기 후 계속: %s", wait_error)
            await asyncio.sleep(_READ_PAGE_WAIT_SECONDS)
    else:
        await asyncio.sleep(_READ_PAGE_WAIT_SECONDS)

    read_args: dict[str, Any] = {"mode": "markdown", "onlyMainContent": True}
    if tab_id:
        read_args["tabId"] = tab_id

    read_page = await hub.call_tool("openchrome/read_page", read_args)
    read_error = _tool_failure_message(read_page, step="read_page")
    if read_error:
        return read_error

    text = extract_browser_tool_text(read_page)
    return snapshot_to_text(text) if text.startswith("- role:") else text


def _should_reset_openchrome_hub(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _OPENCHROME_STALE_SESSION_MARKERS)


async def fetch_url_via_browser(url: str) -> str:
    from core.mcp_client import get_shared_extra_mcp_hub, reset_shared_extra_mcp_hub

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

    for attempt in range(2):
        result = await _fetch_url_via_browser_once(url, hub)
        if attempt == 0 and _should_reset_openchrome_hub(result):
            logger.warning("OpenChrome 연결 오류 감지, shared hub 재연결 시도")
            await reset_shared_extra_mcp_hub()
            hub = await get_shared_extra_mcp_hub()
            if hub is None or not hub.has_tool("openchrome/navigate"):
                return result
            continue
        return result

    return result
