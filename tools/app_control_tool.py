"""
애플리케이션 UI 제어 관련 도구

화면의 요소를 Title, AutoID, OCR 등을 사용하여 탐색하고 제어합니다.
"""

import logging
import json
import time as time_lib
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from actions.app_ui_action import get_app_ui_action

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _coerce_wait_seconds(
    seconds: Any = None,
    *,
    duration: Any = None,
    delay: Any = None,
    time_seconds: Any = None,
) -> float:
    """wait 도구의 대기 시간(초)을 정규화합니다."""
    candidates = {
        "seconds": seconds,
        "duration": duration,
        "delay": delay,
        "time": time_seconds,
    }
    for name, value in candidates.items():
        if value is None:
            continue
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a number")
        if isinstance(value, (int, float)):
            return max(0.0, float(value))
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.lower() in {"null", "none"}:
                continue
            return max(0.0, float(stripped))
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    return 1.0


def wait(
    seconds: Any = None,
    duration: Any = None,
    delay: Any = None,
    time: Any = None,
) -> str:
    """
    지정한 시간(초) 동안 실제로 대기합니다.
    스킬 시퀀스나 UI 로딩 대기 등에 사용합니다.

    seconds/duration/delay/time 중 하나로 대기 시간을 지정할 수 있습니다.
    모두 생략하면 1초 대기합니다.
    """
    try:
        actual_seconds = _coerce_wait_seconds(
            seconds,
            duration=duration,
            delay=delay,
            time_seconds=time,
        )
    except ValueError as exc:
        return json.dumps(
            {"success": False, "message": str(exc)},
            ensure_ascii=False,
        )

    started = time_lib.monotonic()
    logger.info("[Tool] wait 시작: %.3fs", actual_seconds)
    time_lib.sleep(actual_seconds)
    elapsed = time_lib.monotonic() - started
    logger.info("[Tool] wait 완료: requested=%.3fs, elapsed=%.3fs", actual_seconds, elapsed)
    return json.dumps(
        {
            "success": True,
            "message": f"{actual_seconds}초 대기 완료",
            "seconds": actual_seconds,
            "elapsed": round(elapsed, 3),
        },
        ensure_ascii=False,
    )


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


