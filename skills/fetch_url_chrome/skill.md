# Fetch URL Chrome

설치된 Google Chrome(Playwright)으로 URL을 열어 내용을 조회합니다.  
사내 SSO·쿠키 인증이 필요한 페이지는 `fetch_url`(httpx) 대신 이 스킬을 사용하세요.

## 사전 준비

```bash
pip install playwright
playwright install chrome
```

선택: `.env`에 자동화 전용 프로필 경로 지정

```dotenv
CHROME_USER_DATA_DIR=C:\Users\you\.chatRTD\chrome-automation
CHROME_CHANNEL=chrome
```

> 일반 Chrome `Default` 프로필은 Chrome 실행 중 잠금될 수 있습니다.  
> `~/.chatRTD/chrome-automation` 전용 폴더에서 한 번 로그인해 두고 재사용하는 것을 권장합니다.

## 실행 규칙

1. `url`에 조회할 주소를 지정합니다.
2. SSO/MFA가 필요하면 `headless: false`, `wait_seconds: 30` 등으로 로그인 시간을 줍니다.
3. HTML이 필요하면 `return_html: true`를 사용합니다.

## 인자

| 인자 | 설명 | 기본값 |
|------|------|--------|
| url | 조회할 URL | (필수) |
| profile_dir | Chrome user data 폴더 | CHROME_USER_DATA_DIR 또는 ~/.chatRTD/chrome-automation |
| headless | 창 없이 실행 | false |
| wait_seconds | 로드 후 추가 대기(초) | 0 |
| timeout | navigation 타임아웃(초) | 60 |
| max_chars | 본문 최대 길이 | 50000 |
| return_html | HTML 반환 여부 | false |
| channel | Playwright channel | chrome |

## 사용 예

### MCP / 스킬

```
/skill fetch_url_chrome url=https://internal.example.com wait_seconds=30
```

### 첫 로그인 후 재사용

1. `headless=false`, `wait_seconds=60`으로 한 번 실행해 브라우저에서 로그인
2. 이후 같은 `profile_dir`로 다시 호출하면 세션이 유지되는 경우가 많습니다.

## 반환 예

```json
{
  "success": true,
  "url": "https://internal.example.com/dashboard",
  "title": "Dashboard",
  "format": "text",
  "text": "페이지 본문 텍스트...",
  "login_like": false,
  "profile_dir": "C:\\Users\\you\\.chatRTD\\chrome-automation"
}
```

로그인 페이지로 보이면 `login_like: true`, `success: false`와 안내 메시지가 반환됩니다.
