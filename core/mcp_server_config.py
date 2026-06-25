"""
MCP 서버 설정 로더.

chatRTD는 기본 automation MCP(HTTP) 외에 추가 MCP 서버를 병렬로 연결할 수 있습니다.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.llm_config import DEFAULT_MCP_BASE_URL, load_app_config

logger = logging.getLogger(__name__)


def _is_truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class MCPServerConfig:
    """단일 MCP 서버 연결 설정."""

    id: str
    transport: str = "http"  # http | stdio
    url: Optional[str] = None
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    tool_prefix: bool = True

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MCPServerConfig":
        if not isinstance(raw, dict):
            raise ValueError(f"extra_servers 항목은 dict 여야 합니다: {raw}")

        server_id = str(raw.get("id") or "").strip()
        if not server_id:
            raise ValueError(f"extra_servers 항목에 id가 필요합니다: {raw}")

        transport = str(raw.get("transport") or "http").strip().lower()
        args = raw.get("args") or []
        if not isinstance(args, list):
            raise ValueError(f"{server_id}: args는 list 여야 합니다.")

        env = raw.get("env") or {}
        if not isinstance(env, dict):
            raise ValueError(f"{server_id}: env는 dict 여야 합니다.")

        tool_prefix = raw.get("tool_prefix", True)
        if isinstance(tool_prefix, str):
            tool_prefix = _is_truthy(tool_prefix)

        return cls(
            id=server_id,
            transport=transport,
            url=(str(raw["url"]).strip() if raw.get("url") else None),
            command=(str(raw["command"]).strip() if raw.get("command") else None),
            args=[str(arg) for arg in args],
            env={str(k): str(v) for k, v in env.items()},
            enabled=bool(raw.get("enabled", True)),
            tool_prefix=bool(tool_prefix),
        )


def load_mcp_servers(
    config_path: Optional[str] = None,
    *,
    base_url_override: Optional[str] = None,
) -> List[MCPServerConfig]:
    """활성화된 MCP 서버 목록을 반환합니다."""
    config = load_app_config(config_path)
    mcp_config = config.get("mcp", {}) if isinstance(config, dict) else {}
    if not isinstance(mcp_config, dict):
        mcp_config = {}

    primary_url = (
        base_url_override
        or mcp_config.get("base_url")
        or os.getenv("MCP_BASE_URL")
        or DEFAULT_MCP_BASE_URL
    )

    servers: List[MCPServerConfig] = [
        MCPServerConfig(
            id="automation",
            transport="http",
            url=str(primary_url),
            tool_prefix=False,
        )
    ]

    extra_servers = mcp_config.get("extra_servers") or []
    if isinstance(extra_servers, list):
        for entry in extra_servers:
            try:
                servers.append(MCPServerConfig.from_dict(entry))
            except ValueError as exc:
                raise ValueError(f"MCP extra_servers 설정 오류: {exc}") from exc

    return [server for server in servers if server.enabled]


def load_extra_mcp_servers(
    config_path: Optional[str] = None,
) -> List[MCPServerConfig]:
    """기본 automation HTTP 서버를 제외한 추가 MCP 서버만 반환합니다."""
    return [server for server in load_mcp_servers(config_path) if server.id != "automation"]
