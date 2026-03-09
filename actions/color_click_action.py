"""
픽셀 색상 기반 마우스 우클릭 Action

UIA 접근이 어려운 경우에만 사용하는 픽셀 기반 동작입니다.
해상도/스케일링/테마 변화에 민감합니다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from actions.desktop_action import DesktopAction

logger = logging.getLogger(__name__)


@dataclass
class ColorClickResult:
    """색상 탐색 결과"""

    result: str
    x: Optional[int] = None
    y: Optional[int] = None
    message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "x": self.x,
            "y": self.y,
            "message": self.message,
        }


class ColorClickAction:
    """
    특정 RGB를 찾아 우클릭하는 액션
    """

    def __init__(self, rgb: Tuple[int, int, int], tolerance: int = 5, step: int = 1):
        self.rgb = rgb
        self.tolerance = max(0, tolerance)
        self.step = max(1, step)
        self._desktop_action = DesktopAction()

    def find_and_right_click(self, timeout: Optional[float] = None) -> ColorClickResult:
        """
        화면에서 색상을 찾아 이동 후 우클릭합니다.

        Args:
            timeout: 탐색 제한 시간 (초, None이면 무제한)
        """
        result = self._desktop_action.click_by_rgb(
            rgb=self.rgb,
            tolerance=self.tolerance,
            step=self.step,
            button="right",
            timeout=timeout,
        )

        return ColorClickResult(
            result=result.result,
            x=result.x,
            y=result.y,
            message=result.message,
        )
