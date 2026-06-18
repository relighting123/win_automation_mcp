# Fetch URL Info

Browser MCP(`@browsermcp/mcp`)로 URL을 열고 본문 텍스트를 가져옵니다.  
사내 SSO·쿠키 인증이 필요한 페이지에 사용합니다.

## 사전 준비

1. Node.js LTS + Chrome stable 설치
2. [Browser MCP Chrome 확장](https://chromewebstore.google.com/detail/browser-mcp-automate-your/bjfgambnhccakkhmkepdoekmckoijdlc) 설치
3. **최초 1회** Chrome 확장 **Connect** 클릭 (또는 chatRTD/MCP 재시작 후 1회)
   - `/skill fetch_url_info ...` 실행 시 확장 팝업이 자동으로 열리면 Connect만 누르면 됩니다
4. chatRTD 멀티 MCP 활성화 (둘 중 하나)

### `.env`

```dotenv
MCP_BROWSER_MCP_ENABLED=true
```

(하위 호환: `MCP_CHROME_DEVTOOLS_ENABLED=true` 도 Browser MCP를 켭니다.)

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
2. `browsermcp/browser_wait` — 페이지 로딩 대기 (2초)
3. `browsermcp/browser_snapshot` — 접근성 스냅샷에서 본문 텍스트 추출
