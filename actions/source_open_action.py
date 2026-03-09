"""
소스 오픈 업무 Action

단축키로 룰 검색 화면을 열고, RGB 아이콘을 클릭한 뒤 검색어를 입력하여
소스를 여는 시나리오를 업무 단위로 제공합니다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from actions.desktop_action import DesktopAction

logger = logging.getLogger(__name__)


@dataclass
class SourceOpenResponse:
    """소스 오픈 결과"""

    result: str
    message: str
    query: str
    icon_x: Optional[int] = None
    icon_y: Optional[int] = None
    open_shortcut: Optional[str] = None
    submit_shortcut: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.result == "success"

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "message": self.message,
            "query": self.query,
            "icon_x": self.icon_x,
            "icon_y": self.icon_y,
            "open_shortcut": self.open_shortcut,
            "submit_shortcut": self.submit_shortcut,
            "is_success": self.is_success,
        }


class SourceOpenAction:
    """
    룰 검색 기반 소스 오픈 Action
    """

    def __init__(self, desktop_action: Optional[DesktopAction] = None):
        self._desktop_action = desktop_action or DesktopAction()

    def open_source_by_rule_search(
        self,
        query: str,
        icon_rgb: Tuple[int, int, int],
        open_shortcut: str = "ctrl+shift+r",
        submit_shortcut: str = "enter",
        icon_tolerance: int = 5,
        scan_step: int = 1,
        icon_timeout: float = 10.0,
        click_button: str = "left",
        input_interval: float = 0.02,
    ) -> SourceOpenResponse:
        """
        룰 검색 화면에서 소스를 찾아 엽니다.

        Args:
            query: 검색할 소스명/키워드
            icon_rgb: 클릭할 아이콘 RGB
            open_shortcut: 룰 검색 화면을 여는 단축키
            submit_shortcut: 검색 입력 후 실행 단축키
            icon_tolerance: RGB 허용 오차
            scan_step: 픽셀 스캔 간격
            icon_timeout: 아이콘 탐색 제한 시간
            click_button: 아이콘 클릭 버튼
            input_interval: 텍스트 입력 간격
        """
        query = query.strip()
        if not query:
            return SourceOpenResponse(
                result="error",
                message="query는 비어 있을 수 없습니다",
                query=query,
            )

        logger.info(
            "소스 오픈 시작: query=%s shortcut=%s rgb=%s",
            query,
            open_shortcut,
            icon_rgb,
        )

        open_result = self._desktop_action.press_shortcut(open_shortcut)
        if not open_result.is_success:
            return SourceOpenResponse(
                result="error",
                message=f"룰 검색 화면 단축키 실행 실패: {open_result.message}",
                query=query,
                open_shortcut=open_shortcut,
            )

        click_result = self._desktop_action.click_by_rgb(
            rgb=icon_rgb,
            tolerance=icon_tolerance,
            step=scan_step,
            button=click_button,
            timeout=icon_timeout,
        )
        if not click_result.is_success:
            return SourceOpenResponse(
                result=click_result.result,
                message=f"아이콘 클릭 실패: {click_result.message or click_result.result}",
                query=query,
                open_shortcut=open_shortcut,
                icon_x=click_result.x,
                icon_y=click_result.y,
            )

        input_result = self._desktop_action.type_text(
            text=query,
            interval=input_interval,
            submit_shortcut=submit_shortcut,
        )
        if not input_result.is_success:
            return SourceOpenResponse(
                result="error",
                message=f"검색어 입력/실행 실패: {input_result.message}",
                query=query,
                icon_x=click_result.x,
                icon_y=click_result.y,
                open_shortcut=open_shortcut,
                submit_shortcut=submit_shortcut,
            )

        return SourceOpenResponse(
            result="success",
            message="소스 검색 및 열기 동작을 완료했습니다",
            query=query,
            icon_x=click_result.x,
            icon_y=click_result.y,
            open_shortcut=open_shortcut,
            submit_shortcut=submit_shortcut,
        )


def get_source_open_action() -> SourceOpenAction:
    """SourceOpenAction 인스턴스 반환"""
    return SourceOpenAction()
