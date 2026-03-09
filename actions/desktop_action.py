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
    matched_text: Optional[str] = None

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
            "matched_text": self.matched_text,
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

    def _normalize_text(self, value: str, case_sensitive: bool) -> str:
        text = " ".join(value.split())
        return text if case_sensitive else text.lower()

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

    def find_text_position(
        self,
        text: str,
        *,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        timeout: Optional[float] = None,
        min_confidence: float = 50.0,
        language: str = "eng",
    ) -> DesktopActionResult:
        """
        OCR로 화면에서 텍스트 위치를 찾습니다.

        Args:
            text: 찾을 텍스트 문자열
            match_mode: "contains" 또는 "exact"
            case_sensitive: 대소문자 구분 여부
            timeout: 최대 탐색 시간(None이면 1회만 탐색)
            min_confidence: OCR 최소 신뢰도 (0~100)
            language: tesseract 언어 코드(기본: eng)
        """
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        target_text = " ".join(text.split())
        if not target_text:
            return DesktopActionResult(result="error", message="찾을 텍스트가 비어 있습니다")

        match_mode = match_mode.lower().strip()
        if match_mode not in {"contains", "exact"}:
            return DesktopActionResult(result="error", message=f"지원하지 않는 match_mode: {match_mode}")

        try:
            import pytesseract
            from pytesseract import Output
        except Exception as e:  # pragma: no cover
            return DesktopActionResult(
                result="error",
                message=f"pytesseract 로드 실패: {e}. pip install pytesseract 후 사용하세요.",
            )

        try:
            _ = pytesseract.get_tesseract_version()
        except Exception as e:  # pragma: no cover
            return DesktopActionResult(
                result="error",
                message=f"Tesseract 실행 파일을 찾을 수 없습니다: {e}",
            )

        target_norm = self._normalize_text(target_text, case_sensitive=case_sensitive)
        target_words = target_norm.split()
        start = time.monotonic()

        while True:
            screenshot = pyautogui.screenshot()
            ocr_data = pytesseract.image_to_data(
                screenshot,
                lang=language,
                output_type=Output.DICT,
            )

            # line 단위 그룹핑을 위해 word 결과를 먼저 정리합니다.
            line_groups: dict[tuple[int, int, int], list[tuple[str, int, int, int, int]]] = {}
            total = len(ocr_data.get("text", []))
            for i in range(total):
                raw_text = str(ocr_data["text"][i] or "").strip()
                if not raw_text:
                    continue

                try:
                    confidence = float(ocr_data["conf"][i])
                except Exception:
                    confidence = -1.0
                if confidence < min_confidence:
                    continue

                left = int(ocr_data["left"][i])
                top = int(ocr_data["top"][i])
                width = int(ocr_data["width"][i])
                height = int(ocr_data["height"][i])
                block = int(ocr_data["block_num"][i])
                paragraph = int(ocr_data["par_num"][i])
                line = int(ocr_data["line_num"][i])

                key = (block, paragraph, line)
                line_groups.setdefault(key, []).append((raw_text, left, top, width, height))

            # 1) 단일 단어 탐색
            if len(target_words) == 1:
                needle = target_words[0]
                for words in line_groups.values():
                    for word_text, left, top, width, height in words:
                        candidate = self._normalize_text(word_text, case_sensitive=case_sensitive)
                        matched = candidate == needle if match_mode == "exact" else needle in candidate
                        if matched:
                            return DesktopActionResult(
                                result="success",
                                x=left + width // 2,
                                y=top + height // 2,
                                matched_text=word_text,
                            )
            else:
                # 2) 다중 단어(문구) 탐색: line 내 연속 단어 슬라이딩 윈도우
                target_len = len(target_words)
                for words in line_groups.values():
                    sorted_words = sorted(words, key=lambda item: item[1])
                    normalized_words = [
                        self._normalize_text(word_text, case_sensitive=case_sensitive)
                        for word_text, _, _, _, _ in sorted_words
                    ]

                    for start_idx in range(0, len(normalized_words)):
                        if match_mode == "exact":
                            end_idx = start_idx + target_len
                            if end_idx > len(normalized_words):
                                continue
                            segment = " ".join(normalized_words[start_idx:end_idx])
                            if segment != target_norm:
                                continue
                        else:
                            end_idx = len(normalized_words)
                            found = False
                            for j in range(start_idx + target_len, len(normalized_words) + 1):
                                segment = " ".join(normalized_words[start_idx:j])
                                if target_norm in segment:
                                    end_idx = j
                                    found = True
                                    break
                            if not found:
                                continue

                        matched_chunk = sorted_words[start_idx:end_idx]
                        left = min(item[1] for item in matched_chunk)
                        top = min(item[2] for item in matched_chunk)
                        right = max(item[1] + item[3] for item in matched_chunk)
                        bottom = max(item[2] + item[4] for item in matched_chunk)

                        return DesktopActionResult(
                            result="success",
                            x=(left + right) // 2,
                            y=(top + bottom) // 2,
                            matched_text=" ".join(item[0] for item in matched_chunk),
                        )

            if timeout is None:
                return DesktopActionResult(result="not_found", message="텍스트를 찾을 수 없습니다")
            if time.monotonic() - start > timeout:
                return DesktopActionResult(result="timeout", message="텍스트 탐색 시간 초과")

    def click_by_text(
        self,
        text: str,
        *,
        button: str = "left",
        clicks: int = 1,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        timeout: Optional[float] = None,
        min_confidence: float = 50.0,
        language: str = "eng",
    ) -> DesktopActionResult:
        """
        OCR로 텍스트를 찾아 해당 위치를 클릭합니다.
        """
        find_result = self.find_text_position(
            text=text,
            match_mode=match_mode,
            case_sensitive=case_sensitive,
            timeout=timeout,
            min_confidence=min_confidence,
            language=language,
        )
        if not find_result.is_success:
            return find_result

        click_result = self.click_position(
            x=find_result.x or 0,
            y=find_result.y or 0,
            button=button,
            clicks=clicks,
        )
        if click_result.is_success:
            click_result.matched_text = find_result.matched_text
        return click_result


def get_desktop_action() -> DesktopAction:
    """DesktopAction 인스턴스 반환"""
    return DesktopAction()
