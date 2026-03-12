"""
애플리케이션 UI 제어 관련 도구

화면 캡처와 OCR을 사용하여 애플리케이션의 UI 요소를 제어합니다.
전체 데스크톱 보다는 현재 연결된 애플리케이션 윈도우 범위를 우선적으로 탐색합니다.
"""

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from actions.app_ui_action import get_app_ui_action

logger = logging.getLogger(__name__)


def register_app_ui_tools(mcp: FastMCP) -> None:
    """애플리케이션 UI 제어 도구 등록"""

    @mcp.tool()
    async def find_app_text(
        text: str,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        timeout: Optional[float] = None,
        language: str = "eng",
    ) -> str:
        """
        애플리케이션 화면 내에서 OCR을 사용해 특정 텍스트의 위치를 찾습니다.
        
        UIA(UI Automation)로 요소를 찾기 어려울 때 사용합니다.
        현재 연결된 앱 윈도우 영역을 우선적으로 탐색합니다.

        Args:
            text: 찾을 텍스트
            match_mode: 일치 모드 ("contains" 또는 "exact")
            case_sensitive: 대소문자 구분 여부
            timeout: 최대 대기 시간(초)
            language: OCR 언어 (eng, kor 등)
        """
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        action.ensure_focus()

        result = await action.find_text_position(
            text=text,
            match_mode=match_mode,
            case_sensitive=case_sensitive,
            timeout=timeout,
            language=language,
        )
        return str(result.to_dict())

    @mcp.tool()
    async def click_app_text(
        text: str,
        button: str = "left",
        clicks: int = 1,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        timeout: Optional[float] = None,
        language: str = "eng",
    ) -> str:
        """
        애플리케이션 화면에서 텍스트를 찾아 해당 위치를 클릭합니다.
        
        Args:
            text: 클릭할 텍스트
            button: 마우스 버튼 ("left", "right", "middle")
            clicks: 클릭 횟수 (1: 단일 클릭, 2: 더블 클릭)
            match_mode: 일치 모드 ("contains" 또는 "exact")
            timeout: 최대 대기 시간(초)
            language: OCR 언어 (eng, kor 등)
        """
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        action.ensure_focus()

        # 1. 위치 찾기 (Atomic Action)
        find_result = await action.find_text_position(
            text=text,
            match_mode=match_mode,
            case_sensitive=case_sensitive,
            timeout=timeout,
            language=language,
        )
        if not find_result.is_success:
            return str(find_result.to_dict())

        # 2. 클릭하기 (Atomic Action)
        click_result = action.click_position(
            x=find_result.x or 0,
            y=find_result.y or 0,
            button=button,
            clicks=clicks,
        )
        if click_result.is_success:
            click_result.matched_text = find_result.matched_text
            
        return str(click_result.to_dict())

    @mcp.tool()
    def type_app_text(
        text: str,
        interval: float = 0.02,
        submit_shortcut: Optional[str] = None,
    ) -> str:
        """
        현재 포커스된 위치에 텍스트를 입력합니다.
        
        Args:
            text: 입력할 텍스트
            interval: 글자 간 입력 간격
            submit_shortcut: 입력 후 누를 단축키 (예: "enter")
        """
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        action.ensure_focus()

        # 1. 텍스트 입력 (Atomic Action)
        result = action.type_text(
            text=text,
            interval=interval,
        )
        if not result.is_success:
            return str(result.to_dict())
            
        # 2. 제출 단축키 입력 (Atomic Action)
        if submit_shortcut:
            submit_result = action.press_shortcut(submit_shortcut)
            return str(submit_result.to_dict())
            
        return str(result.to_dict())

    @mcp.tool()
    def press_app_shortcut(shortcut: str) -> str:
        """
        시스템/앱 단축키를 입력합니다.
        
        Args:
            shortcut: 단축키 (예: "ctrl+c", "alt+f4", "enter")
        """
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        action.ensure_focus()

        result = action.press_shortcut(shortcut)
        return str(result.to_dict())

    @mcp.tool()
    def click_app_rgb(
        r: int,
        g: int,
        b: int,
        tolerance: int = 5,
        button: str = "left",
        timeout: Optional[float] = None,
    ) -> str:
        """
        특정 색상(RGB)이 나타나는 위치를 찾아 클릭합니다.
        
        Args:
            r, g, b: RGB 색상 값 (0-255)
            tolerance: 허용 오차
            button: 마우스 버튼
            timeout: 최대 대기 시간
        """
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        action.ensure_focus()

        # 1. 위치 찾기 (Atomic Action)
        find_result = action.find_rgb_position(
            rgb=(r, g, b),
            tolerance=tolerance,
            timeout=timeout,
        )
        if not find_result.is_success:
            return str(find_result.to_dict())

        # 2. 클릭하기 (Atomic Action)
        click_result = action.click_position(
            x=find_result.x or 0,
            y=find_result.y or 0,
            button=button,
        )
        return str(click_result.to_dict())

    @mcp.tool()
    def click_app_image(
        image_path: str,
        confidence: float = 0.8,
        button: str = "left",
        clicks: int = 1,
        timeout: Optional[float] = None,
    ) -> str:
        """
        화면에서 이미지를 찾아 클릭합니다.
        앱 윈도우 영역 내에서 이미지를 탐색합니다.

        Args:
            image_path: 이미지 파일 경로
            confidence: 유사도 (0.0~1.0)
            button: 마우스 버튼
            clicks: 클릭 횟수
            timeout: 최대 대기 시간
        """
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        action.ensure_focus()

        # 1. 위치 찾기 (Atomic Action)
        find_result = action.find_image_position(
            image_path=image_path,
            confidence=confidence,
            timeout=timeout,
        )
        if not find_result.is_success:
            return str(find_result.to_dict())

        # 2. 클릭하기 (Atomic Action)
        click_result = action.click_position(
            x=find_result.x or 0,
            y=find_result.y or 0,
            button=button,
            clicks=clicks,
        )
        return str(click_result.to_dict())

    @mcp.tool()
    async def analyze_app_screen(
        keyword: Optional[str] = None,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        language: str = "eng",
        include_components: bool = True,
        component_limit: int = 150,
        include_ocr_hits: bool = True,
        ocr_timeout: Optional[float] = 2.0,
        auto_click_keyword: bool = False,
        click_button: str = "left",
        clicks: int = 1,
    ) -> dict:
        """
        현재 연결된 앱의 화면 상태/구성요소를 분석하고 keyword 좌표를 반환합니다.

        - exe path로 연결된 앱 기준 현재 화면 구성요소(UIA)를 덤프
        - keyword가 있으면 UIA/OCR에서 매칭 좌표(x, y)를 함께 반환
        - auto_click_keyword=True면 매칭 좌표를 즉시 클릭
        """
        action = get_app_ui_action()
        analysis = await action.describe_current_state(
            keyword=keyword,
            match_mode=match_mode,
            case_sensitive=case_sensitive,
            language=language,
            include_components=include_components,
            component_limit=component_limit,
            include_ocr_hits=include_ocr_hits,
            ocr_timeout=ocr_timeout,
        )

        if not keyword:
            return analysis

        uia_hits = (analysis.get("keyword_hits", {}) or {}).get("uia", []) or []
        ocr_hits = (analysis.get("keyword_hits", {}) or {}).get("ocr", []) or []

        selected = None
        if uia_hits:
            button_hits = [
                hit for hit in uia_hits if "button" in str(hit.get("control_type", "")).lower()
            ]
            selected = (button_hits or uia_hits)[0]
        elif ocr_hits:
            selected = ocr_hits[0]

        keyword_action = {
            "requested_keyword": keyword,
            "selected_target": selected,
            "clicked": False,
        }

        if auto_click_keyword and selected:
            click_result = action.click_position(
                x=int(selected.get("x", 0)),
                y=int(selected.get("y", 0)),
                button=click_button,
                clicks=clicks,
            )
            keyword_action["clicked"] = click_result.is_success
            keyword_action["click_result"] = click_result.to_dict()

        analysis["keyword_action"] = keyword_action
        return analysis

    @mcp.tool()
    async def click_app_keyword(
        keyword: str,
        match_mode: str = "contains",
        case_sensitive: bool = False,
        language: str = "eng",
        button: str = "left",
        clicks: int = 1,
        ocr_timeout: Optional[float] = 2.0,
    ) -> dict:
        """
        keyword 기반 텍스트 버튼 동작:
        현재 상태 분석 -> keyword 좌표 추출(x,y) -> 클릭을 한 번에 수행합니다.
        """
        action = get_app_ui_action()
        analysis = await action.describe_current_state(
            keyword=keyword,
            match_mode=match_mode,
            case_sensitive=case_sensitive,
            language=language,
            include_components=True,
            include_ocr_hits=True,
            ocr_timeout=ocr_timeout,
        )

        uia_hits = (analysis.get("keyword_hits", {}) or {}).get("uia", []) or []
        ocr_hits = (analysis.get("keyword_hits", {}) or {}).get("ocr", []) or []

        target = None
        if uia_hits:
            button_hits = [
                hit for hit in uia_hits if "button" in str(hit.get("control_type", "")).lower()
            ]
            target = (button_hits or uia_hits)[0]
        elif ocr_hits:
            target = ocr_hits[0]

        if not target:
            return {
                "result": "not_found",
                "is_success": False,
                "message": f"keyword '{keyword}'에 해당하는 좌표를 찾지 못했습니다",
                "analysis": analysis,
            }

        click_result = action.click_position(
            x=int(target.get("x", 0)),
            y=int(target.get("y", 0)),
            button=button,
            clicks=clicks,
        )
        return {
            "result": click_result.result,
            "is_success": click_result.is_success,
            "message": click_result.message,
            "target": target,
            "click": click_result.to_dict(),
            "screen_flags": analysis.get("screen_flags", {}),
        }

    @mcp.tool()
    def check_app_screen_state() -> dict:
        """
        로그인 화면인지/메인 화면인지 등 현재 화면 상태를 반환합니다.
        """
        action = get_app_ui_action()
        return action.get_screen_state_flags()

    @mcp.tool()
    def find_app_icon_target(
        icon_name: Optional[str] = None,
        keyword: Optional[str] = None,
        timeout: Optional[float] = 3.0,
    ) -> dict:
        """
        미리 정의된 아이콘 이미지/메타데이터를 사용해 아이콘 좌표(x,y)를 찾습니다.
        """
        action = get_app_ui_action()
        action.ensure_focus()
        return action.find_icon_from_registry(
            icon_name=icon_name,
            keyword=keyword,
            timeout=timeout,
        )

    @mcp.tool()
    def click_app_icon_target(
        icon_name: Optional[str] = None,
        keyword: Optional[str] = None,
        timeout: Optional[float] = 3.0,
        button: str = "left",
        clicks: int = 1,
    ) -> dict:
        """
        미리 정의된 아이콘 메타데이터로 좌표를 찾은 후 해당 지점을 클릭합니다.
        """
        action = get_app_ui_action()
        action.ensure_focus()
        found = action.find_icon_from_registry(
            icon_name=icon_name,
            keyword=keyword,
            timeout=timeout,
        )
        if not found.get("is_success"):
            return found

        click_result = action.click_position(
            x=int(found.get("x", 0)),
            y=int(found.get("y", 0)),
            button=button,
            clicks=clicks,
        )
        return {
            "result": click_result.result,
            "is_success": click_result.is_success,
            "message": click_result.message,
            "icon": found,
            "click": click_result.to_dict(),
        }
