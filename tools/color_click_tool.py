"""
색상 기반 마우스 조작 Tool 정의
"""

import logging
from typing import Any

from actions.color_click_action import ColorClickAction

logger = logging.getLogger(__name__)


def register_color_click_tools(mcp: Any) -> None:
    """
    색상 기반 도구 등록

    Args:
        mcp: FastMCP 서버 인스턴스
    """

    @mcp.tool()
    async def right_click_by_rgb(
        r: int,
        g: int,
        b: int,
        tolerance: int = 5,
        step: int = 1,
        timeout: float | None = None,
    ) -> dict:
        """
        화면에서 특정 RGB 픽셀을 찾아 우클릭합니다.

        Args:
            r: Red (0~255)
            g: Green (0~255)
            b: Blue (0~255)
            tolerance: RGB 허용 오차 (기본: 5)
            step: 픽셀 스캔 간격 (기본: 1)
            timeout: 최대 탐색 시간 (초, None이면 제한 없음)
        """
        logger.info(
            "[Tool] right_click_by_rgb 호출: rgb=(%d,%d,%d) tol=%d step=%d timeout=%s",
            r,
            g,
            b,
            tolerance,
            step,
            timeout,
        )

        action = ColorClickAction((r, g, b), tolerance=tolerance, step=step)
        result = action.find_and_right_click(timeout=timeout)
        return result.to_dict()

    logger.info("색상 기반 도구 등록 완료: right_click_by_rgb")
