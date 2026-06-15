"""
URL HTTP 조회 도구.

지정한 URL에서 내용을 가져와 텍스트 또는 JSON으로 반환합니다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_CHARS = 50_000


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


async def fetch_url(
    url: str,
    method: str = "GET",
    timeout: float = _DEFAULT_TIMEOUT,
    max_chars: int = _DEFAULT_MAX_CHARS,
    as_json: bool = False,
    headers: Optional[dict[str, str]] = None,
) -> str:
    """
    URL에서 HTTP 요청으로 내용을 조회합니다.

    Args:
        url: 조회할 URL (http/https)
        method: HTTP 메서드 (기본 GET)
        timeout: 요청 타임아웃(초)
        max_chars: 응답 본문 최대 문자 수
        as_json: True이면 JSON 파싱 후 반환
        headers: 추가 HTTP 헤더
    """
    cleaned_url = (url or "").strip()
    if not cleaned_url:
        return json.dumps(
            {"success": False, "message": "url은 비어 있을 수 없습니다."},
            ensure_ascii=False,
        )

    http_method = (method or "GET").strip().upper()
    if http_method not in {"GET", "HEAD"}:
        return json.dumps(
            {"success": False, "message": f"지원하지 않는 method: {http_method} (GET|HEAD)"},
            ensure_ascii=False,
        )

    max_chars = max(1, min(int(max_chars), 500_000))
    timeout_value = max(1.0, float(timeout))

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_value) as client:
            response = await client.request(http_method, cleaned_url, headers=headers or {})
    except httpx.HTTPError as exc:
        logger.exception("fetch_url HTTP 오류: %s", cleaned_url)
        return json.dumps(
            {"success": False, "message": f"URL 요청 실패: {exc}", "url": cleaned_url},
            ensure_ascii=False,
        )

    content_type = response.headers.get("content-type", "")
    body_text = response.text if http_method != "HEAD" else ""
    truncated = False

    if http_method != "HEAD":
        body_text, truncated = _truncate_text(body_text, max_chars)

    payload: dict[str, Any] = {
        "success": response.is_success,
        "url": str(response.url),
        "status_code": response.status_code,
        "content_type": content_type,
        "truncated": truncated,
        "message": f"HTTP {response.status_code} 조회 완료",
    }

    if http_method == "HEAD":
        payload["headers"] = dict(response.headers)
        return json.dumps(payload, ensure_ascii=False)

    if as_json:
        try:
            parsed = response.json()
            serialized = json.dumps(parsed, ensure_ascii=False, default=str)
            serialized, json_truncated = _truncate_text(serialized, max_chars)
            payload["json"] = json.loads(serialized)
            payload["truncated"] = truncated or json_truncated
            payload["format"] = "json"
        except Exception:
            payload["text"] = body_text
            payload["format"] = "text"
            payload["message"] = (
                f"HTTP {response.status_code} 조회 완료 (JSON 파싱 실패, text 반환)"
            )
    else:
        payload["text"] = body_text
        payload["format"] = "text"

    if not response.is_success:
        payload["success"] = False
        payload["message"] = f"HTTP {response.status_code} 오류"

    return json.dumps(payload, ensure_ascii=False, default=str)


def register_url_fetch_tools(mcp: "FastMCP") -> None:
    """URL 조회 도구 등록."""
    mcp.tool()(fetch_url)
    logger.info("URL 조회 도구 등록 완료: fetch_url")
