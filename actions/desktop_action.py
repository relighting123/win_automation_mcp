"""
데스크톱 공용 Action

UIA 제어가 어려운 상황을 위해 단축키/픽셀 기반 조작을 공통 기능으로 제공합니다.
다른 Action/Tool에서 재사용할 수 있는 상위 기능 계층입니다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DesktopActionResult:
    """데스크톱 조작 결과"""

    result: str
    message: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    shortcut: Optional[str] = None
    button: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.result == "success"

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "message": self.message,
            "x": self.x,
            "y": self.y,
            "shortcut": self.shortcut,
            "button": self.button,
            "is_success": self.is_success,
        }


class DesktopAction:
    """
    단축키/픽셀/마우스 기반 공용 Action
    """

    _KEY_ALIAS = {
        "control": "ctrl",
        "ctl": "ctrl",
        "cmd": "command",
        "option": "alt",
        "windows": "win",
    }

    def _get_pyautogui(self):
        try:
            import pyautogui
        except Exception as e:  # pragma: no cover
            logger.error("pyautogui 로드 실패: %s", e)
            return None, DesktopActionResult(result="error", message=f"pyautogui 로드 실패: {e}")
        return pyautogui, None

    def _normalize_keys(self, shortcut: str) -> list[str]:
        keys = [token.strip().lower() for token in shortcut.split("+") if token.strip()]
        keys = [self._KEY_ALIAS.get(key, key) for key in keys]
        return keys

    def _match(self, pixel: Sequence[int], rgb: Tuple[int, int, int], tolerance: int) -> bool:
        return all(abs(int(p) - int(t)) <= tolerance for p, t in zip(pixel, rgb))

    def press_shortcut(self, shortcut: str, interval: float = 0.05) -> DesktopActionResult:
        """
        단축키 입력

        Args:
            shortcut: 예) "ctrl+shift+r", "enter"
            interval: 조합키 입력 간격
        """
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        keys = self._normalize_keys(shortcut)
        if not keys:
            return DesktopActionResult(result="error", message="유효한 단축키를 입력해주세요")

        try:
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys, interval=max(0.0, interval))
            return DesktopActionResult(result="success", shortcut="+".join(keys))
        except Exception as e:
            logger.error("단축키 입력 실패: %s", e)
            return DesktopActionResult(result="error", message=f"단축키 입력 실패: {e}")

    def type_text(
        self,
        text: str,
        interval: float = 0.02,
        submit_shortcut: Optional[str] = None,
    ) -> DesktopActionResult:
        """
        텍스트 입력 후 선택적으로 제출 단축키를 입력합니다.
        """
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        try:
            pyautogui.write(text, interval=max(0.0, interval))
        except Exception as e:
            logger.error("텍스트 입력 실패: %s", e)
            return DesktopActionResult(result="error", message=f"텍스트 입력 실패: {e}")

        if submit_shortcut:
            submit_result = self.press_shortcut(submit_shortcut)
            if not submit_result.is_success:
                return submit_result

        return DesktopActionResult(result="success")

    def find_rgb_position(
        self,
        rgb: Tuple[int, int, int],
        tolerance: int = 5,
        step: int = 1,
        timeout: Optional[float] = None,
    ) -> DesktopActionResult:
        """
        화면에서 RGB 픽셀 위치를 찾습니다.
        """
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        tolerance = max(0, tolerance)
        step = max(1, step)
        start = time.monotonic()

        while True:
            screenshot = pyautogui.screenshot()
            width, height = screenshot.size
            pixels = screenshot.load()

            for y in range(0, height, step):
                for x in range(0, width, step):
                    if self._match(pixels[x, y], rgb, tolerance):
                        return DesktopActionResult(result="success", x=x, y=y)

            if timeout is None:
                return DesktopActionResult(result="not_found", message="RGB 위치를 찾을 수 없습니다")
            if timeout is not None and time.monotonic() - start > timeout:
                return DesktopActionResult(result="timeout", message="RGB 위치 탐색 시간 초과")

    def click_position(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> DesktopActionResult:
        """
        지정 좌표를 클릭합니다.
        """
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        button = button.lower()
        if button not in {"left", "right", "middle"}:
            return DesktopActionResult(result="error", message=f"지원하지 않는 버튼: {button}")

        try:
            pyautogui.moveTo(x, y)
            pyautogui.click(x=x, y=y, button=button, clicks=max(1, clicks))
            return DesktopActionResult(result="success", x=x, y=y, button=button)
        except Exception as e:
            logger.error("좌표 클릭 실패: %s", e)
            return DesktopActionResult(result="error", message=f"좌표 클릭 실패: {e}")

    def click_by_rgb(
        self,
        rgb: Tuple[int, int, int],
        tolerance: int = 5,
        step: int = 1,
        button: str = "left",
        timeout: Optional[float] = None,
    ) -> DesktopActionResult:
        """
        RGB 픽셀을 찾아 해당 위치를 클릭합니다.
        """
        find_result = self.find_rgb_position(
            rgb=rgb,
            tolerance=tolerance,
            step=step,
            timeout=timeout,
        )
        if not find_result.is_success:
            return find_result

        return self.click_position(
            x=find_result.x or 0,
            y=find_result.y or 0,
            button=button,
        )


def get_desktop_action() -> DesktopAction:
    """DesktopAction 인스턴스 반환"""
    return DesktopAction()
