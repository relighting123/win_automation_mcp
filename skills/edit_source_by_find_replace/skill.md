# Edit Source by Find/Replace
이 스킬은 단일 MCP 서버 안에서 Ctrl+F + 바꾸기처럼 동작합니다.

## 실행 규칙
1. 먼저 `find_text_in_file` 결과로 대상 라인과 문맥을 확인하세요.
2. `replace_text_in_file`는 기본적으로 `occurrence=1`만 바꿉니다.
   - 전체 치환이 필요한 경우에만 `replace_all=true`를 사용하세요.
3. 대량 치환 시에는 `max_replacements` 한도를 함께 지정하세요.
4. 마지막 `find_text_in_file`로 변경이 정확히 반영되었는지 검증하세요.

## 대용량 파일 가이드
- 본 도구는 라인 스트리밍 기반이므로 큰 파일에서도 메모리 사용량이 급증하지 않습니다.
- 대신 멀티라인 패턴(`search_text`에 줄바꿈 포함)은 지원하지 않습니다.
- **정규표현식 지원**: `is_regex=true`를 설정하면 `search_text`를 정규표현식으로 사용할 수 있습니다. 복잡한 패턴 매칭 시 유용합니다.
- 매우 넓은 공통 구문을 치환하면 영향 범위가 커질 수 있으니, 가능한 한 고유한 문맥 문자열을 사용하세요.

## 문맥 기반 치환 (`replace_text_with_context`)
동일한 코드가 파일 내 여러 군데 있을 때, 특정 키워드 근처에 있는 코드만 바꾸고 싶다면 이 도구를 사용하세요.
- `context_text`: 동일 구문 중 특정 위치를 식별할 수 있는 주변 키워드 (이 또한 `is_context_regex=true`로 정규표현식 사용 가능)
- `context_lines`: 해당 키워드가 검색 텍스트 기준 앞뒤 몇 라인 안에 있어야 하는지 지정 (기본 5라인)
