"""
Oracle DB 조회 도구 (SELECT 전용)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from core.oracle_config import (
    get_oracle_settings,
    list_oracle_database_names,
    oracle_config_ready,
)

logger = logging.getLogger(__name__)

_READ_ONLY_PREFIXES = frozenset({"SELECT", "WITH", "SHOW", "DESC", "DESCRIBE", "EXPLAIN"})


def _strip_sql_comments(sql: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", no_block)


def _validate_read_only_sql(sql: str) -> Optional[str]:
    cleaned = _strip_sql_comments(sql).strip().rstrip(";")
    if not cleaned:
        return "SQL이 비어 있습니다."
    first = cleaned.split()[0].upper()
    if first not in _READ_ONLY_PREFIXES:
        return "조회(SELECT/WITH) 쿼리만 실행할 수 있습니다."
    forbidden = re.search(
        r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if forbidden:
        return f"허용되지 않는 SQL 구문입니다: {forbidden.group(0)}"
    return None


def _connect(db: Optional[str] = None):
    import oracledb

    cfg = get_oracle_settings(db)
    if cfg["tns_admin"]:
        os.environ["TNS_ADMIN"] = cfg["tns_admin"]
    if cfg["client_lib_dir"]:
        oracledb.init_oracle_client(lib_dir=cfg["client_lib_dir"])

    return oracledb.connect(
        user=cfg["user"],
        password=cfg["password"],
        dsn=cfg["tns"],
    )


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


async def query_oracle_db(
    sql: str,
    db: Optional[str] = None,
    max_rows: Optional[int] = None,
    bind_params: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Oracle DB에서 SELECT 쿼리를 실행하고 결과를 반환합니다.
    접속 정보는 config/oracle_databases.yaml 또는 .env 의 ORACLE_DB_{별칭}_* 를 사용합니다.

    Args:
        sql: 실행할 SELECT (또는 WITH) 쿼리
        db: DB 별칭 (예: prod, dev). 생략 시 ORACLE_DEFAULT_DB 또는 default 사용
        max_rows: 최대 반환 행 수 (기본: ORACLE_MAX_ROWS 환경변수)
        bind_params: 바인드 파라미터 dict (예: {"dept_id": 10})
    """
    try:
        if not list_oracle_database_names():
            return json.dumps(
                {
                    "success": False,
                    "message": (
                        "config/oracle_databases.yaml (권장) 또는 "
                        ".env 의 ORACLE_DB_{별칭}_USER/PASSWORD/TNS 를 설정하세요. "
                        "예: alias=prd, user/password/host/service_name"
                    ),
                },
                ensure_ascii=False,
            )

        if not oracle_config_ready(db):
            alias = (db or "").strip().lower() or "(default)"
            available = ", ".join(list_oracle_database_names())
            return json.dumps(
                {
                    "success": False,
                    "message": (
                        f"Oracle DB '{alias}' 접속 정보가 불완전합니다. "
                        f"사용 가능한 별칭: {available}"
                    ),
                },
                ensure_ascii=False,
            )

        try:
            import oracledb  # noqa: F401
        except ImportError:
            return json.dumps(
                {
                    "success": False,
                    "message": "oracledb 패키지가 설치되어 있지 않습니다. pip install oracledb",
                },
                ensure_ascii=False,
            )

        sql_err = _validate_read_only_sql(sql)
        if sql_err:
            return json.dumps({"success": False, "message": sql_err}, ensure_ascii=False)

        try:
            cfg = get_oracle_settings(db)
        except ValueError as exc:
            return json.dumps({"success": False, "message": str(exc)}, ensure_ascii=False)

        row_limit = max_rows if max_rows is not None else cfg["max_rows"]
        row_limit = max(1, min(int(row_limit), 10_000))

        conn = _connect(db)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, bind_params or {})
                columns = [str(col[0]) for col in (cur.description or [])]
                fetched = cur.fetchmany(row_limit + 1)
                truncated = len(fetched) > row_limit
                if truncated:
                    fetched = fetched[:row_limit]

                rows: List[Dict[str, Any]] = []
                for row in fetched:
                    rows.append(
                        {
                            col: _serialize_value(val)
                            for col, val in zip(columns, row)
                        }
                    )
        finally:
            conn.close()

        return json.dumps(
            {
                "success": True,
                "db": cfg["alias"],
                "message": f"[{cfg['alias']}] {len(rows)}건 조회 완료"
                + (" (일부 생략)" if truncated else ""),
                "row_count": len(rows),
                "truncated": truncated,
                "columns": columns,
                "rows": rows,
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as exc:
        logger.exception("query_oracle_db 실패")
        return json.dumps(
            {"success": False, "message": f"Oracle 조회 중 오류: {exc}"},
            ensure_ascii=False,
        )


def register_oracle_db_tools(mcp: Any) -> None:
    """Oracle DB 조회 도구 등록."""
    mcp.tool()(query_oracle_db)
    logger.info("Oracle DB 도구 등록 완료: query_oracle_db")
