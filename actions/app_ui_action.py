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

            wrapper = self._pick_target_window()
            if wrapper is not None:
                rect = wrapper.rectangle()
                return (rect.left, rect.top, rect.width(), rect.height())
        except Exception as e:
            logger.debug(f"윈도우 영역 획득 실패: {e}")
        
        return None

    def ensure_focus(self) -> AppUIActionResult:
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

            wrapper = self._pick_target_window()
            if wrapper is None:
                # 마지막 수단: top_window() 시도
                try:
                    wrapper = self._safe_call(lambda: self._session.app.top_window().wrapper_object(), None)
                except Exception:
                    pass
                
            if wrapper is None:
                return AppUIActionResult(result="error", message="포커스를 줄 수 있는 앱 윈도우를 찾지 못했습니다")

            # 윈도우 상태 확인 및 복구
            is_minimized = self._safe_call(wrapper.is_minimized, False)
            if is_minimized:
                logger.info("윈도우가 최소화되어 있어 복구를 시도합니다.")
                wrapper.restore()
                time.sleep(self._session.config.get("timeouts", {}).get("ui_delay", 0.5))

            # 윈도우를 최상단으로 가져오고 포커스 설정
            try:
                # 1. 일반적인 포커스 시도
                wrapper.set_focus()
                
                # 2. 추가적인 강제 활성화 (최소화되어 있지 않아도 뒤에 숨어있을 수 있음)
                # draw_outline은 호출 비용이 커서 기본 포커스 경로에서는 사용하지 않습니다.
            except Exception as e:
                logger.warning(f"set_focus 실패: {e}. 대안을 시도합니다.")
                try:
                    # win32 backend의 경우 더 강력한 활성화 시도
                    wrapper.maximize()
                    wrapper.restore()
                except Exception:
                    pass
            
            # 윈도우 활성화 대기
            time.sleep(self._session.config.get("timeouts", {}).get("after_focus_delay", 0.5))
            
            # 윈도우가 가시적인지 재확인
            if not self._safe_call(wrapper.is_visible, False):
                logger.warning("포커스 시도 후에도 윈도우가 가시적이지 않습니다.")
                # 한 번 더 restore 시도
                self._safe_call(wrapper.restore, None)

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
                
                # 세션 연결 시도 (아직 안 되어 있다면)
                if not self._session.is_connected:
                    self._safe_call(self._session.connect, None)
                
                if self._session.is_connected:
                    target_pid = getattr(self._session.app, 'process', None)
                    if target_pid and fg_pid == target_pid:
                        # 현재 포커스된 창이 우리 앱의 것이라면 해당 창을 그대로 사용
                        from pywinauto.controls.hwndwrapper import HwndWrapper
                        wrapper = HwndWrapper(fg_hwnd)
                        if self._safe_call(wrapper.is_visible, False):
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
                self._session.connect()
            
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

                is_visible = self._safe_call(wrapper.is_visible, False)
                is_minimized = self._safe_call(wrapper.is_minimized, False)
                
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
                            is_visible = self._safe_call(wrapper.is_visible, False)
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
        nodes = [root]
        descendants = self._safe_call(root.descendants, []) or []
        nodes.extend(descendants)

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

    def _list_candidate_child_windows(self, root: Any, *, include_descendants: bool = False) -> list[Any]:
        """속성 클릭 시 탐색 루트로 사용할 child window 후보를 반환합니다."""
        candidates: list[Any] = []
        raw_children = self._safe_call(root.children, []) or []
        if include_descendants:
            descendants = self._safe_call(root.descendants, []) or []
            raw_children.extend(descendants)
        allowed_control_types = {"window", "pane", "document", "group", "custom"}
        seen_ids: set[str] = set()
        for child in raw_children:
            wrapper = self._safe_call(lambda: child.wrapper_object(), None) or child
            if not self._safe_call(wrapper.exists, False):
                continue
            if not self._safe_call(wrapper.is_visible, False):
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

    def _resolve_attr_search_root(
        self,
        *,
        window_target: str,
        child_window_title: Optional[str],
        child_window_match_mode: str,
        case_sensitive: bool,
    ) -> tuple[Optional[Any], str]:
        """
        click_app_by_attr 탐색 루트를 결정합니다.
        - top: 최상위 윈도우에서 탐색
        - child: top의 child window에서 탐색
        - auto: child title이 있으면 child 우선, 없으면 top 사용
        """
        top_window = self._session.cached_window
        if top_window is not None and not self._safe_call(top_window.exists, False):
            top_window = None
        if top_window is None:
            top_window = self._pick_target_window() or self._session.get_top_window()
        if top_window is None:
            return None, "none"

        target_mode = (window_target or "auto").strip().lower()
        child_title = (child_window_title or "").strip()
        children = self._list_candidate_child_windows(top_window)

        def pick_child_by_direct_api() -> Optional[Any]:
            if not child_title:
                return None

            # 사용자가 요청한 pywinauto 기본 방식(top_window.child_window(title=...))을 우선 시도
            direct_wrapper = self._safe_call(
                lambda: top_window.child_window(title=child_title).wrapper_object(),
                None,
            )
            if direct_wrapper is not None and self._safe_call(direct_wrapper.exists, False):
                return direct_wrapper

            # contains/case-insensitive 대응을 위해 title_re 경로도 보강
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
            if regex_wrapper is not None and self._safe_call(regex_wrapper.exists, False):
                return regex_wrapper

            return None

        def pick_child_by_title() -> Optional[Any]:
            if not child_title:
                return None
            direct_matched = pick_child_by_direct_api()
            if direct_matched is not None:
                return direct_matched

            for child in children:
                for candidate_title in self._get_node_title_candidates(child):
                    if self._is_attr_match(
                        actual=candidate_title,
                        expected=child_title,
                        match_mode=child_window_match_mode,
                        case_sensitive=case_sensitive,
                    ):
                        return child

            # direct child에서 못 찾으면 descendants까지 확장 탐색
            descendants = self._list_candidate_child_windows(top_window, include_descendants=True)
            for child in descendants:
                for candidate_title in self._get_node_title_candidates(child):
                    if self._is_attr_match(
                        actual=candidate_title,
                        expected=child_title,
                        match_mode=child_window_match_mode,
                        case_sensitive=case_sensitive,
                    ):
                        return child
            return None

        if target_mode == "top":
            return top_window, "top"

        if target_mode == "child":
            matched_child = pick_child_by_title()
            if matched_child is not None:
                return matched_child, f"child(title={child_title})"
            if child_title:
                return None, f"child_not_found(title={child_title})"
            if children:
                return children[0], "child(first_visible)"
            return None, "child_not_found(no_children)"

        # auto mode
        matched_child = pick_child_by_title()
        if matched_child is not None:
            return matched_child, f"auto->child(title={child_title})"
        return top_window, "auto->top"

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
            if self._verify_process_path(wrapper) and self._safe_call(wrapper.is_visible, False):
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
            "control_type": self._safe_call(lambda: main_wrapper.element_info.control_type, "") or "",
            "rect": self._rect_to_dict(self._safe_call(main_wrapper.rectangle, None)),
        }

        # 2. 모든 타겟 윈도우의 자식 요소 수집
        global_idx = 0
        for wrapper in target_windows:
            win_title = self._safe_call(wrapper.window_text, "Unknown Window")
            nodes = [wrapper]
            descendants = self._safe_call(wrapper.descendants, []) or []
            nodes.extend(descendants)

            for node in nodes:
                if global_idx >= component_limit:
                    break
                
                if not self._safe_call(node.is_visible, False):
                    continue

                title = self._safe_call(node.window_text, "") or ""
                auto_id = self._safe_call(lambda: node.element_info.automation_id, "") or ""
                control_type = self._safe_call(lambda: node.element_info.control_type, "") or ""
                rect = self._safe_call(node.rectangle, None)
                rect_dict = self._rect_to_dict(rect)
                
                # 내부 로직용 데이터 (좌표 포함)
                comp = {
                    "index": global_idx,
                    "title": title,
                    "auto_id": auto_id,
                    "control_type": control_type,
                    "window": win_title,
                    "x": rect_dict.get("center_x"),
                    "y": rect_dict.get("center_y"),
                }
                components.append(comp)

                if target_keyword and self._is_keyword_match(
                    candidate_values=[title, auto_id, control_type],
                    keyword=target_keyword,
                    match_mode=match_mode,
                    case_sensitive=case_sensitive,
                ):
                    keyword_hits.append({
                        "index": global_idx,
                        "title": title,
                        "auto_id": auto_id,
                        "x": rect_dict.get("center_x"),
                        "y": rect_dict.get("center_y"),
                        "source": "uia"
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
        현재 앱 상태/구성요소를 반환하고, keyword 기반 좌표를 함께 제공합니다.
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
        if region is None:
            return AppUIActionResult(result="error", message="대상 애플리케이션 윈도우를 찾을 수 없거나 경로가 일치하지 않습니다.")

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
        child_window_match_mode: str = "contains",
        button: str = "left",
        clicks: int = 1,
        double: bool = False,
        timeout: Optional[float] = None,
        draw_outline: bool = False,
        outline_colour: str = "red",
    ) -> AppUIActionResult:
        """
        속성 기반으로 특정 요소를 찾아 클릭합니다.
        auto_id/control_type/title/legacy_value 중 하나 이상을 입력받아 대상을 식별합니다.
        """
        focus_result = self.ensure_focus()
        if not focus_result.is_success:
            return AppUIActionResult(result="error", message=focus_result.message)

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

        try:
            actual_timeout = timeout if timeout is not None else 5.0
            start = time.monotonic()
            target = None
            search_root_info = "none"
            while True:
                search_root, search_root_info = self._resolve_attr_search_root(
                    window_target=window_target,
                    child_window_title=child_window_title,
                    child_window_match_mode=child_window_match_mode,
                    case_sensitive=case_sensitive,
                )
                if search_root is None:
                    target = None
                else:
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
                    break
                if time.monotonic() - start > actual_timeout:
                    break
                time.sleep(0.2)

            if target is None:
                return AppUIActionResult(
                    result="error",
                    message=(
                        "요소를 찾지 못했습니다: "
                        f"auto_id={auto_id}, control_type={control_type}, title={title}, legacy_value={legacy_value}, "
                        f"window_target={window_target}, child_window_title={child_window_title}, search_root={search_root_info}"
                    ),
                )
            
            # 하이라이트 표시
            if draw_outline:
                try:
                    target.draw_outline(colour=outline_colour)
                except Exception as e:
                    logger.warning(f"테두리 그리기 실패: {e}")
            
            click_method = self._click_with_preferred_action(
                target,
                button=button,
                clicks=clicks,
                double=double,
            )
            return AppUIActionResult(
                result="success",
                message=(
                    "요소 클릭 성공: "
                    f"auto_id={auto_id}, control_type={control_type}, title={title}, legacy_value={legacy_value}, "
                    f"window_target={window_target}, child_window_title={child_window_title}, "
                    f"search_root={search_root_info}, method={click_method}"
                ),
            )
        except Exception as e:
            logger.error(f"속성 기반 요소 클릭 실패: {e}")
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
