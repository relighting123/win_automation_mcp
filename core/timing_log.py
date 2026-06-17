"""요청/도구 실행 구간별 소요 시간 로그 (MCP_REQUEST_TIMING=true)."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


def timing_enabled() -> bool:
    return str(os.getenv("MCP_REQUEST_TIMING", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def configure_mcp_debug_logging() -> None:
    """MCP SDK 내부 요청 로그(ListToolsRequest 등)를 보이게 합니다."""
    if not timing_enabled():
        return
    for name in ("mcp", "mcp.server", "mcp.server.lowlevel"):
        logging.getLogger(name).setLevel(logging.DEBUG)


@contextmanager
def log_timing(scope: str, *, detail: str = "") -> Iterator[None]:
    if not timing_enabled():
        yield
        return

    label = f"{scope} ({detail})" if detail else scope
    started = time.perf_counter()
    logger.info("[timing] %s 시작", label)
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info("[timing] %s 완료 %.1fms", label, elapsed_ms)


def log_timing_done(scope: str, started: float, *, detail: str = "") -> None:
    if not timing_enabled():
        return
    label = f"{scope} ({detail})" if detail else scope
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    logger.info("[timing] %s 완료 %.1fms", label, elapsed_ms)
