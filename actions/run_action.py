"""
실행/분석 업무 Action

애플리케이션의 주요 기능(분석 실행, 내보내기 등)에 대한
업무 의미 단위의 동작을 구현합니다.
"""

import logging
from typing import Optional, List, Any
from dataclasses import dataclass
from enum import Enum

from core.app_session import AppSession
from core.wait_utils import wait_until, retry_on_failure
from ui.main_window import MainWindow
from errors.automation_error import (
    ActionFailedError,
    TimeoutError,
    WindowNotFoundError,
)

logger = logging.getLogger(__name__)


class RunResult(Enum):
    """실행 결과 상태"""
    SUCCESS = "success"
    CANCELLED = "cancelled"
    ERROR = "error"
    TIMEOUT = "timeout"
    NOT_READY = "not_ready"


@dataclass
class RunResponse:
    """
    실행 응답 데이터
    
    Attributes:
        result: 실행 결과 상태
        message: 결과 메시지
        status_text: 최종 상태 텍스트
        elapsed_time: 소요 시간 (초)
        error_detail: 오류 상세 정보 (실패 시)
    """
    result: RunResult
    message: str
    status_text: Optional[str] = None
    elapsed_time: Optional[float] = None
    error_detail: Optional[str] = None
    
    @property
    def is_success(self) -> bool:
        return self.result == RunResult.SUCCESS
    
    def to_dict(self) -> dict:
        return {
            "result": self.result.value,
            "message": self.message,
            "status_text": self.status_text,
            "elapsed_time": self.elapsed_time,
            "error_detail": self.error_detail,
            "is_success": self.is_success,
        }


