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
from dotenv import load_dotenv

# .env 파일이 있으면 환경 변수로 로드합니다.
load_dotenv()


DEFAULT_LLM_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"
DEFAULT_LLM_PROVIDER = "openai_compatible"
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


def _resolve_profile_config(llm_config: Dict[str, Any], profile: str) -> Dict[str, Any]:
    """기본 llm 설정 + profile override를 병합합니다."""
    profile_key = (profile or "default").strip().lower()
    profile_map = llm_config.get("profiles", {})
    profile_config = {}
    if isinstance(profile_map, dict):
        profile_config = profile_map.get(profile_key, {}) or {}

    base_config = {
        k: v
        for k, v in llm_config.items()
        if k != "profiles"
    }
    if isinstance(profile_config, dict):
        base_config.update(profile_config)
    return base_config


def get_llm_profile_settings(profile: str = "default", config_path: Optional[str] = None) -> Dict[str, str]:
    """
    profile별 LLM 설정을 반환합니다.

    기본 profile 목록:
      - default: 공통 기본 모델
      - execution: 단순 도구 실행/파라미터 추출
      - planning: 계획 수립
      - analysis: 상황/데이터 분석
      - reporting: 최종 보고 생성
    """
    config = load_app_config(config_path)
    raw_llm_config = config.get("llm", {}) if isinstance(config, dict) else {}
    llm_config = raw_llm_config if isinstance(raw_llm_config, dict) else {}
    merged = _resolve_profile_config(llm_config, profile)

    provider = (
        merged.get("provider")
        or os.getenv("INTERNAL_LLM_PROVIDER")
        or os.getenv("OPENAI_PROVIDER")
        or DEFAULT_LLM_PROVIDER
    )
    base_url = (
        merged.get("base_url")
        or os.getenv("INTERNAL_LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or DEFAULT_LLM_BASE_URL
    )
    api_key = (
        merged.get("api_key")
        or os.getenv("INTERNAL_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )
    model = (
        merged.get("model")
        or os.getenv("INTERNAL_LLM_MODEL")
        or os.getenv("OPENAI_MODEL")
        or DEFAULT_LLM_MODEL
    )

    return {
        "provider": str(provider),
        "base_url": str(base_url),
        "api_key": str(api_key),
        "model": str(model),
    }


def get_llm_settings(config_path: Optional[str] = None) -> Dict[str, str]:
    """기본(default profile) LLM 설정을 반환합니다."""
    return get_llm_profile_settings(profile="default", config_path=config_path)


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


def get_automation_settings(config_path: Optional[str] = None) -> Dict[str, str]:
    """
    자동화 모드 설정을 반환합니다.

    우선순위: load_app_config → AppSession 싱글톤 config (이미 로드된 경우)
    """
    config = load_app_config(config_path)
    auto_config = config.get("automation", {}) if isinstance(config, dict) else {}

    if not auto_config:
        try:
            from core.app_session import AppSession

            session_config = AppSession.get_instance().config or {}
            if isinstance(session_config, dict):
                auto_config = session_config.get("automation", {}) or {}
        except Exception:
            pass

    raw_mode = auto_config.get("mode", "semi") if isinstance(auto_config, dict) else "semi"
    mode = str(raw_mode).strip().lower()
    if mode not in {"auto", "semi", "manual"}:
        mode = "semi"
    return {"mode": mode}

