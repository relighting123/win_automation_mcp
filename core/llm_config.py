"""
LLM 공통 설정 로더

config/app_config.yaml의 llm 설정을 우선 사용하고,
값이 비어 있거나 누락된 경우 환경변수 fallback을 적용합니다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


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


def get_mcp_settings(config_path: Optional[str] = None) -> Dict[str, str]:
    """
    공통 MCP 설정을 반환합니다.

    우선순위:
      1) app_config.yaml -> mcp
      2) MCP_BASE_URL 환경변수
      3) 하드코딩 기본값
    """
    config = load_app_config(config_path)
    mcp_config = config.get("mcp", {}) if isinstance(config, dict) else {}

    base_url = (
        mcp_config.get("base_url")
        or os.getenv("MCP_BASE_URL")
        or DEFAULT_MCP_BASE_URL
    )

    return {"base_url": str(base_url)}