class RunAction:
    """
    실행/분석 업무 Action
    
    애플리케이션의 주요 실행 기능에 대한 업무 동작을 수행합니다.
    
    Example:
        >>> action = RunAction()
        >>> response = action.run_analysis()
        >>> if response.is_success:
        ...     print(f"분석 완료: {response.status_text}")
    """
    
    def __init__(self, session: Optional[AppSession] = None):
        """
        Args:
            session: 사용할 AppSession (없으면 싱글톤 사용)
        """
        self._session = session or AppSession.get_instance()
        self._main_window: Optional[MainWindow] = None
    
    @property
    def main_window(self) -> MainWindow:
        """메인 윈도우 인스턴스 (lazy loading)"""
        if self._main_window is None:
            self._main_window = MainWindow(self._session)
        return self._main_window
    
    def start_analysis(self) -> RunResponse:
        """분석 시작 (Atomic Action: 실행 버튼 클릭)"""
        try:
            # 1. 메인 윈도우 확인
            if not self.main_window.exists():
                return RunResponse(
                    result=RunResult.NOT_READY,
                    message="메인 윈도우가 없습니다. 먼저 로그인하세요."
                )
            
            # 2. 실행 버튼 활성화 확인
            if not self.main_window.is_run_button_enabled():
                return RunResponse(
                    result=RunResult.NOT_READY,
                    message="실행 버튼이 비활성화 상태입니다"
                )
            
            # 3. 실행 버튼 클릭
            self.main_window.click_run_button()
            logger.info("실행 버튼 클릭")
            
            return RunResponse(result=RunResult.SUCCESS, message="분석이 시작되었습니다")
        except Exception as e:
            logger.error(f"분석 시작 중 오류: {e}")
            return RunResponse(
                result=RunResult.ERROR,
                message=f"분석 시작 실패: {e}",
                error_detail=str(e)
            )

    def wait_for_running(self, timeout: float = 10.0) -> bool:
        """실행 중 상태로 전환 대기 (Atomic Action)"""
        try:
            self.main_window.wait_until_running(timeout=timeout)
            return True
        except TimeoutError:
            return False

    def wait_for_completion(self, start_time: float, timeout: float) -> RunResponse:
        """작업 완료 대기 (Atomic Action)"""
        return self._wait_for_completion(start_time, timeout)
    
    def _wait_for_completion(
        self,
        start_time: float,
        timeout: float
    ) -> RunResponse:
        """실행 완료 대기"""
        import time
        
        try:
            self.main_window.wait_until_completed(timeout=timeout)
            
            elapsed = time.monotonic() - start_time
            status = self.main_window.get_status_text()
            
            # 상태 텍스트로 결과 판단
            if self._is_error_status(status):
                return RunResponse(
                    result=RunResult.ERROR,
                    message="분석이 오류로 종료되었습니다",
                    status_text=status,
                    elapsed_time=elapsed,
                    error_detail=status
                )
            
            logger.info(f"분석 완료: {elapsed:.1f}초")
            return RunResponse(
                result=RunResult.SUCCESS,
                message="분석이 완료되었습니다",
                status_text=status,
                elapsed_time=elapsed
            )
            
        except TimeoutError as e:
            elapsed = time.monotonic() - start_time
            return RunResponse(
                result=RunResult.TIMEOUT,
                message=f"분석 완료 대기 시간 초과 ({timeout}초)",
                status_text=self.main_window.get_status_text(),
                elapsed_time=elapsed,
                error_detail=str(e)
            )
    
    def _is_error_status(self, status: str) -> bool:
        """상태 텍스트가 오류인지 확인"""
        error_keywords = ["error", "failed", "오류", "실패", "에러"]
        status_lower = status.lower()
        return any(keyword in status_lower for keyword in error_keywords)
    
    def stop_analysis(self, timeout: Optional[float] = None) -> RunResponse:
        """
        실행 중인 분석 중지
        
        Args:
            timeout: 중지 완료 대기 시간
        
        Returns:
            RunResponse: 중지 결과
        """
        timeout = timeout or self._session.get_timeout("default_wait")
        
        logger.info("분석 중지 시도")
        
        try:
            # 실행 중인지 확인
            if not self.main_window.is_running():
                return RunResponse(
                    result=RunResult.SUCCESS,
                    message="실행 중인 작업이 없습니다"
                )
            
            # 중지 버튼 클릭
            self.main_window.click_stop_button()
            
            # 중지 완료 대기
            result = wait_until(
                condition=lambda: not self.main_window.is_running(),
                timeout=timeout,
                timeout_message="분석 중지 대기",
                raise_on_timeout=False
            )
            
            if result.success:
                logger.info("분석 중지 완료")
                return RunResponse(
                    result=RunResult.CANCELLED,
                    message="분석이 중지되었습니다",
                    status_text=self.main_window.get_status_text()
                )
            else:
                return RunResponse(
                    result=RunResult.TIMEOUT,
                    message="분석 중지 대기 시간 초과"
                )
                
        except Exception as e:
            logger.error(f"분석 중지 중 오류: {e}")
            return RunResponse(
                result=RunResult.ERROR,
                message=f"분석 중지 실패: {e}",
                error_detail=str(e)
            )
    
    def export_result(
        self,
        file_path: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> RunResponse:
        """
        결과 내보내기
        
        Args:
            file_path: 저장할 파일 경로 (다이얼로그가 나타나면 입력)
            timeout: 내보내기 완료 대기 시간
        
        Returns:
            RunResponse: 내보내기 결과
        """
        timeout = timeout or self._session.get_timeout("default_wait")
        
        logger.info("결과 내보내기 시도")
        
        try:
            # 내보내기 버튼 활성화 확인
            if not self.main_window.is_export_button_enabled():
                return RunResponse(
                    result=RunResult.NOT_READY,
                    message="내보내기 버튼이 비활성화 상태입니다"
                )
            
            # 내보내기 버튼 클릭
            self.main_window.click_export_button()
            
            # 파일 다이얼로그 처리 (필요시)
            if file_path:
                # TODO: 파일 다이얼로그 처리 구현
                # 이 부분은 애플리케이션에 따라 다름
                pass
            
            # 완료 대기 (상태 텍스트로 확인)
            success = self.main_window.wait_for_status_text(
                "완료",  # 또는 "exported", "saved" 등
                timeout=timeout,
                contains=True
            )
            
            status = self.main_window.get_status_text()
            
            if success or "완료" in status.lower() or "success" in status.lower():
                logger.info("내보내기 완료")
                return RunResponse(
                    result=RunResult.SUCCESS,
                    message="내보내기가 완료되었습니다",
                    status_text=status
                )
            else:
                return RunResponse(
                    result=RunResult.ERROR,
                    message="내보내기 결과를 확인할 수 없습니다",
                    status_text=status
                )
                
        except Exception as e:
            logger.error(f"내보내기 중 오류: {e}")
            return RunResponse(
                result=RunResult.ERROR,
                message=f"내보내기 실패: {e}",
                error_detail=str(e)
            )
    
    def search(
        self,
        query: str,
        timeout: Optional[float] = None
    ) -> RunResponse:
        """
        검색 수행
        
        Args:
            query: 검색어
            timeout: 검색 완료 대기 시간
        
        Returns:
            RunResponse: 검색 결과
        """
        timeout = timeout or self._session.get_timeout("default_wait")
        
        logger.info(f"검색 수행: {query}")
        
        try:
            # 검색 실행
            self.main_window.search(query)
            
            # 결과 대기 (그리드에 데이터가 나타날 때까지)
            result = wait_until(
                condition=lambda: self.main_window.get_grid_row_count() > 0,
                timeout=timeout,
                timeout_message=f"검색 결과 대기: {query}",
                raise_on_timeout=False
            )
            
            row_count = self.main_window.get_grid_row_count()
            
            if result.success:
                logger.info(f"검색 완료: {row_count}개 결과")
                return RunResponse(
                    result=RunResult.SUCCESS,
                    message=f"검색 완료: {row_count}개 결과",
                    status_text=f"{row_count} items found"
                )
            else:
                return RunResponse(
                    result=RunResult.SUCCESS,
                    message="검색 완료: 결과 없음",
                    status_text="No items found"
                )
                
        except Exception as e:
            logger.error(f"검색 중 오류: {e}")
            return RunResponse(
                result=RunResult.ERROR,
                message=f"검색 실패: {e}",
                error_detail=str(e)
            )
    
    def get_status(self) -> dict:
        """
        현재 상태 정보 반환
        
        Returns:
            상태 정보 딕셔너리
        """
        try:
            return {
                "window_exists": self.main_window.exists(),
                "is_running": self.main_window.is_running() if self.main_window.exists() else False,
                "run_enabled": self.main_window.is_run_button_enabled() if self.main_window.exists() else False,
                "export_enabled": self.main_window.is_export_button_enabled() if self.main_window.exists() else False,
                "status_text": self.main_window.get_status_text() if self.main_window.exists() else None,
                "grid_row_count": self.main_window.get_grid_row_count() if self.main_window.exists() else 0,
            }
        except Exception as e:
            return {
                "error": str(e)
            }


def get_run_action(session: Optional[AppSession] = None) -> RunAction:
    """RunAction 인스턴스 반환"""
    return RunAction(session)
