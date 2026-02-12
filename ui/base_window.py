"""
공통 UI 탐색 및 대기 로직 (Page Object Pattern 기반)

모든 윈도우 클래스의 기본 클래스입니다.
UI 요소 탐색, 대기, 기본 조작 등의 공통 기능을 제공합니다.

주의:
- 이 클래스는 UI 접근 로직만 담당합니다
- 업무 의미 코드(로그인 성공/실패 판단 등)를 포함하지 않습니다
- 좌표 기반 클릭을 절대 사용하지 않습니다
"""

import logging
from typing import Optional, Any, Dict, Callable
from abc import ABC

from core.app_session import AppSession
from core.wait_utils import wait_until, wait_until_not_none, retry_on_failure
from errors.automation_error import (
    ElementNotFoundError,
    TimeoutError,
    WindowNotFoundError,
    wrap_pywinauto_error,
)

logger = logging.getLogger(__name__)


class BaseWindow(ABC):
    """
    Page Object Pattern 기반 윈도우 클래스
    
    모든 윈도우 UI 클래스의 기본 클래스입니다.
    auto_id와 control_type 기반으로 UI 요소를 탐색합니다.
    
    서브클래스에서 반드시 구현해야 할 것:
    - WINDOW_NAME: locator.yaml의 윈도우 이름
    
    Example:
        >>> class LoginWindow(BaseWindow):
        ...     WINDOW_NAME = "login_window"
        ...     
        ...     def get_username_input(self):
        ...         return self.find_element("username_input")
    """
    
    # 서브클래스에서 정의
    WINDOW_NAME: str = ""
    
    def __init__(self, session: Optional[AppSession] = None):
        """
        Args:
            session: 사용할 AppSession (없으면 싱글톤 사용)
        """
        self._session = session or AppSession.get_instance()
        self._window: Optional[Any] = None
        self._cached_elements: Dict[str, Any] = {}
    
    @property
    def session(self) -> AppSession:
        """현재 세션"""
        return self._session
    
    @property
    def window(self) -> Any:
        """
        윈도우 객체 반환 (lazy loading)
        
        Returns:
            pywinauto WindowSpecification 객체
        """
        if self._window is None:
            self._window = self._find_window()
        return self._window
    
    def _find_window(self) -> Any:
        """
        locator 설정을 사용해 윈도우 찾기
        
        Returns:
            pywinauto WindowSpecification 객체
        """
        if not self.WINDOW_NAME:
            raise NotImplementedError(
                f"{type(self).__name__}에서 WINDOW_NAME을 정의해야 합니다"
            )
        
        try:
            locator = self._session.get_window_locator(self.WINDOW_NAME)
            window = self._session.get_window(**locator)
            return window
        except Exception as e:
            raise WindowNotFoundError(
                window_name=self.WINDOW_NAME,
                cause=e
            )
    
    def refresh_window(self) -> None:
        """윈도우 참조 갱신 (캐시 무효화)"""
        self._window = None
        self._cached_elements.clear()
    
    def exists(self, timeout: float = 0) -> bool:
        """
        윈도우 존재 여부 확인
        
        Args:
            timeout: 대기 시간 (0이면 즉시 확인)
        
        Returns:
            존재 여부
        """
        try:
            if timeout > 0:
                result = wait_until(
                    condition=lambda: self.window.exists(),
                    timeout=timeout,
                    raise_on_timeout=False
                )
                return result.success
            else:
                return self.window.exists()
        except Exception:
            return False
    
    def wait_until_exists(self, timeout: Optional[float] = None) -> "BaseWindow":
        """
        윈도우가 나타날 때까지 대기
        
        Args:
            timeout: 대기 시간 (없으면 기본값 사용)
        
        Returns:
            self (체이닝 지원)
        """
        timeout = timeout or self._session.get_timeout("default_wait")
        
        wait_until(
            condition=lambda: self.window.exists(),
            timeout=timeout,
            timeout_message=f"윈도우 대기: {self.WINDOW_NAME}"
        )
        
        return self
    
    def wait_until_ready(self, timeout: Optional[float] = None) -> "BaseWindow":
        """
        윈도우가 상호작용 가능할 때까지 대기
        
        Args:
            timeout: 대기 시간 (없으면 기본값 사용)
        
        Returns:
            self (체이닝 지원)
        """
        timeout = timeout or self._session.get_timeout("default_wait")
        
        def is_ready():
            try:
                return (
                    self.window.exists() and 
                    self.window.is_visible() and 
                    self.window.is_enabled()
                )
            except Exception:
                return False
        
        wait_until(
            condition=is_ready,
            timeout=timeout,
            timeout_message=f"윈도우 준비 대기: {self.WINDOW_NAME}"
        )
        
        return self
    
    def get_locator(self, element_name: str) -> Dict[str, Any]:
        """
        요소의 locator 정보 반환
        
        Args:
            element_name: locator.yaml에 정의된 요소 이름
        
        Returns:
            locator 딕셔너리
        """
        return self._session.get_locator(self.WINDOW_NAME, element_name)
    
    def find_element(
        self,
        element_name: str,
        use_cache: bool = True
    ) -> Any:
        """
        locator를 사용해 UI 요소 찾기
        
        Args:
            element_name: locator.yaml에 정의된 요소 이름
            use_cache: 캐시 사용 여부
        
        Returns:
            pywinauto 컨트롤 객체
        """
        # 캐시 확인
        if use_cache and element_name in self._cached_elements:
            element = self._cached_elements[element_name]
            try:
                if element.exists():
                    return element
            except Exception:
                pass
            # 캐시된 요소가 유효하지 않음
            del self._cached_elements[element_name]
        
        try:
            locator = self.get_locator(element_name)
            
            # locator에서 'description'을 제외한 모든 항목을 검색 조건으로 사용
            search_criteria = {
                k: v for k, v in locator.items() 
                if k != "description"
            }
            
            element = self.window.child_window(**search_criteria)
            
            # 캐시 저장
            if use_cache:
                self._cached_elements[element_name] = element
            
            return element
            
        except Exception as e:
            raise ElementNotFoundError(
                element_name=element_name,
                locator=locator if "locator" in dir() else None,
                cause=e
            )
    
    def find_element_safe(
        self,
        element_name: str,
        timeout: Optional[float] = None
    ) -> Optional[Any]:
        """
        요소 찾기 (실패 시 None 반환)
        
        Args:
            element_name: 요소 이름
            timeout: 대기 시간 (0이면 즉시 반환)
        
        Returns:
            요소 또는 None
        """
        try:
            element = self.find_element(element_name)
            
            if timeout and timeout > 0:
                wait_until(
                    condition=lambda: element.exists(),
                    timeout=timeout,
                    raise_on_timeout=False
                )
            
            return element if element.exists() else None
        except Exception:
            return None
    
    def wait_for_element(
        self,
        element_name: str,
        timeout: Optional[float] = None,
        condition: str = "exists"
    ) -> Any:
        """
        요소가 특정 조건을 만족할 때까지 대기
        
        Args:
            element_name: 요소 이름
            timeout: 대기 시간
            condition: 대기 조건 ("exists", "visible", "enabled", "ready")
        
        Returns:
            pywinauto 컨트롤 객체
        """
        timeout = timeout or self._session.get_timeout("default_wait")
        element = self.find_element(element_name, use_cache=False)
        
        condition_funcs = {
            "exists": lambda: element.exists(),
            "visible": lambda: element.exists() and element.is_visible(),
            "enabled": lambda: element.exists() and element.is_enabled(),
            "ready": lambda: (
                element.exists() and 
                element.is_visible() and 
                element.is_enabled()
            ),
        }
        
        if condition not in condition_funcs:
            raise ValueError(f"지원하지 않는 조건: {condition}")
        
        wait_until(
            condition=condition_funcs[condition],
            timeout=timeout,
            timeout_message=f"요소 대기 ({condition}): {element_name}"
        )
        
        return element
    
    def wait_for_element_disappear(
        self,
        element_name: str,
        timeout: Optional[float] = None
    ) -> bool:
        """
        요소가 사라질 때까지 대기
        
        Args:
            element_name: 요소 이름
            timeout: 대기 시간
        
        Returns:
            사라졌는지 여부
        """
        timeout = timeout or self._session.get_timeout("default_wait")
        
        try:
            element = self.find_element(element_name, use_cache=False)
            
            result = wait_until(
                condition=lambda: not element.exists(),
                timeout=timeout,
                timeout_message=f"요소 사라짐 대기: {element_name}",
                raise_on_timeout=False
            )
            
            return result.success
        except ElementNotFoundError:
            return True
    
    # ==================== 기본 조작 메서드 ====================
    
    @retry_on_failure(max_attempts=2, retry_interval=0.5)
    def click(self, element_name: str) -> None:
        """
        요소 클릭
        
        Args:
            element_name: 클릭할 요소 이름
        """
        try:
            element = self.wait_for_element(element_name, condition="ready")
            element.click()
            logger.debug(f"클릭: {element_name}")
        except Exception as e:
            raise wrap_pywinauto_error(e, "클릭", element_name)
    
    @retry_on_failure(max_attempts=2, retry_interval=0.5)
    def double_click(self, element_name: str) -> None:
        """
        요소 더블 클릭
        
        Args:
            element_name: 더블 클릭할 요소 이름
        """
        try:
            element = self.wait_for_element(element_name, condition="ready")
            element.double_click()
            logger.debug(f"더블 클릭: {element_name}")
        except Exception as e:
            raise wrap_pywinauto_error(e, "더블 클릭", element_name)
    
    @retry_on_failure(max_attempts=2, retry_interval=0.5)
    def type_text(
        self,
        element_name: str,
        text: str,
        clear_first: bool = True
    ) -> None:
        """
        요소에 텍스트 입력
        
        Args:
            element_name: 입력할 요소 이름
            text: 입력할 텍스트
            clear_first: 기존 텍스트 삭제 여부
        """
        try:
            element = self.wait_for_element(element_name, condition="ready")
            
            if clear_first:
                element.set_text("")
            
            element.type_keys(text, with_spaces=True)
            logger.debug(f"텍스트 입력: {element_name}")
        except Exception as e:
            raise wrap_pywinauto_error(e, "텍스트 입력", element_name)
    
    @retry_on_failure(max_attempts=2, retry_interval=0.5)
    def set_text(
        self,
        element_name: str,
        text: str
    ) -> None:
        """
        요소의 텍스트 설정 (type_keys 대신 직접 설정)
        
        Args:
            element_name: 설정할 요소 이름
            text: 설정할 텍스트
        """
        try:
            element = self.wait_for_element(element_name, condition="ready")
            element.set_text(text)
            logger.debug(f"텍스트 설정: {element_name}")
        except Exception as e:
            raise wrap_pywinauto_error(e, "텍스트 설정", element_name)
    
    def get_text(self, element_name: str) -> str:
        """
        요소의 텍스트 반환
        
        Args:
            element_name: 요소 이름
        
        Returns:
            요소의 텍스트
        """
        try:
            element = self.wait_for_element(element_name, condition="exists")
            return element.window_text()
        except Exception as e:
            raise wrap_pywinauto_error(e, "텍스트 가져오기", element_name)
    
    def get_value(self, element_name: str) -> str:
        """
        입력 요소의 값 반환 (Edit 컨트롤용)
        
        Args:
            element_name: 요소 이름
        
        Returns:
            요소의 값
        """
        try:
            element = self.wait_for_element(element_name, condition="exists")
            # Edit 컨트롤은 texts() 메서드 사용
            texts = element.texts()
            return texts[0] if texts else ""
        except Exception as e:
            raise wrap_pywinauto_error(e, "값 가져오기", element_name)
    
    def is_checked(self, element_name: str) -> bool:
        """
        체크박스/라디오버튼 선택 상태 반환
        
        Args:
            element_name: 요소 이름
        
        Returns:
            선택 여부
        """
        try:
            element = self.wait_for_element(element_name, condition="exists")
            return element.get_toggle_state() == 1
        except Exception as e:
            raise wrap_pywinauto_error(e, "선택 상태 확인", element_name)
    
    def set_checked(self, element_name: str, checked: bool = True) -> None:
        """
        체크박스/라디오버튼 선택 상태 설정
        
        Args:
            element_name: 요소 이름
            checked: 선택 여부
        """
        try:
            element = self.wait_for_element(element_name, condition="ready")
            current = element.get_toggle_state() == 1
            
            if current != checked:
                element.click()
                logger.debug(f"체크 상태 변경: {element_name} -> {checked}")
        except Exception as e:
            raise wrap_pywinauto_error(e, "체크 상태 설정", element_name)
    
    def select_item(
        self,
        element_name: str,
        item: str
    ) -> None:
        """
        콤보박스/리스트에서 항목 선택
        
        Args:
            element_name: 요소 이름
            item: 선택할 항목 텍스트
        """
        try:
            element = self.wait_for_element(element_name, condition="ready")
            element.select(item)
            logger.debug(f"항목 선택: {element_name} -> {item}")
        except Exception as e:
            raise wrap_pywinauto_error(e, "항목 선택", element_name)
    
    def is_element_enabled(self, element_name: str) -> bool:
        """요소 활성화 상태 반환"""
        try:
            element = self.find_element(element_name)
            return element.exists() and element.is_enabled()
        except Exception:
            return False
    
    def is_element_visible(self, element_name: str) -> bool:
        """요소 표시 상태 반환"""
        try:
            element = self.find_element(element_name)
            return element.exists() and element.is_visible()
        except Exception:
            return False
    
    def close(self) -> None:
        """윈도우 닫기"""
        try:
            self.window.close()
            logger.debug(f"윈도우 닫기: {self.WINDOW_NAME}")
        except Exception as e:
            logger.warning(f"윈도우 닫기 실패: {e}")
    
    def focus(self) -> None:
        """윈도우에 포커스 설정"""
        try:
            self.window.set_focus()
            logger.debug(f"윈도우 포커스: {self.WINDOW_NAME}")
        except Exception as e:
            logger.warning(f"윈도우 포커스 실패: {e}")
