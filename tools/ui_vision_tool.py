"""
애플리케이션 UI 제어 관련 도구 (시각 지능 기반)

화면 캡처와 OCR을 사용하여 애플리케이션의 UI 요소를 제어합니다.
전체 데스크톱 보다는 현재 연결된 애플리케이션 윈도우 범위를 우선적으로 탐색합니다.
"""

import logging
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from actions.app_ui_action import get_app_ui_action

logger = logging.getLogger(__name__)


def register_ui_vision_tools(mcp: FastMCP) -> None:
    """애플리케이션 UI 시각 제어 도구 등록"""

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
        logger.info(f"[Tool] type_app_text 호출: text='{text}', interval={interval}, submit_shortcut={submit_shortcut}")
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        focus_result = action.ensure_focus()
        if not focus_result.is_success:
            return str(focus_result.to_dict())

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
            return json.dumps(submit_result.to_dict(), ensure_ascii=False)
            
        return json.dumps(result.to_dict(), ensure_ascii=False)

    @mcp.tool()
    def press_app_shortcut(shortcut: str) -> str:
        """
        시스템/앱 단축키를 입력합니다.
        
        Args:
            shortcut: 단축키 (예: "ctrl+c", "alt+f4", "enter")
        """
        logger.info(f"[Tool] press_app_shortcut 호출: shortcut={shortcut}")
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        focus_result = action.ensure_focus()
        if not focus_result.is_success:
            return str(focus_result.to_dict())

        result = action.press_shortcut(shortcut)
        return json.dumps(result.to_dict(), ensure_ascii=False)

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
        logger.info(f"[Tool] click_app_rgb 호출: r={r}, g={g}, b={b}, tolerance={tolerance}, button={button}, timeout={timeout}")
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        focus_result = action.ensure_focus()
        if not focus_result.is_success:
            return json.dumps(focus_result.to_dict(), ensure_ascii=False)

        # 1. 위치 찾기 (Atomic Action)
        find_result = action.find_rgb_position(
            rgb=(r, g, b),
            tolerance=tolerance,
            timeout=timeout,
        )
        if not find_result.is_success:
            return json.dumps(find_result.to_dict(), ensure_ascii=False)

        # 2. 클릭하기 (Atomic Action)
        click_result = action.click_position(
            x=find_result.x or 0,
            y=find_result.y or 0,
            button=button,
        )
        return json.dumps(click_result.to_dict(), ensure_ascii=False)

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
        logger.info(f"[Tool] click_app_image 호출: path={image_path}, confidence={confidence}, button={button}, clicks={clicks}, timeout={timeout}")
        action = get_app_ui_action()
        # 0. 포커스 확보 (Atomic Action)
        focus_result = action.ensure_focus()
        if not focus_result.is_success:
            return json.dumps(focus_result.to_dict(), ensure_ascii=False)

        # 1. 위치 찾기 (Atomic Action)
        find_result = action.find_image_position(
            image_path=image_path,
            confidence=confidence,
            timeout=timeout,
        )
        if not find_result.is_success:
            return json.dumps(find_result.to_dict(), ensure_ascii=False)

        # 2. 클릭하기 (Atomic Action)
        click_result = action.click_position(
            x=find_result.x or 0,
            y=find_result.y or 0,
            button=button,
            clicks=clicks,
        )
        return json.dumps(click_result.to_dict(), ensure_ascii=False)


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
        logger.info(f"[Tool] click_app_keyword 호출: keyword='{keyword}', match_mode={match_mode}, case_sensitive={case_sensitive}, language={language}, button={button}, clicks={clicks}, ocr_timeout={ocr_timeout}")
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
    async def click_app_element(
        keyword: str,
        element_type: str = "any",
        match_mode: str = "contains",
        case_sensitive: bool = False,
        button: str = "left",
        clicks: int = 1,
    ) -> dict:
        """
        텍스트(keyword)와 UI 형식(element_type)을 함께 만족하는 요소를 찾아 클릭합니다.
        
        Args:
            keyword: 찾을 텍스트 (버튼 이름, 라벨 등)
            element_type: UI 형식 (예: "Button", "Edit", "TabItem", "MenuItem" 등). "any" 이면 형식 검사 생략.
            match_mode: 텍스트 일치 모드 ("contains" 또는 "exact")
            case_sensitive: 대소문자 구분 여부
            button: 마우스 버튼 ("left", "right", "middle")
            clicks: 클릭 횟수
        """
        logger.info(f"[Tool] click_app_element 호출: keyword='{keyword}', element_type={element_type}, match_mode={match_mode}, case_sensitive={case_sensitive}, button={button}, clicks={clicks}")
        action = get_app_ui_action()
        analysis = await action.describe_current_state(
            keyword=keyword,
            match_mode=match_mode,
            case_sensitive=case_sensitive,
            include_components=True,
            include_ocr_hits=True, # OCR 백업 활성화
            component_limit=300,   # 탐색 범위 확대
        )

        components = analysis.get("components", [])
        
        matches = []
        # 1. UIA 구성요소에서 먼저 탐색
        for comp in components:
            comp_type = str(comp.get("control_type", "")).lower()
            target_type = element_type.lower()
            
            type_matched = (target_type == "any") or (target_type in comp_type)
            if not type_matched:
                continue
                
            normalized_keyword = keyword if case_sensitive else keyword.lower()
            normalized_keyword = " ".join(normalized_keyword.split())
            
            candidates = [
                str(comp.get("title", "")),
                str(comp.get("auto_id", "")),
                str(comp.get("class_name", ""))
            ]
            
            text_matched = False
            for cand in candidates:
                cand_norm = cand if case_sensitive else cand.lower()
                cand_norm = " ".join(cand_norm.split())
                
                if match_mode == "exact":
                    if cand_norm == normalized_keyword:
                        text_matched = True
                        break
                else:
                    if normalized_keyword in cand_norm:
                        text_matched = True
                        break
            
            if text_matched:
                matches.append(comp)

        # 2. UIA에서 못 찾으면 OCR 히트에서 탐색 (element_type이 any인 경우에만 우선 권장)
        if not matches:
            ocr_hits = (analysis.get("keyword_hits", {}) or {}).get("ocr", []) or []
            if ocr_hits:
                logger.info(f"UIA에서 '{keyword}'를 찾지 못해 OCR 결과에서 탐색합니다.")
                matches = ocr_hits

        if not matches:
            return {
                "result": "not_found",
                "is_success": False,
                "message": f"keyword '{keyword}' 및 형식 '{element_type}'을(를) 만족하는 요소를 UIA/OCR 모두에서 찾지 못했습니다.",
                "screen_flags": analysis.get("screen_flags", {}),
            }

        target = matches[0]

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
        logger.info("[Tool] check_app_screen_state 호출")
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
        logger.info(f"[Tool] find_app_icon_target 호출: name={icon_name}, keyword={keyword}")
        action = get_app_ui_action()
        # 0. 포커스 확보
        focus_result = action.ensure_focus()
        if not focus_result.is_success:
            return {"result": "error", "message": focus_result.message, "is_success": False}
        
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
        logger.info(f"[Tool] click_app_icon_target 호출: name={icon_name}, keyword={keyword}, button={button}")
        action = get_app_ui_action()
        # 0. 포커스 확보
        focus_result = action.ensure_focus()
        if not focus_result.is_success:
            return {"result": "error", "message": focus_result.message, "is_success": False}
            
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


    logger.info("UI 시각 제어 도구 등록 완료: type_app_text, press_app_shortcut, click_app_rgb, click_app_image, click_app_keyword, click_app_element, check_app_screen_state, find_app_icon_target, click_app_icon_target")
