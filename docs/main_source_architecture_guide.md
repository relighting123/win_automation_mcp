# main 배포 소스 아키텍처/파일 역할 문서

## 0) 문서 기준
- 기준 브랜치: `main`
- 기준 커밋: `b79008ebef6cf338c8a761f96731ab8ded9a1c04`
- 작성 목적: 현재 배포 소스의 **기본 설계 틀**을 먼저 설명하고, 이후 **파일별 역할과 핵심 구현 내용**을 단계적으로 정리

---

## 1) 한눈에 보는 기본 틀 (Big Picture)

이 프로젝트는 **Windows 애플리케이션 자동화용 MCP 서버**입니다.

- 외부 LLM(예: Claude/OpenProvider/OpenAI 호환 클라이언트)은 MCP Tool 호출만 수행
- 서버는 Tool -> Action -> Core 순으로 책임을 분리
- 실제 GUI 제어는 `pywinauto`, `pyautogui`, `winocr`를 조합해 수행

### 1-1. 논리 계층 구조
```text
LLM/클라이언트
  -> mcp_server.py (FastMCP 서버)
    -> tools/* (도구 인터페이스)
      -> actions/* (업무/화면 제어 로직)
        -> core/* (세션/런처/대기/네트워크 공통)
          -> Windows App (pywinauto, pyautogui, OCR)
```

### 1-2. 핵심 설계 원칙
1. **계층 분리**  
   Tool은 Action 호출만 담당, Action이 실제 자동화 시퀀스를 구성
2. **싱글톤 세션 관리**  
   `AppSession`으로 연결 상태/설정/locator를 일원화
3. **상태 기반 대기/재시도**  
   `wait_utils.py`에서 공통 대기/재시도 정책 제공
4. **혼합 탐색 전략**  
   UIA(구조적 탐색) + OCR/이미지/RGB(시각 탐색) 동시 지원

---

## 2) 런타임 설계도 (요청 처리 흐름)

## 2-1. 서버 부팅 흐름
1. `mcp_server.py` 실행
2. 로깅 초기화, 전송 방식(http/sse/stdio) 파라미터 설정
3. `ServerState.initialize()`에서 `AppSession` 초기화
4. Tool 등록 (`register_app_mgmt_tools`, `register_ui_vision_tools`)
5. MCP 서버 run

## 2-2. 일반 Tool 실행 흐름 (예: 텍스트 클릭)
1. LLM이 Tool 호출 (`click_app_text`)
2. Tool(`tools/ui_vision_tool.py`)에서 `AppUIAction` 획득 후 `ensure_focus()`
3. Action(`actions/app_ui_action.py`)에서 OCR/UIA로 좌표 탐색
4. 좌표 클릭/입력/단축키 수행
5. 표준화된 결과(dict/문자열) 반환

## 2-3. 애플리케이션 생명주기 흐름
1. Tool(`launch_application` 등) 호출
2. `AppLauncher`가 `AppSession.start/connect/close/restart` 조합
3. 상태/창 정보 요약 후 반환

---

## 3) 디렉터리 구조와 책임

```text
actions/   : UI 제어 업무 로직
config/    : 앱 설정, locator, icon registry
core/      : 세션/런처/대기/포트 킬 유틸
errors/    : 업무 단위 예외 계층
tools/     : MCP 도구 정의(외부 공개 인터페이스)
LLM/       : Streamlit+OpenProvider(OpenAI 호환) 클라이언트 예시
scripts/   : 보조 스크립트(locator 생성/포트 킬 검증)
tests/     : 수동 검증 성격의 테스트 스크립트
```

---

## 4) 파일별 역할과 주요 소스 내용

## 4-1. 루트 엔트리/오케스트레이션

### `mcp_server.py`
- 역할: FastMCP 서버 진입점
- 핵심 내용:
  - `setup_logging()`: 콘솔/파일 로깅 설정
  - `register_all_tools()`: app 관리 + UI vision tool 등록
  - `ServerState`: 초기화/정리(세션 disconnect 포함)
  - MCP Resource 제공: `config://app`, `config://locators`
  - `main()`: transport/http host/port/path/reload 처리, 서버 실행
  - `run_with_reloader()`: `.py/.yaml` 변경 감지 자동 재시작

