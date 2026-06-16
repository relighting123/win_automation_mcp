"""
Oracle DB 연결 설정 로더 (YAML / .env / 환경변수)

권장: config/oracle_databases.yaml

    default_db: prd
    databases:
      - alias: prd
        user: ...
        password: ...
        host: ...
        port: 1521
        service_name: ...

레거시 .env 다중 DB:

    ORACLE_DEFAULT_DB=prod
    ORACLE_DB_PROD_USER=...
    ORACLE_DB_PROD_PASSWORD=...
    ORACLE_DB_PROD_TNS=...

레거시 단일 설정(ORACLE_USER / ORACLE_PASSWORD / ORACLE_TNS)은 별칭 `default` 로 동작합니다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

DEFAULT_ORACLE_MAX_ROWS = 1000
_DB_FIELD_RE = re.compile(
    r"^ORACLE_DB_([A-Z0-9_]+)_(USER|PASSWORD|TNS|TNS_ADMIN|MAX_ROWS)$",
    re.IGNORECASE,
)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_oracle_config_path(config_path: Optional[str] = None) -> Optional[Path]:
    if config_path:
        explicit = Path(config_path)
        return explicit if explicit.exists() else None

    candidates = [
        _PROJECT_ROOT / "config" / "oracle_databases.yaml",
        Path("config/oracle_databases.yaml"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _shared_settings(yaml_shared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    yaml_shared = yaml_shared or {}
    max_rows_raw = (
        yaml_shared.get("max_rows")
        or os.getenv("ORACLE_MAX_ROWS")
        or str(DEFAULT_ORACLE_MAX_ROWS)
    )
    try:
        max_rows = max(1, min(int(max_rows_raw), 10_000))
    except (TypeError, ValueError):
        max_rows = DEFAULT_ORACLE_MAX_ROWS

    return {
        "tns_admin": (
            str(yaml_shared.get("tns_admin") or os.getenv("ORACLE_TNS_ADMIN") or "")
        ).strip(),
        "client_lib_dir": (
            str(yaml_shared.get("client_lib_dir") or os.getenv("ORACLE_CLIENT_LIB_DIR") or "")
        ).strip(),
        "max_rows": max_rows,
        "default_db": (
            str(yaml_shared.get("default_db") or os.getenv("ORACLE_DEFAULT_DB") or "")
        ).strip().lower(),
    }


def _pick_str(data: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _build_dsn(entry: Dict[str, Any]) -> str:
    tns = _pick_str(entry, "tns", "dsn")
    if tns:
        return tns

    host = _pick_str(entry, "host")
    if not host:
        return ""

    port_raw = entry.get("port", 1521)
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 1521

    service_name = _pick_str(entry, "service_name", "service")
    sid = _pick_str(entry, "sid")
    if service_name:
        return f"{host}:{port}/{service_name}"
    if sid:
        return f"{host}:{port}/{sid}"
    return f"{host}:{port}"


def _merge_entry(alias: str, partial: Dict[str, Any], shared: Dict[str, Any]) -> Dict[str, Any]:
    max_rows = partial.get("max_rows")
    if max_rows is None:
        max_rows = shared["max_rows"]
    else:
        try:
            max_rows = max(1, min(int(max_rows), 10_000))
        except (TypeError, ValueError):
            max_rows = shared["max_rows"]

    password = partial.get("password")
    if password is None:
        password = partial.get("pw", "")

    return {
        "alias": alias,
        "user": _pick_str(partial, "user"),
        "password": password if password is not None else "",
        "tns": _build_dsn(partial),
        "tns_admin": (_pick_str(partial, "tns_admin") or shared["tns_admin"]).strip(),
        "client_lib_dir": shared["client_lib_dir"],
        "max_rows": max_rows,
    }


def _load_oracle_databases_from_yaml(config_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    path = _resolve_oracle_config_path(config_path)
    if path is None:
        return {}

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    shared = _shared_settings(data)
    raw: Dict[str, Dict[str, Any]] = {}
    entries = data.get("databases") or data.get("db") or []
    if not isinstance(entries, list):
        return {}

    for item in entries:
        if not isinstance(item, dict):
            continue
        alias = _pick_str(item, "alias", "name", "id").lower()
        if not alias:
            continue
        raw[alias] = dict(item)

    return {
        alias: _merge_entry(alias, partial, shared)
        for alias, partial in raw.items()
        if partial.get("user") or _pick_str(partial, "tns", "dsn", "host")
    }


def _load_oracle_databases_from_env() -> Dict[str, Dict[str, Any]]:
    shared = _shared_settings()
    raw: Dict[str, Dict[str, Any]] = {}

    legacy_user = (os.getenv("ORACLE_USER") or "").strip()
    if legacy_user:
        raw["default"] = {
            "user": legacy_user,
            "password": os.getenv("ORACLE_PASSWORD") or "",
            "tns": (os.getenv("ORACLE_TNS") or "").strip(),
        }

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


def load_oracle_databases(config_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """등록된 모든 Oracle DB 별칭과 접속 정보를 반환합니다."""
    yaml_dbs = _load_oracle_databases_from_yaml(config_path)
    if yaml_dbs:
        return yaml_dbs
    return _load_oracle_databases_from_env()


def list_oracle_database_names(config_path: Optional[str] = None) -> List[str]:
    return sorted(load_oracle_databases(config_path).keys())


def get_default_oracle_db(config_path: Optional[str] = None) -> str:
    yaml_path = _resolve_oracle_config_path(config_path)
    configured = ""
    if yaml_path is not None:
        try:
            with open(yaml_path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            if isinstance(data, dict):
                configured = str(data.get("default_db") or "").strip().lower()
        except Exception:
            pass
    if not configured:
        configured = (os.getenv("ORACLE_DEFAULT_DB") or "").strip().lower()

    names = list_oracle_database_names(config_path)
    if not names:
        return configured or "default"
    if configured and configured in names:
        return configured
    if "default" in names:
        return "default"
    return names[0]


def get_oracle_settings(db: Optional[str] = None, config_path: Optional[str] = None) -> Dict[str, Any]:
    """지정 별칭(또는 기본 별칭)의 Oracle 접속 정보를 반환합니다."""
    databases = load_oracle_databases(config_path)
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

    alias = (db or get_default_oracle_db(config_path)).strip().lower()
    if alias not in databases:
        available = ", ".join(list_oracle_database_names(config_path))
        raise ValueError(f"Oracle DB '{alias}' 를 찾을 수 없습니다. 사용 가능: {available}")

    return databases[alias]


def oracle_config_ready(db: Optional[str] = None, config_path: Optional[str] = None) -> bool:
    try:
        cfg = get_oracle_settings(db, config_path)
    except ValueError:
        return False
    return bool(cfg["user"] and cfg["password"] and cfg["tns"])
