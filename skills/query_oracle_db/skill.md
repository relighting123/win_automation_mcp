# Query Oracle DB

Oracle DB에서 **조회(SELECT/WITH)** 쿼리를 실행하고 결과를 JSON으로 반환합니다.

## 사전 설정

### 권장: `config/oracle_databases.yaml`

`config/oracle_databases.yaml.example` 을 복사한 뒤 값을 채웁니다.

```yaml
default_db: prd

tns_admin: C:\oracle\network\admin
client_lib_dir:
max_rows: 1000

databases:
  - alias: prd
    user: prod_user
    password: secret
    host: db-prod.example.com
    port: 1521
    service_name: ORCL_PROD

  - alias: dev
    user: dev_user
    password: secret
    host: db-dev.example.com
    port: 1521
    service_name: ORCL_DEV
```

각 DB 항목 **상단에 `alias`** 를 두고, 아래에 `user`, `password`(또는 `pw`), `host`, `port`, `service_name` 등을 정의합니다.

- `tns` 필드를 쓰면 TNS alias 또는 Easy Connect 문자열을 직접 지정할 수 있습니다.
- `host` + `service_name` 조합이면 `host:port/service_name` 형태로 자동 조합됩니다.

### 레거시: `.env` (YAML 없을 때)

```env
ORACLE_DEFAULT_DB=prd
ORACLE_DB_PRD_USER=prod_user
ORACLE_DB_PRD_PASSWORD=secret
ORACLE_DB_PRD_TNS=ORCL_PROD
```

레거시 단일 설정도 지원합니다 (`default` 별칭).

```env
ORACLE_USER=your_user
ORACLE_PASSWORD=your_password
ORACLE_TNS=ORCL
```

## 실행 규칙

1. `db` 인자로 접속할 별칭을 지정합니다 (예: `prd`, `dev`). 생략 시 `default_db` 사용.
2. `sql` 인자에 실행할 SELECT 또는 WITH 쿼리를 지정합니다.
3. 바인드 변수가 필요하면 `bind_params`에 dict 형태로 전달합니다.
4. INSERT/UPDATE/DELETE 등 변경 쿼리는 실행되지 않습니다.

## 예시

- dev DB에서 직원 조회
  - db: `dev`
  - sql: `SELECT * FROM employees WHERE department_id = :dept_id`
  - bind_params: `{"dept_id": 10}`
