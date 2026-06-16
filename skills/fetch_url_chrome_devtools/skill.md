# Fetch URL (Chrome DevTools MCP)

Chrome DevTools MCP(`chrome-devtools-mcp`)를 통해 URL을 열고 본문 텍스트를 가져옵니다.  
Playwright 대신 **Google 공식 Chrome DevTools MCP**를 사용하며, chatRTD **멀티 MCP**로 연결됩니다.

## 사전 준비

1. Node.js LTS + Chrome stable 설치
2. chatRTD 멀티 MCP 활성화 (둘 중 하나)

### 방법 A — `.env`

```dotenv
MCP_CHROME_DEVTOOLS_ENABLED=true
MCP_CHROME_DEVTOOLS_AUTO_CONNECT=true
```

### 방법 B — `config/app_config.yaml`

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

> `--autoConnect`는 **이미 로그인된 Chrome**에 붙습니다. SSO 세션 재사용에 유리합니다.

## 사용 예

```
/skill fetch_url_chrome_devtools url=https://internal.example.com
```

## 동작

1. `chrome-devtools/navigate` — URL 이동
2. `chrome-devtools/evaluate` — `document.body.innerText` 추출

## HTTP 프록시로 연결 (선택)

stdio 대신 mcp-proxy를 쓸 수도 있습니다.

```bash
mcp-proxy --transport streamablehttp --port 8080 -- npx -y chrome-devtools-mcp@latest --slim --autoConnect
```

`app_config.yaml`:

```yaml
mcp:
  extra_servers:
    - id: chrome-devtools
      transport: http
      url: http://127.0.0.1:8080/mcp
      enabled: true
```

## Playwright `fetch_url_chrome`와 비교

| | fetch_url_chrome | fetch_url_chrome_devtools |
|--|------------------|---------------------------|
| 의존성 | Python playwright | Node chrome-devtools-mcp |
| SSO | 전용 프로필 로그인 | 기존 Chrome 세션(`--autoConnect`) |
| chatRTD 통합 | 단일 MCP 도구 | 멀티 MCP |
