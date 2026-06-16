"""Oracle DB 설정 로더 테스트."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from core import oracle_config


def _write_yaml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "oracle_databases.yaml"
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def test_load_yaml_databases_with_alias_and_host(tmp_path, monkeypatch):
    config_path = _write_yaml(
        tmp_path,
        """
        default_db: prd
        tns_admin: C:/oracle/admin
        max_rows: 500
        databases:
          - alias: prd
            user: prod_user
            password: secret
            host: db-prod.example.com
            port: 1521
            service_name: ORCL_PROD
          - alias: dev
            user: dev_user
            pw: dev_secret
            host: db-dev.example.com
            service_name: ORCL_DEV
        """,
    )

    monkeypatch.setattr(oracle_config, "_resolve_oracle_config_path", lambda _=None: config_path)
    databases = oracle_config.load_oracle_databases()

    assert set(databases) == {"prd", "dev"}
    assert databases["prd"]["alias"] == "prd"
    assert databases["prd"]["user"] == "prod_user"
    assert databases["prd"]["password"] == "secret"
    assert databases["prd"]["tns"] == "db-prod.example.com:1521/ORCL_PROD"
    assert databases["prd"]["tns_admin"] == "C:/oracle/admin"
    assert databases["prd"]["max_rows"] == 500
    assert databases["dev"]["password"] == "dev_secret"
    assert databases["dev"]["tns"] == "db-dev.example.com:1521/ORCL_DEV"


def test_yaml_takes_priority_over_env(tmp_path, monkeypatch):
    config_path = _write_yaml(
        tmp_path,
        """
        default_db: prd
        databases:
          - alias: prd
            user: yaml_user
            password: yaml_pw
            tns: YAML_TNS
        """,
    )
    monkeypatch.setenv("ORACLE_DB_PROD_USER", "env_user")
    monkeypatch.setenv("ORACLE_DB_PROD_PASSWORD", "env_pw")
    monkeypatch.setenv("ORACLE_DB_PROD_TNS", "ENV_TNS")
    monkeypatch.setattr(oracle_config, "_resolve_oracle_config_path", lambda _=None: config_path)

    databases = oracle_config.load_oracle_databases()
    assert databases["prd"]["user"] == "yaml_user"
    assert databases["prd"]["tns"] == "YAML_TNS"


def test_env_fallback_when_no_yaml(monkeypatch):
    monkeypatch.setattr(oracle_config, "_resolve_oracle_config_path", lambda _=None: None)
    monkeypatch.setenv("ORACLE_DB_PRD_USER", "env_user")
    monkeypatch.setenv("ORACLE_DB_PRD_PASSWORD", "env_pw")
    monkeypatch.setenv("ORACLE_DB_PRD_TNS", "ENV_TNS")

    databases = oracle_config.load_oracle_databases()
    assert databases["prd"]["user"] == "env_user"
    assert databases["prd"]["tns"] == "ENV_TNS"


def test_get_default_oracle_db_from_yaml(tmp_path, monkeypatch):
    config_path = _write_yaml(
        tmp_path,
        """
        default_db: prd
        databases:
          - alias: prd
            user: u
            password: p
            host: h
            service_name: s
          - alias: dev
            user: u2
            password: p2
            host: h2
            service_name: s2
        """,
    )
    monkeypatch.setattr(oracle_config, "_resolve_oracle_config_path", lambda _=None: config_path)
    assert oracle_config.get_default_oracle_db() == "prd"


def test_get_oracle_settings_unknown_alias(tmp_path, monkeypatch):
    config_path = _write_yaml(
        tmp_path,
        """
        databases:
          - alias: prd
            user: u
            password: p
            host: h
            service_name: s
        """,
    )
    monkeypatch.setattr(oracle_config, "_resolve_oracle_config_path", lambda _=None: config_path)

    with pytest.raises(ValueError, match="Oracle DB 'missing'"):
        oracle_config.get_oracle_settings("missing")
