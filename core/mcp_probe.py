"""MCP HTTP(streamable-http) 서버 연결 프로브."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

import requests

from core.llm_config import DEFAULT_MCP_BASE_URL, DEFAULT_MCP_PORT

logger = logging.getLogger(__name__)

_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

_INIT_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "chatRTD-probe", "version": "1.0.0"},
    },
}


def normalize_mcp_url(url: str) -> str:
    """MCP endpoint URL을 정규화합니다."""
    raw = (url or "").strip() or DEFAULT_MCP_BASE_URL
    parsed = urlparse(raw)
    host = parsed.hostname or "localhost"
    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    elif host in {"localhost", "127.0.0.1"}:
        port = DEFAULT_MCP_PORT
    else:
        port = 80
    scheme = parsed.scheme or "http"
    path = parsed.path or "/mcp"
    if not path.endswith("/mcp"):
        path = path.rstrip("/") + "/mcp"
    return f"{scheme}://{host}:{port}{path}"


def parse_mcp_endpoint(url: str) -> tuple[str, int, str]:
    """(host, port, path)를 반환합니다."""
    normalized = normalize_mcp_url(url)
    parsed = urlparse(normalized)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or DEFAULT_MCP_PORT
    path = parsed.path or "/mcp"
    return host, port, path


def probe_mcp_http(url: str, *, timeout: float = 5.0) -> bool:
    """
    streamable-http MCP 서버가 initialize를 처리하는지 확인합니다.

  GET / 는 404여도 성공으로 오인될 수 있어 POST initialize로 검증합니다.
    """
    target = normalize_mcp_url(url)
    try:
        response = requests.post(
            target,
            json=_INIT_PAYLOAD,
            headers=_MCP_HEADERS,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.debug("MCP probe 실패(%s): %s", target, exc)
        return False

    if response.status_code != 200:
        logger.debug(
            "MCP probe 실패(%s): HTTP %s %s",
            target,
            response.status_code,
            response.text[:200],
        )
        return False

    if not response.headers.get("mcp-session-id"):
        logger.debug("MCP probe 실패(%s): mcp-session-id 헤더 없음", target)
        return False

    return True


def wait_for_mcp_http(
    url: str,
    *,
    attempts: int = 20,
    interval: float = 0.5,
    timeout: float = 3.0,
) -> bool:
    """MCP 서버가 준비될 때까지 initialize 프로브를 반복합니다."""
    for _ in range(max(1, attempts)):
        if probe_mcp_http(url, timeout=timeout):
            return True
        if interval > 0:
            import time

            time.sleep(interval)
    return False
