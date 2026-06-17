# Fetch URL Info

Browser MCP(`@browsermcp/mcp`)로 URL을 열고 본문 텍스트를 가져옵니다.  
사내 SSO·쿠키 인증이 필요한 페이지에 사용합니다.

## 사전 준비

1. Node.js LTS + Chrome stable 설치
2. [Browser MCP Chrome 확장](https://chromewebstore.google.com/detail/browser-mcp-automate-your/bjfgambnhccakkhmkepdoekmckoijdlc) 설치
3. Chrome에서 확장 프로그램 **Connect** 클릭 (탭 연결)
4. chatRTD 멀티 MCP 활성화 (둘 중 하나)

### `.env`

```dotenv
MCP_BROWSER_MCP_ENABLED=true
```

(하위 호환: `MCP_CHROME_DEVTOOLS_ENABLED=true` 도 동일하게 Browser MCP를 켭니다.)

### `config/app_config.yaml`

```yaml
mcp:
  extra_servers:
    - id: browsermcp
      transport: stdio
      command: cmd
      args: [/c, npx, -y, "@browsermcp/mcp@latest"]
      enabled: true
```

## 사용 예

```
/skill fetch_url_info url=https://internal.example.com
```

## 동작

1. `browsermcp/browser_navigate` — URL 이동
2. `browsermcp/browser_snapshot` — 접근성 스냅샷에서 본문 텍스트 추출
