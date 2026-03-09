"""
현재 화면 기준 locator.yaml 업데이트 Action

설정된 executable_path 대상 애플리케이션에 연결한 뒤,
현재 활성 화면(또는 top window)의 UI 요소를 스캔하여
config/locator.yaml을 갱신합니다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from core.app_launcher import get_launcher
from core.app_session import AppSession

logger = logging.getLogger(__name__)


@dataclass
class LocatorUpdateResponse:
    """locator 업데이트 응답"""

    result: str
    message: str
    window_name: Optional[str] = None
    locator_path: Optional[str] = None
    added_or_updated_count: int = 0
    total_element_count: int = 0

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "message": self.message,
            "window_name": self.window_name,
            "locator_path": self.locator_path,
            "added_or_updated_count": self.added_or_updated_count,
            "total_element_count": self.total_element_count,
            "is_success": self.result == "success",
        }


class LocatorUpdateAction:
    """
    현재 화면 정보를 이용해 locator.yaml을 갱신하는 Action
    """

    def __init__(
        self,
        session: Optional[AppSession] = None,
        locator_file_path: Optional[str] = None,
    ):
        self._session = session or AppSession.get_instance()
        self._locator_file_path = locator_file_path

    def update_from_current_screen(
        self,
        window_name: Optional[str] = None,
        include_invisible: bool = False,
        max_elements: int = 200,
        merge_with_existing: bool = True,
    ) -> LocatorUpdateResponse:
        """
        현재 화면 기준으로 locator.yaml 갱신

        Args:
            window_name: locator.yaml에 저장할 윈도우 키 이름 (없으면 자동 생성)
            include_invisible: 비가시 요소 포함 여부
            max_elements: 최대 요소 수집 개수
            merge_with_existing: 기존 요소와 병합할지 여부
        """
        if max_elements <= 0:
            return LocatorUpdateResponse(
                result="error",
                message="max_elements는 1 이상이어야 합니다",
            )

        try:
            self._ensure_connected_to_configured_exe()
            target_window = self._get_current_app_window()

            window_locator = self._build_window_locator(target_window)
            resolved_window_name = (
                window_name.strip()
                if window_name and window_name.strip()
                else self._generate_window_name(window_locator)
            )

            new_elements = self._collect_elements(
                target_window=target_window,
                include_invisible=include_invisible,
                max_elements=max_elements,
            )

            locator_path = self._resolve_locator_path()
            locator_path.parent.mkdir(parents=True, exist_ok=True)

            existing = self._load_existing_locator(locator_path)
            old_entry = existing.get(resolved_window_name, {})
            old_elements = (
                old_entry.get("elements", {})
                if isinstance(old_entry, dict)
                else {}
            )

            if merge_with_existing:
                merged_elements = dict(old_elements)
                merged_elements.update(new_elements)
                final_elements = merged_elements
                changed_count = len(new_elements)
            else:
                final_elements = new_elements
                changed_count = len(new_elements)

            existing[resolved_window_name] = {
                "window": window_locator,
                "elements": final_elements,
            }

            with open(locator_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(existing, f, allow_unicode=True, sort_keys=False)

            # 런타임 세션에서도 즉시 최신 locator를 사용하도록 갱신
            self._session.reload_locators()

            message = (
                f"locator.yaml 업데이트 완료: window={resolved_window_name}, "
                f"changed={changed_count}, total={len(final_elements)}"
            )
            logger.info(message)

            return LocatorUpdateResponse(
                result="success",
                message=message,
                window_name=resolved_window_name,
                locator_path=str(locator_path),
                added_or_updated_count=changed_count,
                total_element_count=len(final_elements),
            )
        except Exception as e:
            logger.error(f"locator 업데이트 실패: {e}")
            return LocatorUpdateResponse(
                result="error",
                message=f"locator 업데이트 실패: {e}",
            )

    def _ensure_connected_to_configured_exe(self) -> None:
        if self._session.is_connected:
            return

        executable_path = (
            self._session.config.get("application", {}).get("executable_path")
        )
        if not executable_path:
            raise ValueError("config/app_config.yaml에 executable_path가 없습니다")

        launcher = get_launcher()

        # 우선 실행 중 프로세스 연결을 시도하고, 실패하면 실행합니다.
        try:
            launcher.connect_to_running(path=executable_path)
            logger.info(f"실행 중 앱 연결 성공: {executable_path}")
        except Exception:
            launcher.launch(path=executable_path, wait_for_ready=True)
            logger.info(f"앱 실행 후 연결 성공: {executable_path}")

    def _get_current_app_window(self) -> Any:
        app = self._session.app
        app_windows = app.windows()
        app_handles = {getattr(w, "handle", None) for w in app_windows}

        # 가능하면 현재 활성 윈도우를 우선 사용
        try:
            from pywinauto import Desktop

            backend = self._session.config.get("application", {}).get(
                "backend", "uia"
            )
            active = Desktop(backend=backend).get_active()
            active_handle = getattr(active, "handle", None)
            if active_handle in app_handles:
                return active.wrapper_object()
        except Exception as e:
            logger.debug(f"활성 윈도우 확인 실패, top_window로 대체: {e}")

        return app.top_window().wrapper_object()

    def _build_window_locator(self, window_wrapper: Any) -> Dict[str, Any]:
        info = window_wrapper.element_info

        title = self._clean_text(getattr(info, "name", ""))
        auto_id = self._clean_text(getattr(info, "automation_id", ""))
        class_name = self._clean_text(getattr(info, "class_name", ""))
        control_type = self._clean_text(getattr(info, "control_type", ""))

        locator: Dict[str, Any] = {}
        if title:
            locator["title"] = title
        if control_type:
            locator["control_type"] = control_type
        if auto_id:
            locator["auto_id"] = auto_id
        elif class_name:
            locator["class_name"] = class_name

        if not locator:
            raise ValueError("현재 화면에서 윈도우 식별 정보를 추출하지 못했습니다")

        return locator

    def _collect_elements(
        self,
        target_window: Any,
        include_invisible: bool,
        max_elements: int,
    ) -> Dict[str, Dict[str, Any]]:
        elements: Dict[str, Dict[str, Any]] = {}
        signature_count: Dict[tuple, int] = {}
        key_count: Dict[str, int] = {}

        for child in target_window.descendants():
            if len(elements) >= max_elements:
                break

            if not include_invisible:
                try:
                    if not child.is_visible():
                        continue
                except Exception:
                    continue

            locator = self._build_element_locator(child)
            if not locator:
                continue

            signature = tuple(
                (k, locator[k])
                for k in ("auto_id", "title", "class_name", "control_type")
                if k in locator
            )
            idx = signature_count.get(signature, 0)
            signature_count[signature] = idx + 1
            if idx > 0:
                locator["found_index"] = idx

            element_key = self._build_element_key(locator, key_count)
            elements[element_key] = locator

        return elements

    def _build_element_locator(self, element: Any) -> Dict[str, Any]:
        info = element.element_info

        title = self._clean_text(getattr(info, "name", ""))
        auto_id = self._clean_text(getattr(info, "automation_id", ""))
        class_name = self._clean_text(getattr(info, "class_name", ""))
        control_type = self._clean_text(getattr(info, "control_type", ""))

        locator: Dict[str, Any] = {}

        if auto_id:
            locator["auto_id"] = auto_id
        elif title:
            locator["title"] = title
        elif class_name:
            locator["class_name"] = class_name
        else:
            return {}

        if control_type:
            locator["control_type"] = control_type

        desc_value = auto_id or title or class_name
        if desc_value:
            locator["description"] = f"{control_type or 'Control'}: {desc_value}"

        return locator

    def _build_element_key(
        self,
        locator: Dict[str, Any],
        key_count: Dict[str, int],
    ) -> str:
        base_source = (
            locator.get("auto_id")
            or locator.get("title")
            or locator.get("class_name")
            or "element"
        )
        control_type = self._to_snake_case(str(locator.get("control_type", "")))
        base = self._to_snake_case(str(base_source))
        if control_type and not base.endswith(control_type):
            base = f"{base}_{control_type}"

        if not base:
            base = "element"

        idx = key_count.get(base, 0)
        key_count[base] = idx + 1
        if idx == 0:
            return base
        return f"{base}_{idx + 1}"

    def _generate_window_name(self, window_locator: Dict[str, Any]) -> str:
        source = (
            window_locator.get("auto_id")
            or window_locator.get("title")
            or window_locator.get("class_name")
            or "captured"
        )
        base = self._to_snake_case(str(source))
        if not base.endswith("_window"):
            base = f"{base}_window"
        return base

    def _resolve_locator_path(self) -> Path:
        if self._locator_file_path:
            return Path(self._locator_file_path)
        return Path(__file__).resolve().parent.parent / "config" / "locator.yaml"

    def _load_existing_locator(self, locator_path: Path) -> Dict[str, Any]:
        if not locator_path.exists():
            return {}

        with open(locator_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {}
        return data

    @staticmethod
    def _to_snake_case(value: str) -> str:
        text = value.strip()
        if not text:
            return ""
        text = re.sub(r"[^a-zA-Z0-9]+", "_", text)
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
        text = re.sub(r"_+", "_", text)
        return text.strip("_").lower()

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()


def get_locator_update_action(
    session: Optional[AppSession] = None,
    locator_file_path: Optional[str] = None,
) -> LocatorUpdateAction:
    """LocatorUpdateAction 인스턴스 반환"""
    return LocatorUpdateAction(session=session, locator_file_path=locator_file_path)

