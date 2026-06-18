"""
Browser MCP Chrome 확장 연결 상태 확인 및 Connect 유도.

공식 Browser MCP는 보안상 확장의 Connect 클릭을 코드로 대체할 수 없습니다.
스킬 실행 전 연결을 확인하고, 필요 시 확장 팝업을 열어 한 번의 클릭만 하면 되게 돕습니다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

BROWSER_MCP_EXTENSION_ID = "bjfgambnhccakkhmkepdoekmckoijdlc"
BROWSER_MCP_POPUP_URL = f"chrome-extension://{BROWSER_MCP_EXTENSION_ID}/popup.html"
_NO_CONNECTION_MARKERS = (
    "No connection to browser extension",
    "No tab is connected",
    "browser extension",
    "Connect' button",
)


def _is_truthy(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def browser_mcp_auto_ensure_enabled() -> bool:
    return _is_truthy(os.getenv("BROWSER_MCP_AUTO_ENSURE_CONNECT"), default=True)


def browser_mcp_connect_wait_seconds() -> float:
    raw = os.getenv("BROWSER_MCP_CONNECT_WAIT_SECONDS", "20")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 20.0


def is_browser_mcp_connection_error(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker.lower() in lowered for marker in _NO_CONNECTION_MARKERS)


def _extract_tool_error(result: dict[str, Any]) -> str:
    if result.get("error"):
        return str(result["error"])
    if result.get("isError"):
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                return str(block.get("text", ""))
    return ""


def _chrome_executable_candidates() -> list[str]:
    candidates: list[str] = []
    for name in ("chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        candidates.extend(
            [
                str(Path(program_files) / "Google/Chrome/Application/chrome.exe"),
                str(Path(program_files_x86) / "Google/Chrome/Application/chrome.exe"),
                str(Path(local) / "Google/Chrome/Application/chrome.exe"),
            ]
        )
    return candidates


def open_browser_mcp_connect_popup() -> bool:
    """Browser MCP 확장 팝업을 엽니다. Connect 버튼이 보이는 화면까지는 자동으로 갑니다."""
    for chrome in _chrome_executable_candidates():
        if not Path(chrome).exists():
            continue
        try:
            subprocess.Popen(
                [chrome, BROWSER_MCP_POPUP_URL],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Browser MCP 확장 팝업 실행: %s", chrome)
            return True
        except Exception as exc:
            logger.debug("Chrome 팝업 실행 실패 (%s): %s", chrome, exc)

    if sys.platform == "win32":
        try:
            os.startfile(BROWSER_MCP_POPUP_URL)  # type: ignore[attr-defined]
            logger.info("Browser MCP 확장 팝업 실행: os.startfile")
            return True
        except Exception as exc:
            logger.debug("os.startfile 팝업 실행 실패: %s", exc)
    return False


async def probe_browser_mcp_connection(hub: Any) -> bool:
    """browser_snapshot으로 확장 연결 여부를 확인합니다."""
    try:
        result = await hub.call_tool("browsermcp/browser_snapshot", {})
    except Exception as exc:
        logger.debug("Browser MCP 연결 확인 실패: %s", exc)
        return False

    if result.get("error"):
        return not is_browser_mcp_connection_error(str(result["error"]))

    if result.get("isError"):
        return not is_browser_mcp_connection_error(_extract_tool_error(result))

    return True


async def ensure_browser_mcp_connected(
    hub: Any,
    *,
    wait_seconds: Optional[float] = None,
    open_popup: Optional[bool] = None,
) -> tuple[bool, str]:
    """
    Browser MCP 확장 연결을 확인하고, 필요하면 팝업을 연 뒤 잠시 대기합니다.

    Returns:
        (connected, message)
    """
    if hub is None:
        return False, (
            "Browser MCP가 활성화되지 않았습니다. "
            ".env에 MCP_BROWSER_MCP_ENABLED=true 를 설정하고 chatRTD를 재시작하세요."
        )

    if await probe_browser_mcp_connection(hub):
        return True, "Browser MCP 확장이 이미 연결되어 있습니다."

    should_open_popup = browser_mcp_auto_ensure_enabled() if open_popup is None else bool(open_popup)
    timeout = browser_mcp_connect_wait_seconds() if wait_seconds is None else max(0.0, float(wait_seconds))

    if should_open_popup:
        if open_browser_mcp_connect_popup():
            message = (
                "Browser MCP 확장 팝업을 열었습니다. "
                "Connect 버튼을 한 번 눌러 주세요."
            )
        else:
            message = (
                "Browser MCP 확장이 연결되지 않았습니다. "
                "Chrome 툴바의 Browser MCP 아이콘을 눌러 Connect를 클릭하세요."
            )
    else:
        message = (
            "Browser MCP 확장이 연결되지 않았습니다. "
            "Chrome에서 Browser MCP → Connect를 눌러 주세요."
        )

    if timeout <= 0:
        return False, message

    logger.info("Browser MCP Connect 대기 시작 (%.1fs)", timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        if await probe_browser_mcp_connection(hub):
            return True, "Browser MCP 확장 연결 완료."

    return False, (
        f"{message} ({int(timeout)}초 내 자동 연결되지 않았습니다. "
        "Connect 후 같은 스킬을 다시 실행하세요."
    )