### `automation_graph.py`
- 역할: 정의된 plan 순서를 그대로 실행하는 최소 LangGraph 실행기
- 핵심 내용:
  - `AutomationState` 정의
  - `load_plan_steps_from_json()`: JSON plan 파일 파싱
  - `planner_node`(plan 검증) -> `executor_node`(순차 tool 호출) -> `finalizer_node`(요약)
  - `run_automation_from_plan_json()`으로 `plans/*.json` 실행 지원

### `mcp_client.py`
- 역할: HTTP 기반 MCP 호출 예시 클라이언트
- 핵심 내용:
  - `list_tools()`, `call_tool()`
  - 단순 endpoint 가정형 구현(프로토타입 성격)

### `__init__.py`
- 역할: 패키지 메타 정보 제공
- 핵심 내용:
  - 버전/작성자 및 계층 구조 설명 문자열

---

## 4-2. Core 계층 (공통 기반)

### `core/app_session.py`
- 역할: `pywinauto.Application` 싱글톤 래퍼 + 설정/locator 로더
- 핵심 내용:
  - `SessionState`(`DISCONNECTED/CONNECTING/CONNECTED/ERROR`)
  - 설정 로딩: `app_config.yaml` + fallback default
  - locator 로딩: `locator.yaml`
  - 연결 메서드: `connect()`, `start()`, `disconnect()`, `reconnect()`
  - 윈도우 접근: `get_window()`, `get_window_by_locator()`
  - 설정 조회: timeout/retry/locator getter

### `core/app_launcher.py`
- 역할: 앱 생명주기 orchestration (실행/연결/종료/재시작)
- 핵심 내용:
  - `launch()`, `connect_to_running()`, `ensure_running()`
  - `close(force=False)`에서 정상 종료 실패 시 강제 종료 fallback
  - `get_process_info()`로 창 목록/상태 요약

### `core/wait_utils.py`
- 역할: 조건 기반 대기/재시도 유틸
- 핵심 내용:
  - `wait_until()`, `wait_until_value()`, `wait_until_not_none()`
  - `retry_on_failure`, `retry_with_backoff` 데코레이터
  - `WaitContext`로 기본 timeout/poll 변경 가능

### `core/network_utils.py`
- 역할: 포트 점유 프로세스 종료 유틸(Windows 명령 기반)
- 핵심 내용:
  - `kill_process_on_port(port)`  
  - `netstat/findstr`로 PID 찾고 `taskkill` 수행

### `core/__init__.py`
- 역할: core API 재노출

---

## 4-3. Action 계층 (업무/화면 제어)

### `actions/app_ui_action.py`
- 역할: UIA/OCR/이미지/RGB를 통합한 실제 자동화 동작 구현
- 핵심 내용:
  - 결과 모델: `AppUIActionResult`
  - 포커스/윈도우 선택: `ensure_focus()`, `_pick_target_window()`
  - 상태 분석: `describe_current_state()`, `get_screen_state_flags()`
  - UIA 컴포넌트 수집: `_collect_uia_components()`
  - OCR 탐색: `find_text_position()`, `_extract_ocr_hits()`
  - 이미지 탐색: `find_image_position()`
  - 픽셀/입력 제어: `find_rgb_position()`, `click_position()`, `type_text()`, `press_shortcut()`

### `actions/__init__.py`
- 역할: `AppUIAction` export

---

## 4-4. Tool 계층 (MCP 외부 인터페이스)

### `tools/app_mgmt_tool.py`
- 역할: 앱 관리 Tool 등록
- 핵심 내용:
  - `launch_application`
  - `connect_to_application`
  - `close_application`
  - `restart_application`
  - `get_connection_status`
  - `generate_locators` (script 연동)

### `tools/app_control_tool.py`
- 역할: 화면 인식/클릭/입력 도구 등록
- 핵심 내용:
  - 도구들: `find_element_by_title_or_uid`, `find_element_by_ocr`, `find_element_by_auto_id`, `click_element_by_title`, `click_element_by_uid`, `type_app_text`, `press_app_shortcut`, `click_app_position`, `click_app_element`

### `tools/__init__.py`
- 역할: tool registration 함수 재노출

---

## 4-5. Error 계층

