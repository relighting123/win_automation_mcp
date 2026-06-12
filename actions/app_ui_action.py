"""
애플리케이션 UI 제어 Action (픽셀/OCR 기반)

UIA 제어가 어려운 상황을 위해 화면 캡처 및 OCR 기반 조작 기능을 제공합니다.
전체 데스크톱이 아닌 현재 연결된 애플리케이션 윈도우 영역을 우선적으로 탐색합니다.
"""

from __future__ import annotations

import logging
import time
import asyncio
import re
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.app_session import AppSession
from core.app_launcher import get_launcher

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
        self._launcher = get_launcher()

    def _get_desktop_region(self, pyautogui: Any) -> Tuple[int, int, int, int]:
        """전체 PC 화면 영역(left, top, width, height)을 반환합니다."""
        size = pyautogui.size()
        return (0, 0, int(size.width), int(size.height))

    def _wrapper_to_region(
        self,
        wrapper: Any,
        *,
        expand_px: int = 4,
    ) -> Optional[Tuple[int, int, int, int]]:
        """wrapper의 화면 영역(left, top, width, height)을 반환합니다."""
        if wrapper is None:
            return None
        try:
            rect = wrapper.rectangle()
            left = int(rect.left) - max(0, expand_px)
            top = int(rect.top) - max(0, expand_px)
            width = int(rect.width()) + (2 * max(0, expand_px))
            height = int(rect.height()) + (2 * max(0, expand_px))
            if left < 0:
                width += left
                left = 0
            if top < 0:
                height += top
                top = 0
            if width <= 0 or height <= 0:
                return None
            return (left, top, width, height)
        except Exception as e:
            logger.debug("wrapper 영역 획득 실패: %s", e)
            return None

    def _get_app_window_region(self, wrapper: Optional[Any] = None) -> Optional[Tuple[int, int, int, int]]:
        """
        현재 연결된 애플리케이션의 메인 윈도우 영역(left, top, width, height)을 반환합니다.
        연결되지 않은 경우 연결을 시도합니다.
        """
        try:
            if wrapper is not None:
                return self._wrapper_to_region(wrapper)

            if not self._session.is_connected:
                logger.info("세션이 연결되지 않아 애플리케이션 실행/연결을 시도합니다.")
                self._launcher.ensure_running()

            if not self._session.is_connected:
                return None

            picked = self._pick_target_window()
            return self._wrapper_to_region(picked)
        except Exception as e:
            logger.debug(f"윈도우 영역 획득 실패: {e}")

        return None

    def _iter_rgb_search_targets(
        self,
        *,
        window_target: str = "auto",
        child_window_title: Optional[str] = None,
        child_window_auto_id: Optional[str] = None,
        child_window_match_mode: str = "contains",
        case_sensitive: bool = False,
        region_expand_px: int = 4,
    ) -> list[tuple[str, Any, Tuple[int, int, int, int]]]:
        """
        RGB 탐색에 사용할 (label, wrapper, region) 목록을 반환합니다.

        - auto + child 미지정: pick된 top window 1개 (legacy)
        - top: 프로세스 top window + child window(Find 등) 영역 순회
        - child/auto+child: child_window_title/auto_id로 좁힌 영역
        """
        target_mode = (window_target or "top").strip().lower()
        child_title = (child_window_title or "").strip()
        child_auto_id = (child_window_auto_id or "").strip()
        legacy_single = target_mode == "auto" and not child_title and not child_auto_id

        if legacy_single:
            wrapper = self._pick_target_window() or self._session.get_top_window()
            region = self._wrapper_to_region(wrapper, expand_px=region_expand_px)
            if wrapper is not None and region is not None:
                return [("auto->single", wrapper, region)]
            return []

        targets: list[tuple[str, Any, Tuple[int, int, int, int]]] = []
        top_windows = self._iter_process_top_windows()
        if not top_windows:
            picked = self._pick_target_window()
            top_windows = [picked] if picked is not None else []

        for top_window in top_windows:
            top_label = self._format_window_label(top_window)
            search_roots = self._iter_attr_search_roots(
                window_target=window_target,
                child_window_title=child_window_title,
                child_window_auto_id=child_window_auto_id,
                child_window_match_mode=child_window_match_mode,
                case_sensitive=case_sensitive,
                top_window_override=top_window,
            )
            for search_root, search_root_info in search_roots:
                if search_root is None:
                    logger.info(
                        "[rgb] search_root 없음: top=%s, info=%s",
                        top_label,
                        search_root_info,
                    )
                    continue
                region = self._wrapper_to_region(search_root, expand_px=region_expand_px)
                if region is None:
                    continue
                targets.append((f"{search_root_info} (top={top_label})", search_root, region))
        return targets

    def ensure_focus(self, *, invalidate_cache: bool = False) -> AppUIActionResult:
        """애플리케이션 윈도우를 최상단으로 가져오고 포커스를 설정합니다."""
        try:
            # 애플리케이션 실행 중인지 확인하고, 아니면 실행 (Auto-Launch)
            self._launcher.ensure_running()
            
            if not self._session.is_connected:
                # 연결 시도
                try:
                    self._session.connect()
                except Exception as e:
                    return AppUIActionResult(result="error", message=f"애플리케이션 연결 실패: {e}")

            if invalidate_cache:
                self._session.cached_window = None

            wrapper = self._pick_target_window()
            if wrapper is None:
                # 마지막 수단: top_window() 시도
                try:
                    wrapper = self._safe_call(lambda: self._session.app.top_window().wrapper_object(), None)
                except Exception:
                    pass
                
            if wrapper is None:
                return AppUIActionResult(result="error", message="포커스를 줄 수 있는 앱 윈도우를 찾지 못했습니다")

            activated = self._activate_window(wrapper)
            if not activated:
                logger.warning(
                    "포커스 활성화가 완전히 확인되지 않았습니다. title=%s",
                    self._safe_call(wrapper.window_text, ""),
                )

            return AppUIActionResult(
                result="success",
                message=f"애플리케이션 포커스 설정 완료: {self._safe_call(wrapper.window_text, '')}",
            )
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

    def _safe_call(self, func, default=None):
        try:
            return func()
        except Exception:
            return default

    def _rect_to_dict(self, rect: Any) -> dict:
        if rect is None:
            return {}
        return {
            "left": int(self._safe_call(lambda: rect.left, 0) or 0),
            "top": int(self._safe_call(lambda: rect.top, 0) or 0),
            "right": int(self._safe_call(lambda: rect.right, 0) or 0),
            "bottom": int(self._safe_call(lambda: rect.bottom, 0) or 0),
            "width": int(self._safe_call(lambda: rect.width(), 0) or 0),
            "height": int(self._safe_call(lambda: rect.height(), 0) or 0),
            "center_x": int(self._safe_call(lambda: rect.left + (rect.width() / 2), 0) or 0),
            "center_y": int(self._safe_call(lambda: rect.top + (rect.height() / 2), 0) or 0),
        }

    def _verify_process_path(self, wrapper: Any) -> bool:
        """윈도우의 프로세스 경로가 설정된 실행 경로와 일치하는지 확인합니다."""
        target_path = self._session.config.get("application", {}).get("executable_path")
        if not target_path:
            return True  # 경로가 설정되어 있지 않으면 검사 생략 (Loose matching)

        try:
            import psutil
            pid = self._safe_call(lambda: wrapper.element_info.process_id, None)
            if pid is None:
                return False
            
            proc = psutil.Process(pid)
            actual_path = self._safe_call(lambda: proc.exe(), "").lower().replace('/', '\\')
            target_path_norm = target_path.lower().replace('/', '\\')
            
            match = (actual_path == target_path_norm)
            if not match:
                logger.debug(f"Process path MISMATCH: Actual='{actual_path}', Expected='{target_path_norm}'")
            return match
        except Exception as e:
            logger.debug(f"프로세스 경로 검증 중 오류: {e}")
            return False

    def _pick_target_window(self) -> Optional[Any]:
        """현재 앱에서 가장 가능성이 높은 대상 윈도우 wrapper를 반환합니다."""
        # 0. [개선] 현재 시스템에서 포커스를 가진(Foreground) 윈도우가 우리 앱의 것이라면 최우선 선택
        try:
            import win32gui
            import win32process
            
            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd:
                _, fg_pid = win32process.GetWindowThreadProcessId(fg_hwnd)
                
                # 세션 연결 시도 (아직 안 되어 있다면, 없으면 실행)
                if not self._session.is_connected:
                    self._safe_call(self._launcher.ensure_running, None)
                
                if self._session.is_connected:
                    target_pid = getattr(self._session.app, 'process', None)
                    if target_pid and fg_pid == target_pid:
                        # 현재 포커스된 창이 우리 앱의 것이라면 해당 창을 그대로 사용
                        from pywinauto.controls.hwndwrapper import HwndWrapper
                        wrapper = HwndWrapper(fg_hwnd)
                        if self._safe_call(lambda: wrapper.is_visible(), False):
                            logger.debug(f"현재 활성화된 윈도우를 타겟으로 선택: '{self._safe_call(wrapper.window_text, '')}'")
                            self._session.cached_window = wrapper
                            return wrapper
        except Exception as e:
            logger.debug(f"Foreground window 체크 중 오류 (무시): {e}")

        # 1. 캐시된 윈도우가 유효한지 먼저 확인 (성능 최적화)
        cached = self._session.cached_window
        if cached:
            try:
                if cached.exists() and (cached.is_visible() or cached.is_minimized()):
                    return cached
            except Exception:
                self._session.cached_window = None


        try:
            if not self._session.is_connected:
                self._launcher.ensure_running()
            
            app_config = self._session.config.get("application", {})
            target_proc_name = app_config.get("process_name", "").lower()
            
            # 1) 세션에 연결된 앱의 윈도우들 중 가시적인 것 확인
            windows = self._session.app.windows()
            for i, w in enumerate(windows):
                wrapper = self._safe_call(lambda: w.wrapper_object(), None)
                if wrapper is None:
                    try:
                        wrapper = w
                    except Exception:
                        continue
                
                # 경로 검증
                is_valid_path = self._verify_process_path(wrapper)
                title = self._safe_call(wrapper.window_text, "unknown")
                logger.debug(f"윈도우 '{title}' 검사: path_valid={is_valid_path}")
                
                if not is_valid_path:
                    continue

                is_visible = self._safe_call(lambda: wrapper.is_visible(), False)
                is_minimized = self._safe_call(lambda: wrapper.is_minimized(), False)
                
                if is_visible or is_minimized:
                    logger.debug(f"적합한 상위 윈도우 발견: '{title}' (visible={is_visible}, minimized={is_minimized})")
                    self._session.cached_window = wrapper
                    return wrapper
            
            # 2) 가시성은 없지만 핸들이 있는 첫 번째 유효한 윈도우
            for w in windows:
                wrapper = self._safe_call(lambda: w.wrapper_object(), None)
                if wrapper and self._verify_process_path(wrapper):
                    title = self._safe_call(wrapper.window_text, "unknown")
                    logger.debug(f"가시성은 없지만 경로가 일치하는 윈도우 발견: '{title}'")
                    self._session.cached_window = wrapper
                    return wrapper

            # 3) fallback: 전체 데스크톱에서 경로가 정확히 일치하는 윈도우 탐색
            if target_proc_name:
                try:
                    from pywinauto import Desktop
                    logger.debug(f"데스크톱 Fallback 탐색 시작 (프로세스명: {target_proc_name})")
                    
                    desktop_windows = Desktop(backend=self._session.backend).windows()
                    for w in desktop_windows:
                        wrapper = self._safe_call(lambda: w.wrapper_object(), None)
                        if not wrapper:
                            continue
                        
                        try:
                            import psutil
                            pid = wrapper.element_info.process_id
                            proc = psutil.Process(pid)
                            proc_name = proc.name().lower()
                        except Exception:
                            proc_name = ""

                        if proc_name == target_proc_name:
                            is_visible = self._safe_call(lambda: wrapper.is_visible(), False)
                            if is_visible:
                                title = self._safe_call(wrapper.window_text, "")
                                logger.info(f"프로세스 매칭으로 윈도우 발견: '{title}' (PID: {pid})")
                                self._session.cached_window = wrapper
                                return wrapper
                except Exception as e:
                    logger.debug(f"Fallback 탐색 중 오류: {e}")

            return None
        except Exception as e:
            logger.debug("대상 윈도우 선택 실패: %s", e)
            return None

    def _get_window_search_identity(self, wrapper: Any) -> Dict[str, str]:
        """탐색 중인 창의 title/auto_id 등 핵심 식별 정보를 반환합니다."""
        title_candidates = self._get_node_title_candidates(wrapper)
        title = title_candidates[0] if title_candidates else ""

        handle = self._get_wrapper_handle(wrapper)
        if not title and handle:
            try:
                import win32gui

                win32_title = str(win32gui.GetWindowText(handle) or "").strip()
                if win32_title:
                    title = win32_title
            except Exception:
                pass

        auto_id = str(self._safe_call(lambda: wrapper.element_info.automation_id, "") or "").strip()
        control_id = str(self._safe_call(lambda: wrapper.element_info.control_id, "") or "").strip()
        control_type = str(self._safe_call(lambda: wrapper.element_info.control_type, "") or "").strip()
        class_name = str(self._safe_call(lambda: wrapper.element_info.class_name, "") or "").strip()
        return {
            "title": title or "-",
            "auto_id": auto_id or "-",
            "control_id": control_id or "-",
            "uia_control_type": control_type or "-",
            "class_name": class_name or "-",
            "hwnd": str(handle) if handle else "-",
        }

    def _format_search_window_log(self, wrapper: Any) -> str:
        """click/rgb 탐색 로그용 창 식별 문자열."""
        info = self._get_window_search_identity(wrapper)
        return (
            f"title={info['title']}, auto_id={info['auto_id']}, "
            f"control_id={info['control_id']}, uia_type={info['uia_control_type']}, hwnd={info['hwnd']}"
        )

    def _log_search_window(self, *, tool: str, wrapper: Any, scope: str = "") -> None:
        info = self._get_window_search_identity(wrapper)
        logger.info(
            "[%s] 현재 탐색 창: title=%s, auto_id=%s, control_id=%s, uia_type=%s, hwnd=%s, scope=%s",
            tool,
            info["title"],
            info["auto_id"],
            info["control_id"],
            info["uia_control_type"],
            info["hwnd"],
            scope or "-",
        )

    def _safe_draw_outline(
        self,
        node: Any,
        *,
        colour: str,
        label: str = "",
    ) -> None:
        try:
            node.draw_outline(colour=colour)
            logger.info(
                "[outline] %s colour=%s node=%s",
                label or "highlight",
                colour,
                self._format_search_window_log(node),
            )
        except Exception as e:
            logger.warning("outline 실패 (%s): %s", label or "highlight", e)

    def _colour_to_win32_rgb(self, colour: str) -> int:
        colours = {
            "green": 0x00FF00,
            "blue": 0xFF0000,
            "red": 0x0000FF,
        }
        normalized = (colour or "green").strip().lower()
        if normalized in colours:
            return colours[normalized]
        return colours["green"]

    def _safe_draw_screen_rect_outline(
        self,
        *,
        left: int,
        top: int,
        right: int,
        bottom: int,
        colour: str,
        thickness: int = 3,
        label: str = "",
    ) -> None:
        try:
            import win32con
            import win32gui

            rgb = self._colour_to_win32_rgb(colour)
            hdc = win32gui.GetDC(0)
            pen = win32gui.CreatePen(win32con.PS_SOLID, thickness, rgb)
            old_pen = win32gui.SelectObject(hdc, pen)
            old_brush = win32gui.SelectObject(hdc, win32gui.GetStockObject(win32con.NULL_BRUSH))
            win32gui.Rectangle(hdc, left, top, right, bottom)
            win32gui.SelectObject(hdc, old_pen)
            win32gui.SelectObject(hdc, old_brush)
            win32gui.DeleteObject(pen)
            win32gui.ReleaseDC(0, hdc)
            logger.info(
                "[outline] %s colour=%s rect=(%s,%s,%s,%s)",
                label or "screen_rect",
                colour,
                left,
                top,
                right,
                bottom,
            )
        except Exception as e:
            logger.warning("screen outline 실패 (%s): %s", label or "screen_rect", e)

    def _safe_draw_rgb_search_region(
        self,
        *,
        wrapper: Any,
        region: Tuple[int, int, int, int],
        colour: str,
        label: str,
    ) -> None:
        if wrapper is not None and hasattr(wrapper, "draw_outline"):
            self._safe_draw_outline(wrapper, colour=colour, label=label)
            return

        left, top, width, height = region
        self._safe_draw_screen_rect_outline(
            left=left,
            top=top,
            right=left + max(1, width) - 1,
            bottom=top + max(1, height) - 1,
            colour=colour,
            label=label,
        )

    def _safe_draw_pixel_marker(
        self,
        *,
        x: int,
        y: int,
        colour: str,
        size_px: int = 12,
        label: str = "",
    ) -> None:
        half = max(2, size_px // 2)
        self._safe_draw_screen_rect_outline(
            left=x - half,
            top=y - half,
            right=x + half,
            bottom=y + half,
            colour=colour,
            thickness=2,
            label=label or f"pixel({x},{y})",
        )

    def _format_window_label(self, wrapper: Any) -> str:
        """로그/오류 메시지용 윈도우 식별 문자열을 반환합니다."""
        info = self._get_window_search_identity(wrapper)
        title_candidates = self._get_node_title_candidates(wrapper)
        parts = [f"title={info['title']}", f"auto_id={info['auto_id']}"]
        if len(title_candidates) > 1:
            parts.append(f"alt_titles={title_candidates[1:3]}")
        if info["uia_control_type"] != "-":
            parts.append(f"type={info['uia_control_type']}")
        if info["class_name"] != "-":
            parts.append(f"class={info['class_name']}")
        if info["hwnd"] != "-":
            parts.append(f"hwnd={info['hwnd']}")
        return ", ".join(parts)

    def _get_wrapper_handle(self, wrapper: Any) -> Optional[int]:
        """wrapper에서 HWND를 추출합니다."""
        for accessor in (
            lambda: wrapper.handle,
            lambda: wrapper.element_info.handle,
        ):
            try:
                handle = accessor()
                if handle:
                    return int(handle)
            except Exception:
                continue
        return None

    def _is_wrapper_foreground(self, wrapper: Any) -> bool:
        """대상 윈도우(또는 동일 프로세스)가 foreground인지 확인합니다."""
        try:
            import win32gui
            import win32process

            fg_hwnd = win32gui.GetForegroundWindow()
            if not fg_hwnd:
                return False

            wrapper_hwnd = self._get_wrapper_handle(wrapper)
            if wrapper_hwnd and fg_hwnd == wrapper_hwnd:
                return True

            _, fg_pid = win32process.GetWindowThreadProcessId(fg_hwnd)
            target_pid = getattr(self._session.app, "process", None)
            return bool(target_pid and fg_pid == target_pid)
        except Exception as e:
            logger.debug("foreground 확인 실패: %s", e)
            return False

    def _activate_window(self, wrapper: Any, *, max_attempts: int = 3) -> bool:
        """윈도우를 앞으로 가져오고 foreground 전환을 재시도합니다."""
        after_focus_delay = self._session.config.get("timeouts", {}).get("after_focus_delay", 0.5)
        ui_delay = self._session.config.get("timeouts", {}).get("ui_delay", 0.5)

        for attempt in range(1, max_attempts + 1):
            is_minimized = self._safe_call(lambda: wrapper.is_minimized(), False)
            if is_minimized:
                logger.info("윈도우가 최소화되어 있어 복구를 시도합니다.")
                self._safe_call(wrapper.restore, None)
                time.sleep(ui_delay)

            try:
                wrapper.set_focus()
            except Exception as e:
                logger.warning("set_focus 실패 (attempt=%d): %s", attempt, e)
                try:
                    wrapper.maximize()
                    wrapper.restore()
                except Exception:
                    pass

            time.sleep(after_focus_delay)

            if self._is_wrapper_foreground(wrapper):
                self._session.cached_window = wrapper
                return True

            logger.info(
                "foreground 전환 미확인 (attempt=%d/%d). title=%s",
                attempt,
                max_attempts,
                self._safe_call(wrapper.window_text, ""),
            )

        if not self._safe_call(lambda: wrapper.is_visible(), False):
            logger.warning("포커스 시도 후에도 윈도우가 가시적이지 않습니다.")
            self._safe_call(wrapper.restore, None)

        self._session.cached_window = wrapper
        return self._is_wrapper_foreground(wrapper)

    def _iter_process_top_windows(self) -> list[Any]:
        """연결된 프로세스의 top-level 윈도우 목록을 반환합니다."""
        if not self._session.is_connected:
            return []

        windows: list[Any] = []
        for w in self._session.app.windows():
            wrapper = self._safe_call(lambda: w.wrapper_object(), None) or w
            if not self._verify_process_path(wrapper):
                continue
            if not self._safe_call(lambda: wrapper.exists(), False):
                continue
            windows.append(wrapper)
        return windows

    def _is_keyword_match(
        self,
        candidate_values: List[str],
        keyword: str,
        match_mode: str,
        case_sensitive: bool,
    ) -> bool:
        normalized_keyword = self._normalize_text(keyword, case_sensitive=case_sensitive)
        if not normalized_keyword:
            return False
        for value in candidate_values:
            normalized_value = self._normalize_text(value or "", case_sensitive=case_sensitive)
            if match_mode == "exact":
                if normalized_value == normalized_keyword:
                    return True
            else:
                if normalized_keyword in normalized_value:
                    return True
        return False

    def _is_attr_match(
        self,
        *,
        actual: str,
        expected: str,
        match_mode: str,
        case_sensitive: bool,
    ) -> bool:
        if not expected:
            return True
        normalized_actual = self._normalize_text(actual or "", case_sensitive=case_sensitive)
        normalized_expected = self._normalize_text(expected or "", case_sensitive=case_sensitive)
        if match_mode == "exact":
            return normalized_actual == normalized_expected
        return normalized_expected in normalized_actual

    def _extract_legacy_value(self, node: Any) -> str:
        """UIA 노드의 LegacyIAccessible value를 최대한 안전하게 추출합니다."""
        # 1) pywinauto helper
        try:
            legacy_props = self._safe_call(node.legacy_properties, None)
            if isinstance(legacy_props, dict):
                value = legacy_props.get("Value") or legacy_props.get("value")
                if value is not None:
                    return str(value)
        except Exception:
            pass

        # 2) COM legacy interface
        for iface_attr in ("iface_legacy_iaccessible", "iface_legacy"):
            iface = self._safe_call(lambda: getattr(node, iface_attr), None)
            if iface is None:
                continue
            for value_attr in ("CurrentValue", "Value"):
                value = self._safe_call(lambda: getattr(iface, value_attr), None)
                if value is not None:
                    return str(value)

        # 3) element_info fallback
        for info_attr in ("legacy_value", "value"):
            value = self._safe_call(lambda: getattr(node.element_info, info_attr), None)
            if value is not None:
                return str(value)
        return ""

    def _find_first_matching_node(
        self,
        *,
        root: Any,
        auto_id: Optional[str],
        control_type: Optional[str],
        title: Optional[str],
        title_match_mode: str,
        legacy_value: Optional[str],
        legacy_match_mode: str,
        case_sensitive: bool,
    ) -> Optional[Any]:
        descendants = self._safe_call(root.descendants, []) or []
        nodes = [root]
        nodes.extend(descendants)

        self._log_search_window(tool="click_app_by_attr", wrapper=root, scope="descendants_scan")
        logger.info(
            "[click_app_by_attr] descendants 순회: search_root=%s, descendants=%d, total_nodes=%d, "
            "target_auto_id=%s, target_control_type=%s, target_title=%s, target_legacy_value=%s",
            self._format_search_window_log(root),
            len(descendants),
            len(nodes),
            auto_id,
            control_type,
            title,
            legacy_value,
        )
        if len(descendants) == 0:
            logger.warning(
                "[click_app_by_attr] search_root 아래 descendants가 0개입니다: %s",
                self._format_window_label(root),
            )

        for node in nodes:
            node_auto_id = str(self._safe_call(lambda: node.element_info.automation_id, "") or "")
            node_control_type = str(self._safe_call(lambda: node.element_info.control_type, "") or "")
            node_title = str(self._safe_call(node.window_text, "") or "")
            node_legacy_value = ""

            if auto_id and node_auto_id != auto_id:
                continue
            if control_type and node_control_type.lower() != str(control_type).lower():
                continue
            if title and not self._is_attr_match(
                actual=node_title,
                expected=title,
                match_mode=title_match_mode,
                case_sensitive=case_sensitive,
            ):
                continue
            if legacy_value:
                node_legacy_value = self._extract_legacy_value(node)
            if legacy_value and not self._is_attr_match(
                actual=node_legacy_value,
                expected=legacy_value,
                match_mode=legacy_match_mode,
                case_sensitive=case_sensitive,
            ):
                continue
            return node
        return None

    def _get_node_title_candidates(self, node: Any) -> list[str]:
        """노드에서 title 매칭에 사용할 후보 문자열 목록을 반환합니다."""
        values: list[str] = []
        values.append(str(self._safe_call(node.window_text, "") or ""))
        values.append(str(self._safe_call(lambda: node.element_info.name, "") or ""))
        values.append(str(self._safe_call(lambda: node.element_info.rich_text, "") or ""))

        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = " ".join(str(value).split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _list_candidate_child_windows(
        self,
        root: Any,
        *,
        include_descendants: bool = False,
        require_visible: bool = True,
    ) -> list[Any]:
        """속성 클릭 시 탐색 루트로 사용할 child window 후보를 반환합니다."""
        candidates: list[Any] = []
        raw_children = self._safe_call(root.children, []) or []
        if include_descendants:
            descendants = self._safe_call(root.descendants, []) or []
            raw_children.extend(descendants)
        allowed_control_types = {"window", "pane", "document", "group", "custom", "dialog"}
        seen_ids: set[str] = set()
        for child in raw_children:
            wrapper = self._safe_call(lambda: child.wrapper_object(), None) or child
            if not self._safe_call(lambda: wrapper.exists(), False):
                continue
            if require_visible and not self._safe_call(lambda: wrapper.is_visible(), False):
                continue

            node_id = str(self._safe_call(lambda: wrapper.element_info.handle, None) or "")
            if not node_id:
                node_id = str(self._safe_call(lambda: wrapper.element_info.runtime_id, None) or "")
            if not node_id:
                node_id = str(id(wrapper))
            if node_id in seen_ids:
                continue
            seen_ids.add(node_id)

            control_type = str(self._safe_call(lambda: wrapper.element_info.control_type, "") or "").lower()
            if control_type and control_type not in allowed_control_types:
                continue
            candidates.append(wrapper)
        return candidates

    def _summarize_child_window_candidates(self, root: Any, limit: int = 8) -> list[str]:
        """child window 탐색 실패 시 디버깅용 후보 제목 목록을 반환합니다."""
        summaries: list[str] = []
        children = self._list_candidate_child_windows(root, include_descendants=True)
        for child in children[:limit]:
            titles = self._get_node_title_candidates(child)
            control_type = str(self._safe_call(lambda: child.element_info.control_type, "") or "")
            auto_id = str(self._safe_call(lambda: child.element_info.automation_id, "") or "")
            label = titles[0] if titles else "(no title)"
            summaries.append(f"{label} [type={control_type}, auto_id={auto_id or '-'}]")
        return summaries

    def _matches_child_window_spec(
        self,
        node: Any,
        *,
        child_title: str,
        child_auto_id: str,
        child_window_match_mode: str,
        case_sensitive: bool,
    ) -> bool:
        """노드가 child_window_title/auto_id 조건과 일치하는지 확인합니다."""
        title_ok = True
        auto_id_ok = True
        if child_title:
            title_ok = any(
                self._is_attr_match(
                    actual=candidate_title,
                    expected=child_title,
                    match_mode=child_window_match_mode,
                    case_sensitive=case_sensitive,
                )
                for candidate_title in self._get_node_title_candidates(node)
            )
        if child_auto_id:
            node_auto_id = str(self._safe_call(lambda: node.element_info.automation_id, "") or "")
            auto_id_ok = node_auto_id == child_auto_id
        return title_ok and auto_id_ok

    def _resolve_attr_search_root(
        self,
        *,
        window_target: str,
        child_window_title: Optional[str],
        child_window_auto_id: Optional[str],
        child_window_match_mode: str,
        case_sensitive: bool,
        top_window_override: Optional[Any] = None,
        allow_invisible_children: bool = False,
    ) -> tuple[Optional[Any], str]:
        """
        click_app_by_attr 탐색 루트를 결정합니다.
        - top: 최상위 윈도우에서 탐색
        - child: top의 child window에서 탐색
        - auto: child title이 있으면 child 우선, 없으면 top 사용
        """
        top_window = top_window_override
        if top_window is None:
            top_window = self._pick_target_window() or self._session.get_top_window()
        if top_window is None:
            return None, "none"

        logger.info(
            "[click_app_by_attr] top window: %s",
            self._format_window_label(top_window),
        )

        target_mode = (window_target or "auto").strip().lower()
        child_title = (child_window_title or "").strip()
        child_auto_id = (child_window_auto_id or "").strip()
        children = self._list_candidate_child_windows(
            top_window,
            require_visible=not allow_invisible_children,
        )

        def child_matches_filters(child: Any) -> bool:
            return self._matches_child_window_spec(
                child,
                child_title=child_title,
                child_auto_id=child_auto_id,
                child_window_match_mode=child_window_match_mode,
                case_sensitive=case_sensitive,
            )

        if target_mode in {"child", "auto"} and (child_title or child_auto_id):
            if self._matches_child_window_spec(
                top_window,
                child_title=child_title,
                child_auto_id=child_auto_id,
                child_window_match_mode=child_window_match_mode,
                case_sensitive=case_sensitive,
            ):
                logger.info(
                    "[click_app_by_attr] top window가 child_window_title과 일치하여 child 탐색을 건너뜁니다: %s",
                    self._format_window_label(top_window),
                )
                return (
                    top_window,
                    f"top_as_child(title={child_title}, auto_id={child_auto_id or '-'})",
                )

        def pick_child_by_direct_api() -> Optional[Any]:
            if not child_title and not child_auto_id:
                return None

            criteria: dict[str, str] = {}
            if child_title and child_window_match_mode == "exact":
                criteria["title"] = child_title
            if child_auto_id:
                criteria["auto_id"] = child_auto_id
            if criteria:
                direct_wrapper = self._safe_call(
                    lambda: top_window.child_window(**criteria).wrapper_object(),
                    None,
                )
                if direct_wrapper is not None and self._safe_call(lambda: direct_wrapper.exists(), False):
                    return direct_wrapper

            if child_title:
                pattern = re.escape(child_title)
                if child_window_match_mode == "contains":
                    pattern = f".*{pattern}.*"
                else:
                    pattern = f"^{pattern}$"
                if not case_sensitive:
                    pattern = f"(?i){pattern}"

                regex_wrapper = self._safe_call(
                    lambda: top_window.child_window(title_re=pattern).wrapper_object(),
                    None,
                )
                if regex_wrapper is not None and self._safe_call(lambda: regex_wrapper.exists(), False):
                    if not child_auto_id or child_matches_filters(regex_wrapper):
                        return regex_wrapper

            return None

        def pick_child_by_title() -> Optional[Any]:
            if not child_title and not child_auto_id:
                return None
            direct_matched = pick_child_by_direct_api()
            if direct_matched is not None:
                return direct_matched

            for child in children:
                if child_matches_filters(child):
                    return child

            descendants = self._list_candidate_child_windows(
                top_window,
                include_descendants=True,
                require_visible=not allow_invisible_children,
            )
            for child in descendants:
                if child_matches_filters(child):
                    return child
            return None

        def pick_child_with_visibility_fallback() -> Optional[Any]:
            matched = pick_child_by_title()
            if matched is not None:
                return matched
            if allow_invisible_children:
                return None

            invisible_children = self._list_candidate_child_windows(
                top_window,
                require_visible=False,
            )
            for child in invisible_children:
                if child_matches_filters(child):
                    logger.info(
                        "가시성 필터 없이 child window 매칭: title=%s",
                        self._safe_call(child.window_text, ""),
                    )
                    return child

            invisible_descendants = self._list_candidate_child_windows(
                top_window,
                include_descendants=True,
                require_visible=False,
            )
            for child in invisible_descendants:
                if child_matches_filters(child):
                    logger.info(
                        "가시성 필터 없이 descendant child 매칭: title=%s",
                        self._safe_call(child.window_text, ""),
                    )
                    return child
            return None

        if target_mode == "top":
            return top_window, "top"

        if target_mode == "child":
            matched_child = pick_child_with_visibility_fallback()
            if matched_child is not None:
                return matched_child, f"child(title={child_title}, auto_id={child_auto_id or '-'})"
            if child_title or child_auto_id:
                candidates = self._summarize_child_window_candidates(top_window)
                return None, f"child_not_found(title={child_title}, auto_id={child_auto_id}, candidates={candidates})"
            if children:
                return children[0], "child(first_visible)"
            return None, "child_not_found(no_children)"

        # auto mode
        matched_child = pick_child_with_visibility_fallback()
        if matched_child is not None:
            return matched_child, f"auto->child(title={child_title}, auto_id={child_auto_id or '-'})"
        if child_title or child_auto_id:
            candidates = self._summarize_child_window_candidates(top_window)
            logger.warning(
                "child window 미발견: title=%s, auto_id=%s, candidates=%s",
                child_title or "-",
                child_auto_id or "-",
                candidates,
            )
            return None, f"child_not_found(title={child_title}, auto_id={child_auto_id}, candidates={candidates})"
        return top_window, "auto->top"

    def _iter_attr_search_roots(
        self,
        *,
        window_target: str,
        child_window_title: Optional[str],
        child_window_auto_id: Optional[str],
        child_window_match_mode: str,
        case_sensitive: bool,
        top_window_override: Optional[Any] = None,
        allow_invisible_children: bool = False,
    ) -> list[tuple[Optional[Any], str]]:
        """
        click_app_by_attr가 순회할 search root 목록을 반환합니다.

        top.descendants()만으로는 Find 같은 child window 내부 컨트롤(Close)이
        빠질 수 있어, top 모드에서는 top + child window 각각을 search root로 봅니다.
        child_window_title/auto_id가 지정된 경우에는 해당 child만 탐색합니다.
        """
        target_mode = (window_target or "auto").strip().lower()
        child_title = (child_window_title or "").strip()
        child_auto_id = (child_window_auto_id or "").strip()
        child_scoped = target_mode == "child" or (
            target_mode == "auto" and bool(child_title or child_auto_id)
        )

        if child_scoped:
            root, info = self._resolve_attr_search_root(
                window_target=window_target,
                child_window_title=child_window_title,
                child_window_auto_id=child_window_auto_id,
                child_window_match_mode=child_window_match_mode,
                case_sensitive=case_sensitive,
                top_window_override=top_window_override,
                allow_invisible_children=allow_invisible_children,
            )
            return [(root, info)]

        top_window = top_window_override
        if top_window is None:
            top_window = self._pick_target_window() or self._session.get_top_window()
        if top_window is None:
            return [(None, "none")]

        prefix = "top" if target_mode == "top" else "auto->top"
        roots: list[tuple[Any, str]] = [(top_window, prefix)]
        child_roots = self._list_candidate_child_windows(
            top_window,
            include_descendants=True,
            require_visible=False,
        )
        for index, child in enumerate(child_roots):
            label = self._format_window_label(child)
            child_prefix = "child" if target_mode == "top" else "auto->child"
            roots.append((child, f"{child_prefix}[{index}]({label})"))
        return roots

    def _click_with_preferred_action(
        self,
        target: Any,
        *,
        button: str,
        clicks: int,
        double: bool,
    ) -> str:
        """
        가능한 경우 invoke/select 기반 접근을 우선 시도하고, 실패 시 input 클릭으로 fallback 합니다.
        반환값은 실제 적용된 클릭 방식입니다.
        """
        if double or clicks > 1:
            target.double_click_input(button=button)
            return "double_click_input"

        if button.lower() == "left":
            control_type = str(self._safe_call(lambda: target.element_info.control_type, "") or "").lower()
            prefer_tree = control_type in {"treeitem", "tree"}
            preferred_methods = ["invoke", "select"] if prefer_tree else ["invoke"]

            for method_name in preferred_methods:
                method = self._safe_call(lambda: getattr(target, method_name), None)
                if method is None:
                    continue
                try:
                    method()
                    return method_name
                except Exception:
                    continue

        target.click_input(button=button)
        return "click_input"

    def _collect_uia_components(
        self,
        keyword: Optional[str] = None,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        component_limit: int = 300,
    ) -> tuple[list[dict], list[dict], dict]:
        """프로세스의 모든 가시적인 윈도우에서 UIA 구성요소를 수집합니다."""
        if not self._session.is_connected:
            self._safe_call(self._session.connect, None)
        
        if not self._session.is_connected:
            return [], [], {}

        # 1. 해당 프로세스의 모든 가시적인 윈도우 찾기
        all_windows = self._session.app.windows()
        target_windows = []
        for w in all_windows:
            wrapper = self._safe_call(lambda: w.wrapper_object(), None) or w
            if self._verify_process_path(wrapper) and self._safe_call(lambda: wrapper.is_visible(), False):
                target_windows.append(wrapper)

        if not target_windows:
            return [], [], {}

        components: list[dict] = []
        keyword_hits: list[dict] = []
        target_keyword = (keyword or "").strip()
        
        # 첫 번째 윈도우 정보
        main_wrapper = target_windows[0]
        summary_window = {
            "title": self._safe_call(main_wrapper.window_text, "") or "",
        }

        # 2. 모든 타겟 윈도우의 자식 요소 수집 (title/auto_id만 반환, 좌표는 keyword 매칭 시에만 계산)
        global_idx = 0
        for wrapper in target_windows:
            nodes = [wrapper]
            descendants = self._safe_call(wrapper.descendants, []) or []
            nodes.extend(descendants)

            for node in nodes:
                if global_idx >= component_limit:
                    break
                
                if not self._safe_call(lambda: node.is_visible(), False):
                    continue

                title = self._safe_call(node.window_text, "") or ""
                auto_id = self._safe_call(lambda: node.element_info.automation_id, "") or ""
                if not title and not auto_id:
                    continue

                components.append({
                    "index": global_idx,
                    "title": title,
                    "auto_id": auto_id,
                })

                if target_keyword:
                    control_type = self._safe_call(lambda: node.element_info.control_type, "") or ""
                    if self._is_keyword_match(
                        candidate_values=[title, auto_id, control_type],
                        keyword=target_keyword,
                        match_mode=match_mode,
                        case_sensitive=case_sensitive,
                    ):
                        rect = self._safe_call(node.rectangle, None)
                        rect_dict = self._rect_to_dict(rect)
                        keyword_hits.append({
                            "index": global_idx,
                            "title": title,
                            "auto_id": auto_id,
                            "control_type": control_type,
                            "x": rect_dict.get("center_x"),
                            "y": rect_dict.get("center_y"),
                            "source": "uia",
                        })
                
                global_idx += 1
            
            if global_idx >= component_limit:
                break

        return components, keyword_hits, summary_window



    async def _extract_ocr_hits(
        self,
        keyword: str,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        language: str = "eng",
        timeout: Optional[float] = 2.0,
        hit_limit: int = 20,
    ) -> list[dict]:
        """앱 화면 OCR 결과에서 keyword 좌표 목록을 반환합니다."""
        if not keyword.strip():
            return []

        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return []

        try:
            import winocr
        except Exception:
            return []

        lang = self._get_best_winocr_lang(language)
        region = self._get_app_window_region()
        normalized_keyword = self._normalize_text(keyword, case_sensitive=case_sensitive)
        started = time.monotonic()

        while True:
            screenshot = pyautogui.screenshot(region=region)
            raw_ocr_result = await winocr.recognize_pil(screenshot, lang)
            ocr_result = winocr.picklify(raw_ocr_result)

            hits: list[dict] = []
            for line in ocr_result.get("lines", []):
                for word in line.get("words", []):
                    raw_text = word.get("text", "") or ""
                    normalized_text = self._normalize_text(raw_text, case_sensitive=case_sensitive)
                    is_match = (
                        normalized_text == normalized_keyword
                        if match_mode == "exact"
                        else normalized_keyword in normalized_text
                    )
                    if not is_match:
                        continue

                    rect = word.get("bounding_rect", {})
                    rel_x = int(rect.get("x", 0) + rect.get("width", 0) / 2)
                    rel_y = int(rect.get("y", 0) + rect.get("height", 0) / 2)
                    abs_x = rel_x + (region[0] if region else 0)
                    abs_y = rel_y + (region[1] if region else 0)
                    hits.append(
                        {
                            "text": raw_text,
                            "x": abs_x,
                            "y": abs_y,
                            "rect": rect,
                            "source": "ocr",
                        }
                    )
                    if len(hits) >= max(1, hit_limit):
                        return hits

            if hits:
                return hits
            if timeout is None:
                return []
            if time.monotonic() - started > timeout:
                return []


    def get_screen_state_flags(self) -> dict:
        """현재 active window 기준 화면 상태 플래그를 반환합니다."""
        wrapper = self._pick_target_window()
        title = ""
        control_type = ""
        if wrapper is not None:
            title = str(self._safe_call(wrapper.window_text, "") or "")
            control_type = str(self._safe_call(wrapper.control_type, "") or "")

        title_norm = title.lower()
        login_like_keywords = ["login", "sign in", "signin", "log in", "인증", "로그인"]
        is_login_like = any(keyword in title_norm for keyword in login_like_keywords)

        current_screen = "login" if is_login_like else ("main" if title else "unknown")
        return {
            "active_window_detected": bool(wrapper is not None),
            "active_window_title": title,
            "active_window_control_type": control_type,
            "login_like": is_login_like,
            "current_screen": current_screen,
        }

    async def describe_current_state(
        self,
        *,
        keyword: Optional[str] = None,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        language: str = "eng",
        include_components: bool = True,
        component_limit: int = 150,
        include_ocr_hits: bool = True,
        ocr_hit_limit: int = 20,
        ocr_timeout: Optional[float] = 2.0,
    ) -> dict:
        """
        현재 앱 상태/구성요소를 반환합니다.

        components에는 title과 auto_id만 포함되며,
        keyword가 지정된 경우에만 keyword_hits 좌표를 계산합니다.
        """
        focus_result = self.ensure_focus()
        screen_flags = self.get_screen_state_flags()

        app_info = {
            "connected": bool(self._session.is_connected),
            "session_state": self._session.state.value,
            "configured_executable_path": self._session.config.get("application", {}).get("executable_path"),
            "configured_process_name": self._session.config.get("application", {}).get("process_name"),
        }

        components: list[dict] = []
        uia_keyword_hits: list[dict] = []
        target_window: dict = {}
        if include_components:
            components, uia_keyword_hits, target_window = self._collect_uia_components(
                keyword=keyword,
                match_mode=match_mode,
                case_sensitive=case_sensitive,
                component_limit=component_limit,
            )

        ocr_keyword_hits: list[dict] = []
        if keyword and include_ocr_hits:
            ocr_keyword_hits = await self._extract_ocr_hits(
                keyword=keyword,
                match_mode=match_mode,
                case_sensitive=case_sensitive,
                language=language,
                timeout=ocr_timeout,
                hit_limit=ocr_hit_limit,
            )

        return {
            "result": "success",
            "is_success": True,
            "message": "현재 화면 상태를 수집했습니다",
            "focus": focus_result.to_dict(),
            "app": app_info,
            "screen_flags": screen_flags,
            "target_window": target_window,
            "components": components,
            "keyword": keyword,
            "keyword_hits": {
                "uia": uia_keyword_hits,
                "ocr": ocr_keyword_hits,
            },
        }

    def press_shortcut(self, shortcut: str, interval: float = 0.05, repeat: int = 1) -> AppUIActionResult:
        """단축키 입력"""
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        keys = self._normalize_keys(shortcut)
        if not keys:
            return AppUIActionResult(result="error", message="유효한 단축키를 입력해주세요")

        try:
            for _ in range(max(1, repeat)):
                if len(keys) == 1:
                    pyautogui.press(keys[0])
                else:
                    pyautogui.hotkey(*keys, interval=max(0.0, interval))
                if repeat > 1:
                    time.sleep(interval)
            return AppUIActionResult(result="success", shortcut="+".join(keys))
        except Exception as e:
            logger.error("단축키 입력 실패: %s", e)
            return AppUIActionResult(result="error", message=f"단축키 입력 실패: {e}")

    def type_text(
        self,
        text: str,
        interval: float = 0.02,
    ) -> AppUIActionResult:
        """
        텍스트 입력
        
        pyautogui.write 대신 Unicode를 지원하는 pywinauto.keyboard.send_keys를 사용합니다.
        이는 한글 입력 문제를 해결하고 더 안정적인 입력을 제공합니다.
        """
        try:
            from pywinauto.keyboard import send_keys
            # with_spaces=True: 공백 유지
            # with_tabs=True: 탭 유지
            # with_newlines=True: 개행 유지
            send_keys(text, with_spaces=True, with_tabs=True, with_newlines=True, pause=max(0.001, interval))
            return AppUIActionResult(result="success")
        except Exception as e:
            logger.error(f"텍스트 입력 실패 (send_keys): {e}")
            # Fallback to pyautogui if send_keys fails for some reason
            pyautogui, error_result = self._get_pyautogui()
            if not error_result:
                try:
                    pyautogui.write(text, interval=max(0.0, interval))
                    return AppUIActionResult(result="success", message="pyautogui로 대체하여 입력됨")
                except Exception as pe:
                    logger.error(f"pyautogui 입력도 실패: {pe}")
            
            return AppUIActionResult(result="error", message=f"텍스트 입력 실패: {e}")

    def _find_rgb_in_region(
        self,
        *,
        rgb: Tuple[int, int, int],
        region: Tuple[int, int, int, int],
        tolerance: int,
        step: int,
        screenshot: Any,
    ) -> Optional[Tuple[int, int]]:
        pixels = np.array(screenshot)
        target_pixels = pixels[:, :, :3]
        diff = np.abs(target_pixels.astype(np.int16) - np.array(rgb, dtype=np.int16))
        mask = np.all(diff <= tolerance, axis=-1)

        if step > 1:
            reduced_mask = np.zeros_like(mask)
            reduced_mask[::step, ::step] = mask[::step, ::step]
            mask = reduced_mask

        coords = np.where(mask)
        if coords[0].size == 0:
            return None

        y_idx, x_idx = coords[0][0], coords[1][0]
        final_x = int(x_idx) + region[0]
        final_y = int(y_idx) + region[1]
        return final_x, final_y

    def find_rgb_position(
        self,
        rgb: Tuple[int, int, int],
        tolerance: int = 5,
        step: int = 1,
        timeout: Optional[float] = None,
        *,
        window_target: str = "auto",
        child_window_title: Optional[str] = None,
        child_window_auto_id: Optional[str] = None,
        child_window_match_mode: str = "contains",
        case_sensitive: bool = False,
        focus_search_root: bool = False,
        search_scope: str = "app",
        region_expand_px: int = 4,
        draw_outline: bool = False,
        outline_colour: str = "red",
        search_outline_colour: str = "green",
        outline_scope: str = "all",
    ) -> AppUIActionResult:
        """
        화면에서 RGB 픽셀 위치를 찾습니다.

        draw_outline=True 시 outline_scope에 따라 탐색 영역/발견 픽셀을 강조합니다:
          - search: 순회 중인 search_root(창) 또는 region만
          - target: 발견한 픽셀 위치만
          - all: 탐색 영역 + 픽셀 (기본)
        """
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        scope_mode = (search_scope or "app").strip().lower()
        if scope_mode not in {"app", "desktop"}:
            return AppUIActionResult(
                result="error",
                message=f"지원하지 않는 search_scope: {search_scope} (app|desktop)",
            )

        target_mode = (window_target or "auto").strip().lower()
        if scope_mode == "app" and target_mode not in {"auto", "top", "child"}:
            return AppUIActionResult(
                result="error",
                message=f"지원하지 않는 window_target: {window_target} (auto|top|child)",
            )

        outline_scope = (outline_scope or "all").strip().lower()
        if outline_scope not in {"search", "target", "all"}:
            return AppUIActionResult(
                result="error",
                message=f"지원하지 않는 outline_scope: {outline_scope} (search|target|all)",
            )
        outline_search = draw_outline and outline_scope in {"search", "all"}
        outline_target = draw_outline and outline_scope in {"target", "all"}
        outline_pause = float(self._session.config.get("timeouts", {}).get("ui_delay", 0.3))

        tolerance = max(0, tolerance)
        step = max(1, step)
        start = time.monotonic()

        if scope_mode == "desktop":
            desktop_region = self._get_desktop_region(pyautogui)
            search_targets: list[tuple[str, Any, Tuple[int, int, int, int]]] = [
                ("desktop(full_screen)", None, desktop_region)
            ]
            focus_search_root = False
            logger.info(
                "[rgb] 전체 화면 탐색: search_scope=desktop, region=%s",
                desktop_region,
            )
        else:
            search_targets = self._iter_rgb_search_targets(
                window_target=window_target,
                child_window_title=child_window_title,
                child_window_auto_id=child_window_auto_id,
                child_window_match_mode=child_window_match_mode,
                case_sensitive=case_sensitive,
                region_expand_px=region_expand_px,
            )
            if not search_targets:
                return AppUIActionResult(
                    result="error",
                    message="RGB 탐색 대상 윈도우를 찾을 수 없거나 경로가 일치하지 않습니다.",
                )

            searched_labels = [label for label, _, _ in search_targets]
            logger.info(
                "[rgb] 탐색 대상 %d개: search_scope=app, window_target=%s, child_window_title=%s, targets=%s",
                len(search_targets),
                window_target,
                child_window_title,
                searched_labels,
            )

        searched_labels = [label for label, _, _ in search_targets]

        while True:
            for label, wrapper, region in search_targets:
                if wrapper is not None:
                    self._log_search_window(tool="rgb", wrapper=wrapper, scope=label)
                else:
                    logger.info("[rgb] 현재 탐색: scope=%s, region=%s", label, region)
                logger.info("[rgb] 탐색 영역: region=%s", region)
                if focus_search_root and wrapper is not None:
                    self._safe_call(wrapper.set_focus, None)
                    time.sleep(self._session.config.get("timeouts", {}).get("after_focus_delay", 0.1))

                if outline_search:
                    self._safe_draw_rgb_search_region(
                        wrapper=wrapper,
                        region=region,
                        colour=search_outline_colour,
                        label=f"rgb_search={label}",
                    )
                    time.sleep(outline_pause)

                screenshot = pyautogui.screenshot(region=region)
                matched = self._find_rgb_in_region(
                    rgb=rgb,
                    region=region,
                    tolerance=tolerance,
                    step=step,
                    screenshot=screenshot,
                )
                if matched is None:
                    continue

                final_x, final_y = matched
                logger.info(
                    "RGB %s 발견: (%s, %s), search_root=%s",
                    rgb,
                    final_x,
                    final_y,
                    label,
                )
                if outline_target:
                    self._safe_draw_pixel_marker(
                        x=final_x,
                        y=final_y,
                        colour=outline_colour,
                        label=f"rgb_target search_root={label}",
                    )
                    time.sleep(outline_pause)
                return AppUIActionResult(
                    result="success",
                    x=final_x,
                    y=final_y,
                    message=f"RGB 발견: search_root={label}",
                )

            if timeout is None:
                logger.warning(
                    "RGB %s를 찾을 수 없습니다. search_targets=%s",
                    rgb,
                    searched_labels,
                )
                return AppUIActionResult(
                    result="not_found",
                    message=f"RGB 위치를 찾을 수 없습니다. search_targets={searched_labels}",
                )
            if time.monotonic() - start > timeout:
                logger.warning("RGB %s 탐색 시간 초과 (%ss)", rgb, timeout)
                return AppUIActionResult(
                    result="timeout",
                    message=f"RGB 위치 탐색 시간 초과. search_targets={searched_labels}",
                )

            time.sleep(0.1)

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
        """
        애플리케이션 화면에서 텍스트 위치를 찾습니다.
        UIA(UI Automation)를 우선적으로 탐색하고, 발견되지 않으면 OCR을 사용합니다.
        """
        pyautogui, error_result = self._get_pyautogui()
        if error_result:
            return error_result

        target_text = " ".join(text.split())
        if not target_text:
            return AppUIActionResult(result="error", message="찾을 텍스트가 비어 있습니다")

        match_mode = match_mode.lower().strip()
        if match_mode not in {"contains", "exact"}:
            return AppUIActionResult(result="error", message=f"지원하지 않는 match_mode: {match_mode}")

        # 1. UIA 우선 탐색 (표준 UI 요소에 대해 빠르고 정확함)
        # UIA는 즉각적인 결과를 제공하므로 별도 루프 이전에 먼저 확인합니다.
        _, uia_hits, _ = self._collect_uia_components(
            keyword=target_text,
            match_mode=match_mode,
            case_sensitive=case_sensitive
        )
        if uia_hits:
            target = uia_hits[0]
            logger.info(f"UIA를 통해 텍스트 '{target_text}' 위치를 찾았습니다: ({target.get('x')}, {target.get('y')})")
            return AppUIActionResult(
                result="success",
                x=int(target.get("x", 0)),
                y=int(target.get("y", 0)),
                matched_text=target.get("title", ""),
            )

        # 2. OCR 탐색 (UIA로 찾지 못한 경우 시도)
        try:
            import winocr
        except Exception as e:
            return AppUIActionResult(result="error", message=f"winocr 로드 실패: {e}")

        # 최적의 언어 선택
        lang = self._get_best_winocr_lang(language)
        target_norm = self._normalize_text(target_text, case_sensitive=case_sensitive)
        
        # 타임아웃 기본값 설정 (None이면 2초 정도 대기)
        actual_timeout = timeout if timeout is not None else 2.0
        start = time.monotonic()

        # 앱 윈도우 영역 획득
        region = self._get_app_window_region()
        if region is None:
            # 설정 상의 앱이 구동되지 않은 것으로 간주하고 중단 (전체 화면으로 탐색되는 것을 방지)
            return AppUIActionResult(result="error", message="대상 애플리케이션 윈도우를 찾을 수 없습니다. (전체 화면 탐색 방지를 위해 중단됨)")
        
        logger.info(f"OCR을 통해 텍스트 '{target_text}' 탐색 시작 (region={region}, lang={lang}, timeout={actual_timeout})")
        
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
                        
                        logger.info(f"OCR을 통해 텍스트 '{target_text}' 탐색 성공")
                        return AppUIActionResult(
                            result="success",
                            x=center_x,
                            y=center_y,
                            matched_text=raw_text,
                        )

            # 타임아웃 체크
            if time.monotonic() - start > actual_timeout:
                return AppUIActionResult(result="timeout", message=f"텍스트 '{target_text}'를 찾을 수 없습니다 (OCR 탐색 시간 초과)")
            
            # 잠깐 대기 후 재시도
            await asyncio.sleep(0.2)

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
        if search_region is None:
            return AppUIActionResult(result="error", message="대상 애플리케이션 윈도우를 찾을 수 없거나 경로가 일치하지 않습니다.(전체 화면 탐색 방지)")

        start = time.monotonic()

        while True:
            locate_kwargs = {"grayscale": grayscale}
            if search_region is not None:
                locate_kwargs["region"] = search_region
            
            use_confidence = False
            if confidence is not None:
                # confidence 파라미터는 OpenCV가 설치되어 있어야만 사용 가능
                try:
                    import cv2
                    locate_kwargs["confidence"] = confidence
                    use_confidence = True
                except ImportError:
                    logger.warning("OpenCV(cv2)가 설치되지 않아 confidence 파라미터를 사용할 수 없습니다. Exact Match(100% 일치) 모드로 동작합니다.")
            
            try:
                box = pyautogui.locateOnScreen(str(target), **locate_kwargs)
            except Exception as e:
                logger.error(f"이미지 매칭 중 오류 발생: {e}")
                return AppUIActionResult(result="error", message=f"이미지 매칭 실패: {e}")

            if box is not None:
                center = pyautogui.center(box)
                return AppUIActionResult(result="success", x=int(center.x), y=int(center.y))

            if timeout is None:
                msg = "이미지를 찾을 수 없습니다"
                if confidence and not use_confidence:
                    msg += " (OpenCV 미설치로 Exact Match 시도됨)"
                return AppUIActionResult(result="not_found", message=msg)
            if time.monotonic() - start > timeout:
                return AppUIActionResult(result="timeout", message="이미지 탐색 시간 초과")

    def click_element_by_attr(
        self,
        auto_id: Optional[str] = None,
        control_type: Optional[str] = None,
        title: Optional[str] = None,
        title_match_mode: str = "exact",
        legacy_value: Optional[str] = None,
        legacy_match_mode: str = "exact",
        case_sensitive: bool = False,
        window_target: str = "auto",
        child_window_title: Optional[str] = None,
        child_window_auto_id: Optional[str] = None,
        child_window_match_mode: str = "contains",
        button: str = "left",
        clicks: int = 1,
        double: bool = False,
        timeout: Optional[float] = None,
        draw_outline: bool = False,
        outline_colour: str = "red",
        search_outline_colour: str = "green",
        outline_scope: str = "all",
    ) -> AppUIActionResult:
        """
        속성 기반으로 특정 요소를 찾아 클릭합니다.
        auto_id/control_type/title/legacy_value 중 하나 이상을 입력받아 대상을 식별합니다.

        draw_outline=True 시 outline_scope에 따라 테두리 표시:
          - search: 순회 중인 search_root(창)만
          - target: 찾은 요소만
          - all: search_root + target (기본)
        """
        title_match_mode = (title_match_mode or "exact").strip().lower()
        if title_match_mode not in {"exact", "contains"}:
            return AppUIActionResult(
                result="error",
                message=f"지원하지 않는 title_match_mode: {title_match_mode} (exact|contains)",
            )
        legacy_match_mode = (legacy_match_mode or "exact").strip().lower()
        if legacy_match_mode not in {"exact", "contains"}:
            return AppUIActionResult(
                result="error",
                message=f"지원하지 않는 legacy_match_mode: {legacy_match_mode} (exact|contains)",
            )
        child_window_match_mode = (child_window_match_mode or "contains").strip().lower()
        if child_window_match_mode not in {"exact", "contains"}:
            return AppUIActionResult(
                result="error",
                message=f"지원하지 않는 child_window_match_mode: {child_window_match_mode} (exact|contains)",
            )
        window_target = (window_target or "auto").strip().lower()
        if window_target not in {"auto", "top", "child"}:
            return AppUIActionResult(
                result="error",
                message=f"지원하지 않는 window_target: {window_target} (auto|top|child)",
            )

        if not any([auto_id, control_type, title, legacy_value]):
            return AppUIActionResult(
                result="error",
                message="검색 조건(auto_id, control_type, title, legacy_value)이 하나 이상 필요합니다.",
            )

        outline_scope = (outline_scope or "all").strip().lower()
        if outline_scope not in {"search", "target", "all"}:
            return AppUIActionResult(
                result="error",
                message=f"지원하지 않는 outline_scope: {outline_scope} (search|target|all)",
            )
        outline_search = draw_outline and outline_scope in {"search", "all"}
        outline_target = draw_outline and outline_scope in {"target", "all"}
        outline_pause = float(self._session.config.get("timeouts", {}).get("ui_delay", 0.3))

        logger.info(
            "[click_app_by_attr] 시작: auto_id=%s, title=%s, child_window_title=%s, child_window_auto_id=%s, window_target=%s",
            auto_id,
            title,
            child_window_title,
            child_window_auto_id,
            window_target,
        )

        try:
            actual_timeout = timeout if timeout is not None else 5.0
            start = time.monotonic()
            target = None
            search_root = None
            search_root_info = "none"
            matched_search_root = None
            matched_search_root_info = "none"
            scanned_top_labels: list[str] = []
            while True:
                focus_result = self.ensure_focus(invalidate_cache=True)
                if not focus_result.is_success:
                    return AppUIActionResult(result="error", message=focus_result.message)

                top_windows = self._iter_process_top_windows()
                if not top_windows:
                    picked = self._pick_target_window() or self._session.get_top_window()
                    top_windows = [picked] if picked is not None else []

                top_labels = [self._format_window_label(w) for w in top_windows]
                scanned_top_labels = top_labels
                logger.info(
                    "[click_app_by_attr] 순회 top window 목록 (%d개): %s",
                    len(top_labels),
                    top_labels,
                )

                for top_window in top_windows:
                    logger.info(
                        "[click_app_by_attr] top window 순회 시작: %s",
                        self._format_window_label(top_window),
                    )
                    search_roots = self._iter_attr_search_roots(
                        window_target=window_target,
                        child_window_title=child_window_title,
                        child_window_auto_id=child_window_auto_id,
                        child_window_match_mode=child_window_match_mode,
                        case_sensitive=case_sensitive,
                        top_window_override=top_window,
                    )
                    for search_root, search_root_info in search_roots:
                        if search_root is None:
                            logger.info(
                                "[click_app_by_attr] search_root 없음: top=%s, info=%s",
                                self._format_window_label(top_window),
                                search_root_info,
                            )
                            continue

                        self._log_search_window(
                            tool="click_app_by_attr",
                            wrapper=search_root,
                            scope=search_root_info,
                        )
                        logger.info(
                            "[click_app_by_attr] search_root from top=%s",
                            self._format_search_window_log(top_window),
                        )

                        if outline_search:
                            self._safe_draw_outline(
                                search_root,
                                colour=search_outline_colour,
                                label=f"search_root={search_root_info}",
                            )
                            time.sleep(outline_pause)

                        target = self._find_first_matching_node(
                            root=search_root,
                            auto_id=auto_id,
                            control_type=control_type,
                            title=title,
                            title_match_mode=title_match_mode,
                            legacy_value=legacy_value,
                            legacy_match_mode=legacy_match_mode,
                            case_sensitive=case_sensitive,
                        )
                        if target is not None:
                            matched_search_root = search_root
                            matched_search_root_info = search_root_info
                            break
                    if target is not None:
                        break

                if target is not None:
                    break
                if time.monotonic() - start > actual_timeout:
                    break
                time.sleep(0.2)

            if target is None:
                logger.warning(
                    "[click_app_by_attr] 실패: top_windows=%s, search_root=%s, auto_id=%s, title=%s, child_window_title=%s",
                    scanned_top_labels,
                    search_root_info,
                    auto_id,
                    title,
                    child_window_title,
                )
                return AppUIActionResult(
                    result="error",
                    message=(
                        "요소를 찾지 못했습니다: "
                        f"auto_id={auto_id}, control_type={control_type}, title={title}, legacy_value={legacy_value}, "
                        f"window_target={window_target}, child_window_title={child_window_title}, "
                        f"child_window_auto_id={child_window_auto_id}, top_windows={scanned_top_labels}, "
                        f"search_root={search_root_info}"
                    ),
                )
            
            search_root = matched_search_root
            search_root_info = matched_search_root_info

            matched_auto_id = str(self._safe_call(lambda: target.element_info.automation_id, "") or "")
            matched_title = str(self._safe_call(target.window_text, "") or "")
            matched_type = str(self._safe_call(lambda: target.element_info.control_type, "") or "")

            if search_root is not None:
                self._safe_call(search_root.set_focus, None)
                time.sleep(self._session.config.get("timeouts", {}).get("after_focus_delay", 0.2))

            if outline_target:
                self._safe_draw_outline(
                    target,
                    colour=outline_colour,
                    label=f"target(title={matched_title}, search_root={search_root_info})",
                )
                time.sleep(outline_pause)
            click_method = self._click_with_preferred_action(
                target,
                button=button,
                clicks=clicks,
                double=double,
            )
            logger.info(
                "[click_app_by_attr] 성공: matched(title=%s, auto_id=%s, type=%s), method=%s, search_root=%s",
                matched_title,
                matched_auto_id,
                matched_type,
                click_method,
                search_root_info,
            )
            return AppUIActionResult(
                result="success",
                message=(
                    "요소 클릭 성공: "
                    f"auto_id={auto_id}, control_type={control_type}, title={title}, legacy_value={legacy_value}, "
                    f"window_target={window_target}, child_window_title={child_window_title}, "
                    f"child_window_auto_id={child_window_auto_id}, matched_title={matched_title}, "
                    f"matched_auto_id={matched_auto_id}, matched_control_type={matched_type}, "
                    f"search_root={search_root_info}, method={click_method}"
                ),
            )
        except Exception as e:
            logger.error("[click_app_by_attr] 예외: %s", e)
            return AppUIActionResult(result="error", message=f"요소 클릭 실패: {e}")

    def highlight_element_by_attr(
        self,
        auto_id: Optional[str] = None,
        control_type: Optional[str] = None,
        title: Optional[str] = None,
        timeout: Optional[float] = None,
        outline_colour: str = "green",
    ) -> AppUIActionResult:
        """
        클릭 없이 특정 요소를 찾아 화면에 강조(outline) 표시합니다.
        """
        self.ensure_focus()
        top_window = self._session.get_top_window()
        if top_window is None:
            return AppUIActionResult(result="error", message="대상 애플리케이션 윈도우를 확보할 수 없습니다.")

        criteria = {}
        if auto_id: criteria["auto_id"] = auto_id
        if control_type: criteria["control_type"] = control_type
        if title: criteria["title"] = title

        if not criteria:
            return AppUIActionResult(result="error", message="검색 조건이 필요합니다.")

        try:
            target = top_window.child_window(**criteria)
            actual_timeout = timeout if timeout is not None else 5.0
            
            target.wait("exists", timeout=actual_timeout)
            target.draw_outline(colour=outline_colour)
            
            return AppUIActionResult(result="success", message=f"요소 강조 표시 성공: {criteria}")
        except Exception as e:
            return AppUIActionResult(result="error", message=f"요소 강조 표시 실패: {e}")

    def get_element_coords_by_attr(
        self,
        auto_id: Optional[str] = None,
        control_type: Optional[str] = None,
        title: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> AppUIActionResult:
        """
        특정 요소를 찾아 그 중심 좌표를 반환합니다.
        """
        self.ensure_focus()
        top_window = self._session.get_top_window()
        if top_window is None:
            return AppUIActionResult(result="error", message="대상 애플리케이션 윈도우를 확보할 수 없습니다.")

        criteria = {}
        if auto_id: criteria["auto_id"] = auto_id
        if control_type: criteria["control_type"] = control_type
        if title: criteria["title"] = title

        if not criteria:
            return AppUIActionResult(result="error", message="검색 조건이 필요합니다.")

        try:
            target = top_window.child_window(**criteria)
            actual_timeout = timeout if timeout is not None else 5.0
            
            target.wait("exists", timeout=actual_timeout)
            
            # 좌표 획득
            rect = target.rectangle()
            center = rect.mid_point()
            
            return AppUIActionResult(
                result="success", 
                message=f"요소 좌표 획득 성공: {criteria}",
                x=int(center.x),
                y=int(center.y)
            )
        except Exception as e:
            return AppUIActionResult(result="error", message=f"요소 좌표 획득 실패: {e}")




def get_app_ui_action(session: Optional[AppSession] = None) -> AppUIAction:
    """AppUIAction 인스턴스 반환"""
    return AppUIAction(session)
