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
        self._apply_timings()
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
    def backend(self) -> str:
        """pywinauto backend"""
        return self._backend

    @property
    def config(self) -> Dict[str, Any]:
        """설정 딕셔너리"""
        return self._config
    
    @property
    def locators(self) -> Dict[str, Any]:
        """Locator 딕셔너리"""
        return self._locators
    
    def get_timeout(self, timeout_type: str = "default_wait") -> float:
        """타임아웃 설정 값 반환 (비정상적인 값에 대한 기본값 처리 포함)"""
        timeouts = self._config.get("timeouts", {})
        val = timeouts.get(timeout_type)
        if val is None:
            # YAML에서 값이 비어있을 경우 (None) 기본값 처리
            defaults = {
                "default_wait": 10.0,
                "long_wait": 60.0,
                "short_wait": 5.0,
                "retry_interval": 0.5
            }
            return defaults.get(timeout_type, 10.0)
        return float(val)
    
    def get_retry_attempts(self, retry_type: str = "default_attempts") -> int:
        """재시도 횟수 설정 값 반환 (비정상적인 값에 대한 기본값 처리 포함)"""
        retry = self._config.get("retry", {})
        val = retry.get(retry_type)
        if val is None:
            return 3
        return int(val)
    
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
            title: 윈도우 제목 (전체 일치)
            title_re: 윈도우 제목 정규식 (부분 일치 가능)
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
            
            # 연결 전략 시도
            if self._try_connect(process, path, title, **kwargs):
                # 연결 후 경로 검증 (엄격한 경로 제한)
                if self._verify_connection_path():
                    self._state = SessionState.CONNECTED
                    self._bring_to_front()
                    return self
                else:
                    self.disconnect()
                    logger.warning("연결된 프로세스의 실행 파일 경로가 설정과 일치하지 않아 연결을 해제합니다.")
                
        except Exception as e:
            self._state = SessionState.ERROR
            logger.error(f"애플리케이션 연결 실패: {e}")
            
            # 실패 시 현재 열려있는 윈도우 목록을 가져와서 힌트 제공
            available_windows = []
            try:
                from pywinauto import Desktop
                available_windows = [w.window_text() for w in Desktop(backend=self._backend).windows() if w.window_text()]
            except Exception:
                pass

            raise ConnectionError(
                message="애플리케이션 연결 실패",
                cause=e,
                details={
                    "process": process,
                    "path": path,
                    "title": title,
                    "available_windows_hints": available_windows[:20]
                }
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
    
    def _try_connect(self, process=None, path=None, title=None, **kwargs) -> bool:
        """다양한 전략으로 연결 시도"""
        strategies = []
        
        # 1. 명시적 인자 전략
        if process: strategies.append({"process": process})
        if path: strategies.append({"path": path})
        if title: strategies.append({"title": title})
        if kwargs.get("title_re"): strategies.append({"title_re": kwargs.get("title_re")})
        
        # 2. 설정 기반 자동 전략 (명시적 인자가 부족할 때)
        if not strategies:
            app_config = self._config.get("application", {})
            conf_path = app_config.get("executable_path")
            
            if conf_path:
                # PID 기반 선행 검색 시도 (경로가 정확히 일치하는 프로세스 검색)
                pid = self._find_pid_by_path(conf_path)
                if pid:
                    strategies.append({"process": pid})
                else:
                    # PID가 없으면 경로 기반 시도 (Fallback)
                    strategies.append({"path": conf_path})
            
            # 보안 강화를 위해 타이틀 기반 폴백은 더 이상 사용하지 않습니다.

        for args in strategies:
            try:
                logger.debug(f"연결 시도 중: {args}")
                self._app.connect(**args, **kwargs)
                logger.info(f"애플리케이션 연결 성공: {args}")
                return True
            except Exception as e:
                logger.debug(f"연결 실패 ({args}): {e}")
        
        return False

    def _bring_to_front(self) -> None:
        """메인 윈도우를 최상단으로 가져오기"""
        try:
            top_win = self._app.top_window()
            if top_win.exists():
                if top_win.is_minimized():
                    top_win.restore()
                top_win.set_focus()
                logger.info("윈도우를 맨 앞으로 가져왔습니다.")
        except Exception as e:
            logger.debug(f"포커스 설정 실패 (무시): {e}")

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

    def _apply_timings(self) -> None:
        """pywinauto의 기본 동작 타이밍을 설정합니다."""
        try:
            from pywinauto.timings import Timings
            speed = self._config.get("application", {}).get("automation_speed", "normal")
            
            if speed == "fast":
                Timings.fast()
                logger.info("pywinauto Timings: [FAST] 모드로 설정되었습니다.")
            else:
                Timings.defaults()
                logger.info("pywinauto Timings: [NORMAL] 모드로 설정되었습니다.")
        except Exception as e:
            logger.warning(f"타이밍 설정 적용 실패: {e}")

    def _find_pid_by_path(self, target_path: str) -> Optional[int]:
        """실행 파일 경로를 기준으로 PID를 찾습니다."""
        try:
            import psutil
            target_path = target_path.lower().replace('/', '\\')
            for proc in psutil.process_iter(['pid', 'exe']):
                try:
                    exe = proc.info['exe']
                    if exe and exe.lower().replace('/', '\\') == target_path:
                        return proc.info['pid']
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.debug(f"PID 검색 중 오류: {e}")
        return None

    def _verify_connection_path(self) -> bool:
        """현재 연결된 앱의 프로세스 경로가 설정된 경로와 일치하는지 확인합니다."""
        target_path = self._config.get("application", {}).get("executable_path")
        if not target_path or self._app is None:
            return True
            
        try:
            import psutil
            # pywinauto.Application 객체는 연결 후 .process 속성에 PID를 가집니다.
            pid = getattr(self._app, 'process', None)
            if pid is None:
                return True
                
            proc = psutil.Process(pid)
            actual_path = proc.exe().lower().replace('/', '\\')
            target_path_norm = target_path.lower().replace('/', '\\')
            return actual_path == target_path_norm
        except Exception:
            return False
    def get_top_window(self) -> Any:
        """
        애플리케이션의 최상위 윈도우(Main Window)를 반환합니다.
        """
        try:
            top_win = self.app.top_window()
            if top_win.exists():
                return top_win
        except Exception as e:
            logger.debug(f"최상위 윈도우 획득 실패: {e}")
        return None
