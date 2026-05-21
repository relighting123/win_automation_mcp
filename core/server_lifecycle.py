"""
MCP 서버 라이프사이클 헬퍼

`automation_graph.py`와 같이 MCP 서버에 의존하는 클라이언트가
서버를 빠르게 띄우고/공유/회수할 수 있도록 돕는 유틸리티.

핵심 기능:
- `is_server_ready(base_url)` : 서버가 응답 가능한지 빠르게 체크
- `wait_for_server(base_url, timeout)` : 일정 시간 동안 폴링하며 준비 대기
- `ensure_mcp_server(base_url, auto_start=...)` : 서버가 죽어 있으면
  자동으로 `mcp_server.py`를 백그라운드 프로세스로 띄우고 ready 까지 대기
- 컨텍스트 매니저 형태(`mcp_server_context(...)`) 지원

서버가 이미 떠 있는 환경(개발자가 별도 터미널에서 띄워둔 경우)에서는
프로세스를 새로 띄우지 않고 그대로 재사용합니다. 이 헬퍼가 서버를 띄운
경우에만 종료 시 함께 정리합니다.
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# mcp_server.py가 위치한 프로젝트 루트
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SERVER_ENTRYPOINT = _PROJECT_ROOT / "mcp_server.py"


def _parse_host_port(base_url: str) -> tuple[str, int]:
    """`http://host:port/...` 형태 URL에서 host, port를 추출합니다."""
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _tcp_open(host: str, port: int, timeout: float = 0.3) -> bool:
    """TCP 단순 연결로 포트 점유 여부를 빠르게 확인합니다."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_server_ready(base_url: str, timeout: float = 1.5) -> bool:
    """
    MCP 엔드포인트가 정상 응답하는지 빠르게 확인합니다.

    FastMCP streamable-http 서버는 GET 요청에 다양한 상태(보통 405/406/400 등)를
    돌려주는데, 어떤 응답이든 와도 "프로세스는 살아있다"로 간주합니다.
    """
    host, port = _parse_host_port(base_url)
    if not _tcp_open(host, port, timeout=min(timeout, 0.5)):
        return False

    try:
        # 단순 HEAD/GET으로도 충분 - HTTP 응답이 오면 살아있는 것으로 본다
        with httpx.Client(timeout=timeout) as client:
            client.get(base_url)
        return True
    except httpx.HTTPError:
        # 연결은 되지만 응답이 비정상인 경우 - 일단 살아있으니 OK 처리
        return _tcp_open(host, port, timeout=0.2)


def wait_for_server(base_url: str, timeout: float = 30.0, interval: float = 0.3) -> bool:
    """서버가 준비될 때까지 폴링하며 대기합니다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_server_ready(base_url):
            return True
        time.sleep(interval)
    return False


def _build_server_command(
    base_url: str,
    *,
    log_level: str = "INFO",
    extra_args: Optional[list[str]] = None,
) -> list[str]:
    """`python mcp_server.py ...` 형태 실행 명령을 구성합니다."""
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    path = parsed.path or "/mcp"

    cmd = [
        sys.executable,
        str(_SERVER_ENTRYPOINT),
        "--transport", "http",
        "--host", str(host),
        "--port", str(port),
        "--path", str(path),
        "--log-level", log_level,
    ]
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def start_mcp_server(
    base_url: str,
    *,
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> subprocess.Popen:
    """
    MCP 서버를 백그라운드 프로세스로 띄웁니다.

    Args:
        base_url: 서버 URL (http://host:port/path)
        log_level: 자식 프로세스의 로그 레벨
        log_file: stdout/stderr를 기록할 파일 경로 (None이면 부모와 동일하게 출력)
        extra_args: mcp_server.py에 추가로 전달할 인자

    Returns:
        subprocess.Popen 인스턴스 (이미 ready 대기는 별도로 수행해야 함)
    """
    if not _SERVER_ENTRYPOINT.exists():
        raise FileNotFoundError(
            f"mcp_server.py를 찾을 수 없습니다: {_SERVER_ENTRYPOINT}"
        )

    cmd = _build_server_command(base_url, log_level=log_level, extra_args=extra_args)
    logger.info("MCP 서버 자동 기동: %s", " ".join(cmd))

    stdout = stderr = None
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        stdout = open(log_file, "ab", buffering=0)
        stderr = stdout

    # 새 프로세스 그룹으로 띄워서 부모가 받는 Ctrl+C가 곧장 자식에 전파되지 않도록 분리
    popen_kwargs: dict = {
        "stdout": stdout,
        "stderr": stderr,
        "cwd": str(_PROJECT_ROOT),
        "env": os.environ.copy(),
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kwargs["start_new_session"] = True

    return subprocess.Popen(cmd, **popen_kwargs)


def stop_mcp_server(process: subprocess.Popen, timeout: float = 5.0) -> None:
    """띄워둔 MCP 서버 프로세스를 안전하게 종료합니다."""
    if process.poll() is not None:
        return
    logger.info("MCP 서버 프로세스 종료 시도 (PID=%s)", process.pid)
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("MCP 서버가 timeout 내 종료되지 않아 강제 종료합니다.")
        process.kill()
    except Exception as exc:  # pragma: no cover - best effort cleanup
        logger.debug("MCP 서버 종료 중 오류(무시): %s", exc)


def ensure_mcp_server(
    base_url: str,
    *,
    auto_start: bool = True,
    startup_timeout: float = 30.0,
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> Optional[subprocess.Popen]:
    """
    MCP 서버가 응답 가능한지 확인하고, 필요하면 자동으로 띄웁니다.

    Returns:
        - 새로 띄운 경우: 해당 subprocess.Popen (호출 측에서 정리 가능)
        - 이미 떠 있던 경우: None (재사용)
    """
    if is_server_ready(base_url):
        logger.info("MCP 서버가 이미 응답 중입니다: %s", base_url)
        return None

    if not auto_start:
        raise RuntimeError(
            f"MCP 서버에 연결할 수 없습니다: {base_url}\n"
            "별도 터미널에서 `python mcp_server.py`를 먼저 실행하거나 "
            "`auto_start=True`로 호출하세요."
        )

    process = start_mcp_server(
        base_url,
        log_level=log_level,
        log_file=log_file,
        extra_args=extra_args,
    )

    if not wait_for_server(base_url, timeout=startup_timeout):
        stop_mcp_server(process)
        raise RuntimeError(
            f"MCP 서버 기동 대기 시간 초과({startup_timeout}s): {base_url}"
        )

    logger.info("MCP 서버 기동 완료: %s", base_url)
    return process


@contextlib.contextmanager
def mcp_server_context(
    base_url: str,
    *,
    auto_start: bool = True,
    startup_timeout: float = 30.0,
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> Iterator[Optional[subprocess.Popen]]:
    """
    `with` 블록 내에서만 MCP 서버를 보장하는 컨텍스트 매니저.

    이 헬퍼가 새로 띄운 경우에만 컨텍스트 종료 시 자동 정리합니다.
    이미 떠 있던 서버는 종료하지 않습니다.
    """
    process = ensure_mcp_server(
        base_url,
        auto_start=auto_start,
        startup_timeout=startup_timeout,
        log_level=log_level,
        log_file=log_file,
        extra_args=extra_args,
    )
    try:
        yield process
    finally:
        if process is not None:
            stop_mcp_server(process)
