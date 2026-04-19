"""
애플리케이션 UI 제어 관련 도구

화면의 요소를 Title, AutoID, OCR 등을 사용하여 탐색하고 제어합니다.
"""

import logging
import json
from typing import Optional, List, Dict, Any

from mcp.server.fastmcp import FastMCP

from actions.app_ui_action import get_app_ui_action

logger = logging.getLogger(__name__)




async def find_app_by_ocr(
    keyword: str,
    language: str = "kor+eng",
    timeout: float = 2.0,
    match_mode: str = "contains"
) -> str:
    """
    WinOCR을 사용하여 화면의 텍스트 위치를 찾습니다.
    
    Args:
        keyword: 찾을 텍스트
        language: OCR 언어 (예: "kor+eng", "eng")
        timeout: 최대 대기 시간
        match_mode: 일치 모드 ("exact" 또는 "contains")
    """
    logger.info(f"[Tool] find_app_by_ocr 호출: keyword='{keyword}', language={language}")
    action = get_app_ui_action()
    analysis = await action.describe_current_state(
        keyword=keyword,
        match_mode=match_mode,
        language=language,
        include_components=False,
        include_ocr_hits=True,
        ocr_timeout=timeout
    )
    
    hits = (analysis.get("keyword_hits", {}) or {}).get("ocr", []) or []
    
    return json.dumps({
        "success": len(hits) > 0,
        "count": len(hits),
        "elements": hits,
        "message": f"{len(hits)}개의 텍스트 요소를 OCR로 찾았습니다." if hits else "OCR로 텍스트를 찾지 못했습니다."
    }, ensure_ascii=False)




async def click_app_by_text(
    keyword: str,
    match_mode: str = "contains",
    case_sensitive: bool = False,
    button: str = "left",
    clicks: int = 1,
) -> str:
    """
    UI 요소의 Title(Name)을 사용하여 요소를 찾아 클릭합니다.
    
    Args:
        keyword: 찾을 Title 텍스트
        match_mode: 일치 모드 ("exact" 또는 "contains")
        case_sensitive: 대소문자 구분 여부
        button: 마우스 버튼 ("left", "right", "middle")
        clicks: 클릭 횟수
    """
    logger.info(f"[Tool] click_app_by_text 호출: keyword='{keyword}', match_mode={match_mode}")
    action = get_app_ui_action()
    analysis = await action.describe_current_state(
        keyword=keyword,
        match_mode=match_mode,
        case_sensitive=case_sensitive,
        include_components=True,
        include_ocr_hits=False,
        component_limit=300
    )
    
    hits = (analysis.get("keyword_hits", {}) or {}).get("uia", []) or []
    # Title 매칭 필터링
    title_hits = []
    for h in hits:
        h_title = str(h.get("title", ""))
        if match_mode == "exact":
            if case_sensitive:
                if h_title == keyword: title_hits.append(h)
            else:
                if h_title.lower() == keyword.lower(): title_hits.append(h)
        else:
            if case_sensitive:
                if keyword in h_title: title_hits.append(h)
            else:
                if keyword.lower() in h_title.lower(): title_hits.append(h)

    if not title_hits:
        return json.dumps({"success": False, "message": f"Title '{keyword}'를 가진 요소를 찾지 못했습니다."}, ensure_ascii=False)
        
    target = title_hits[0]
    click_result = action.click_position(
        x=int(target.get("x", 0)),
        y=int(target.get("y", 0)),
        button=button,
        clicks=clicks
    )
    return json.dumps(click_result.to_dict(), ensure_ascii=False)




def type_app_text(
    text: str,
    interval: float = 0.02,
    submit_shortcut: Optional[str] = None,
) -> str:
    """
    현재 포커스된 위치에 텍스트를 입력합니다.
    """
    action = get_app_ui_action()
    focus_result = action.ensure_focus()
    if not focus_result.is_success:
        return json.dumps(focus_result.to_dict(), ensure_ascii=False)

    result = action.type_text(text=text, interval=interval)
    if not result.is_success:
        return json.dumps(result.to_dict(), ensure_ascii=False)
        
    if submit_shortcut:
        submit_result = action.press_shortcut(submit_shortcut)
        return json.dumps(submit_result.to_dict(), ensure_ascii=False)
        
    return json.dumps(result.to_dict(), ensure_ascii=False)


def press_app_shortcut(shortcut: str) -> str:
    """
    시스템/앱 단축키를 입력합니다.
    """
    action = get_app_ui_action()
    focus_result = action.ensure_focus()
    if not focus_result.is_success:
        return json.dumps(focus_result.to_dict(), ensure_ascii=False)

    result = action.press_shortcut(shortcut)
    return json.dumps(result.to_dict(), ensure_ascii=False)


