# Weekly Report (주간 보고)

`reports/daily/` 폴더의 일일 MD 파일을 모아 주간 보고서를 만듭니다.

## 사용

```
/skill weekly_report
/skill weekly_report start_date=2026-06-10 end_date=2026-06-16
```

인자 생략 시 **오늘 포함 최근 7일** 일일 보고서를 사용합니다.

## 출력

`reports/weekly/weekly_YYYY-MM-DD_YYYY-MM-DD.md`

## 예약 실행

매주 금요일 18:30:

```powershell
schtasks /Create /TN "chatRTD-WeeklyReport" /SC WEEKLY /D FRI /ST 18:30 ^
  /TR "cmd /c cd /d C:\path\to\win_automation_mcp && python scripts\run_weekly_report.py" ^
  /F
```

## 권장 흐름

1. 평일: `daily_work_summary` (예약)
2. 금요일: `weekly_report` (예약)
3. 주간 MD를 팀 공유/메일

## 배포

일일 보고서가 먼저 쌓여 있어야 합니다. `daily_work_summary` 예약 작업이 동작하는지 확인한 뒤 주간 작업을 등록하세요.