def click_at_focus(
    button: str = "right",
    clicks: int = 1,
    require_app_focus: bool = True,
    ensure_window_focus: bool = False,
    offset_x: int = 0,
    offset_y: int = 0,
) -> str:
    """
    현재 키보드 포커스 위치의 (x, y)를 구한 뒤,
    click_app_position과 동일한 click_position 경로로 클릭합니다.

    Args:
        button: left|right|middle (기본 right)
        clicks: 클릭 횟수 (기본 1)
        require_app_focus: 포커스가 연결된 앱에 있을 때만 클릭 (기본 True)
        ensure_window_focus: 앱 윈도우를 최상단으로 가져올지 여부 (기본 False).
            스킬 시퀀스 중간 단계에서는 False를 유지해 이전 단계의 키보드 포커스를 보존하세요.
        offset_x: 포커스 x 좌표 보정 (픽셀, 기본 0)
        offset_y: 포커스 y 좌표 보정 (픽셀, 기본 0)
    """
    logger.info(
        "[Tool] click_at_focus 호출: button=%s, clicks=%s, require_app_focus=%s, "
        "ensure_window_focus=%s, offset_x=%s, offset_y=%s",
        button,
        clicks,
        require_app_focus,
        ensure_window_focus,
        offset_x,
        offset_y,
    )
    action = get_app_ui_action()
    result = action.click_at_focus(
        button=button,
        clicks=clicks,
        require_app_focus=require_app_focus,
        ensure_window_focus=ensure_window_focus,
        offset_x=offset_x,
        offset_y=offset_y,
    )
    payload = result.to_dict()
    logger.info(
        "[Tool] click_at_focus 결과: success=%s, base=(%s,%s), offset=(%s,%s), click=(%s,%s), message=%s",
        payload.get("is_success"),
        payload.get("base_x"),
        payload.get("base_y"),
        payload.get("offset_x"),
        payload.get("offset_y"),
        payload.get("x"),
        payload.get("y"),
        payload.get("message"),
    )
    return json.dumps(payload, ensure_ascii=False)


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

    uia_hits = (analysis.get("keyword_hits", {}) or {}).get("uia", []) or []
    target_type = element_type.lower()
    matches = []
    for hit in uia_hits:
        hit_type = str(hit.get("control_type", "")).lower()
        if target_type == "any" or target_type in hit_type:
            matches.append(hit)

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
    poll_interval: Optional[float] = None,
    draw_outline: bool = False,
    outline_colour: str = "red",
    search_outline_colour: str = "green",
    top_outline_colour: str = "blue",
    outline_scope: str = "all",
    allow_invisible_children: bool = False,
) -> str:
    """
    pywinauto(UIA) 속성 기반으로 요소를 직접 찾아 클릭합니다.
    auto_id, control_type, title, legacy_value 중 하나 이상을 지정해야 합니다.
    title_match_mode:
      - exact: title 완전 일치
      - contains: title 포함 일치
    legacy_match_mode:
      - exact: LegacyIAccessible value 완전 일치
      - contains: LegacyIAccessible value 포함 일치
    window_target:
      - auto: child_window_title 지정 시 child 우선, 없으면 top 윈도우 기준 탐색
      - top: 최상위 윈도우 기준 탐색
      - child: child 윈도우 기준 탐색
    child_window_title:
      - window_target=child 또는 auto에서 child 윈도우 제목 필터
    child_window_auto_id:
      - child 윈도우 AutomationId 필터 (title과 함께 사용 가능)
    child_window_match_mode:
      - exact: child_window_title 완전 일치
      - contains: child_window_title 포함 일치
    draw_outline을 True로 설정하면 탐색/클릭 대상을 강조 표시합니다.
    outline_scope:
      - top: 순회 중인 top window(프로세스 최상위 창)만
      - search: top window + 순회 중인 search_root(창)
      - target: 찾은 요소만
      - all: top window + search_root + target (기본)
    top_outline_colour: top window 테두리 색 (기본 blue)
    search_outline_colour: search_root 테두리 색 (기본 green)
    outline_colour: target 요소 테두리 색 (기본 red)
    timeout:
      - null/미지정: 1회만 탐색 (폴링 없음)
      - 양수: 해당 시간(초)까지 재시도
    poll_interval:
      - null/미지정: 기본 간격(0.2초)으로 재시도
      - 0: 재시도 사이 대기 없음
      - 양수: 지정한 간격(초)으로 재시도
    allow_invisible_children:
      - True: 보이지 않는 child window(로그인 모달 등)도 탐색·HWND 활성화 후보에 포함
    """
    logger.info(
        "[Tool] click_app_by_attr 호출: auto_id=%s, title=%s, child_window_title=%s, child_window_auto_id=%s, window_target=%s, timeout=%s, poll_interval=%s",
        auto_id,
        title,
        child_window_title,
        child_window_auto_id,
        window_target,
        timeout,
        poll_interval,
    )
    action = get_app_ui_action()

    result = action.click_element_by_attr(
        auto_id=auto_id,
        control_type=control_type,
        title=title,
        title_match_mode=title_match_mode,
        legacy_value=legacy_value,
        legacy_match_mode=legacy_match_mode,
        case_sensitive=case_sensitive,
        window_target=window_target,
        child_window_title=child_window_title,
        child_window_auto_id=child_window_auto_id,
        child_window_match_mode=child_window_match_mode,
        button=button,
        clicks=clicks,
        double=double,
        timeout=timeout,
        poll_interval=poll_interval,
        draw_outline=draw_outline,
        outline_colour=outline_colour,
        search_outline_colour=search_outline_colour,
        top_outline_colour=top_outline_colour,
        outline_scope=outline_scope,
        allow_invisible_children=allow_invisible_children,
    )
    payload = result.to_dict()
    logger.info(
        "[Tool] click_app_by_attr 결과: success=%s, result=%s, message=%s",
        payload.get("is_success"),
        payload.get("result"),
        payload.get("message"),
    )
    return json.dumps(payload, ensure_ascii=False)


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


