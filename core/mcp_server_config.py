"""
MCP 서버 설정 로더.

chatRTD는 기본 automation MCP(HTTP) 외에 OpenChrome 등 추가 MCP 서버를
병렬로 연결할 수 있습니다.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.llm_config import DEFAULT_MCP_BASE_URL, load_app_config

logger = logging.getLogger(__name__)

# stdio MCP 자식 프로세스에 부모 환경에서 전달할 OpenChrome/Chrome 관련 변수
STDIO_CHROME_ENV_KEYS = (
    "CHROME_PATH",
    "CHROME_HEADLESS_SHELL",
    "OPENCHROME_HOME",
    "OPENCHROME_API_KEYS_PATH",
    "OPENCHROME_MCP_CONFIG_PATHS",
    "OPENCHROME_CONTROLLER_LOCK_DIR",
    "OPENCHROME_VAULT_DIR",
    "OPENCHROME_HANDOFF_KEY_FILE",
    "OPENCHROME_FILE_UPLOAD_TEMP_DIR",
    "OPENCHROME_FILE_UPLOAD_ROOTS",
    "OPENCHROME_AUTO_ELECT",
)


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


def _openchrome_enabled_from_env() -> bool:
    return _is_truthy(os.getenv("MCP_OPENCHROME_ENABLED"))


def resolve_chrome_path() -> Optional[str]:
    """OpenChrome MCP가 사용할 Chrome 실행 파일 경로를 반환합니다."""
    env_path = (os.getenv("CHROME_PATH") or "").strip()
    if env_path and Path(env_path).is_file():
        return env_path

    candidates: List[str] = []
    if sys.platform == "win32":
        for env_key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = (os.getenv(env_key) or "").strip()
            if not base:
                continue
            candidates.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    elif sys.platform == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )
    else:
        candidates.extend(
            [
                "/usr/bin/google-chrome-stable",
                "/usr/bin/google-chrome",
                "/snap/bin/chromium",
                "/snap/bin/google-chrome",
            ]
        )
        for command in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium"):
            resolved = shutil.which(command)
            if resolved:
                candidates.append(resolved)

    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def build_openchrome_stdio_env(extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """OpenChrome stdio MCP에 전달할 환경 변수를 구성합니다."""
    env: Dict[str, str] = {}
    for key in STDIO_CHROME_ENV_KEYS:
        value = (os.getenv(key) or "").strip()
        if value:
            env[key] = value

    chrome_path = resolve_chrome_path()
    if chrome_path:
        env.setdefault("CHROME_PATH", chrome_path)

    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items() if str(v).strip()})
    return env


def _legacy_browser_mcp_enabled_from_env() -> bool:
    return _is_truthy(os.getenv("MCP_BROWSER_MCP_ENABLED")) or _is_truthy(
        os.getenv("MCP_CHROME_DEVTOOLS_ENABLED")
    )


def _openchrome_server_from_env() -> Optional[MCPServerConfig]:
    if not _openchrome_enabled_from_env():
        return None

    args = ["-y", "openchrome-mcp@latest", "serve", "--auto-launch"]

    openchrome_env = build_openchrome_stdio_env()

    if sys.platform == "win32":
        return MCPServerConfig(
            id="openchrome",
            transport="stdio",
            command="cmd",
            args=["/c", "npx", *args],
            env=openchrome_env,
            tool_prefix=True,
        )

    return MCPServerConfig(
        id="openchrome",
        transport="stdio",
        command="npx",
        args=args,
        env=openchrome_env,
        tool_prefix=True,
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

    openchrome_server = _openchrome_server_from_env()
    if openchrome_server and not any(server.id == openchrome_server.id for server in servers):
        servers.append(openchrome_server)
    elif _legacy_browser_mcp_enabled_from_env() and not openchrome_server:
        logger.warning(
            "MCP_BROWSER_MCP_ENABLED / MCP_CHROME_DEVTOOLS_ENABLED 는 제거되었습니다. "
            ".env 에 MCP_OPENCHROME_ENABLED=true 를 설정하세요."
        )

    return [_enrich_openchrome_server(server) for server in servers if server.enabled]


def _enrich_openchrome_server(server: MCPServerConfig) -> MCPServerConfig:
    if server.id != "openchrome":
        return server
    return MCPServerConfig(
        id=server.id,
        transport=server.transport,
        url=server.url,
        command=server.command,
        args=list(server.args),
        env=build_openchrome_stdio_env(server.env),
        enabled=server.enabled,
        tool_prefix=server.tool_prefix,
    )


def load_extra_mcp_servers(
    config_path: Optional[str] = None,
) -> List[MCPServerConfig]:
    """기본 automation HTTP 서버를 제외한 추가 MCP 서버만 반환합니다."""
    return [server for server in load_mcp_servers(config_path) if server.id != "automation"]
