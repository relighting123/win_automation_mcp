"""
애플리케이션 UI 제어 Action (픽셀/OCR 기반)

UIA 제어가 어려운 상황을 위해 화면 캡처 및 OCR 기반 조작 기능을 제공합니다.
전체 데스크톱이 아닌 현재 연결된 애플리케이션 윈도우 영역을 우선적으로 탐색합니다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from core.app_session import AppSession

logger = logging.getLogger(__name__)


@dataclass
class AppUIActionResult:
    """애플리케이션 UI 조작 결과"""

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


class AppUIAction:
    """
    OCR/픽셀/마우스 기반 애플리케이션 UI 제어 Action
    """

    _KEY_ALIAS = {
        "control": "ctrl",
        "ctl": "ctrl",
        "cmd": "command",
        "option": "alt",
        "windows": "win",
    }

    def __init__(self, session: Optional[AppSession] = None):
        self._session = session or AppSession.get_instance()

    def _get_app_window_region(self) -> Optional[Tuple[int, int, int, int]]:
        """
        현재 연결된 애플리케이션의 메인 윈도우 영역(left, top, width, height)을 반환합니다.
        연결되지 않은 경우 연결을 시도합니다.
        """
        try:
            if not self._session.is_connected:
                logger.info("세션이 연결되지 않아 연결을 시도합니다.")
                self._session.connect()
            
            if not self._session.is_connected:
                return None
            
            # 메인 윈도우 가져오기 시도
            from ui.main_window import MainWindow
            main_win = MainWindow(self._session)
            if main_win.exists():
                rect = main_win.window.rectangle()
                # rect: (left, top, right, bottom)
                return (rect.left, rect.top, rect.width(), rect.height())
        except Exception as e:
            logger.debug(f"윈도우 영역 획득 실패: {e}")
        
        return None

    def ensure_focus(self) -> AppUIActionResult:
        """애플리케이션 윈도우를 최상단으로 가져오고 포커스를 설정합니다."""
        try:
            if not self._session.is_connected:
                self._session.connect()
            
            from ui.main_window import MainWindow
            main_win = MainWindow(self._session)
            if main_win.exists():
                main_win.focus()
                # 윈도우 활성화 대기 (필요시)
                time.sleep(0.5)
                return AppUIActionResult(result="success", message="애플리케이션 포커스 설정 완료")
            return AppUIActionResult(result="error", message="메인 윈도우를 찾을 수 없습니다")
        except Exception as e:
            logger.error(f"포커스 설정 실패: {e}")
            return AppUIActionResult(result="error", message=f"포커스 설정 실패: {e}")

    def _get_best_winocr_lang(self, requested_lang: str) -> str:
        """
        요청된 언어 또는 매핑된 언어가 Windows OCR에서 지원되는지 확인하고 최적의 언어 코드를 반환합니다.
        """
        import winocr
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language

        # Tesseract 코드(eng, kor) -> Windows 코드(en, ko)
        lang_map = {"eng": "en", "kor": "ko"}
        
        candidates = []
        for l in requested_lang.split(","):
            l = l.strip().lower()
            if not l:
                continue
            mapped = lang_map.get(l, l)
            candidates.append(mapped)
        
        # 시스템 기본값 및 일반적인 후보군 추가
        candidates.extend(["ko", "en-US", "en-GB", "en"])

        for cand in candidates:
            try:
                if OcrEngine.is_language_supported(Language(cand)):
                    return cand
            except Exception:
                continue
        
        return "en-US"  # 최후의 수단

    def _get_pyautogui(self):
        try:
            import pyautogui
        except Exception as e:  # pragma: no cover
            logger.error("pyautogui 로드 실패: %s", e)
            return None, AppUIActionResult(result="error", message=f"pyautogui 로드 실패: {e}")
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

    def press_shortcut(self, shortcut: str, interval: float = 0.05) -> AppUIActionResult:
        """단축키 입력"""
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        keys = self._normalize_keys(shortcut)
        if not keys:
            return AppUIActionResult(result="error", message="유효한 단축키를 입력해주세요")

        try:
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys, interval=max(0.0, interval))
            return AppUIActionResult(result="success", shortcut="+".join(keys))
        except Exception as e:
            logger.error("단축키 입력 실패: %s", e)
            return AppUIActionResult(result="error", message=f"단축키 입력 실패: {e}")

    def type_text(
        self,
        text: str,
        interval: float = 0.02,
    ) -> AppUIActionResult:
        """텍스트 입력"""
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        try:
            pyautogui.write(text, interval=max(0.0, interval))
            return AppUIActionResult(result="success")
        except Exception as e:
            logger.error("텍스트 입력 실패: %s", e)
            return AppUIActionResult(result="error", message=f"텍스트 입력 실패: {e}")

    def find_rgb_position(
        self,
        rgb: Tuple[int, int, int],
        tolerance: int = 5,
        step: int = 1,
        timeout: Optional[float] = None,
    ) -> AppUIActionResult:
        """화면에서 RGB 픽셀 위치를 찾습니다."""
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        tolerance = max(0, tolerance)
        step = max(1, step)
        start = time.monotonic()

        region = self._get_app_window_region()

        while True:
            screenshot = pyautogui.screenshot(region=region)
            width, height = screenshot.size
            pixels = screenshot.load()

            for y in range(0, height, step):
                for x in range(0, width, step):
                    if self._match(pixels[x, y], rgb, tolerance):
                        # 리전이 있는 경우 절대 좌표로 변환
                        final_x = x + (region[0] if region else 0)
                        final_y = y + (region[1] if region else 0)
                        return AppUIActionResult(result="success", x=final_x, y=final_y)

            if timeout is None:
                return AppUIActionResult(result="not_found", message="RGB 위치를 찾을 수 없습니다")
            if timeout is not None and time.monotonic() - start > timeout:
                return AppUIActionResult(result="timeout", message="RGB 위치 탐색 시간 초과")

    def click_position(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> AppUIActionResult:
        """지정 좌표를 클릭합니다."""
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        button = button.lower()
        if button not in {"left", "right", "middle"}:
            return AppUIActionResult(result="error", message=f"지원하지 않는 버튼: {button}")

        try:
            pyautogui.moveTo(x, y)
            pyautogui.click(x=x, y=y, button=button, clicks=max(1, clicks))
            return AppUIActionResult(result="success", x=x, y=y, button=button)
        except Exception as e:
            logger.error("좌표 클릭 실패: %s", e)
            return AppUIActionResult(result="error", message=f"좌표 클릭 실패: {e}")

    async def find_text_position(
        self,
        text: str,
        *,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        timeout: Optional[float] = None,
        language: str = "eng",
    ) -> AppUIActionResult:
        """OCR로 애플리케이션 화면에서 텍스트 위치를 찾습니다."""
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        target_text = " ".join(text.split())
        if not target_text:
            return AppUIActionResult(result="error", message="찾을 텍스트가 비어 있습니다")

        match_mode = match_mode.lower().strip()
        if match_mode not in {"contains", "exact"}:
            return AppUIActionResult(result="error", message=f"지원하지 않는 match_mode: {match_mode}")

        try:
            import winocr
        except Exception as e:
            return AppUIActionResult(result="error", message=f"winocr 로드 실패: {e}")

        # 최적의 언어 선택
        lang = self._get_best_winocr_lang(language)
        
        target_norm = self._normalize_text(target_text, case_sensitive=case_sensitive)
        start = time.monotonic()

        # 앱 윈도우 영역 획득
        region = self._get_app_window_region()
        
        while True:
            screenshot = pyautogui.screenshot(region=region)
            
            # Windows OCR 실행
            raw_ocr_result = await winocr.recognize_pil(screenshot, lang)
            ocr_result = winocr.picklify(raw_ocr_result)
            
            for line in ocr_result.get("lines", []):
                for word in line.get("words", []):
                    raw_text = word.get("text", "")
                    
                    candidate = self._normalize_text(raw_text, case_sensitive=case_sensitive)
                    matched = False
                    if match_mode == "exact":
                        matched = candidate == target_norm
                    else:
                        matched = target_norm in candidate
                    
                    if matched:
                        rect = word.get("bounding_rect", {})
                        # 리전 내의 상대 좌표를 획득
                        rel_x = int(rect.get("x", 0) + rect.get("width", 0) / 2)
                        rel_y = int(rect.get("y", 0) + rect.get("height", 0) / 2)
                        
                        # 절대 좌표로 변환
                        center_x = rel_x + (region[0] if region else 0)
                        center_y = rel_y + (region[1] if region else 0)
                        
                        return AppUIActionResult(
                            result="success",
                            x=center_x,
                            y=center_y,
                            matched_text=raw_text,
                        )

            if timeout is None:
                return AppUIActionResult(result="not_found", message="텍스트를 찾을 수 없습니다")
            if time.monotonic() - start > timeout:
                return AppUIActionResult(result="timeout", message="텍스트 탐색 시간 초과")

    def find_image_position(
        self,
        image_path: str,
        *,
        confidence: Optional[float] = None,
        grayscale: bool = False,
        timeout: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> AppUIActionResult:
        """화면에서 이미지(아이콘/그림) 위치를 찾습니다."""
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        target = Path(image_path)
        if not target.exists() or not target.is_file():
            return AppUIActionResult(result="error", message=f"이미지 파일을 찾을 수 없습니다: {image_path}")

        # 기본 region이 없으면 앱 윈도우 지원
        search_region = region or self._get_app_window_region()

        start = time.monotonic()

        while True:
            locate_kwargs = {"grayscale": grayscale}
            if search_region is not None:
                locate_kwargs["region"] = search_region
            if confidence is not None:
                locate_kwargs["confidence"] = confidence

            box = pyautogui.locateOnScreen(str(target), **locate_kwargs)

            if box is not None:
                center = pyautogui.center(box)
                return AppUIActionResult(result="success", x=int(center.x), y=int(center.y))

            if timeout is None:
                return AppUIActionResult(result="not_found", message="이미지를 찾을 수 없습니다")
            if time.monotonic() - start > timeout:
                return AppUIActionResult(result="timeout", message="이미지 탐색 시간 초과")


def get_app_ui_action(session: Optional[AppSession] = None) -> AppUIAction:
    """AppUIAction 인스턴스 반환"""
    return AppUIAction(session)
