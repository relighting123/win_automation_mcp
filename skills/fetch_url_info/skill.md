# Fetch URL Info

Playwright `launch_persistent_context`로 URL을 열고 본문 텍스트를 가져옵니다.  
`user_data_dir`에 쿠키·SSO 세션이 유지됩니다.

## 사전 준비

1. Playwright 설치

```bash
pip install playwright
playwright install chromium
```

설치된 Chrome을 쓰려면 (권장, Windows):

```dotenv
PLAYWRIGHT_CHANNEL=chrome
```

2. (선택) 브라우저 프로필 경로 — SSO 로그인 유지

```dotenv
CHATRTD_BROWSER_PROFILE_DIR=C:\Users\you\.chatrtd\browser-profile
```

첫 실행 시 `headless=False`(기본)로 브라우저가 뜨면 **한 번 로그인**해 두면 이후 같은 프로필로 세션이 유지됩니다.

```dotenv
# 로그인 후 백그라운드만 쓸 때
PLAYWRIGHT_HEADLESS=true
```

## 사용 예

```
/skill fetch_url_info url=https://internal.example.com
```

## 동작

1. `fetch_url_content` — Playwright로 `page.goto` → `body` 텍스트 반환