async def describe_current_state(
    keyword: Optional[str] = None,
    match_mode: str = "contains",
    case_sensitive: bool = False,
    include_components: bool = True,
    component_limit: int = 150,
) -> str:
    """
    현재 애플리케이션의 화면 상태와 UI 구성요소 목록을 가져옵니다.

    components에는 각 요소의 title과 auto_id만 포함됩니다.
    keyword가 지정된 경우 keyword_hits에 매칭 결과가 추가됩니다.
    """
    logger.info(f"[Tool] describe_current_state 호출: keyword={keyword}")
    action = get_app_ui_action()
    result = await action.describe_current_state(
        keyword=keyword,
        match_mode=match_mode,
        case_sensitive=case_sensitive,
        include_components=include_components,
        component_limit=component_limit,
    )
    
    # keyword_hits에서 LLM용 좌표/내부 필드 제거
    if "keyword_hits" in result:
        for source in ["uia", "ocr"]:
            for hit in result["keyword_hits"].get(source, []):
                hit.pop("x", None)
                hit.pop("y", None)
                hit.pop("control_type", None)

    return json.dumps(result, ensure_ascii=False)



def find_app_by_rgb(
    r: int,
    g: int,
    b: int,
    tolerance: int = 5,
    timeout: Optional[float] = None,
    window_target: str = "top",
    child_window_title: Optional[str] = None,
    child_window_auto_id: Optional[str] = None,
    child_window_match_mode: str = "contains",
    case_sensitive: bool = False,
    search_scope: str = "app",
    focus_before_search: bool = False,
    draw_outline: bool = False,
    outline_colour: str = "red",
    search_outline_colour: str = "green",
    outline_scope: str = "all",
) -> str:
    """
    화면에서 특정 RGB 색상을 가진 픽셀의 좌표를 찾습니다.

    search_scope:
      - app: 연결된 앱 윈도우 영역에서 탐색 (기본)
      - desktop: 전체 PC 화면(모든 모니터 가상 데스크톱)에서 탐색

    window_target (search_scope=app 일 때):
      - top (기본): 프로세스 top window + child window(Find 등) 영역을 순회
      - auto: child_window_title 미지정 시 pick된 top 1개, 지정 시 child 우선
      - child: child_window_title/auto_id로 좁힌 영역만 탐색

    focus_before_search:
      - False (기본): RGB 캡처 전 포커스를 바꾸지 않아 desktop과 유사하게 색 유지
      - True: 탐색 전 앱 포커스 (UI 색이 바뀔 수 있음)

    draw_outline을 True로 설정하면 탐색 영역/발견 픽셀을 강조 표시합니다.
    outline_scope:
      - search: 순회 중인 search_root(창) 또는 region만
      - target: 발견한 픽셀 위치만
      - all: 탐색 영역 + 픽셀 (기본)
    """
    logger.info(
        "[Tool] find_app_by_rgb 호출: rgb=(%s, %s, %s), tolerance=%s, search_scope=%s, window_target=%s, child_window_title=%s",
        r,
        g,
        b,
        tolerance,
        search_scope,
        window_target,
        child_window_title,
    )
    action = get_app_ui_action()

    scope_mode = (search_scope or "app").strip().lower()
    try:
        action._launcher.ensure_running()
    except Exception as exc:
        return json.dumps(
            {"result": "error", "message": f"애플리케이션 연결 실패: {exc}", "is_success": False},
            ensure_ascii=False,
        )

    if scope_mode != "desktop" and focus_before_search:
        focus_result = action.ensure_focus()
        if not focus_result.is_success:
            return json.dumps(focus_result.to_dict(), ensure_ascii=False)

    result = action.find_rgb_position(
        rgb=(r, g, b),
        tolerance=tolerance,
        timeout=timeout,
        window_target=window_target,
        child_window_title=child_window_title,
        child_window_auto_id=child_window_auto_id,
        child_window_match_mode=child_window_match_mode,
        case_sensitive=case_sensitive,
        search_scope=search_scope,
        focus_search_root=focus_before_search,
        draw_outline=draw_outline,
        outline_colour=outline_colour,
        search_outline_colour=search_outline_colour,
        outline_scope=outline_scope,
    )
    return json.dumps(result.to_dict(), ensure_ascii=False)


