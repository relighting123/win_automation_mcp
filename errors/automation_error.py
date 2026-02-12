"""
업무 단위 예외 클래스 정의

pywinauto 예외를 그대로 던지지 않고, 업무 의미가 있는 예외로 래핑합니다.
이를 통해 LLM이 이해할 수 있는 명확한 오류 메시지를 제공합니다.
"""

from typing import Optional, Any


class AutomationError(Exception):
    """
    자동화 작업의 기본 예외 클래스
    
    모든 자동화 관련 예외의 부모 클래스입니다.
    업무 의미가 있는 메시지와 함께 원본 예외를 보존합니다.
    """
    
    def __init__(
        self,
        message: str,
        cause: Optional[Exception] = None,
        details: Optional[dict] = None
    ):
        """
        Args:
            message: 업무 의미가 있는 오류 메시지
            cause: 원본 예외 (pywinauto 예외 등)
            details: 추가 상세 정보 (디버깅용)
        """
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.details = details or {}
    
    def __str__(self) -> str:
        result = self.message
        if self.cause:
            result += f" (원인: {type(self.cause).__name__}: {self.cause})"
        return result
    
    def to_dict(self) -> dict:
        """예외 정보를 딕셔너리로 변환 (로깅/직렬화용)"""
        return {
            "error_type": type(self).__name__,
            "message": self.message,
            "cause": str(self.cause) if self.cause else None,
            "cause_type": type(self.cause).__name__ if self.cause else None,
            "details": self.details,
        }


class ConnectionError(AutomationError):
    """
    애플리케이션 연결 실패 예외
    
    애플리케이션 실행, 연결, 또는 세션 관리 중 발생하는 오류입니다.
    """
    
    def __init__(
        self,
        message: str = "애플리케이션에 연결할 수 없습니다",
        cause: Optional[Exception] = None,
        app_name: Optional[str] = None,
        details: Optional[dict] = None
    ):
        details = details or {}
        if app_name:
            details["app_name"] = app_name
        super().__init__(message, cause, details)
        self.app_name = app_name


class ElementNotFoundError(AutomationError):
    """
    UI 요소를 찾을 수 없는 예외
    
    지정된 locator로 UI 요소를 찾지 못했을 때 발생합니다.
    """
    
    def __init__(
        self,
        element_name: str,
        locator: Optional[dict] = None,
        cause: Optional[Exception] = None,
        details: Optional[dict] = None
    ):
        message = f"UI 요소를 찾을 수 없습니다: {element_name}"
        details = details or {}
        details["element_name"] = element_name
        if locator:
            details["locator"] = locator
        super().__init__(message, cause, details)
        self.element_name = element_name
        self.locator = locator


class TimeoutError(AutomationError):
    """
    작업 시간 초과 예외
    
    지정된 시간 내에 작업이 완료되지 않았을 때 발생합니다.
    """
    
    def __init__(
        self,
        operation: str,
        timeout_seconds: float,
        cause: Optional[Exception] = None,
        details: Optional[dict] = None
    ):
        message = f"작업 시간이 초과되었습니다: {operation} ({timeout_seconds}초)"
        details = details or {}
        details["operation"] = operation
        details["timeout_seconds"] = timeout_seconds
        super().__init__(message, cause, details)
        self.operation = operation
        self.timeout_seconds = timeout_seconds


class ActionFailedError(AutomationError):
    """
    업무 동작 실패 예외
    
    특정 업무 동작(Action)이 실패했을 때 발생합니다.
    """
    
    def __init__(
        self,
        action_name: str,
        reason: str,
        cause: Optional[Exception] = None,
        details: Optional[dict] = None
    ):
        message = f"업무 동작 실패: {action_name} - {reason}"
        details = details or {}
        details["action_name"] = action_name
        details["reason"] = reason
        super().__init__(message, cause, details)
        self.action_name = action_name
        self.reason = reason


class LoginError(AutomationError):
    """
    로그인 실패 예외
    
    로그인 과정에서 발생하는 모든 오류를 포함합니다.
    """
    
    def __init__(
        self,
        reason: str,
        username: Optional[str] = None,
        cause: Optional[Exception] = None,
        details: Optional[dict] = None
    ):
        message = f"로그인 실패: {reason}"
        details = details or {}
        if username:
            details["username"] = username
        super().__init__(message, cause, details)
        self.reason = reason
        self.username = username


class SessionError(AutomationError):
    """
    세션 관련 예외
    
    애플리케이션 세션 상태와 관련된 오류입니다.
    """
    
    def __init__(
        self,
        message: str = "세션 오류가 발생했습니다",
        session_state: Optional[str] = None,
        cause: Optional[Exception] = None,
        details: Optional[dict] = None
    ):
        details = details or {}
        if session_state:
            details["session_state"] = session_state
        super().__init__(message, cause, details)
        self.session_state = session_state


class WindowNotFoundError(AutomationError):
    """
    윈도우를 찾을 수 없는 예외
    
    지정된 윈도우가 존재하지 않거나 접근할 수 없을 때 발생합니다.
    """
    
    def __init__(
        self,
        window_name: str,
        cause: Optional[Exception] = None,
        details: Optional[dict] = None
    ):
        message = f"윈도우를 찾을 수 없습니다: {window_name}"
        details = details or {}
        details["window_name"] = window_name
        super().__init__(message, cause, details)
        self.window_name = window_name


class InvalidStateError(AutomationError):
    """
    유효하지 않은 상태 예외
    
    예상하지 못한 애플리케이션 상태일 때 발생합니다.
    """
    
    def __init__(
        self,
        expected_state: str,
        actual_state: str,
        cause: Optional[Exception] = None,
        details: Optional[dict] = None
    ):
        message = f"유효하지 않은 상태: 예상 '{expected_state}', 실제 '{actual_state}'"
        details = details or {}
        details["expected_state"] = expected_state
        details["actual_state"] = actual_state
        super().__init__(message, cause, details)
        self.expected_state = expected_state
        self.actual_state = actual_state


def wrap_pywinauto_error(
    error: Exception,
    operation: str,
    element_name: Optional[str] = None
) -> AutomationError:
    """
    pywinauto 예외를 업무 단위 예외로 래핑하는 유틸리티 함수
    
    Args:
        error: 원본 pywinauto 예외
        operation: 수행 중이던 작업 이름
        element_name: 관련 UI 요소 이름 (있는 경우)
    
    Returns:
        적절한 AutomationError 서브클래스
    """
    error_type = type(error).__name__
    
    # ElementNotFoundError 계열
    if "ElementNotFound" in error_type or "not found" in str(error).lower():
        return ElementNotFoundError(
            element_name=element_name or "unknown",
            cause=error,
            details={"operation": operation}
        )
    
    # Timeout 계열
    if "Timeout" in error_type or "timeout" in str(error).lower():
        return TimeoutError(
            operation=operation,
            timeout_seconds=0,  # 원본에서 추출 어려움
            cause=error
        )
    
    # 기본 래핑
    return AutomationError(
        message=f"{operation} 중 오류 발생",
        cause=error,
        details={"element_name": element_name} if element_name else {}
    )
