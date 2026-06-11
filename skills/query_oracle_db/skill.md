# Query Oracle DB

Oracle DB에서 **조회(SELECT/WITH)** 쿼리를 실행하고 결과를 JSON으로 반환합니다.

## 사전 설정 (.env)

여러 DB는 **별칭(prefix)** 으로 `.env`에 정의합니다.

```env
ORACLE_DEFAULT_DB=prod

# 공통 (모든 DB에 적용, 개별 DB에서 덮어쓰기 가능)
ORACLE_TNS_ADMIN=C:\oracle\network\admin
ORACLE_CLIENT_LIB_DIR=
ORACLE_MAX_ROWS=1000

# prod DB
ORACLE_DB_PROD_USER=prod_user
ORACLE_DB_PROD_PASSWORD=secret
ORACLE_DB_PROD_TNS=ORCL_PROD

# dev DB
ORACLE_DB_DEV_USER=dev_user
ORACLE_DB_DEV_PASSWORD=secret
ORACLE_DB_DEV_TNS=ORCL_DEV
```

레거시 단일 설정도 지원합니다 (`default` 별칭).

```env
ORACLE_USER=your_user
ORACLE_PASSWORD=your_password
ORACLE_TNS=ORCL
```

## 실행 규칙

1. `db` 인자로 접속할 별칭을 지정합니다 (예: `prod`, `dev`). 생략 시 `ORACLE_DEFAULT_DB` 사용.
2. `sql` 인자에 실행할 SELECT 또는 WITH 쿼리를 지정합니다.
3. 바인드 변수가 필요하면 `bind_params`에 dict 형태로 전달합니다.
4. INSERT/UPDATE/DELETE 등 변경 쿼리는 실행되지 않습니다.

## 예시

- dev DB에서 직원 조회
  - db: `dev`
  - sql: `SELECT * FROM employees WHERE department_id = :dept_id`
  - bind_params: `{"dept_id": 10}`
