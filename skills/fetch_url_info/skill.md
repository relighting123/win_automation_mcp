# Fetch URL Info

URL에서 HTTP GET으로 내용을 조회합니다. Windows UI 자동화 없이 동작합니다.

## 실행 규칙

1. `url` 인자에 조회할 주소를 지정합니다.
2. JSON API라면 `as_json: true`로 파싱된 결과를 받을 수 있습니다.
3. 응답이 너무 길면 `max_chars`까지 잘라 반환합니다.

## 인자

| 인자 | 설명 | 기본값 |
|------|------|--------|
| url | 조회할 URL | (필수) |
| method | GET 또는 HEAD | GET |
| as_json | JSON 파싱 시도 | false |
| max_chars | 본문 최대 길이 | 50000 |
| timeout | 타임아웃(초) | 30 |

## 사용 예

### MCP 스킬 직접 호출

```
fetch_url_info(url="https://httpbin.org/get")
```

### chatRTD

```
/skill fetch_url_info url=https://example.com
```

### /analyze (semi 권장)

`manual` 모드는 `mode: ai` 인자를 LLM이 채우지 않으므로, URL 조회는 **semi** 또는 스킬 직접 호출을 사용하세요.

```
/analyze semi https://example.com 페이지 제목 관련 텍스트 가져와줘
```

## 반환 예

```json
{
  "success": true,
  "url": "https://example.com/",
  "status_code": 200,
  "content_type": "text/html",
  "format": "text",
  "text": "<!doctype html>...",
  "truncated": false
}
```
