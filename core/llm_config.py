"""
LLM 공통 설정 로더 (Dual-LLM 지원)

본 모듈은 두 종류의 LLM을 분리해서 관리합니다.

- reasoning LLM: 계획 수립, 상황 분석, 클립보드/리포트 분석 등 사고력 중심 작업.
  주로 외부 LLM (Groq, OpenAI 호환 API)을 사용합니다.
- task LLM: 파라미터 추출, 스킬 ID 매핑 같이 입력→구조화 출력에 가까운 단순 작업.
  로컬에서 서빙되는 Gemma (또는 파인튜닝된 Gemma) 같은 경량 LLM을 사용하는 것을 권장합니다.

설정 우선순위(role = reasoning/task):
  1) app_config.yaml -> llm.<role>          (신규 dual 설정)
  2) app_config.yaml -> llm                  (legacy single 설정, 양쪽 LLM에 동일 적용)
  3) <ROLE>_LLM_* 환경변수 (예: TASK_LLM_BASE_URL)
  4) INTERNAL_LLM_* 환경변수
  5) OPENAI_* 환경변수
  6) 하드코딩 기본값
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()


DEFAULT_LLM_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"
DEFAULT_MCP_BASE_URL = "http://localhost:8000/mcp"

# Gemma 로컬 서빙 기본값 (vLLM / Ollama 의 OpenAI 호환 엔드포인트 가정)
DEFAULT_TASK_LLM_BASE_URL = "http://localhost:8001/v1"
DEFAULT_TASK_LLM_MODEL = "google/gemma-3-4b-it"
DEFAULT_TASK_LLM_PROVIDER = "gemma"

# reasoning role 의 기본 provider
DEFAULT_REASONING_LLM_PROVIDER = "openai"


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
        return {}


def _coalesce(*values: Any) -> Optional[str]:
    """첫 번째 truthy 한 값을 문자열로 반환합니다."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return str(value)
    return None


def get_llm_settings(config_path: Optional[str] = None) -> Dict[str, str]:
    """
    기존 코드 호환을 위한 단일 LLM 설정 (= reasoning LLM 과 동일).

    내부적으로는 `get_role_llm_settings("reasoning")` 결과의 핵심 필드만 노출합니다.
    """
    settings = get_role_llm_settings("reasoning", config_path)
    return {
        "base_url": settings["base_url"],
        "api_key": settings["api_key"],
        "model": settings["model"],
    }


def get_role_llm_settings(role: str, config_path: Optional[str] = None) -> Dict[str, str]:
    """
    역할(role) 별 LLM 설정을 반환합니다.

    role: "reasoning" | "task"
    반환 dict:
        - base_url
        - api_key
        - model
        - provider: "openai" | "gemma" | 그 외 호환 식별자
        - structured_output_method: "function_calling" | "json_mode" | "json_schema"
        - temperature: float (문자열로 반환)
    """
    role = (role or "").lower().strip() or "reasoning"
    if role not in {"reasoning", "task"}:
        raise ValueError(f"Unknown LLM role: {role}")

    config = load_app_config(config_path)
    llm_root = config.get("llm", {}) if isinstance(config, dict) else {}
    role_cfg = llm_root.get(role, {}) if isinstance(llm_root, dict) else {}
    if not isinstance(role_cfg, dict):
        role_cfg = {}

    # legacy 단일 설정은 role 키가 아닌 llm 루트 자체를 사용
    legacy_cfg = {
        k: v for k, v in (llm_root or {}).items() if k not in {"reasoning", "task"}
    }

    role_env_prefix = "TASK_LLM" if role == "task" else "REASONING_LLM"

    role_default_provider = (
        DEFAULT_TASK_LLM_PROVIDER if role == "task" else DEFAULT_REASONING_LLM_PROVIDER
    )
    role_default_base_url = (
        DEFAULT_TASK_LLM_BASE_URL if role == "task" else DEFAULT_LLM_BASE_URL
    )
    role_default_model = (
        DEFAULT_TASK_LLM_MODEL if role == "task" else DEFAULT_LLM_MODEL
    )

    base_url = _coalesce(
        role_cfg.get("base_url"),
        legacy_cfg.get("base_url"),
        os.getenv(f"{role_env_prefix}_BASE_URL"),
        os.getenv("INTERNAL_LLM_BASE_URL"),
        os.getenv("OPENAI_BASE_URL"),
        role_default_base_url,
    )
    api_key = _coalesce(
        role_cfg.get("api_key"),
        legacy_cfg.get("api_key"),
        os.getenv(f"{role_env_prefix}_API_KEY"),
        os.getenv("INTERNAL_LLM_API_KEY"),
        os.getenv("OPENAI_API_KEY"),
    ) or ""
    model = _coalesce(
        role_cfg.get("model"),
        legacy_cfg.get("model"),
        os.getenv(f"{role_env_prefix}_MODEL"),
        os.getenv("INTERNAL_LLM_MODEL"),
        os.getenv("OPENAI_MODEL"),
        role_default_model,
    )
    provider = _coalesce(
        role_cfg.get("provider"),
        legacy_cfg.get("provider"),
        os.getenv(f"{role_env_prefix}_PROVIDER"),
        role_default_provider,
    ).lower()

    # Gemma 는 OpenAI 호환 function calling 을 잘 지원하지 않으므로 json_mode 를 기본값으로 둡니다.
    default_struct_method = "json_mode" if provider == "gemma" else "function_calling"
    structured_output_method = _coalesce(
        role_cfg.get("structured_output_method"),
        legacy_cfg.get("structured_output_method"),
        os.getenv(f"{role_env_prefix}_STRUCTURED_OUTPUT_METHOD"),
        default_struct_method,
    )

    temperature = _coalesce(
        role_cfg.get("temperature"),
        legacy_cfg.get("temperature"),
        os.getenv(f"{role_env_prefix}_TEMPERATURE"),
        "0",
    )

    return {
        "base_url": str(base_url),
        "api_key": str(api_key),
        "model": str(model),
        "provider": str(provider),
        "structured_output_method": str(structured_output_method),
        "temperature": str(temperature),
    }


def get_dual_llm_settings(config_path: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """reasoning / task 양쪽 설정을 한 번에 반환합니다."""
    return {
        "reasoning": get_role_llm_settings("reasoning", config_path),
        "task": get_role_llm_settings("task", config_path),
    }


def get_mcp_settings(config_path: Optional[str] = None) -> Dict[str, str]:
    """공통 MCP 설정을 반환합니다."""
    config = load_app_config(config_path)
    mcp_config = config.get("mcp", {}) if isinstance(config, dict) else {}

    base_url = (
        mcp_config.get("base_url")
        or os.getenv("MCP_BASE_URL")
        or DEFAULT_MCP_BASE_URL
    )

    return {"base_url": str(base_url)}


def get_automation_settings(config_path: Optional[str] = None) -> Dict[str, str]:
    """자동화 모드 설정을 반환합니다."""
    config = load_app_config(config_path)
    auto_config = config.get("automation", {}) if isinstance(config, dict) else {}
    mode = auto_config.get("mode", "semi")
    return {"mode": str(mode)}