### `errors/automation_error.py`
- 역할: 업무 의미 중심 예외 체계
- 핵심 내용:
  - 베이스: `AutomationError`
  - 세부 예외:
    - `ConnectionError`, `ElementNotFoundError`, `TimeoutError`
    - `ActionFailedError`, `LoginError`, `SessionError`
    - `WindowNotFoundError`, `InvalidStateError`
  - `wrap_pywinauto_error()`로 원본 예외를 업무 예외로 매핑

### `errors/__init__.py`
- 역할: 예외 클래스 export

---

## 4-6. 설정 파일

### `config/app_config.yaml`
- 역할: 앱 실행/연결/타임아웃/재시도/로그/서버 기본 설정
- 핵심 내용:
  - `application`: executable_path, process_name, backend, startup_timeout
  - `timeouts`, `retry`, `logging`, `server`

### `config/locator.yaml`
- 역할: UIA locator 외부화(선택형)
- 핵심 내용:
  - `active_window.window` + `elements.*` 형태


### `config/__init__.py`
- 역할: 패키지 마커

---

## 4-7. LLM/운영 보조

### `LLM/streamlit_app.py`
- 역할: OpenProvider(OpenAI 호환) 기반 대화형 UI + MCP tool-call 브리지 예시
- 핵심 내용:
  - `get_mcp_tools()`로 MCP tool schema 수집
  - `call_mcp_tool()`로 실제 tools/call 실행
  - 다중 iteration으로 tool 호출-응답 루프 수행

### `LLM/openprovider_tool_guide.md`
- 역할: OpenProvider(OpenAI 호환)+MCP 사용 안내 문서

### `README.md`
- 역할: 프로젝트 개요/원칙/실행 방법 문서
- 참고:
  - 일부 파일명/계층 설명은 과거 구조 기준 내용이 포함되어 있어
    실제 구현은 현재 소스(`tools/ui_vision_tool.py`, `actions/app_ui_action.py`)를 우선 참조

---

## 4-8. 스크립트/테스트

### `scripts/generate_locators.py`
- 역할: 현재 활성 앱의 UIA 요소를 추출해 `locator.yaml` 갱신
- 핵심 내용:
  - 창 정보/요소(descendants) 추출
  - `--type`으로 저장 키 지정(기본 `active_window`)

### `scripts/verify_port_kill.py`
- 역할: 더미 서버를 띄워 `kill_process_on_port()` 동작을 검증

### `tests/verify_window_focus.py`
- 역할: Notepad 대상 `ensure_focus()` 복구/포커스 동작 검증(수동 실행형)

### `tests/verify_generic_sequence.py`
- 역할: 텍스트 클릭-대기-단축키 시퀀스 실행 검증(수동 실행형)

---

## 5) 구현 관점에서의 핵심 포인트 (세부)

1. **현재 실질 핵심 로직 중심 파일**
   - `actions/app_ui_action.py`
   - `tools/ui_vision_tool.py`
   - `core/app_session.py`
   - `mcp_server.py`

2. **확장 시 진입 순서(권장)**
   1) Action 추가 -> 2) Tool 래핑 -> 3) `register_all_tools()` 등록 -> 4) config 보강

3. **운영 시 주의점**
   - `network_utils.py`는 Windows 명령 의존(`netstat`, `taskkill`)
   - OCR/이미지 기반 기능은 해상도/스케일/테마 영향이 큼
   - `README` 일부 구조 설명은 코드 현황과 차이가 있을 수 있어, 실제 구현 파일 우선 확인 필요

---

## 6) 빠른 참조 (핵심 파일 10선)
1. `mcp_server.py` - 서버 진입/등록/실행
2. `tools/ui_vision_tool.py` - UI 자동화용 MCP 인터페이스
3. `actions/app_ui_action.py` - UIA+OCR+이미지+RGB 핵심 로직
4. `tools/app_mgmt_tool.py` - 실행/연결/종료 인터페이스
5. `core/app_session.py` - 세션/설정/locator 싱글톤
6. `core/app_launcher.py` - 앱 생명주기 제어
7. `core/wait_utils.py` - 대기/재시도 정책
8. `errors/automation_error.py` - 예외 모델
9. `config/app_config.yaml` - 운영 기본값
10. `scripts/generate_locators.py` - locator 생성 자동화
