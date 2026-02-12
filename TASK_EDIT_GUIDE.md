# 기능 추가/수정 가이드 (초보용)

이 문서는 두 가지 케이스를 **어디부터/무엇을** 수정해야 하는지 순서대로 설명합니다.

1) **UI와 무관한 기능** (예: RGB 찾아 우클릭)  
2) **UI 관련 기능** (활성화된 윈도우에서 특정 title/type 로그인 창 찾기)

---

## 1) UI와 무관한 기능 추가/수정 (RGB 찾기 등)

### 핵심 원칙
- UI 계층(`ui/`, `locator.yaml`)은 **수정하지 않음**
- 실제 동작은 `actions/`, 외부 노출은 `tools/`

### 수정 순서 (추천)
1. **Action 추가/수정**
   - 위치: `actions/`
   - 역할: 실제 동작 로직 (예: 스크린샷 분석, 마우스 이동)
   - 예: `actions/color_click_action.py`

2. **Tool 추가/수정**
   - 위치: `tools/`
   - 역할: MCP 도구 함수 정의, Action만 호출
   - 예: `tools/color_click_tool.py`

3. **Tool 등록**
   - 위치: `mcp_server.py`
   - 역할: 서버가 도구를 인식하도록 등록
   - 함수: `register_all_tools()`

4. **의존성 추가 (필요 시)**
   - 위치: `requirements.txt`
   - 예: `pyautogui`, `Pillow`

### 체크리스트
- Action에 로직이 있고 Tool은 Action만 호출하는가
- `mcp_server.py`에 등록했는가
- 필요한 패키지를 설치했는가

---

## 2) UI 관련 기능 추가/수정 (활성화된 윈도우에서 로그인 창 찾기)

### 핵심 원칙
- UI 탐색 규칙은 `locator.yaml`에 모음
- UI 조작은 `ui/`에서만 수행
- 업무 흐름은 `actions/`
- MCP 노출은 `tools/`

### 수정 순서 (추천)
1. **Locator 정의 추가**
   - 위치: `config/locator.yaml`
   - 목적: 로그인 창/요소의 title, control_type, auto_id 정의

2. **UI 클래스 수정/추가**
   - 위치: `ui/login_window.py` 또는 새 UI 클래스
   - 내용: 활성화된 윈도우 기준 탐색 로직 추가

3. **Action 수정**
   - 위치: `actions/login_action.py`
   - 내용: “활성화된 로그인 창 찾기 → 입력 → 클릭” 흐름 반영

4. **Tool 수정**
   - 위치: `tools/login_tool.py`
   - 내용: MCP 도구가 새 Action 로직을 호출하도록 연결

### 체크리스트
- Locator가 `locator.yaml`에 정의되어 있는가
- UI 계층에서만 UI 탐색/조작을 하는가
- Action은 업무 로직, Tool은 Action 호출만 하는가

---

## 요약

- **UI 무관 기능**: `actions/` + `tools/` + `mcp_server.py` (+ `requirements.txt`)
- **UI 관련 기능**: `config/` + `ui/` + `actions/` + `tools/`

