# Fetch URL Info

OpenChrome(`openchrome-mcp`)로 URL을 열고 본문 텍스트를 가져옵니다.  
사내 SSO·쿠키 인증이 필요한 페이지에 사용합니다.

## 사전 준비

1. Node.js LTS + Chrome stable 설치
2. chatRTD 멀티 MCP 활성화

### `.env`

```dotenv
MCP_OPENCHROME_ENABLED=true
```

첫 도구 호출 시 OpenChrome이 **실제 Chrome을 자동 실행**합니다.  
Browser MCP처럼 Chrome 확장 + Connect 버튼은 **필요 없습니다**.

### `config/app_config.yaml`

```yaml
mcp:
  extra_servers:
    - id: openchrome
      transport: stdio
      command: cmd
      args: [/c, npx, -y, "openchrome-mcp@latest", serve, --auto-launch]
      enabled: true
```

## 사용 예

```
/skill fetch_url_info url=https://internal.example.com
```

## 동작

1. `openchrome/navigate` — URL 이동 (CDP, 로그인 세션 유지)
2. `openchrome/read_page` — 본문 Markdown 추출