def click_app_position(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1
) -> str:
    """
    지정된 좌표(x, y)를 클릭합니다.
    """
    action = get_app_ui_action()
    focus_result = action.ensure_focus()
    if not focus_result.is_success:
        return json.dumps(focus_result.to_dict(), ensure_ascii=False)

    result = action.click_position(x=x, y=y, button=button, clicks=clicks)
    return json.dumps(result.to_dict(), ensure_ascii=False)


async def click_app_by_keyword(
    keyword: str,
    element_type: str = "any",
    match_mode: str = "contains",
    case_sensitive: bool = False,
    button: str = "left",
    clicks: int = 1,
) -> str:
    """
    키워드와 UI 형식(element_type)을 함께 만족하는 요소를 찾아 클릭합니다.
    """
    action = get_app_ui_action()
    analysis = await action.describe_current_state(
        keyword=keyword,
        match_mode=match_mode,
        case_sensitive=case_sensitive,
        include_components=True,
        include_ocr_hits=True,
        component_limit=300
    )

    components = analysis.get("components", [])
    matches = []
    for comp in components:
        comp_type = str(comp.get("control_type", "")).lower()
        target_type = element_type.lower()
        if (target_type == "any") or (target_type in comp_type):
            if any(kw_hit.get("index") == comp.get("index") for kw_hit in analysis.get("keyword_hits", {}).get("uia", [])):
                matches.append(comp)

    if not matches:
        ocr_hits = (analysis.get("keyword_hits", {}) or {}).get("ocr", []) or []
        if ocr_hits:
            matches = ocr_hits

    if not matches:
        return json.dumps({"success": False, "message": f"'{keyword}' 요소를 찾지 못했습니다."}, ensure_ascii=False)

    target = matches[0]
    click_result = action.click_position(
        x=int(target.get("x", 0)),
        y=int(target.get("y", 0)),
        button=button,
        clicks=clicks
    )
    return json.dumps(click_result.to_dict(), ensure_ascii=False)


def click_app_by_attr(
    auto_id: Optional[str] = None,
    control_type: Optional[str] = None,
    title: Optional[str] = None,
    button: str = "left",
    double: bool = False,
    timeout: Optional[float] = None,
    draw_outline: bool = False,
    outline_colour: str = "red",
) -> str:
    """
    pywinauto의 child_window 기능을 사용하여 요소를 직접 찾아 클릭합니다.
    auto_id, control_type, title 중 하나 이상을 지정해야 합니다.
    draw_outline을 True로 설정하면 클릭 전 요소를 강조 표시합니다.
    """
    action = get_app_ui_action()
    result = action.click_element_by_attr(
        auto_id=auto_id,
        control_type=control_type,
        title=title,
        button=button,
        double=double,
        timeout=timeout,
        draw_outline=draw_outline,
        outline_colour=outline_colour
    )
    return json.dumps(result.to_dict(), ensure_ascii=False)


def highlight_app_by_attr(
    auto_id: Optional[str] = None,
    control_type: Optional[str] = None,
    title: Optional[str] = None,
    timeout: Optional[float] = None,
    outline_colour: str = "green",
) -> str:
    """
    클릭 없이 특정 요소를 찾아 화면에 강조(outline) 표시합니다.
    """
    action = get_app_ui_action()
    result = action.highlight_element_by_attr(
        auto_id=auto_id,
        control_type=control_type,
        title=title,
        timeout=timeout,
        outline_colour=outline_colour
    )
    return json.dumps(result.to_dict(), ensure_ascii=False)


def get_app_coords_by_attr(
    auto_id: Optional[str] = None,
    control_type: Optional[str] = None,
    title: Optional[str] = None,
    timeout: Optional[float] = None,
) -> str:
    """
    특정 요소를 찾아 그 중심 좌표(x, y)를 반환합니다.
    """
    action = get_app_ui_action()
    result = action.get_element_coords_by_attr(
        auto_id=auto_id,
        control_type=control_type,
        title=title,
        timeout=timeout
    )
    return json.dumps(result.to_dict(), ensure_ascii=False)


def register_app_control_tools(mcp: FastMCP) -> None:
    """애플리케이션 UI 제어 도구 등록"""
    mcp.tool()(find_app_by_ocr)
    mcp.tool()(click_app_by_text)
    mcp.tool()(type_app_text)
    mcp.tool()(press_app_shortcut)
    mcp.tool()(click_app_position)
    mcp.tool()(click_app_by_keyword)
    mcp.tool()(click_app_by_attr)
    mcp.tool()(highlight_app_by_attr)
    mcp.tool()(get_app_coords_by_attr)

    logger.info("애플리케이션 제어 도구 등록 완료")