def click_app_by_rgb(
    r: int,
    g: int,
    b: int,
    tolerance: int = 5,
    button: str = "left",
    clicks: int = 1,
    timeout: Optional[float] = None,
    window_target: str = "top",
    child_window_title: Optional[str] = None,
    child_window_auto_id: Optional[str] = None,
    child_window_match_mode: str = "contains",
    case_sensitive: bool = False,
    search_scope: str = "app",
    focus_before_search: bool = False,
    draw_outline: bool = False,
    outline_colour: str = "red",
    search_outline_colour: str = "green",
    outline_scope: str = "all",
) -> str:
    """
    화면에서 특정 RGB 색상을 가진 픽셀을 찾아 클릭합니다.

    search_scope / window_target / focus_before_search / draw_outline 옵션은 find_app_by_rgb와 동일합니다.
    """
    logger.info(
        "[Tool] click_app_by_rgb 호출: rgb=(%s, %s, %s), tolerance=%s, search_scope=%s, window_target=%s, child_window_title=%s",
        r,
        g,
        b,
        tolerance,
        search_scope,
        window_target,
        child_window_title,
    )
    action = get_app_ui_action()
    scope_mode = (search_scope or "app").strip().lower()
    try:
        action._launcher.ensure_running()
    except Exception as exc:
        return json.dumps(
            {"result": "error", "message": f"애플리케이션 연결 실패: {exc}", "is_success": False},
            ensure_ascii=False,
        )

    if scope_mode != "desktop" and focus_before_search:
        focus_result = action.ensure_focus()
        if not focus_result.is_success:
            return json.dumps(focus_result.to_dict(), ensure_ascii=False)

    find_result = action.find_rgb_position(
        rgb=(r, g, b),
        tolerance=tolerance,
        timeout=timeout,
        window_target=window_target,
        child_window_title=child_window_title,
        child_window_auto_id=child_window_auto_id,
        child_window_match_mode=child_window_match_mode,
        case_sensitive=case_sensitive,
        search_scope=search_scope,
        focus_search_root=focus_before_search,
        draw_outline=draw_outline,
        outline_colour=outline_colour,
        search_outline_colour=search_outline_colour,
        outline_scope=outline_scope,
    )
    
    if not find_result.is_success:
        return json.dumps(find_result.to_dict(), ensure_ascii=False)
        
    click_result = action.click_position(
        x=find_result.x,
        y=find_result.y,
        button=button,
        clicks=clicks
    )
    return json.dumps(click_result.to_dict(), ensure_ascii=False)


def register_app_control_tools(mcp: "FastMCP") -> None:
    """애플리케이션 UI 제어 도구 등록"""
    mcp.tool()(wait)
    mcp.tool()(describe_current_state)
    mcp.tool()(find_app_by_ocr)
    mcp.tool()(type_app_text)
    mcp.tool()(press_app_shortcut)
    mcp.tool()(click_at_focus)
    mcp.tool()(click_app_position)
    mcp.tool()(click_app_by_keyword)
    mcp.tool()(click_app_by_attr)
    mcp.tool()(highlight_app_by_attr)
    mcp.tool()(get_app_coords_by_attr)
    mcp.tool()(find_app_by_rgb)
    mcp.tool()(click_app_by_rgb)

    logger.info("애플리케이션 제어 도구 등록 완료")
