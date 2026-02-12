"""
Wait/Retry 공통 유틸리티

sleep() 사용을 금지하고, 조건 기반 대기와 재시도 로직을 제공합니다.
모든 대기는 조건 함수를 통해 명시적으로 수행됩니다.
"""

import time
import logging
from typing import Callable, TypeVar, Optional, Any, Union
from functools import wraps
from dataclasses import dataclass
from enum import Enum

from errors.automation_error import TimeoutError, AutomationError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class WaitCondition(Enum):
    """대기 조건 유형"""
    EXISTS = "exists"
    VISIBLE = "visible"
    ENABLED = "enabled"
    READY = "ready"
    CUSTOM = "custom"


@dataclass
class WaitResult:
    """대기 결과"""
    success: bool
    elapsed_time: float
    result: Any = None
    error: Optional[Exception] = None


def wait_until(
    condition: Callable[[], bool],
    timeout: float = 10.0,
    poll_interval: float = 0.5,
    timeout_message: str = "조건 대기 시간 초과",
    raise_on_timeout: bool = True
) -> WaitResult:
    """
    조건이 참이 될 때까지 대기
    
    sleep()을 직접 사용하지 않고, 조건 함수를 주기적으로 평가합니다.
    
    Args:
        condition: 참/거짓을 반환하는 조건 함수
        timeout: 최대 대기 시간 (초)
        poll_interval: 조건 확인 주기 (초)
        timeout_message: 시간 초과 시 오류 메시지
        raise_on_timeout: 시간 초과 시 예외 발생 여부
    
    Returns:
        WaitResult: 대기 결과
    
    Raises:
        TimeoutError: raise_on_timeout=True이고 시간 초과 시
    
    Example:
        >>> result = wait_until(
        ...     lambda: element.exists(),
        ...     timeout=10,
        ...     timeout_message="로그인 버튼 대기 시간 초과"
        ... )
    """
    start_time = time.monotonic()
    last_error: Optional[Exception] = None
    
    while True:
        elapsed = time.monotonic() - start_time
        
        try:
            if condition():
                logger.debug(f"조건 만족: {elapsed:.2f}초 경과")
                return WaitResult(
                    success=True,
                    elapsed_time=elapsed
                )
        except Exception as e:
            last_error = e
            logger.debug(f"조건 확인 중 예외: {e}")
        
        if elapsed >= timeout:
            logger.warning(f"대기 시간 초과: {timeout_message} ({timeout}초)")
            if raise_on_timeout:
                raise TimeoutError(
                    operation=timeout_message,
                    timeout_seconds=timeout,
                    cause=last_error
                )
            return WaitResult(
                success=False,
                elapsed_time=elapsed,
                error=last_error
            )
        
        # 다음 확인까지 대기 (남은 시간 고려)
        remaining = timeout - elapsed
        wait_time = min(poll_interval, remaining)
        if wait_time > 0:
            time.sleep(wait_time)


def wait_until_value(
    func: Callable[[], T],
    expected_value: T,
    timeout: float = 10.0,
    poll_interval: float = 0.5,
    timeout_message: str = "값 대기 시간 초과"
) -> WaitResult:
    """
    함수 반환값이 기대값과 일치할 때까지 대기
    
    Args:
        func: 값을 반환하는 함수
        expected_value: 기대하는 값
        timeout: 최대 대기 시간 (초)
        poll_interval: 확인 주기 (초)
        timeout_message: 시간 초과 시 오류 메시지
    
    Returns:
        WaitResult: 대기 결과 (result에 마지막 반환값 포함)
    """
    last_value = None
    
    def check():
        nonlocal last_value
        last_value = func()
        return last_value == expected_value
    
    result = wait_until(
        condition=check,
        timeout=timeout,
        poll_interval=poll_interval,
        timeout_message=timeout_message,
        raise_on_timeout=True
    )
    result.result = last_value
    return result


