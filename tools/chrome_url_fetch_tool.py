"""
Chrome(Playwright) 기반 URL 조회 도구.

사내 SSO 등 브라우저 세션이 필요한 URL을 크롬으로 열어 내용을 가져옵니다.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_CHARS = 50_000
_DEFAULT_WAIT_SECONDS = 0.0
_LOGIN_KEYWORDS = ("login", "sign in", "signin", "log in", "인증", "로그인", "microsoft")


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _resolve_profile_dir(profile_dir: Optional[str]) -> Path:
    raw = (profile_dir or os.getenv("CHROME_USER_DATA_DIR", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".chatRTD" / "chrome-automation"


def _resolve_channel(channel: Optional[str]) -> str:
    return (channel or os.getenv("CHROME_CHANNEL", "chrome")).strip() or "chrome"


def _looks_like_login_page(url: str, title: str) -> bool:
    combined = f"{url} {title}".lower()
    return any(keyword in combined for keyword in _LOGIN_KEYWORDS)


async def fetch_url_chrome(
    url: str,
    profile_dir: Optional[str] = None,
    headless: bool = False,
    wait_seconds: float = _DEFAULT_WAIT_SECONDS,
    timeout: float = _DEFAULT_TIMEOUT,
    max_chars: int = _DEFAULT_MAX_CHARS,
    return_html: bool = False,
    channel: Optional[str] = None,
) -> str:
    """
    설치된 Google Chrome(Playwright)으로 URL을 열고 페이지 내용을 조회합니다.

    사내 SSO가 필요한 URL은 headless=False로 실행한 뒤 wait_seconds로
    사용자가 로그인할 시간을 줄 수 있습니다. 동일 profile_dir을 재사용하면
    이후 요청에서 세션을 유지할 수 있습니다.

    Args:
        url: 조회할 URL (http/https)
        profile_dir: Chrome user data 디렉터리 (미지정 시 CHROME_USER_DATA_DIR 또는 ~/.chatRTD/chrome-automation)
        headless: True면 창 없이 실행 (SSO/MFA에는 비권장)
        wait_seconds: 페이지 로드 후 추가 대기 시간(초). 로그인 완료 대기용
        timeout: navigation 타임아웃(초)
        max_chars: 응답 본문 최대 문자 수
        return_html: True면 HTML, False면 body 텍스트 반환
        channel: Playwright browser channel (기본 chrome, CHROME_CHANNEL 환경변수)
    """
    cleaned_url = (url or "").strip()
    if not cleaned_url:
        return json.dumps(
            {"success": False, "message": "url은 비어 있을 수 없습니다."},
            ensure_ascii=False,
        )

    if async_playwright is None:
        return json.dumps(
            {
                "success": False,
                "message": (
                    "playwright 패키지가 설치되지 않았습니다. "
                    "pip install playwright 후 playwright install chrome 를 실행하세요."
                ),
                "url": cleaned_url,
            },
            ensure_ascii=False,
        )

    resolved_profile = _resolve_profile_dir(profile_dir)
    resolved_channel = _resolve_channel(channel)
    max_chars = max(1, min(int(max_chars), 500_000))
    timeout_ms = max(1_000, int(float(timeout) * 1000))
    wait_ms = max(0, int(float(wait_seconds) * 1000))

    resolved_profile.mkdir(parents=True, exist_ok=True)

    context = None
    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(resolved_profile),
                channel=resolved_channel,
                headless=bool(headless),
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            response = await page.goto(
                cleaned_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)

            final_url = page.url
            title = await page.title()
            body = await page.content() if return_html else await page.inner_text("body")
            body, truncated = _truncate_text(body or "", max_chars)

            status_code = response.status if response is not None else None
            login_like = _looks_like_login_page(final_url, title)

            payload: dict[str, Any] = {
                "success": not login_like,
                "url": final_url,
                "requested_url": cleaned_url,
                "status_code": status_code,
                "title": title,
                "format": "html" if return_html else "text",
                "truncated": truncated,
                "profile_dir": str(resolved_profile),
                "channel": resolved_channel,
                "headless": bool(headless),
                "login_like": login_like,
            }

            if return_html:
                payload["html"] = body
            else:
                payload["text"] = body

            if login_like:
                payload["message"] = (
                    "로그인/인증 페이지로 보입니다. headless=false, wait_seconds를 늘리거나 "
                    "profile_dir에서 한 번 로그인한 뒤 다시 시도하세요."
                )
            else:
                payload["message"] = f"Chrome으로 페이지 조회 완료 (HTTP {status_code})"

            return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.exception("fetch_url_chrome 오류: %s", cleaned_url)
        hint = ""
        message = str(exc).lower()
        if "user data directory is already in use" in message or "profile" in message:
            hint = " Chrome이 이미 실행 중이면 종료하거나 별도 profile_dir을 사용하세요."
        return json.dumps(
            {
                "success": False,
                "message": f"Chrome URL 조회 실패: {exc}.{hint}",
                "url": cleaned_url,
                "profile_dir": str(resolved_profile),
            },
            ensure_ascii=False,
        )
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                logger.debug("Chrome context 종료 중 오류", exc_info=True)


def register_chrome_url_fetch_tools(mcp: "FastMCP") -> None:
    """Chrome URL 조회 도구 등록."""
    mcp.tool()(fetch_url_chrome)
    logger.info("Chrome URL 조회 도구 등록 완료: fetch_url_chrome")
