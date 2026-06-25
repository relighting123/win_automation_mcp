"""HTTP API 접근 설정 로더 (app_config.yaml / 환경변수)."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from core.llm_config import load_app_config

DEFAULT_API_TIMEOUT = 30.0
DEFAULT_MAX_RESPONSE_CHARS = 200_000
DEFAULT_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_ENV_VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env_vars(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        return os.getenv(match.group(1), "")

    return _ENV_VAR_RE.sub(_replace, value)


def _expand_headers(headers: Dict[str, Any]) -> Dict[str, str]:
    expanded: Dict[str, str] = {}
    for key, raw in headers.items():
        if raw is None:
            continue
        text = _expand_env_vars(str(raw).strip())
        if text:
            expanded[str(key)] = text
    return expanded


def get_api_access_settings(config_path: Optional[str] = None) -> Dict[str, Any]:
    """api_access 설정을 반환합니다."""
    config = load_app_config(config_path)
    api_access = config.get("api_access", {}) if isinstance(config, dict) else {}

    if not api_access:
        try:
            from core.app_session import AppSession

            session_config = AppSession.get_instance().config or {}
            if isinstance(session_config, dict):
                api_access = session_config.get("api_access", {}) or {}
        except Exception:
            pass

    if not isinstance(api_access, dict):
        api_access = {}

    raw_hosts = api_access.get("allowed_hosts", [])
    allowed_hosts: List[str] = []
    if isinstance(raw_hosts, list):
        allowed_hosts = [str(host).strip().lower() for host in raw_hosts if str(host).strip()]

    raw_methods = api_access.get("allowed_methods", list(DEFAULT_ALLOWED_METHODS))
    allowed_methods: List[str] = []
    if isinstance(raw_methods, list) and raw_methods:
        allowed_methods = [str(method).strip().upper() for method in raw_methods if str(method).strip()]
    else:
        allowed_methods = sorted(DEFAULT_ALLOWED_METHODS)

    timeout_raw = api_access.get("default_timeout", DEFAULT_API_TIMEOUT)
    try:
        default_timeout = max(1.0, min(float(timeout_raw), 300.0))
    except (TypeError, ValueError):
        default_timeout = DEFAULT_API_TIMEOUT

    max_chars_raw = api_access.get("max_response_chars", DEFAULT_MAX_RESPONSE_CHARS)
    try:
        max_response_chars = max(1_000, min(int(max_chars_raw), 2_000_000))
    except (TypeError, ValueError):
        max_response_chars = DEFAULT_MAX_RESPONSE_CHARS

    profiles: Dict[str, Dict[str, Any]] = {}
    raw_profiles = api_access.get("apis", [])
    if isinstance(raw_profiles, list):
        for entry in raw_profiles:
            if not isinstance(entry, dict):
                continue
            alias = str(entry.get("alias") or "").strip().lower()
            base_url = str(entry.get("base_url") or "").strip()
            if not alias or not base_url:
                continue
            headers = entry.get("headers", {})
            profiles[alias] = {
                "alias": alias,
                "base_url": base_url.rstrip("/") + "/",
                "headers": headers if isinstance(headers, dict) else {},
            }

    return {
        "enabled": bool(api_access.get("enabled", False)),
        "default_timeout": default_timeout,
        "max_response_chars": max_response_chars,
        "allowed_hosts": allowed_hosts,
        "allowed_methods": allowed_methods,
        "profiles": profiles,
    }


def list_api_profile_names(config_path: Optional[str] = None) -> List[str]:
    settings = get_api_access_settings(config_path)
    return sorted(settings.get("profiles", {}).keys())


def get_api_profile(alias: Optional[str], config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not alias or not str(alias).strip():
        return None
    key = str(alias).strip().lower()
    settings = get_api_access_settings(config_path)
    profile = settings.get("profiles", {}).get(key)
    if not profile:
        return None
    return {
        "alias": profile["alias"],
        "base_url": profile["base_url"],
        "headers": _expand_headers(profile.get("headers", {})),
    }


def _normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def _host_matches_pattern(host: str, pattern: str) -> bool:
    host = _normalize_host(host)
    pattern = _normalize_host(pattern)
    if not host or not pattern:
        return False
    if pattern == host:
        return True
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return host == suffix or host.endswith("." + suffix)
    return False


def is_host_allowed(host: str, *, config_path: Optional[str] = None) -> bool:
    settings = get_api_access_settings(config_path)
    allowed_hosts = settings.get("allowed_hosts", [])
    if not allowed_hosts:
        return False
    normalized = _normalize_host(host)
    return any(_host_matches_pattern(normalized, pattern) for pattern in allowed_hosts)


def validate_http_method(method: str, *, config_path: Optional[str] = None) -> Optional[str]:
    normalized = (method or "").strip().upper()
    if not normalized:
        return "HTTP method가 비어 있습니다."
    settings = get_api_access_settings(config_path)
    allowed = {m.upper() for m in settings.get("allowed_methods", [])}
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        return f"허용되지 않은 HTTP method입니다: {normalized} (허용: {allowed_text})"
    return None


def build_request_target(
    url: str,
    *,
    api_alias: Optional[str] = None,
    config_path: Optional[str] = None,
) -> tuple[str, Dict[str, str], Optional[str]]:
    """
    최종 요청 URL과 프로필 기본 헤더를 반환합니다.

    Returns:
        (final_url, profile_headers, error_message)
    """
    if not url or not str(url).strip():
        return "", {}, "url은 비어 있을 수 없습니다."

    raw_url = str(url).strip()
    profile = get_api_profile(api_alias, config_path=config_path)
    profile_headers: Dict[str, str] = profile.get("headers", {}) if profile else {}

    if profile:
        final_url = urljoin(profile["base_url"], raw_url.lstrip("/"))
    else:
        final_url = raw_url

    parsed = urlparse(final_url)
    if parsed.scheme not in {"http", "https"}:
        return "", profile_headers, "http 또는 https URL만 호출할 수 있습니다."

    if not parsed.netloc:
        return "", profile_headers, f"유효하지 않은 URL입니다: {final_url}"

    settings = get_api_access_settings(config_path)
    if not settings.get("enabled", False):
        return (
            "",
            profile_headers,
            "api_access.enabled=true 및 api_access.allowed_hosts 설정이 필요합니다.",
        )

    if not is_host_allowed(parsed.hostname or "", config_path=config_path):
        allowed_text = ", ".join(settings.get("allowed_hosts", [])) or "(없음)"
        return (
            "",
            profile_headers,
            f"허용되지 않은 호스트입니다: {parsed.hostname} (허용 호스트: {allowed_text})",
        )

    if api_alias and not profile:
        available = ", ".join(list_api_profile_names(config_path=config_path)) or "(없음)"
        return (
            "",
            profile_headers,
            f"알 수 없는 API 프로필입니다: {api_alias} (사용 가능: {available})",
        )

    return final_url, profile_headers, None
