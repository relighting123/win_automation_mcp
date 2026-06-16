# Daily Work Summary (일일 업무 정리)

`report_config.yaml`에 지정한 **웹 URL**, **Oracle 쿼리**, **고정 섹션**을 모아  
`reports/daily/YYYY-MM-DD.md` 파일로 저장합니다.

## 사전 준비

1. 설정 파일 복사

```bash
copy skills\daily_work_summary\report_config.yaml.example skills\daily_work_summary\report_config.yaml
```

2. `report_config.yaml`에 수집할 URL/DB/섹션 편집

3. Chrome DevTools MCP 활성화 (사내 웹 SSO)

```dotenv
MCP_CHROME_DEVTOOLS_ENABLED=true
MCP_CHROME_DEVTOOLS_AUTO_CONNECT=true
```

4. (선택) 보고서 저장 경로 — `config/app_config.yaml`

```yaml
reports:
  daily_dir: "reports/daily"
  weekly_dir: "reports/weekly"
  config_file: "skills/daily_work_summary/report_config.yaml"
```

## 사용

```
/skill daily_work_summary
/skill daily_work_summary report_date=2026-06-16
```

## 출력 예

`reports/daily/2026-06-16.md`

## 예약 실행 (Windows 작업 스케줄러)

매일 18:00 자동 실행 예:

```powershell
schtasks /Create /TN "chatRTD-DailySummary" /SC DAILY /ST 18:00 ^
  /TR "cmd /c cd /d C:\path\to\win_automation_mcp && python scripts\run_daily_summary.py" ^
  /F
```

또는:

```bat
python scripts\run_daily_summary.py
```

## 배포 요약

| 단계 | 내용 |
|------|------|
| 1 | `pip install -e .` + `.env` / `app_config.yaml` 설정 |
| 2 | `report_config.yaml` 회사 환경에 맞게 편집 |
| 3 | 수동 테스트: `/skill daily_work_summary` |
| 4 | Windows 작업 스케줄러로 `scripts/run_daily_summary.py` 등록 |
| 5 | 주간: 금요일에 `scripts/run_weekly_report.py` 등록 |

서버 PC에서 MCP가 항상 떠 있어야 하면 작업 스케줄러 대신 **로그온 시 chatRTD/MCP 시작** + `--no-server` 스크립트 조합을 쓰세요.
