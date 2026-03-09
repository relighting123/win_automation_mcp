"""
소스 오픈 Tool 정의
"""

import logging
from typing import Any

from actions.source_open_action import get_source_open_action

logger = logging.getLogger(__name__)


def register_source_open_tools(mcp: Any) -> None:
    """
    소스 오픈 도구 등록

    Args:
        mcp: FastMCP 서버 인스턴스
    """

    @mcp.tool()
    async def open_source_by_rule_search(
        query: str,
        icon_r: int,
        icon_g: int,
        icon_b: int,
        open_shortcut: str = "ctrl+shift+r",
        submit_shortcut: str = "enter",
        icon_tolerance: int = 5,
        scan_step: int = 1,
        icon_timeout: float = 10.0,
        click_button: str = "left",
        input_interval: float = 0.02,
    ) -> dict:
        """
        룰 검색 화면을 열어 소스를 검색 후 엽니다.

        동작 순서:
        1) open_shortcut 입력
        2) icon_rgb 위치 탐색 및 클릭
        3) query 입력 + submit_shortcut 실행

        Args:
            query: 검색할 소스 키워드
            icon_r: 클릭 대상 아이콘 Red
            icon_g: 클릭 대상 아이콘 Green
            icon_b: 클릭 대상 아이콘 Blue
            open_shortcut: 룰 검색 화면 오픈 단축키
            submit_shortcut: 검색 실행 단축키 (예: enter)
            icon_tolerance: RGB 허용 오차
            scan_step: 픽셀 스캔 간격
            icon_timeout: 아이콘 탐색 제한 시간
            click_button: 아이콘 클릭 버튼
            input_interval: 텍스트 입력 간격
        """
        logger.info(
            "[Tool] open_source_by_rule_search 호출: query=%s, shortcut=%s, icon_rgb=(%d,%d,%d)",
            query,
            open_shortcut,
            icon_r,
            icon_g,
            icon_b,
        )

        action = get_source_open_action()
        response = action.open_source_by_rule_search(
            query=query,
            icon_rgb=(icon_r, icon_g, icon_b),
            open_shortcut=open_shortcut,
            submit_shortcut=submit_shortcut,
            icon_tolerance=icon_tolerance,
            scan_step=scan_step,
            icon_timeout=icon_timeout,
            click_button=click_button,
            input_interval=input_interval,
        )
        return response.to_dict()

    logger.info("소스 오픈 도구 등록 완료: open_source_by_rule_search")
