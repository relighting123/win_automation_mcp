# Fetch URL Info

Chrome DevTools MCP(`chrome-devtools-mcp`)로 URL을 열고 본문 텍스트를 가져옵니다.  
사내 SSO·쿠키 인증이 필요한 페이지에 사용합니다.

## 사전 준비

1. Node.js LTS + Chrome stable 설치
2. chatRTD 멀티 MCP 활성화 (둘 중 하나)

### `.env`

```dotenv
MCP_CHROME_DEVTOOLS_ENABLED=true
MCP_CHROME_DEVTOOLS_AUTO_CONNECT=true
```

### `config/app_config.yaml`

```yaml
mcp:
  extra_servers:
    - id: chrome-devtools
      transport: stdio
      command: cmd
      args: [/c, npx, -y, chrome-devtools-mcp@latest, --slim, --autoConnect, --no-usage-statistics]
      enabled: true
```

3. Chrome 144+에서 `chrome://inspect/#remote-debugging` → 원격 디버깅 허용
4. 평소 쓰는 Chrome을 켠 뒤 chatRTD 재시작

## 사용 예

```
/skill fetch_url_info url=https://internal.example.com
```

## 동작

1. `chrome-devtools/navigate` — URL 이동
2. `chrome-devtools/evaluate` — `document.body.innerText` 추출
