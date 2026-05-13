"""
LLM 공통 설정 로더

config/app_config.yaml의 llm 설정을 우선 사용하고,
값이 비어 있거나 누락된 경우 환경변수 fallback을 적용합니다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

# .env 파일이 있으면 환경 변수로 로드합니다.
load_dotenv()


DEFAULT_LLM_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"
DEFAULT_MCP_BASE_URL = "http://localhost:8000/mcp"


def _resolve_config_path(config_path: Optional[str] = None) -> Optional[Path]:
    if config_path:
        explicit = Path(config_path)
        return explicit if explicit.exists() else None

    candidates = [
        Path(__file__).resolve().parent.parent / "config" / "app_config.yaml",
        Path("config/app_config.yaml"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def load_app_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """app_config.yaml 전체 설정을 로드합니다."""
    path = _resolve_config_path(config_path)
    if path is None:
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        # 설정 오류로 앱이 죽지 않게 빈 설정 반환
        return {}


def get_llm_settings(config_path: Optional[str] = None) -> Dict[str, str]:
    """
    공통 LLM 설정을 반환합니다.

    우선순위:
      1) app_config.yaml -> llm
      2) INTERNAL_LLM_* 환경변수
      3) OPENAI_* 환경변수
      4) 하드코딩 기본값
    """
    config = load_app_config(config_path)
    llm_config = config.get("llm", {}) if isinstance(config, dict) else {}

    base_url = (
        llm_config.get("base_url")
        or os.getenv("INTERNAL_LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or DEFAULT_LLM_BASE_URL
    )
    api_key = (
        llm_config.get("api_key")
        or os.getenv("INTERNAL_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )
    model = (
        llm_config.get("model")
        or os.getenv("INTERNAL_LLM_MODEL")
        or os.getenv("OPENAI_MODEL")
        or DEFAULT_LLM_MODEL
    )

    return {
        "base_url": str(base_url),
        "api_key": str(api_key),
        "model": str(model),
    }


def _normalize_mcp_url(url: Any) -> str:
    return str(url).strip()


def _collect_mcp_base_urls(
    primary_base_url: str,
    configured_base_urls: Any,
    env_base_urls: Optional[str],
    servers: Dict[str, str],
) -> List[str]:
    urls: List[str] = []

    def add_url(candidate: Any) -> None:
        normalized = _normalize_mcp_url(candidate)
        if normalized and normalized not in urls:
            urls.append(normalized)

    add_url(primary_base_url)

    if isinstance(configured_base_urls, list):
        for candidate in configured_base_urls:
            add_url(candidate)

    if env_base_urls:
        for candidate in env_base_urls.split(","):
            add_url(candidate)

    for candidate in servers.values():
        add_url(candidate)

    if not urls:
        add_url(DEFAULT_MCP_BASE_URL)
    return urls


def get_mcp_settings(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    공통 MCP 설정을 반환합니다.

    우선순위:
      1) app_config.yaml -> mcp
      2) MCP_BASE_URL 환경변수
      3) 하드코딩 기본값
    """
    config = load_app_config(config_path)
    mcp_config = config.get("mcp", {}) if isinstance(config, dict) else {}

    primary_base_url = (
        mcp_config.get("base_url")
        or os.getenv("MCP_BASE_URL")
        or DEFAULT_MCP_BASE_URL
    )
    configured_base_urls = mcp_config.get("base_urls", [])
    env_base_urls = os.getenv("MCP_BASE_URLS")

    raw_servers = mcp_config.get("servers", {})
    servers: Dict[str, str] = {}
    if isinstance(raw_servers, dict):
        for alias, url in raw_servers.items():
            alias_text = str(alias).strip()
            url_text = _normalize_mcp_url(url)
            if alias_text and url_text:
                servers[alias_text] = url_text

    base_urls = _collect_mcp_base_urls(
        primary_base_url=str(primary_base_url),
        configured_base_urls=configured_base_urls,
        env_base_urls=env_base_urls,
        servers=servers,
    )

    return {
        "base_url": base_urls[0],
        "base_urls": base_urls,
        "servers": servers,
    }


def get_automation_settings(config_path: Optional[str] = None) -> Dict[str, str]:
    """
    자동화 모드 설정을 반환합니다.
    """
    config = load_app_config(config_path)
    auto_config = config.get("automation", {}) if isinstance(config, dict) else {}
    mode = auto_config.get("mode", "semi")
    return {"mode": str(mode)}

