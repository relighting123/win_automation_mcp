# 기능 추가/수정 가이드 (active-window 방식)

현재 구조는 **화면 분리(login/main) 없이**,  
`active window + OCR/UIA + 좌표 액션`을 기본으로 사용합니다.

---

## 핵심 원칙

- UI 분리 객체(`ui/login_window.py`, `ui/main_window.py`)를 만들지 않음
- 실제 동작은 `actions/app_ui_action.py`에 구현
- MCP 노출은 `tools/app_ui_tool.py`에 추가
- 서버 등록은 `mcp_server.py -> register_all_tools()`에서 관리

---

## 수정 순서 (추천)

1. **Action 추가/수정**
   - 위치: `actions/app_ui_action.py`
   - 역할: 화면 분석, 키워드/OCR 탐색, 아이콘 탐색, 클릭/단축키/입력 로직

2. **Tool 추가/수정**
   - 위치: `tools/app_ui_tool.py`
   - 역할: MCP tool 함수 정의, Action 호출

3. **Tool 등록 확인**
   - 위치: `mcp_server.py`
   - 함수: `register_all_tools()`

4. **아이콘 메타데이터(필요 시)**
   - 위치: `config/icon_registry.yaml`
   - 항목: `image_path`, `keywords`, `confidence`, `grayscale`

---

## 체크리스트

- Tool이 Action만 호출하는가
- 키워드 탐색 실패 시 fallback(OCR/아이콘) 경로가 있는가
- 클릭 전 `ensure_focus()`가 수행되는가
- 변경 후 `python3 -m compileall .`가 통과하는가

