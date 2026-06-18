"""
Playwright URL 본문 수집 MCP 도구.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from core.browser_fetch import fetch_url_via_browser

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


async def fetch_url_content(url: str) -> str:
    """
    Playwright로 URL을 열고 본문 텍스트를 반환합니다.

    Args:
        url: 수집할 페이지 URL
    """
    target = (url or "").strip()
    if not target:
        return json.dumps(
            {"success": False, "message": "url 인자가 필요합니다."},
            ensure_ascii=False,
        )

    logger.info("[Tool] fetch_url_content 호출: url=%s", target)
    try:
        text = await fetch_url_via_browser(target)
    except Exception as exc:
        logger.exception("[Tool] fetch_url_content 실패: %s", exc)
        return json.dumps(
            {"success": False, "message": f"URL 수집 중 오류: {exc}"},
            ensure_ascii=False,
        )

    if text.startswith("[") and any(
        marker in text
        for marker in ("오류", "미설치", "Error:")
    ):
        return json.dumps({"success": False, "message": text}, ensure_ascii=False)

    return json.dumps(
        {"success": True, "url": target, "text": text},
        ensure_ascii=False,
    )


def register_browser_tools(mcp: "FastMCP") -> None:
    mcp.tool()(fetch_url_content)
    logger.info("browser 도구 등록 완료: fetch_url_content")
