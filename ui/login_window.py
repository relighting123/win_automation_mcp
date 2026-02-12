"""
로그인 윈도우 UI 클래스 (Page Object Pattern)

로그인 윈도우의 UI 요소에 대한 접근만 담당합니다.
업무 로직(로그인 성공/실패 판단 등)은 포함하지 않습니다.

주의:
- 이 클래스는 UI 접근 로직만 담당합니다
- 로그인 성공/실패 등의 업무 판단은 LoginAction에서 수행합니다
"""

import logging
from typing import Optional

from core.app_session import AppSession
from ui.base_window import BaseWindow

logger = logging.getLogger(__name__)


class LoginWindow(BaseWindow):
    """
    로그인 윈도우 UI 클래스
    
    로그인 화면의 UI 요소(사용자명, 비밀번호, 로그인 버튼 등)에
    대한 접근 메서드를 제공합니다.
    
    Example:
        >>> login_window = LoginWindow()
        >>> login_window.wait_until_exists()
        >>> login_window.input_username("user1")
        >>> login_window.input_password("password123")
        >>> login_window.click_login_button()
    """
    
    WINDOW_NAME = "login_window"
    
    def __init__(self, session: Optional[AppSession] = None):
        super().__init__(session)
    
    # ==================== 요소 접근 메서드 ====================
    
    def get_username_input(self):
        """사용자명 입력 필드 반환"""
        return self.find_element("username_input")
    
    def get_password_input(self):
        """비밀번호 입력 필드 반환"""
        return self.find_element("password_input")
    
    def get_login_button(self):
        """로그인 버튼 반환"""
        return self.find_element("login_button")
    
    def get_cancel_button(self):
        """취소 버튼 반환"""
        return self.find_element("cancel_button")
    
    def get_error_message_label(self):
        """오류 메시지 레이블 반환"""
        return self.find_element_safe("error_message")
    
    def get_remember_checkbox(self):
        """자동 로그인 체크박스 반환"""
        return self.find_element_safe("remember_checkbox")
    
    # ==================== 입력 메서드 ====================
    
    def input_username(self, username: str) -> None:
        """
        사용자명 입력
        
        Args:
            username: 입력할 사용자명
        """
        self.set_text("username_input", username)
        logger.debug(f"사용자명 입력: {username}")
    
    def input_password(self, password: str) -> None:
        """
        비밀번호 입력
        
        Args:
            password: 입력할 비밀번호
        """
        self.set_text("password_input", password)
        logger.debug("비밀번호 입력 완료")
    
    def clear_username(self) -> None:
        """사용자명 필드 비우기"""
        self.set_text("username_input", "")
    
    def clear_password(self) -> None:
        """비밀번호 필드 비우기"""
        self.set_text("password_input", "")
    
    def clear_all_inputs(self) -> None:
        """모든 입력 필드 비우기"""
        self.clear_username()
        self.clear_password()
    
    # ==================== 버튼 클릭 메서드 ====================
    
    def click_login_button(self) -> None:
        """로그인 버튼 클릭"""
        self.click("login_button")
        logger.debug("로그인 버튼 클릭")
    
    def click_cancel_button(self) -> None:
        """취소 버튼 클릭"""
        self.click("cancel_button")
        logger.debug("취소 버튼 클릭")
    
    # ==================== 체크박스 메서드 ====================
    
    def set_remember_me(self, checked: bool = True) -> None:
        """
        자동 로그인 체크박스 설정
        
        Args:
            checked: 체크 여부
        """
        checkbox = self.get_remember_checkbox()
        if checkbox and checkbox.exists():
            self.set_checked("remember_checkbox", checked)
            logger.debug(f"자동 로그인 설정: {checked}")
    
    def is_remember_me_checked(self) -> bool:
        """자동 로그인 체크 여부 반환"""
        try:
            return self.is_checked("remember_checkbox")
        except Exception:
            return False
    
    # ==================== 상태 확인 메서드 ====================
    
    def get_username_value(self) -> str:
        """현재 입력된 사용자명 반환"""
        return self.get_value("username_input")
    
    def get_error_message(self) -> Optional[str]:
        """
        오류 메시지 텍스트 반환
        
        Returns:
            오류 메시지 또는 None (오류가 없거나 요소가 없을 때)
        """
        try:
            label = self.get_error_message_label()
            if label and label.exists() and label.is_visible():
                return label.window_text()
        except Exception:
            pass
        return None
    
    def has_error_message(self) -> bool:
        """오류 메시지 표시 여부"""
        message = self.get_error_message()
        return bool(message and message.strip())
    
    def is_login_button_enabled(self) -> bool:
        """로그인 버튼 활성화 여부"""
        return self.is_element_enabled("login_button")
    
    def is_username_input_enabled(self) -> bool:
        """사용자명 입력 필드 활성화 여부"""
        return self.is_element_enabled("username_input")
    
    def is_password_input_enabled(self) -> bool:
        """비밀번호 입력 필드 활성화 여부"""
        return self.is_element_enabled("password_input")
    
    # ==================== 대기 메서드 ====================
    
    def wait_until_inputs_ready(self, timeout: Optional[float] = None) -> None:
        """입력 필드가 준비될 때까지 대기"""
        self.wait_for_element("username_input", timeout=timeout, condition="ready")
        self.wait_for_element("password_input", timeout=timeout, condition="ready")
    
    def wait_for_error_message(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        오류 메시지가 나타날 때까지 대기
        
        Args:
            timeout: 대기 시간
        
        Returns:
            오류 메시지 텍스트 또는 None
        """
        timeout = timeout or self._session.get_timeout("short_wait")
        
        try:
            self.wait_for_element(
                "error_message",
                timeout=timeout,
                condition="visible"
            )
            return self.get_error_message()
        except Exception:
            return None
    
    def wait_until_closed(self, timeout: Optional[float] = None) -> bool:
        """
        로그인 윈도우가 닫힐 때까지 대기
        
        Args:
            timeout: 대기 시간
        
        Returns:
            닫혔는지 여부
        """
        from core.wait_utils import wait_until
        
        timeout = timeout or self._session.get_timeout("default_wait")
        
        result = wait_until(
            condition=lambda: not self.exists(),
            timeout=timeout,
            timeout_message="로그인 윈도우 닫힘 대기",
            raise_on_timeout=False
        )
        
        return result.success
