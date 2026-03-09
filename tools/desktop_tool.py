"""
공용 데스크톱 제어 Tool 정의

여러 업무 Tool에서 재사용할 수 있는 상위 기능을 제공합니다.
- 단축키 입력
- RGB 위치 탐색
- 좌표 클릭
- RGB 기반 클릭
- 텍스트(OCR) 위치 탐색
- 텍스트(OCR) 기반 클릭
"""

import logging
from typing import Any

from actions.desktop_action import get_desktop_action

logger = logging.getLogger(__name__)


def register_desktop_tools(mcp: Any) -> None:
    """
    공용 데스크톱 도구 등록

    Args:
        mcp: FastMCP 서버 인스턴스
    """

    @mcp.tool()
    async def press_shortcut(shortcut: str, interval: float = 0.05) -> dict:
        """
        지정한 단축키를 입력합니다.

        Args:
            shortcut: 예) "ctrl+shift+r", "enter"
            interval: 조합키 입력 간격
        """
        logger.info("[Tool] press_shortcut 호출: shortcut=%s", shortcut)
        action = get_desktop_action()
        result = action.press_shortcut(shortcut=shortcut, interval=interval)
        return result.to_dict()

    @mcp.tool()
    async def find_rgb_position(
        r: int,
        g: int,
        b: int,
        tolerance: int = 5,
        step: int = 1,
        timeout: float | None = None,
    ) -> dict:
        """
        화면에서 특정 RGB 위치를 찾습니다.

        Args:
            r: Red (0~255)
            g: Green (0~255)
            b: Blue (0~255)
            tolerance: RGB 허용 오차
            step: 픽셀 스캔 간격
            timeout: 최대 탐색 시간
        """
        logger.info(
            "[Tool] find_rgb_position 호출: rgb=(%d,%d,%d), tol=%d, step=%d, timeout=%s",
            r,
            g,
            b,
            tolerance,
            step,
            timeout,
        )
        action = get_desktop_action()
        result = action.find_rgb_position(
            rgb=(r, g, b),
            tolerance=tolerance,
            step=step,
            timeout=timeout,
        )
        return result.to_dict()

    @mcp.tool()
    async def click_position(
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> dict:
        """
        지정한 좌표를 클릭합니다.

        Args:
            x: X 좌표
            y: Y 좌표
            button: left/right/middle
            clicks: 클릭 횟수
        """
        logger.info("[Tool] click_position 호출: x=%d, y=%d, button=%s, clicks=%d", x, y, button, clicks)
        action = get_desktop_action()
        result = action.click_position(x=x, y=y, button=button, clicks=clicks)
        return result.to_dict()

    @mcp.tool()
    async def click_by_rgb(
        r: int,
        g: int,
        b: int,
        tolerance: int = 5,
        step: int = 1,
        button: str = "left",
        timeout: float | None = None,
    ) -> dict:
        """
        RGB 픽셀을 찾아 해당 위치를 클릭합니다.

        Args:
            r: Red (0~255)
            g: Green (0~255)
            b: Blue (0~255)
            tolerance: RGB 허용 오차
            step: 픽셀 스캔 간격
            button: left/right/middle
            timeout: 최대 탐색 시간
        """
        logger.info(
            "[Tool] click_by_rgb 호출: rgb=(%d,%d,%d), tol=%d, step=%d, button=%s, timeout=%s",
            r,
            g,
            b,
            tolerance,
            step,
            button,
            timeout,
        )
        action = get_desktop_action()
        result = action.click_by_rgb(
            rgb=(r, g, b),
            tolerance=tolerance,
            step=step,
            button=button,
            timeout=timeout,
        )
        return result.to_dict()

    @mcp.tool()
    async def find_text_position(
        text: str,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        timeout: float | None = None,
        min_confidence: float = 50.0,
        language: str = "eng",
    ) -> dict:
        """
        OCR로 화면에서 특정 텍스트 위치를 찾습니다.

        Args:
            text: 찾을 텍스트
            match_mode: contains 또는 exact
            case_sensitive: 대소문자 구분 여부
            timeout: 최대 탐색 시간
            min_confidence: OCR 최소 신뢰도 (0~100)
            language: tesseract 언어 코드 (기본: eng)
        """
        logger.info(
            "[Tool] find_text_position 호출: text=%s, mode=%s, timeout=%s",
            text,
            match_mode,
            timeout,
        )
        action = get_desktop_action()
        result = action.find_text_position(
            text=text,
            match_mode=match_mode,
            case_sensitive=case_sensitive,
            timeout=timeout,
            min_confidence=min_confidence,
            language=language,
        )
        return result.to_dict()

    @mcp.tool()
    async def click_by_text(
        text: str,
        button: str = "left",
        clicks: int = 1,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        timeout: float | None = None,
        min_confidence: float = 50.0,
        language: str = "eng",
    ) -> dict:
        """
        OCR로 텍스트를 찾아 해당 위치를 클릭합니다.

        Args:
            text: 찾을 텍스트
            button: left/right/middle
            clicks: 클릭 횟수
            match_mode: contains 또는 exact
            case_sensitive: 대소문자 구분 여부
            timeout: 최대 탐색 시간
            min_confidence: OCR 최소 신뢰도 (0~100)
            language: tesseract 언어 코드 (기본: eng)
        """
        logger.info(
            "[Tool] click_by_text 호출: text=%s, button=%s, clicks=%d, mode=%s, timeout=%s",
            text,
            button,
            clicks,
            match_mode,
            timeout,
        )
        action = get_desktop_action()
        result = action.click_by_text(
            text=text,
            button=button,
            clicks=clicks,
            match_mode=match_mode,
            case_sensitive=case_sensitive,
            timeout=timeout,
            min_confidence=min_confidence,
            language=language,
        )
        return result.to_dict()

    logger.info(
        "공용 데스크톱 도구 등록 완료: press_shortcut, find_rgb_position, click_position, click_by_rgb, "
        "find_text_position, click_by_text"
    )
