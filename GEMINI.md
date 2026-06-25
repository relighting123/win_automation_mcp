# chatRTD — Windows Automation Agent

이 프로젝트는 **chatRTD** Windows 자동화 에이전트입니다. Gemini CLI가 MCP 도구를 통해 아래 작업을 수행합니다.

## 역할

- Windows 프로그램 UI 자동화 (pywinauto)
- Oracle DB 조회 (`query_oracle_db`, `db=prd` 등)
- 일일/주간 업무 보고서 (`daily_work_summary`, `weekly_report`)

## MCP 서버

- 기본 URL: `http://localhost:8001/mcp`
- 런처(`scripts/start_chatrtd_gemini.py`)가 서버 미기동 시 자동 시작을 시도합니다.

## 주요 스킬

| 스킬 | 용도 |
|------|------|
| `query_oracle_db` | Oracle SELECT 조회 |
| `daily_work_summary` | 일일 업무 MD 보고서 |
| `weekly_report` | 주간 보고서 (일일 MD 병합) |

## DB 설정

`config/oracle_databases.yaml` — `alias`, `user`, `password`, `host`, `service_name`

## 보고서 설정

`skills/daily_work_summary/report_config.yaml`

## 응답 규칙

- 한국어로 간결하게 보고
- 도구/스킬 실행 결과를 근거로 설명
- 변경 쿼리(INSERT/UPDATE/DELETE)는 실행하지 않음
