"""
픽셀 색상 기반 마우스 우클릭 Action

UIA 접근이 어려운 경우에만 사용하는 픽셀 기반 동작입니다.
해상도/스케일링/테마 변화에 민감합니다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

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

    def _match(self, pixel: Iterable[int]) -> bool:
        return all(abs(p - t) <= self.tolerance for p, t in zip(pixel, self.rgb))

    def find_and_right_click(self, timeout: Optional[float] = None) -> ColorClickResult:
        """
        화면에서 색상을 찾아 이동 후 우클릭합니다.

        Args:
            timeout: 탐색 제한 시간 (초, None이면 무제한)
        """
        try:
            import pyautogui
        except Exception as e:  # pragma: no cover
            logger.error(f"pyautogui 로드 실패: {e}")
            return ColorClickResult(result="error", message=f"pyautogui 로드 실패: {e}")

        start = time.monotonic()
        screenshot = pyautogui.screenshot()
        width, height = screenshot.size
        pixels = screenshot.load()

        for y in range(0, height, self.step):
            if timeout is not None and time.monotonic() - start > timeout:
                return ColorClickResult(result="timeout", message="색상 탐색 시간 초과")
            for x in range(0, width, self.step):
                if self._match(pixels[x, y]):
                    pyautogui.moveTo(x, y)
                    pyautogui.click(button="right")
                    return ColorClickResult(result="success", x=x, y=y)

        return ColorClickResult(result="not_found", message="RGB not found")