def wait_until_not_none(
    func: Callable[[], Optional[T]],
    timeout: float = 10.0,
    poll_interval: float = 0.5,
    timeout_message: str = "값 대기 시간 초과"
) -> T:
    """
    함수 반환값이 None이 아닐 때까지 대기 후 값 반환
    
    Args:
        func: 값을 반환하는 함수
        timeout: 최대 대기 시간 (초)
        poll_interval: 확인 주기 (초)
        timeout_message: 시간 초과 시 오류 메시지
    
    Returns:
        함수의 반환값 (None이 아닌 값)
    """
    result_value: Optional[T] = None
    
    def check():
        nonlocal result_value
        result_value = func()
        return result_value is not None
    
    wait_until(
        condition=check,
        timeout=timeout,
        poll_interval=poll_interval,
        timeout_message=timeout_message,
        raise_on_timeout=True
    )
    
    return result_value  # type: ignore


def retry_on_failure(
    max_attempts: int = 3,
    retry_interval: float = 1.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None
):
    """
    실패 시 재시도하는 데코레이터
    
    지정된 예외 발생 시 자동으로 재시도합니다.
    
    Args:
        max_attempts: 최대 시도 횟수
        retry_interval: 재시도 간 대기 시간 (초)
        exceptions: 재시도할 예외 타입들
        on_retry: 재시도 시 호출할 콜백 (시도 횟수, 예외)
    
    Example:
        >>> @retry_on_failure(max_attempts=3, retry_interval=1.0)
        ... def click_button():
        ...     element.click()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    logger.warning(
                        f"시도 {attempt}/{max_attempts} 실패: "
                        f"{func.__name__} - {e}"
                    )
                    
                    if on_retry:
                        on_retry(attempt, e)
                    
                    if attempt < max_attempts:
                        time.sleep(retry_interval)
            
            # 모든 시도 실패
            raise AutomationError(
                message=f"{func.__name__} 실패 ({max_attempts}회 시도)",
                cause=last_exception
            )
        
        return wrapper
    return decorator


def retry_with_backoff(
    max_attempts: int = 3,
    base_interval: float = 1.0,
    max_interval: float = 30.0,
    exponential: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    지수 백오프를 사용한 재시도 데코레이터
    
    실패할 때마다 대기 시간이 증가합니다.
    
    Args:
        max_attempts: 최대 시도 횟수
        base_interval: 기본 대기 시간 (초)
        max_interval: 최대 대기 시간 (초)
        exponential: True면 지수 백오프, False면 선형 증가
        exceptions: 재시도할 예외 타입들
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_attempts:
                        if exponential:
                            interval = min(
                                base_interval * (2 ** (attempt - 1)),
                                max_interval
                            )
                        else:
                            interval = min(
                                base_interval * attempt,
                                max_interval
                            )
                        
                        logger.warning(
                            f"시도 {attempt}/{max_attempts} 실패, "
                            f"{interval:.1f}초 후 재시도: {e}"
                        )
                        time.sleep(interval)
            
            raise AutomationError(
                message=f"{func.__name__} 실패 ({max_attempts}회 시도)",
                cause=last_exception
            )
        
        return wrapper
    return decorator


class WaitContext:
    """
    대기 컨텍스트 매니저
    
    특정 스코프 내에서 기본 대기 설정을 변경할 때 사용합니다.
    
    Example:
        >>> with WaitContext(timeout=30, poll_interval=1.0):
        ...     # 이 블록 내에서는 기본 타임아웃이 30초
        ...     wait_for_element()
    """
    
    _default_timeout: float = 10.0
    _default_poll_interval: float = 0.5
    _stack: list = []
    
    def __init__(
        self,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None
    ):
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._previous_timeout: Optional[float] = None
        self._previous_poll_interval: Optional[float] = None
    
    def __enter__(self):
        # 현재 설정 저장
        self._previous_timeout = WaitContext._default_timeout
        self._previous_poll_interval = WaitContext._default_poll_interval
        
        # 새 설정 적용
        if self.timeout is not None:
            WaitContext._default_timeout = self.timeout
        if self.poll_interval is not None:
            WaitContext._default_poll_interval = self.poll_interval
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # 이전 설정 복원
        if self._previous_timeout is not None:
            WaitContext._default_timeout = self._previous_timeout
        if self._previous_poll_interval is not None:
            WaitContext._default_poll_interval = self._previous_poll_interval
        
        return False
    
    @classmethod
    def get_default_timeout(cls) -> float:
        """현재 기본 타임아웃 반환"""
        return cls._default_timeout
    
    @classmethod
    def get_default_poll_interval(cls) -> float:
        """현재 기본 폴링 간격 반환"""
        return cls._default_poll_interval
