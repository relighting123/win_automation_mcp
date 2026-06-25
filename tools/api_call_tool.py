"""
HTTP API 호출 도구.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

import httpx

from core.api_config import (
    build_request_target,
    get_api_access_settings,
    validate_http_method,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _merge_headers(
    profile_headers: Dict[str, str],
    request_headers: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    merged = dict(profile_headers)
    if isinstance(request_headers, dict):
        for key, value in request_headers.items():
            if value is None:
                continue
            merged[str(key)] = str(value)
    return merged


def _serialize_response_body(
    content: bytes,
    content_type: str,
    *,
    max_chars: int,
) -> tuple[Any, bool, str]:
    text = content.decode("utf-8", errors="replace")
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    lowered = (content_type or "").lower()
    if "application/json" in lowered or text.lstrip().startswith(("{", "[")):
        try:
            return json.loads(text), truncated, "json"
        except json.JSONDecodeError:
            pass

    return text, truncated, "text"


async def http_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, Any]] = None,
    body: Optional[str] = None,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    api_alias: Optional[str] = None,
) -> str:
    """
    설정된 허용 호스트에 HTTP 요청을 보내고 응답을 반환합니다.
    접근 정책은 config/app_config.yaml 의 api_access 를 사용합니다.

    Args:
        url: 요청 URL (api_alias 사용 시 base_url 기준 상대 경로 가능)
        method: HTTP method (기본 GET)
        headers: 추가 요청 헤더
        body: 원문 요청 본문 (json_body와 동시 사용 불가)
        json_body: JSON 요청 본문
        params: 쿼리 파라미터
        timeout: 요청 타임아웃(초). 생략 시 api_access.default_timeout
        api_alias: app_config.api_access.apis 에 정의된 API 프로필 별칭
    """
    try:
        method_err = validate_http_method(method)
        if method_err:
            return json.dumps({"success": False, "message": method_err}, ensure_ascii=False)

        if body is not None and json_body is not None:
            return json.dumps(
                {"success": False, "message": "body와 json_body는 동시에 사용할 수 없습니다."},
                ensure_ascii=False,
            )

        final_url, profile_headers, target_err = build_request_target(url, api_alias=api_alias)
        if target_err:
            return json.dumps({"success": False, "message": target_err}, ensure_ascii=False)

        settings = get_api_access_settings()
        request_timeout = timeout if timeout is not None else settings["default_timeout"]
        request_timeout = max(1.0, min(float(request_timeout), 300.0))
        merged_headers = _merge_headers(profile_headers, headers)

        request_kwargs: Dict[str, Any] = {
            "method": method.strip().upper(),
            "url": final_url,
            "headers": merged_headers or None,
            "params": params,
            "timeout": request_timeout,
        }
        if json_body is not None:
            request_kwargs["json"] = json_body
        elif body is not None:
            request_kwargs["content"] = body

        logger.info("[Tool] http_request %s %s", request_kwargs["method"], final_url)

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.request(**request_kwargs)

        response_body, truncated, body_format = _serialize_response_body(
            response.content,
            response.headers.get("content-type", ""),
            max_chars=settings["max_response_chars"],
        )

        return json.dumps(
            {
                "success": True,
                "message": f"HTTP {response.status_code} 응답 수신",
                "url": final_url,
                "method": request_kwargs["method"],
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response_body,
                "body_format": body_format,
                "truncated": truncated,
            },
            ensure_ascii=False,
            default=str,
        )
    except httpx.TimeoutException:
        logger.warning("http_request 타임아웃: %s", url)
        return json.dumps(
            {"success": False, "message": f"요청 시간 초과 ({timeout or 'default'}초): {url}"},
            ensure_ascii=False,
        )
    except httpx.RequestError as exc:
        logger.warning("http_request 네트워크 오류: %s", exc)
        return json.dumps(
            {"success": False, "message": f"HTTP 요청 실패: {exc}"},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("http_request 실패")
        return json.dumps(
            {"success": False, "message": f"HTTP 호출 중 오류: {exc}"},
            ensure_ascii=False,
        )


def register_api_call_tools(mcp: "FastMCP") -> None:
    """HTTP API 호출 도구 등록."""
    mcp.tool()(http_request)
    logger.info("API 호출 도구 등록 완료: http_request")
