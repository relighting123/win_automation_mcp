"""
로그인 업무 Action

"로그인 한다"라는 업무 의미 단위의 동작을 구현합니다.
UI 클래스를 조합하여 로그인 프로세스를 수행하고,
조건 분기와 재시도 로직을 포함합니다.

주의:
- pywinauto를 직접 호출하지 않습니다
- UI 객체를 통해서만 화면을 조작합니다
- 업무 수준의 예외를 발생시킵니다
"""

import logging
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from core.app_session import AppSession
from core.wait_utils import wait_until, retry_on_failure
from ui.login_window import LoginWindow
from ui.main_window import MainWindow
from errors.automation_error import (
    LoginError,
    ActionFailedError,
    TimeoutError,
    WindowNotFoundError,
)

logger = logging.getLogger(__name__)


class LoginResult(Enum):
    """로그인 결과 상태"""
    SUCCESS = "success"
    INVALID_CREDENTIALS = "invalid_credentials"
    ACCOUNT_LOCKED = "account_locked"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class LoginResponse:
    """
    로그인 응답 데이터
    
    Attributes:
        result: 로그인 결과 상태
        message: 결과 메시지
        username: 로그인한 사용자명
        error_detail: 오류 상세 정보 (실패 시)
    """
    result: LoginResult
    message: str
    username: Optional[str] = None
    error_detail: Optional[str] = None
    
    @property
    def is_success(self) -> bool:
        return self.result == LoginResult.SUCCESS
    
    def to_dict(self) -> dict:
        return {
            "result": self.result.value,
            "message": self.message,
            "username": self.username,
            "error_detail": self.error_detail,
            "is_success": self.is_success,
        }


