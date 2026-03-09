"""
FastMCP 서버 진입점

pywinauto 기반 Windows 자동화를 위한 FastMCP 서버입니다.
LLM이 Windows 애플리케이션을 도구(tool)처럼 제어할 수 있게 합니다.

아키텍처:
    LLM (Claude 등)
        ↓ MCP Protocol
    FastMCP Server (이 파일)
        ↓ Tool 호출
    Tools 계층 (tools/*.py)
        ↓ Action 호출
    Actions 계층 (actions/*.py)
        ↓ UI 조작
    UI 계층 (ui/*.py)
        ↓ pywinauto
    Windows Application

사용법:
    # 서버 실행
    python -m mcp_server
    
    # 또는 직접 실행
    python mcp_server.py

설정:
    - config/app_config.yaml: 애플리케이션 설정
    - config/locator.yaml: UI 요소 locator
"""

import logging
import sys
from pathlib import Path
from typing import Optional

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from mcp.server.fastmcp import FastMCP

# 로깅 설정
def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """로깅 설정"""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    handlers = [logging.StreamHandler(sys.stderr)]
    
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        handlers=handlers
    )

# 로깅 초기화
setup_logging(level="INFO", log_file="win_mcp/logs/mcp_server.log")
logger = logging.getLogger(__name__)


# ============================================================
# FastMCP 서버 생성
# ============================================================

mcp = FastMCP(
    name="Windows Automation MCP Server",
    instructions="""
Windows 애플리케이션 자동화를 위한 MCP 서버입니다.

이 서버는 pywinauto를 사용하여 Windows 프로그램을 제어합니다.
LLM은 제공되는 도구들을 통해 다음 작업을 수행할 수 있습니다:

- 애플리케이션 실행/종료/재시작
- 로그인/로그아웃
- 분석/처리 작업 실행
- 검색 및 데이터 내보내기

사용 전 애플리케이션 설정(config/app_config.yaml)과
UI locator(config/locator.yaml)를 확인하세요.
"""
)


# ============================================================
# Tool 등록
# ============================================================

def register_all_tools() -> None:
    """모든 도구를 FastMCP 서버에 등록"""
    from tools.app_tool import register_app_tools
    from tools.color_click_tool import register_color_click_tools
    from tools.app_ui_tool import register_app_ui_tools
    from tools.login_tool import register_login_tools
    from tools.run_tool import register_run_tools
    from tools.source_open_tool import register_source_open_tools
    
    # 애플리케이션 관리 도구
    register_app_tools(mcp)
    
    # 색상 기반 도구
    register_color_click_tools(mcp)

    # 애플리케이션 UI 도구 (OCR/픽셀)
    register_app_ui_tools(mcp)
    
    # 로그인 관련 도구
    register_login_tools(mcp)
    
    # 실행/분석 관련 도구
    register_run_tools(mcp)

    # 소스 오픈 도구
    register_source_open_tools(mcp)
    
    logger.info("모든 도구 등록 완료")


# ============================================================
# 서버 상태 관리
# ============================================================

class ServerState:
    """
    서버 상태 관리
    
    FastMCP 서버는 상태를 최소한만 유지합니다.
    AppSession 싱글톤을 통해 애플리케이션 연결 상태를 관리합니다.
    """
    
    def __init__(self):
        self._initialized = False
    
    def initialize(self) -> None:
        """서버 초기화"""
        if self._initialized:
            return
        
        logger.info("서버 초기화 시작")
        
        # AppSession 초기화 (설정 로드)
        from core.app_session import AppSession
        session = AppSession.get_instance()
        
        # 도구 등록
        register_all_tools()
        
        self._initialized = True
        logger.info("서버 초기화 완료")
    
    def cleanup(self) -> None:
        """서버 정리"""
        logger.info("서버 정리 시작")
        
        try:
            from core.app_session import AppSession
            session = AppSession.get_instance()
            session.disconnect()
        except Exception as e:
            logger.warning(f"세션 정리 중 오류: {e}")
        
        self._initialized = False
        logger.info("서버 정리 완료")


# 전역 서버 상태
_server_state = ServerState()


# ============================================================
# 서버 이벤트 핸들러
# ============================================================

@mcp.resource("config://app")
async def get_app_config() -> str:
    """
    애플리케이션 설정을 반환합니다.
    
    LLM이 현재 설정된 애플리케이션 정보를 확인할 때 사용합니다.
    """
    import yaml
    from core.app_session import AppSession
    
    session = AppSession.get_instance()
    config = session.config
    
    return yaml.dump(config, allow_unicode=True, default_flow_style=False)


