# OpenProvider Windows Automation Tool Guide

이 문서는 OpenProvider(또는 OpenAI 호환 API)를 사용하여 Windows 자동화 도구를 효과적으로 사용하는 방법을 설명합니다.

## 시스템 아키텍처

1. **사용자**: Streamlit UI를 통해 자연어로 명령을 내립니다.
2. **LLM(OpenProvider/OpenAI 호환 모델)**: 사용자의 의도를 파악하고 적절한 MCP 도구를 호출합니다.
3. **Streamlit App**: LLM의 도구 호출(Tool Call) 요청을 받아 로컬 MCP 서버로 전달합니다.
4. **MCP 서버**: `pywinauto`를 사용하여 실제 Windows 애플리케이션을 조작합니다.
5. **결과 반환**: 실행 결과가 다시 LLM으로 전달되어 최종 답변을 생성합니다.

---

## 주요 도구 목록 및 사용법

### 1. 애플리케이션 관리
- **launch_application**: 앱이 꺼져 있을 때 실행합니다. (예: `executable_path="notepad"`)
- **connect_to_application**: 이미 실행 중인 앱을 제어할 때 사용합니다.
- **close_application**: 현재 연결된 앱을 종료합니다.

### 2. UI 요소 조작
- **click_app_text**: 화면 텍스트를 OCR로 인식해 해당 위치를 클릭합니다.
- **click_app_keyword**: 현재 화면 분석 후 keyword에 맞는 요소를 탐색하여 클릭합니다.
- **click_app_icon_target**: 미리 정의된 아이콘(이미지)을 찾아 클릭합니다.

### 3. 입력 액션
- **type_app_text**: 텍스트를 입력합니다.
- **press_app_shortcut**: 단축키를 보냅니다 (예: `ctrl+s`, `enter`).

---

## 효과적인 프롬프트 예시

- "메모장을 켜고 '안녕하세요'라고 적어줘"
- "계산기 앱에서 123 더하기 456을 해줘"
- "지금 열린 창에서 '저장' 버튼을 찾아 클릭해줘"

## 설정 방법

1. `python mcp_server.py` 명령어로 MCP 서버를 실행합니다. (기본 포트: 8000)
2. Streamlit 앱 사이드바에서 **LLM Base URL / API Key / Model**을 입력합니다.
3. 대화를 시작합니다.

## 권장 체크리스트

- Base URL이 OpenAI 호환 엔드포인트(`/v1`)인지 확인
- 선택한 모델이 tool calling을 지원하는지 확인
- MCP URL이 `http://localhost:8000/mcp`와 일치하는지 확인