class LoginAction:
    """
    로그인 업무 Action
    
    로그인 관련 업무 동작을 수행합니다.
    UI 클래스를 조합하여 완전한 로그인 프로세스를 구현합니다.
    
    Example:
        >>> action = LoginAction()
        >>> response = action.login("user1", "password123")
        >>> if response.is_success:
        ...     print("로그인 성공!")
    """
    
    # 오류 메시지 매핑 (애플리케이션별로 커스터마이즈 필요)
    ERROR_MESSAGES = {
        "invalid": LoginResult.INVALID_CREDENTIALS,
        "잘못된": LoginResult.INVALID_CREDENTIALS,
        "wrong": LoginResult.INVALID_CREDENTIALS,
        "locked": LoginResult.ACCOUNT_LOCKED,
        "잠긴": LoginResult.ACCOUNT_LOCKED,
        "network": LoginResult.NETWORK_ERROR,
        "네트워크": LoginResult.NETWORK_ERROR,
        "connection": LoginResult.NETWORK_ERROR,
        "연결": LoginResult.NETWORK_ERROR,
    }
    
    def __init__(self, session: Optional[AppSession] = None):
        """
        Args:
            session: 사용할 AppSession (없으면 싱글톤 사용)
        """
        self._session = session or AppSession.get_instance()
        self._login_window: Optional[LoginWindow] = None
        self._main_window: Optional[MainWindow] = None
    
    @property
    def login_window(self) -> LoginWindow:
        """로그인 윈도우 인스턴스 (lazy loading)"""
        if self._login_window is None:
            self._login_window = LoginWindow(self._session)
        return self._login_window
    
    @property
    def main_window(self) -> MainWindow:
        """메인 윈도우 인스턴스 (lazy loading)"""
        if self._main_window is None:
            self._main_window = MainWindow(self._session)
        return self._main_window
    
    def prepare_login(self, timeout: float = 5.0) -> bool:
        """로그인 입력 전 준비 (입력 필드 대기 및 초기화)"""
        try:
            self.login_window.wait_until_inputs_ready(timeout=timeout)
            self.login_window.clear_all_inputs()
            return True
        except Exception as e:
            logger.error(f"로그인 준비 실패: {e}")
            return False

    def perform_login_inputs(
        self,
        username: str,
        password: str,
        remember_me: bool = False
    ) -> bool:
        """로그인 정보 입력 및 버튼 클릭 (Atomic Action들의 조합이지만, UI 레벨의 한 단위로 볼 수 있음)"""
        try:
            self.login_window.input_username(username)
            self.login_window.input_password(password)
            if remember_me:
                self.login_window.set_remember_me(True)
            self.login_window.click_login_button()
            return True
        except Exception as e:
            logger.error(f"로그인 입력 처리 실패: {e}")
            return False

    def check_result(self, username: str, timeout: float) -> LoginResponse:
        """로그인 결과 확인 (Atomic Action)"""
        return self._check_login_result(username, timeout)
    
    def _wait_for_login_window(self, timeout: float) -> bool:
        """로그인 윈도우 대기"""
        try:
            self.login_window.wait_until_exists(timeout=timeout)
            self.login_window.focus()
            return True
        except (TimeoutError, WindowNotFoundError):
            return False
    
    def _check_login_result(
        self,
        username: str,
        timeout: float
    ) -> LoginResponse:
        """
        로그인 결과 확인
        
        로그인 버튼 클릭 후 결과를 확인합니다:
        - 로그인 윈도우가 닫히면 성공
        - 오류 메시지가 나타나면 실패
        """
        # 로그인 윈도우 닫힘 또는 오류 메시지 대기
        start_time = 0
        check_interval = 0.5
        elapsed = 0
        
        while elapsed < timeout:
            # 로그인 윈도우가 닫혔는지 확인
            if not self.login_window.exists():
                # 메인 윈도우 나타나는지 확인
                if self.main_window.exists(timeout=3):
                    logger.info(f"로그인 성공: {username}")
                    return LoginResponse(
                        result=LoginResult.SUCCESS,
                        message="로그인에 성공했습니다",
                        username=username
                    )
                else:
                    # 윈도우가 닫혔지만 메인 윈도우가 없음
                    return LoginResponse(
                        result=LoginResult.UNKNOWN_ERROR,
                        message="로그인 윈도우가 닫혔지만 메인 윈도우가 나타나지 않았습니다",
                        username=username
                    )
            
            # 오류 메시지 확인
            error_msg = self.login_window.get_error_message()
            if error_msg:
                result = self._parse_error_message(error_msg)
                logger.warning(f"로그인 실패: {error_msg}")
                return LoginResponse(
                    result=result,
                    message=f"로그인 실패: {error_msg}",
                    username=username,
                    error_detail=error_msg
                )
            
            # 대기
            import time
            time.sleep(check_interval)
            elapsed += check_interval
        
        # 시간 초과
        return LoginResponse(
            result=LoginResult.TIMEOUT,
            message="로그인 결과 확인 시간 초과",
            username=username
        )
    
    def _parse_error_message(self, error_msg: str) -> LoginResult:
        """오류 메시지를 분석하여 결과 타입 반환"""
        error_lower = error_msg.lower()
        
        for keyword, result in self.ERROR_MESSAGES.items():
            if keyword in error_lower:
                return result
        
        return LoginResult.UNKNOWN_ERROR
    
    def logout(self, timeout: Optional[float] = None) -> bool:
        """
        로그아웃 수행
        
        Args:
            timeout: 로그아웃 완료 대기 시간
        
        Returns:
            성공 여부
        """
        timeout = timeout or self._session.get_timeout("default_wait")
        
        logger.info("로그아웃 시도")
        
        try:
            # 메인 윈도우 확인
            if not self.main_window.exists():
                logger.warning("메인 윈도우가 없습니다 (이미 로그아웃됨)")
                return True
            
            # File > Logout 또는 Exit 메뉴 선택
            # (애플리케이션에 따라 다를 수 있음)
            try:
                self.main_window.select_file_menu("Logout")
            except Exception:
                # Logout 메뉴가 없으면 Exit 시도
                self.main_window.select_file_menu("Exit")
            
            # 로그인 윈도우 또는 종료 대기
            result = wait_until(
                condition=lambda: (
                    self.login_window.exists() or
                    not self.main_window.exists()
                ),
                timeout=timeout,
                timeout_message="로그아웃 완료 대기",
                raise_on_timeout=False
            )
            
            if result.success:
                logger.info("로그아웃 완료")
                return True
            else:
                logger.warning("로그아웃 시간 초과")
                return False
                
        except Exception as e:
            logger.error(f"로그아웃 중 오류: {e}")
            return False
    
    def is_logged_in(self) -> bool:
        """
        현재 로그인 상태 확인
        
        Returns:
            로그인 상태 여부
        """
        try:
            # 메인 윈도우가 있고 로그인 윈도우가 없으면 로그인 상태
            return (
                self.main_window.exists() and
                not self.login_window.exists()
            )
        except Exception:
            return False
    
    def wait_for_login_window(
        self,
        timeout: Optional[float] = None
    ) -> bool:
        """
        로그인 윈도우가 나타날 때까지 대기
        
        Args:
            timeout: 대기 시간
        
        Returns:
            나타났는지 여부
        """
        timeout = timeout or self._session.get_timeout("default_wait")
        return self._wait_for_login_window(timeout)
    
    def cancel_login(self) -> bool:
        """
        로그인 취소
        
        Returns:
            성공 여부
        """
        try:
            if self.login_window.exists():
                self.login_window.click_cancel_button()
                return self.login_window.wait_until_closed(timeout=5)
            return True
        except Exception as e:
            logger.warning(f"로그인 취소 실패: {e}")
            return False


def get_login_action(session: Optional[AppSession] = None) -> LoginAction:
    """LoginAction 인스턴스 반환"""
    return LoginAction(session)
