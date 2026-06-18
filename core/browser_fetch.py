"""
Playwright persistent context로 URL 본문을 가져오는 헬퍼.

user_data_dir에 쿠키·SSO 세션을 유지합니다.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE_DIR = Path.home() / ".chatrtd" / "browser-profile"
_NAVIGATION_TIMEOUT_MS = 60_000


def _is_truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_browser_profile_dir() -> Path:
    raw = (
        os.getenv("CHATRTD_BROWSER_PROFILE_DIR")
        or os.getenv("PLAYWRIGHT_USER_DATA_DIR")
        or ""
    ).strip()
    profile = Path(raw).expanduser() if raw else _DEFAULT_PROFILE_DIR
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def resolve_headless() -> bool:
    if os.getenv("PLAYWRIGHT_HEADLESS") is not None:
        return _is_truthy(os.getenv("PLAYWRIGHT_HEADLESS"))
    return False


def resolve_browser_channel() -> Optional[str]:
    channel = (os.getenv("PLAYWRIGHT_CHANNEL") or "chrome").strip()
    return channel or None


def snapshot_to_text(snapshot: str) -> str:
    """AX/스냅샷 문자열에서 읽을 수 있는 텍스트를 추출합니다."""
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


async def _launch_persistent_context(playwright: Any) -> Any:
    profile_dir = resolve_browser_profile_dir()
    headless = resolve_headless()
    channel = resolve_browser_channel()

    launch_kwargs: dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "accept_downloads": False,
    }
    if channel:
        launch_kwargs["channel"] = channel

    try:
        return await playwright.chromium.launch_persistent_context(**launch_kwargs)
    except Exception as exc:
        if not channel:
            raise
        logger.warning("channel=%s 실행 실패, 내장 chromium으로 재시도: %s", channel, exc)
        launch_kwargs.pop("channel", None)
        return await playwright.chromium.launch_persistent_context(**launch_kwargs)


async def fetch_url_via_browser(url: str) -> str:
    target = (url or "").strip()
    if not target:
        return "[오류] url이 필요합니다."

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return (
            "[Playwright 미설치] pip install playwright 실행 후 "
            "playwright install chromium (또는 PLAYWRIGHT_CHANNEL=chrome)"
        )

    try:
        async with async_playwright() as playwright:
            context = await _launch_persistent_context(playwright)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(
                    target,
                    wait_until="domcontentloaded",
                    timeout=_NAVIGATION_TIMEOUT_MS,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass

                text = (await page.inner_text("body")).strip()
                if text:
                    return text

                title = await page.title()
                return f"(본문 없음, 제목: {title})"
            finally:
                await context.close()
    except Exception as exc:
        logger.exception("Playwright URL 수집 실패: %s", exc)
        return f"[오류] URL 수집 실패: {exc}"