@mcp.resource("config://locators")
async def get_locators_config() -> str:
    """
    UI locator 설정을 반환합니다.
    
    LLM이 사용 가능한 UI 요소 정보를 확인할 때 사용합니다.
    """
    import yaml
    from core.app_session import AppSession
    
    session = AppSession.get_instance()
    locators = session.locators
    
    return yaml.dump(locators, allow_unicode=True, default_flow_style=False)


# ============================================================
# 서버 실행
# ============================================================

def run_with_reloader(args):
    """파일 변경 감지 및 자동 재시작 로직 (Master Process)"""
    import subprocess
    import time
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    class ReloadHandler(FileSystemEventHandler):
        def __init__(self, restart_func):
            self.restart_func = restart_func
            self._last_reload = 0

        def on_any_event(self, event):
            # .py 또는 .yaml 파일 변경 시에만 재시작
            if event.is_directory:
                return
            if not event.src_path.endswith(('.py', '.yaml')):
                return
            
            # 디바운싱: 너무 빈번한 재시작 방지 (1초 간격)
            now = time.time()
            if now - self._last_reload < 1.0:
                return
            self._last_reload = now
            
            logger.info(f"변경 감지됨: {event.src_path}. 서버를 재시작합니다...")
            self.restart_func()

    process = None

    def start_server():
        nonlocal process
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        
        # 실제 서버 프로세스 실행 (자신을 subprocess로 실행하되 --reload 없이)
        cmd = [sys.executable] + [a for a in sys.argv if a != "--reload"]
        process = subprocess.Popen(cmd)

    # 초기 실행
    start_server()

    # 파일 감시 시작
    event_handler = ReloadHandler(start_server)
    observer = Observer()
    # 현재 디렉토리 감시
    observer.schedule(event_handler, path=str(Path(__file__).parent), recursive=True)
    observer.start()

    logger.info("Auto-reload 활성화됨. 파일 변경을 감시합니다.")

    try:
        while True:
            time.sleep(1)
            # 하위 프로세스가 죽었는지 체크
            if process.poll() is not None:
                logger.warning("서버 프로세스가 종료되었습니다. 재시작 대기 중...")
                time.sleep(2)
                start_server()
    except KeyboardInterrupt:
        observer.stop()
        if process:
            process.terminate()
    observer.join()


def main():
    """메인 진입점"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Windows Automation MCP Server"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨 (기본: INFO)"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="설정 파일 경로"
    )
    parser.add_argument(
        "--transport",
        default="http",
        choices=["stdio", "http", "streamable-http", "sse"],
        help="전송 방식 (기본: http)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP 호스트 (기본: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP 포트 (기본: 8000)"
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="HTTP 경로 (기본: /mcp)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="파일 변경 시 자동 재시작 활성화"
    )
    
    args = parser.parse_args()
    
    if args.reload:
        run_with_reloader(args)
        return

    # 로깅 레벨 업데이트
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # 포트 충돌 해결 (기존 프로세스 종료)
    if args.transport in ("http", "streamable-http", "sse"):
        from core.network_utils import kill_process_on_port
        kill_process_on_port(args.port)
    
    # 서버 초기화
    _server_state.initialize()
    
    logger.info("FastMCP 서버 시작")
    logger.info(f"서버 이름: {mcp.name}")
    logger.info(f"서버 버전: {mcp.version if hasattr(mcp, 'version') else '1.0.0'}")
    
    try:
        # FastMCP 서버 실행
        if args.transport in ("http", "streamable-http"):
            mcp.settings.host = args.host
            mcp.settings.port = args.port
            mcp.settings.streamable_http_path = args.path
            logger.info(f"HTTP 서버 주소: http://{args.host}:{args.port}{args.path}")
            mcp.run(transport="streamable-http")
        elif args.transport == "sse":
            mcp.settings.host = args.host
            mcp.settings.port = args.port
            mcp.settings.mount_path = args.path
            logger.info(f"SSE 서버 주소: http://{args.host}:{args.port}{args.path}")
            mcp.run(transport="sse")
        else:
            mcp.run()
    except KeyboardInterrupt:
        logger.info("서버 종료 요청")
    except Exception as e:
        logger.error(f"서버 오류: {e}")
        # subprocess 환경이 아닐 때만 raise (reloader에서 핸들링하도록)
        if not args.reload:
            raise
    finally:
        _server_state.cleanup()
        logger.info("서버 종료")


if __name__ == "__main__":
    main()
