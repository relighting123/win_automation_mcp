"""
Oracle DB 연결 설정 로더 (.env / 환경변수)

다중 DB는 .env 에 별칭별로 정의합니다.

    ORACLE_DEFAULT_DB=prod
    ORACLE_DB_PROD_USER=...
    ORACLE_DB_PROD_PASSWORD=...
    ORACLE_DB_PROD_TNS=...
    ORACLE_DB_DEV_USER=...
    ...

레거시 단일 설정(ORACLE_USER / ORACLE_PASSWORD / ORACLE_TNS)은 별칭 `default` 로 동작합니다.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

DEFAULT_ORACLE_MAX_ROWS = 1000
_DB_FIELD_RE = re.compile(
    r"^ORACLE_DB_([A-Z0-9_]+)_(USER|PASSWORD|TNS|TNS_ADMIN|MAX_ROWS)$",
    re.IGNORECASE,
)


def _shared_settings() -> Dict[str, Any]:
    max_rows_raw = os.getenv("ORACLE_MAX_ROWS", str(DEFAULT_ORACLE_MAX_ROWS))
    try:
        max_rows = max(1, min(int(max_rows_raw), 10_000))
    except ValueError:
        max_rows = DEFAULT_ORACLE_MAX_ROWS

    return {
        "tns_admin": (os.getenv("ORACLE_TNS_ADMIN") or "").strip(),
        "client_lib_dir": (os.getenv("ORACLE_CLIENT_LIB_DIR") or "").strip(),
        "max_rows": max_rows,
    }


def _merge_entry(alias: str, partial: Dict[str, Any], shared: Dict[str, Any]) -> Dict[str, Any]:
    max_rows = partial.get("max_rows")
    if max_rows is None:
        max_rows = shared["max_rows"]
    else:
        max_rows = max(1, min(int(max_rows), 10_000))

    return {
        "alias": alias,
        "user": (partial.get("user") or "").strip(),
        "password": partial.get("password") or "",
        "tns": (partial.get("tns") or "").strip(),
        "tns_admin": (partial.get("tns_admin") or shared["tns_admin"]).strip(),
        "client_lib_dir": shared["client_lib_dir"],
        "max_rows": max_rows,
    }


def load_oracle_databases() -> Dict[str, Dict[str, Any]]:
    """등록된 모든 Oracle DB 별칭과 접속 정보를 반환합니다."""
    shared = _shared_settings()
    raw: Dict[str, Dict[str, Any]] = {}

    # 레거시 단일 설정 → default
    legacy_user = (os.getenv("ORACLE_USER") or "").strip()
    if legacy_user:
        raw["default"] = {
            "user": legacy_user,
            "password": os.getenv("ORACLE_PASSWORD") or "",
            "tns": (os.getenv("ORACLE_TNS") or "").strip(),
        }

    # ORACLE_DB_{ALIAS}_{FIELD}
    for key, value in os.environ.items():
        match = _DB_FIELD_RE.match(key)
        if not match:
            continue
        alias = match.group(1).lower()
        field = match.group(2).upper()
        entry = raw.setdefault(alias, {})
        if field == "USER":
            entry["user"] = value.strip()
        elif field == "PASSWORD":
            entry["password"] = value
        elif field == "TNS":
            entry["tns"] = value.strip()
        elif field == "TNS_ADMIN":
            entry["tns_admin"] = value.strip()
        elif field == "MAX_ROWS":
            try:
                entry["max_rows"] = max(1, min(int(value), 10_000))
            except ValueError:
                pass

    return {
        alias: _merge_entry(alias, partial, shared)
        for alias, partial in raw.items()
        if partial.get("user") or partial.get("tns")
    }


def list_oracle_database_names() -> List[str]:
    return sorted(load_oracle_databases().keys())


def get_default_oracle_db() -> str:
    configured = (os.getenv("ORACLE_DEFAULT_DB") or "").strip().lower()
    names = list_oracle_database_names()
    if not names:
        return configured or "default"
    if configured and configured in names:
        return configured
    if "default" in names:
        return "default"
    return names[0]


def get_oracle_settings(db: Optional[str] = None) -> Dict[str, Any]:
    """지정 별칭(또는 기본 별칭)의 Oracle 접속 정보를 반환합니다."""
    databases = load_oracle_databases()
    if not databases:
        shared = _shared_settings()
        return {
            "alias": "",
            "user": "",
            "password": "",
            "tns": "",
            "tns_admin": shared["tns_admin"],
            "client_lib_dir": shared["client_lib_dir"],
            "max_rows": shared["max_rows"],
        }

    alias = (db or get_default_oracle_db()).strip().lower()
    if alias not in databases:
        available = ", ".join(list_oracle_database_names())
        raise ValueError(f"Oracle DB '{alias}' 를 찾을 수 없습니다. 사용 가능: {available}")

    return databases[alias]


def oracle_config_ready(db: Optional[str] = None) -> bool:
    try:
        cfg = get_oracle_settings(db)
    except ValueError:
        return False
    return bool(cfg["user"] and cfg["password"] and cfg["tns"])
