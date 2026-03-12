"""
pywinauto Application 래퍼

pywinauto의 Application 객체를 직접 감싸서
재연결, 상태 관리, 설정 로드 등의 기능을 제공합니다.
"""

import logging
from typing import Optional, Any, Dict
from pathlib import Path
from enum import Enum
from threading import Lock

import yaml

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """세션 상태"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class AppSession:
    """
    pywinauto Application 래퍼 클래스
    
    애플리케이션 연결 상태를 관리하고, pywinauto Application 객체에
    대한 안전한 접근을 제공합니다. 재연결 및 상태 복구 기능을 포함합니다.
    
    Attributes:
        app: pywinauto Application 객체
        state: 현재 세션 상태
        config: 애플리케이션 설정
    
    Example:
        >>> session = AppSession()
        >>> session.connect()
        >>> active_window = session.app.top_window()
    """
    
    _instance: Optional["AppSession"] = None
    _lock = Lock()
    
    def __new__(cls, *args, **kwargs):
        """싱글톤 패턴 구현"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        backend: str = "uia"
    ):
        """
        Args:
            config_path: 설정 파일 경로 (기본: config/app_config.yaml)
            backend: pywinauto backend ("uia" 또는 "win32")
        """
        if self._initialized:
            return
        
        self._app: Optional[Any] = None  # pywinauto.Application
        self._state = SessionState.DISCONNECTED
        self._backend = backend
        self._config: Dict[str, Any] = {}
        self._locators: Dict[str, Any] = {}
        
        # 설정 로드
        if config_path:
            self._load_config(config_path)
        else:
            self._load_default_config()
        
        self._load_locators()
        self._initialized = True
    
    def _load_config(self, config_path: str) -> None:
        """설정 파일 로드"""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
            logger.info(f"설정 로드 완료: {config_path}")
        except Exception as e:
            logger.warning(f"설정 로드 실패, 기본값 사용: {e}")
            self._load_default_config()
    
    def _load_default_config(self) -> None:
        """기본 설정 로드 시도"""
        default_paths = [
            Path(__file__).parent.parent / "config" / "app_config.yaml",
            Path("config/app_config.yaml"),
        ]
        
        for path in default_paths:
            if path.exists():
                self._load_config(str(path))
                return
        
        # 기본 설정 사용
        self._config = {
            "application": {
                "backend": "uia",
                "startup_timeout": 30,
            },
            "timeouts": {
                "default_wait": 10,
                "long_wait": 60,
                "short_wait": 3,
                "retry_interval": 0.5,
            },
            "retry": {
                "default_attempts": 3,
                "connection_attempts": 5,
            }
        }
        logger.info("기본 설정 사용")
    
    def _load_locators(self) -> None:
        """locator 설정 로드"""
        locator_paths = [
            Path(__file__).parent.parent / "config" / "locator.yaml",
            Path("config/locator.yaml"),
        ]
        
        for path in locator_paths:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self._locators = yaml.safe_load(f) or {}
                    logger.info(f"Locator 로드 완료: {path}")
                    return
                except Exception as e:
                    logger.warning(f"Locator 로드 실패: {e}")
        
        self._locators = {}
    
    @property
    def state(self) -> SessionState:
        """현재 세션 상태"""
        return self._state
    
    @property
    def is_connected(self) -> bool:
        """연결 상태 여부"""
        return self._state == SessionState.CONNECTED
    
    @property
    def app(self) -> Any:
        """pywinauto Application 객체 (연결 필요)"""
        if self._app is None:
            from errors.automation_error import SessionError
            raise SessionError(
                message="애플리케이션에 연결되지 않았습니다",
                session_state=self._state.value
            )
        return self._app
    
    @property
    def config(self) -> Dict[str, Any]:
        """설정 딕셔너리"""
        return self._config
    
    @property
    def locators(self) -> Dict[str, Any]:
        """Locator 딕셔너리"""
        return self._locators
    
    def get_timeout(self, timeout_type: str = "default_wait") -> float:
        """타임아웃 설정 값 반환"""
        timeouts = self._config.get("timeouts", {})
        return float(timeouts.get(timeout_type, 10))
    
    def get_retry_attempts(self, retry_type: str = "default_attempts") -> int:
        """재시도 횟수 설정 값 반환"""
        retry = self._config.get("retry", {})
        return int(retry.get(retry_type, 3))
    
    def get_locator(self, window_name: str, element_name: str) -> Dict[str, Any]:
        """
        locator 정보 반환
        
        Args:
            window_name: 윈도우 이름 (예: "active_window")
            element_name: 요소 이름 (예: "submit_button")
        
        Returns:
            locator 딕셔너리 (auto_id, control_type 등)
        """
        from errors.automation_error import ElementNotFoundError
        
        window_locators = self._locators.get(window_name, {})
        elements = window_locators.get("elements", {})
        
        if element_name not in elements:
            raise ElementNotFoundError(
                element_name=f"{window_name}.{element_name}",
                details={"available_elements": list(elements.keys())}
            )
        
        return elements[element_name]
    
    def get_window_locator(self, window_name: str) -> Dict[str, Any]:
        """
        윈도우 locator 정보 반환
        
        Args:
            window_name: 윈도우 이름 (예: "active_window")
        
        Returns:
            윈도우 locator 딕셔너리
        """
        from errors.automation_error import WindowNotFoundError
        
        window_locators = self._locators.get(window_name, {})
        window_info = window_locators.get("window", {})
        
        if not window_info:
            raise WindowNotFoundError(
                window_name=window_name,
                details={"available_windows": list(self._locators.keys())}
            )
        
        return window_info
    
    def connect(
        self,
        process: Optional[int] = None,
        path: Optional[str] = None,
        title: Optional[str] = None,
        **kwargs
    ) -> "AppSession":
        """
        실행 중인 애플리케이션에 연결
        
        Args:
            process: 프로세스 ID
            path: 실행 파일 경로
            title: 윈도우 제목
            **kwargs: pywinauto Application.connect() 추가 인자
        
        Returns:
            self (체이닝 지원)
        """
        from errors.automation_error import ConnectionError
        
        try:
            from pywinauto import Application
        except ImportError:
            raise ConnectionError(
                message="pywinauto가 설치되지 않았습니다",
                details={"install": "pip install pywinauto"}
            )
        
        self._state = SessionState.CONNECTING
        logger.info("애플리케이션 연결 시도")
        
        try:
            self._app = Application(backend=self._backend)
            
            connect_args = {}
            if process:
                connect_args["process"] = process
            elif path:
                connect_args["path"] = path
            elif title:
                connect_args["title"] = title
            else:
                # 설정에서 경로 가져오기
                app_config = self._config.get("application", {})
                exe_path = app_config.get("executable_path")
                if exe_path:
                    connect_args["path"] = exe_path
                else:
                    raise ConnectionError(
                        message="연결 대상을 지정해주세요 (process, path, 또는 title)"
                    )
            
            connect_args.update(kwargs)
            self._app.connect(**connect_args)
            
            self._state = SessionState.CONNECTED
            logger.info(f"애플리케이션 연결 성공: {connect_args}")
            
            return self
            
        except Exception as e:
            self._state = SessionState.ERROR
            logger.error(f"애플리케이션 연결 실패: {e}")
            raise ConnectionError(
                message="애플리케이션 연결 실패",
                cause=e,
                details={"connect_args": str(connect_args)}
            )
    
    def start(
        self,
        path: Optional[str] = None,
        **kwargs
    ) -> "AppSession":
        """
        애플리케이션 실행 및 연결
        
        Args:
            path: 실행 파일 경로 (없으면 설정에서 가져옴)
            **kwargs: pywinauto Application.start() 추가 인자
        
        Returns:
            self (체이닝 지원)
        """
        from errors.automation_error import ConnectionError
        from core.wait_utils import wait_until
        
        try:
            from pywinauto import Application
        except ImportError:
            raise ConnectionError(
                message="pywinauto가 설치되지 않았습니다"
            )
        
        self._state = SessionState.CONNECTING
        
        # 실행 경로 결정
        exe_path = path or self._config.get("application", {}).get("executable_path")
        if not exe_path:
            raise ConnectionError(
                message="실행 파일 경로를 지정해주세요"
            )
        
        startup_timeout = self._config.get("application", {}).get("startup_timeout", 30)
        
        logger.info(f"애플리케이션 실행: {exe_path}")
        
        try:
            self._app = Application(backend=self._backend)
            self._app.start(exe_path, **kwargs)
            
            # 메인 윈도우 대기
            wait_until(
                condition=lambda: len(self._app.windows()) > 0,
                timeout=startup_timeout,
                timeout_message=f"애플리케이션 시작 대기 ({exe_path})"
            )
            
            self._state = SessionState.CONNECTED
            logger.info("애플리케이션 실행 및 연결 성공")
            
            return self
            
        except Exception as e:
            self._state = SessionState.ERROR
            logger.error(f"애플리케이션 실행 실패: {e}")
            raise ConnectionError(
                message="애플리케이션 실행 실패",
                cause=e,
                details={"path": exe_path}
            )
    
    def disconnect(self) -> None:
        """애플리케이션 연결 해제"""
        if self._app is not None:
            self._app = None
        self._state = SessionState.DISCONNECTED
        logger.info("애플리케이션 연결 해제")
    
    def reconnect(self) -> "AppSession":
        """
        애플리케이션 재연결
        
        기존 연결을 해제하고 다시 연결합니다.
        """
        logger.info("애플리케이션 재연결 시도")
        self.disconnect()
        return self.connect()
    
    def get_window(
        self,
        title: Optional[str] = None,
        auto_id: Optional[str] = None,
        control_type: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        윈도우 객체 반환
        
        Args:
            title: 윈도우 제목
            auto_id: 윈도우 AutomationId
            control_type: 컨트롤 타입
            **kwargs: 추가 검색 조건
        
        Returns:
            pywinauto WindowSpecification 객체
        """
        search_criteria = {}
        
        if title:
            search_criteria["title"] = title
        if auto_id:
            search_criteria["auto_id"] = auto_id
        if control_type:
            search_criteria["control_type"] = control_type
        
        search_criteria.update(kwargs)
        
        return self.app.window(**search_criteria)
    
    def get_window_by_locator(self, window_name: str) -> Any:
        """
        locator 설정을 사용해 윈도우 객체 반환
        
        Args:
            window_name: locator.yaml에 정의된 윈도우 이름
        
        Returns:
            pywinauto WindowSpecification 객체
        """
        locator = self.get_window_locator(window_name)
        return self.get_window(**locator)
    
    @classmethod
    def get_instance(cls) -> "AppSession":
        """싱글톤 인스턴스 반환"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """싱글톤 인스턴스 초기화 (테스트용)"""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.disconnect()
                cls._instance._initialized = False
            cls._instance = None
