"""
애플리케이션 실행/종료 관리

애플리케이션의 생명주기를 관리합니다.
실행, 종료, 재시작, 프로세스 확인 등의 기능을 제공합니다.
"""

import logging
import subprocess
from typing import Optional, List, Dict, Any
from pathlib import Path

from core.app_session import AppSession, SessionState
from core.wait_utils import wait_until, retry_on_failure
from errors.automation_error import (
    ConnectionError,
    ActionFailedError,
    TimeoutError,
)

logger = logging.getLogger(__name__)


class AppLauncher:
    """
    애플리케이션 실행/종료 관리자
    
    타겟 애플리케이션의 생명주기를 관리합니다.
    AppSession과 협력하여 애플리케이션을 실행하고 연결합니다.
    
    Example:
        >>> launcher = AppLauncher()
        >>> session = launcher.launch()
        >>> # 작업 수행
        >>> launcher.close()
    """
    
    def __init__(self, session: Optional[AppSession] = None):
        """
        Args:
            session: 사용할 AppSession 인스턴스 (없으면 싱글톤 사용)
        """
        self._session = session or AppSession.get_instance()
    
    @property
    def session(self) -> AppSession:
        """현재 세션 반환"""
        return self._session
    
    @property
    def is_running(self) -> bool:
        """애플리케이션 실행 중 여부"""
        return self._session.is_connected
    
    def launch(
        self,
        path: Optional[str] = None,
        args: Optional[List[str]] = None,
        wait_for_ready: bool = True,
        **kwargs
    ) -> AppSession:
        """
        애플리케이션 실행
        
        Args:
            path: 실행 파일 경로 (없으면 설정에서 가져옴)
            args: 명령행 인자
            wait_for_ready: 애플리케이션 준비 대기 여부
            **kwargs: pywinauto start() 추가 인자
        
        Returns:
            연결된 AppSession
        """
        if self._session.is_connected:
            logger.info("이미 연결된 세션이 있습니다")
            return self._session
        
        exe_path = path or self._session.config.get(
            "application", {}
        ).get("executable_path")
        
        if not exe_path:
            raise ConnectionError(
                message="실행 파일 경로가 지정되지 않았습니다"
            )
        
        # 경로 존재 확인
        if not Path(exe_path).exists():
            logger.warning(f"실행 파일을 찾을 수 없습니다: {exe_path}")
            # 원격 환경에서는 경로가 다를 수 있으므로 경고만 출력
        
        logger.info(f"애플리케이션 실행: {exe_path}")
        
        # 명령행 인자 처리
        if args:
            kwargs["cmd_line"] = " ".join(args)
        
        return self._session.start(path=exe_path, **kwargs)
    
    def connect_to_running(
        self,
        process_id: Optional[int] = None,
        title: Optional[str] = None,
        path: Optional[str] = None
    ) -> AppSession:
        """
        이미 실행 중인 애플리케이션에 연결
        
        Args:
            process_id: 프로세스 ID
            title: 윈도우 제목
            path: 실행 파일 경로
        
        Returns:
            연결된 AppSession
        """
        return self._session.connect(
            process=process_id,
            title=title,
            path=path
        )
    
    @retry_on_failure(max_attempts=3, retry_interval=2.0)
    def ensure_running(self) -> AppSession:
        """
        애플리케이션이 실행 중인지 확인하고, 아니면 실행
        
        Returns:
            연결된 AppSession
        """
        if self._session.is_connected:
            # 연결 상태 확인
            try:
                windows = self._session.app.windows()
                if windows:
                    return self._session
            except Exception:
                logger.warning("기존 연결이 유효하지 않음, 재연결 시도")
                self._session.disconnect()
        
        # 이미 실행 중인지 확인 후 연결 시도
        try:
            return self._session.connect()
        except ConnectionError:
            # 실행 중이 아니면 새로 실행
            return self.launch()
    
    def close(self, force: bool = False, timeout: float = 10.0) -> bool:
        """
        애플리케이션 종료
        
        Args:
            force: 강제 종료 여부
            timeout: 종료 대기 시간 (초)
        
        Returns:
            종료 성공 여부
        """
        if not self._session.is_connected:
            logger.info("종료할 애플리케이션이 없습니다")
            return True
        
        logger.info(f"애플리케이션 종료 시도 (force={force})")
        
        try:
            app = self._session.app
            
            if force:
                # 강제 종료
                app.kill()
            else:
                # 정상 종료 시도
                for window in app.windows():
                    try:
                        window.close()
                    except Exception as e:
                        logger.debug(f"윈도우 종료 실패: {e}")
            
            # 종료 대기
            try:
                wait_until(
                    condition=lambda: not self._is_process_running(),
                    timeout=timeout,
                    timeout_message="애플리케이션 종료 대기",
                    raise_on_timeout=False
                )
            except TimeoutError:
                if not force:
                    logger.warning("정상 종료 실패, 강제 종료 시도")
                    app.kill()
            
            self._session.disconnect()
            logger.info("애플리케이션 종료 완료")
            return True
            
        except Exception as e:
            logger.error(f"애플리케이션 종료 실패: {e}")
            self._session.disconnect()
            return False
    
    def restart(self, **kwargs) -> AppSession:
        """
        애플리케이션 재시작
        
        Args:
            **kwargs: launch()에 전달할 인자
        
        Returns:
            새로 연결된 AppSession
        """
        logger.info("애플리케이션 재시작")
        self.close(force=True, timeout=5.0)
        return self.launch(**kwargs)
    
    def _is_process_running(self) -> bool:
        """프로세스 실행 중 여부 확인"""
        try:
            if self._session.is_connected:
                windows = self._session.app.windows()
                return len(windows) > 0
        except Exception:
            pass
        return False
    
    def get_process_info(self) -> Dict[str, Any]:
        """
        현재 프로세스 정보 반환
        
        Returns:
            프로세스 정보 딕셔너리
        """
        if not self._session.is_connected:
            return {
                "running": False,
                "state": self._session.state.value
            }
        
        try:
            app = self._session.app
            windows = app.windows()
            
            return {
                "running": True,
                "state": self._session.state.value,
                "window_count": len(windows),
                "windows": [
                    {
                        "title": w.window_text(),
                        "control_type": w.element_info.control_type if hasattr(w, "element_info") else "unknown"
                    }
                    for w in windows
                ]
            }
        except Exception as e:
            return {
                "running": False,
                "state": self._session.state.value,
                "error": str(e)
            }


def get_launcher() -> AppLauncher:
    """기본 AppLauncher 인스턴스 반환"""
    return AppLauncher()
