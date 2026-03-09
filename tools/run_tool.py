"""
FastMCP 실행/분석 Tool 정의

LLM이 호출할 수 있는 실행 및 분석 관련 도구들을 정의합니다.
Tool 함수는 Actions 계층만 호출하며, pywinauto를 직접 사용하지 않습니다.
"""

import logging
from typing import Optional, Any

from actions.run_action import RunAction, RunResponse, get_run_action
from errors.automation_error import AutomationError

logger = logging.getLogger(__name__)


def register_run_tools(mcp: Any) -> None:
    """
    FastMCP 서버에 실행/분석 관련 도구 등록
    
    Args:
        mcp: FastMCP 서버 인스턴스
    """
    
    @mcp.tool()
    async def run_analysis(
        wait_for_completion: bool = True,
        timeout: float = 300.0
    ) -> dict:
        """
        분석/처리 작업을 실행합니다.
        
        애플리케이션의 주요 분석 또는 처리 기능을 실행합니다.
        실행 버튼을 클릭하고, 선택적으로 작업 완료까지 대기합니다.
        
        Args:
            wait_for_completion: 작업 완료까지 대기할지 여부 (기본: True)
            timeout: 완료 대기 최대 시간 (초, 기본: 300초/5분)
        
        Returns:
            dict: 실행 결과
                - is_success (bool): 성공 여부
                - result (str): 결과 상태 (success, error, timeout, not_ready)
                - message (str): 결과 메시지
                - status_text (str, optional): 애플리케이션 상태 텍스트
                - elapsed_time (float, optional): 소요 시간 (초)
                - error_detail (str, optional): 오류 상세 정보
        
        Examples:
            >>> await run_analysis()
            {"is_success": True, "result": "success", "message": "분석이 완료되었습니다", "elapsed_time": 45.2, ...}
            
            >>> await run_analysis(wait_for_completion=False)
            {"is_success": True, "result": "success", "message": "분석이 시작되었습니다", ...}
        """
        logger.info(f"[Tool] run_analysis 호출: wait={wait_for_completion}, timeout={timeout}")
        
        try:
            action = get_run_action()
            import time
            start_time = time.monotonic()
            
            # 1. 분석 시작 (Atomic Action)
            response = action.start_analysis()
            if not response.is_success:
                return response.to_dict()
            
            # 2. 실행 상태 진입 대기 (Atomic Action)
            action.wait_for_running(timeout=10.0)
            
            # 3. 완료 대기 (선택적, Atomic Action)
            if wait_for_completion:
                return action.wait_for_completion(start_time, timeout).to_dict()
            else:
                return response.to_dict()
            
        except AutomationError as e:
            logger.error(f"[Tool] run_analysis 오류: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": str(e),
                "error_detail": e.to_dict() if hasattr(e, "to_dict") else str(e)
            }
        except Exception as e:
            logger.error(f"[Tool] run_analysis 예외: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": f"분석 실행 중 오류 발생: {e}",
                "error_detail": str(e)
            }
    
    @mcp.tool()
    async def stop_analysis() -> dict:
        """
        실행 중인 분석/처리 작업을 중지합니다.
        
        현재 진행 중인 작업을 취소합니다.
        작업이 진행 중이지 않으면 아무 동작도 하지 않습니다.
        
        Returns:
            dict: 중지 결과
                - is_success (bool): 중지 성공 여부
                - result (str): 결과 상태 (cancelled, success, error)
                - message (str): 결과 메시지
                - status_text (str, optional): 애플리케이션 상태 텍스트
        
        Examples:
            >>> await stop_analysis()
            {"is_success": True, "result": "cancelled", "message": "분석이 중지되었습니다", ...}
        """
        logger.info("[Tool] stop_analysis 호출")
        
        try:
            action = get_run_action()
            response: RunResponse = action.stop_analysis()
            
            result = response.to_dict()
            logger.info(f"[Tool] stop_analysis 결과: {result['result']}")
            
            return result
            
        except AutomationError as e:
            logger.error(f"[Tool] stop_analysis 오류: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": str(e),
                "error_detail": e.to_dict() if hasattr(e, "to_dict") else str(e)
            }
        except Exception as e:
            logger.error(f"[Tool] stop_analysis 예외: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": f"분석 중지 중 오류 발생: {e}",
                "error_detail": str(e)
            }
    
    @mcp.tool()
    async def export_result(file_path: Optional[str] = None) -> dict:
        """
        분석 결과를 파일로 내보냅니다.
        
        현재 분석 결과를 파일로 저장합니다.
        내보내기 버튼을 클릭하고, 필요시 파일 경로를 지정합니다.
        
        Args:
            file_path: 저장할 파일 경로 (선택사항, 지정하지 않으면 기본 경로 사용)
        
        Returns:
            dict: 내보내기 결과
                - is_success (bool): 성공 여부
                - result (str): 결과 상태
                - message (str): 결과 메시지
                - status_text (str, optional): 애플리케이션 상태 텍스트
        
        Examples:
            >>> await export_result()
            {"is_success": True, "result": "success", "message": "내보내기가 완료되었습니다", ...}
            
            >>> await export_result(file_path="C:/output/result.xlsx")
            {"is_success": True, "result": "success", "message": "내보내기가 완료되었습니다", ...}
        """
        logger.info(f"[Tool] export_result 호출: file_path={file_path}")
        
        try:
            action = get_run_action()
            response: RunResponse = action.export_result(file_path=file_path)
            
            result = response.to_dict()
            logger.info(f"[Tool] export_result 결과: {result['result']}")
            
            return result
            
        except AutomationError as e:
            logger.error(f"[Tool] export_result 오류: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": str(e),
                "error_detail": e.to_dict() if hasattr(e, "to_dict") else str(e)
            }
        except Exception as e:
            logger.error(f"[Tool] export_result 예외: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": f"내보내기 중 오류 발생: {e}",
                "error_detail": str(e)
            }
    
    @mcp.tool()
    async def search(query: str) -> dict:
        """
        데이터를 검색합니다.
        
        지정된 검색어로 애플리케이션 내 데이터를 검색합니다.
        검색 결과는 애플리케이션의 데이터 그리드에 표시됩니다.
        
        Args:
            query: 검색할 텍스트
        
        Returns:
            dict: 검색 결과
                - is_success (bool): 검색 성공 여부
                - result (str): 결과 상태
                - message (str): 결과 메시지 (검색 결과 개수 포함)
                - status_text (str, optional): 상태 텍스트
        
        Examples:
            >>> await search("2024")
            {"is_success": True, "result": "success", "message": "검색 완료: 15개 결과", ...}
            
            >>> await search("존재하지않는데이터")
            {"is_success": True, "result": "success", "message": "검색 완료: 결과 없음", ...}
        """
        logger.info(f"[Tool] search 호출: query={query}")
        
        try:
            action = get_run_action()
            response: RunResponse = action.search(query=query)
            
            result = response.to_dict()
            logger.info(f"[Tool] search 결과: {result['result']}")
            
            return result
            
        except AutomationError as e:
            logger.error(f"[Tool] search 오류: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": str(e),
                "error_detail": e.to_dict() if hasattr(e, "to_dict") else str(e)
            }
        except Exception as e:
            logger.error(f"[Tool] search 예외: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": f"검색 중 오류 발생: {e}",
                "error_detail": str(e)
            }
    
    @mcp.tool()
    async def get_application_status() -> dict:
        """
        애플리케이션의 현재 상태를 조회합니다.
        
        메인 윈도우의 현재 상태, 버튼 활성화 상태, 실행 상태 등을 확인합니다.
        이 정보를 사용하여 다음 수행할 작업을 결정할 수 있습니다.
        
        Returns:
            dict: 상태 정보
                - window_exists (bool): 메인 윈도우 존재 여부
                - is_running (bool): 작업 실행 중 여부
                - run_enabled (bool): 실행 버튼 활성화 여부
                - export_enabled (bool): 내보내기 버튼 활성화 여부
                - status_text (str, optional): 상태바 텍스트
                - grid_row_count (int): 데이터 그리드 행 개수
        
        Examples:
            >>> await get_application_status()
            {
                "window_exists": True,
                "is_running": False,
                "run_enabled": True,
                "export_enabled": True,
                "status_text": "Ready",
                "grid_row_count": 100
            }
        """
        logger.info("[Tool] get_application_status 호출")
        
        try:
            action = get_run_action()
            status = action.get_status()
            
            logger.info(f"[Tool] get_application_status 결과: {status}")
            
            return status
            
        except Exception as e:
            logger.error(f"[Tool] get_application_status 예외: {e}")
            return {
                "error": str(e),
                "window_exists": False
            }
    
    logger.info("실행 도구 등록 완료: run_analysis, stop_analysis, export_result, search, get_application_status")
