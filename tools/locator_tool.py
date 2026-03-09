"""
FastMCP locator 업데이트 Tool 정의

현재 화면 기준으로 locator.yaml을 자동 갱신하는 도구를 제공합니다.
"""

import logging
from typing import Any, Optional

from actions.locator_update_action import (
    LocatorUpdateResponse,
    get_locator_update_action,
)

logger = logging.getLogger(__name__)


def register_locator_tools(mcp: Any) -> None:
    """
    FastMCP 서버에 locator 갱신 도구 등록

    Args:
        mcp: FastMCP 서버 인스턴스
    """

    @mcp.tool()
    async def update_locator_from_current_screen(
        window_name: Optional[str] = None,
        include_invisible: bool = False,
        max_elements: int = 200,
        merge_with_existing: bool = True,
    ) -> dict:
        """
        현재 화면을 스캔해 config/locator.yaml을 갱신합니다.

        설정된 executable_path 대상 앱에 연결한 뒤, 현재 활성 화면(또는 top window)의
        윈도우/요소 정보를 추출하여 locator.yaml의 해당 window 섹션을 업데이트합니다.

        Args:
            window_name: locator.yaml에 저장할 윈도우 키 이름 (미지정 시 자동 생성)
            include_invisible: 보이지 않는 요소까지 수집할지 여부
            max_elements: 최대 요소 수집 개수
            merge_with_existing: 기존 요소와 병합할지 여부

        Returns:
            dict: 업데이트 결과
                - is_success (bool): 성공 여부
                - result (str): success/error
                - message (str): 결과 메시지
                - window_name (str, optional): 업데이트된 윈도우 키
                - locator_path (str, optional): 저장된 locator 파일 경로
                - added_or_updated_count (int): 추가/갱신된 요소 수
                - total_element_count (int): 최종 요소 수
        """
        logger.info(
            "[Tool] update_locator_from_current_screen 호출: "
            "window_name=%s include_invisible=%s max_elements=%d merge=%s",
            window_name,
            include_invisible,
            max_elements,
            merge_with_existing,
        )

        try:
            action = get_locator_update_action()
            response: LocatorUpdateResponse = action.update_from_current_screen(
                window_name=window_name,
                include_invisible=include_invisible,
                max_elements=max_elements,
                merge_with_existing=merge_with_existing,
            )
            return response.to_dict()
        except Exception as e:
            logger.error(f"[Tool] update_locator_from_current_screen 예외: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": f"locator 업데이트 중 오류 발생: {e}",
                "error_detail": str(e),
            }

    logger.info("locator 도구 등록 완료: update_locator_from_current_screen")

