# FastMCP Windows Automation Server

pywinauto 기반 Windows 프로그램 자동화를 위한 FastMCP 서버입니다.

## 아키텍처 개요

LLM이 Windows 애플리케이션을 "도구(tool)"처럼 제어할 수 있게 합니다.

```
┌─────────────────────────────────────────────────────────────┐
│                         LLM (Claude)                        │
│                     (의사결정/판단만 수행)                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ MCP Protocol
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastMCP Server                           │
│                    (mcp_server.py)                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    Tools Layer                       │   │
│  │  app_tool.py | desktop_tool.py | source_open_tool.py │   │
│  │  login_tool.py | run_tool.py | color_click_tool.py   │   │
│  │  (업무 의미 단위 인터페이스)                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                   Actions Layer                      │   │
│  │  login_action.py | run_action.py                    │   │
│  │  (업무 로직, 조건 분기, 재시도)                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                     UI Layer                         │   │
│  │  base_window.py | login_window.py | main_window.py  │   │
│  │  (Page Object Pattern, UI 접근 전용)                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    Core Layer                        │   │
│  │  app_session.py | app_launcher.py | wait_utils.py   │   │
│  │  (pywinauto 래퍼, 유틸리티)                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ pywinauto (backend="uia")
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Windows Application                        │
└─────────────────────────────────────────────────────────────┘
```

## 프로젝트 구조

```
win_mcp/
├── mcp_server.py           # FastMCP 서버 진입점
│
├── config/
│   ├── app_config.yaml     # 애플리케이션 설정 (경로, 타임아웃)
│   └── locator.yaml        # UI 요소 locator (auto_id 기반)
│
├── core/
│   ├── app_launcher.py     # 애플리케이션 실행/종료 관리
│   ├── app_session.py      # pywinauto Application 래퍼
│   └── wait_utils.py       # wait/retry 유틸리티
│
├── ui/
│   ├── base_window.py      # 공통 UI 탐색, Page Object 기반
│   ├── login_window.py     # 로그인 윈도우 UI
│   └── main_window.py      # 메인 윈도우 UI
│
├── actions/
│   ├── login_action.py     # 로그인 업무 로직
│   └── run_action.py       # 실행/분석 업무 로직
│
├── tools/
│   ├── app_tool.py         # 애플리케이션 관리 도구
│   ├── desktop_tool.py     # 공용 데스크톱 제어 도구(단축키/RGB/클릭)
│   ├── source_open_tool.py # 룰 검색 기반 소스 오픈 도구
│   ├── login_tool.py       # 로그인 관련 도구
│   ├── run_tool.py         # 실행/분석 관련 도구
│   └── color_click_tool.py # RGB 기반 우클릭 도구(호환용)
│
├── errors/
│   └── automation_error.py # 업무 단위 예외 클래스
│
└── logs/                   # 로그 파일 디렉토리
```

## 계층별 역할

### 1. Tools Layer (tools/)
- **역할**: FastMCP tool 함수 정의
- **원칙**:
  - 업무 의미 단위로만 정의 (login, run_analysis, export_result 등)
  - Actions 계층만 호출
  - pywinauto 직접 호출 금지
  - UI locator 작성 금지
  - LLM을 위한 명확한 docstring 제공

### 2. Actions Layer (actions/)
- **역할**: 업무 로직 구현
- **원칙**:
  - UI를 조합하여 하나의 업무 수행
  - 조건 분기, 재시도 로직 포함
  - 업무 수준 예외 발생
  - UI 객체 직접 생성 가능

### 3. UI Layer (ui/)
- **역할**: Page Object Pattern 기반 UI 접근
- **원칙**:
  - auto_id + control_type 기반 탐색
  - 업무 의미 코드 포함 금지
  - locator.yaml의 설정 사용
  - 기본 조작 메서드만 제공

### 4. Core Layer (core/)
- **역할**: pywinauto 래퍼 및 유틸리티
- **원칙**:
  - pywinauto Application 직접 래핑
  - 재연결/재시작 가능 구조
  - 설정 파일 관리
  - wait/retry 공통 유틸리티

## 설치

```bash
# 의존성 설치
pip install -r win_mcp/requirements.txt

# 또는 개별 설치
pip install mcp pywinauto pyyaml
```

> OCR 기반 도구(`find_text_position`, `click_by_text`)는 Windows 10/11의 내장 OCR 엔진(`winocr`)을 사용합니다.
> 별도의 중량급 AI 모델이나 외부 바이너리 설치가 필요 없는 초경량 아키텍처입니다.

## 설정

### 1. 애플리케이션 설정 (config/app_config.yaml)

```yaml
application:
  executable_path: "C:\\Program Files\\YourApp\\app.exe"
  process_name: "app.exe"
  backend: "uia"
  startup_timeout: 30

timeouts:
  default_wait: 10
  long_wait: 60
  short_wait: 3
```

### 2. UI Locator 설정 (config/locator.yaml)

```yaml
login_window:
  window:
    title: "Login"
    auto_id: "LoginWindow"
  elements:
    username_input:
      auto_id: "txtUsername"
      control_type: "Edit"
    password_input:
      auto_id: "txtPassword"
      control_type: "Edit"
    login_button:
      auto_id: "btnLogin"
      control_type: "Button"
```

### 3. 아이콘 레지스트리 설정 (config/icon_registry.yaml)

```yaml
icons:
  login_submit:
    image_path: "assets/icons/login_submit.png"
    confidence: 0.82
    grayscale: false
    keywords: ["login", "signin", "로그인"]
    description: "로그인 실행 아이콘"
```

## 서버 실행

```bash
# 서버 실행
python -m mcp_server

# 또는
cd win_mcp
python mcp_server.py

# 로그 레벨 지정
python -m mcp_server --log-level DEBUG

# HTTP 전송 방식 (기본)
python mcp_server.py --transport http --host 127.0.0.1 --port 8000 --path /mcp
```

## 사용 가능한 도구

### 애플리케이션 관리
- `launch_application`: 애플리케이션 실행
- `connect_to_application`: 실행 중인 앱에 연결
- `close_application`: 애플리케이션 종료
- `restart_application`: 애플리케이션 재시작
- `get_connection_status`: 연결 상태 확인

### 로그인
- `login`: 로그인 수행
- `logout`: 로그아웃
- `check_login_status`: 로그인 상태 확인
- `wait_for_login_window`: 로그인 윈도우 대기

### 실행/분석
- `run_analysis`: 분석 작업 실행
- `stop_analysis`: 실행 중인 작업 중지
- `export_result`: 결과 내보내기
- `search`: 검색 수행
- `get_application_status`: 애플리케이션 상태 조회

### 공용 데스크톱 제어
- `press_shortcut`: 단축키 입력
- `find_rgb_position`: RGB 위치 탐색
- `click_position`: 좌표 클릭
- `click_by_rgb`: RGB 위치 탐색 후 클릭
- `find_text_position`: Windows OCR 텍스트 위치 탐색
- `click_by_text`: Windows OCR 텍스트 위치 탐색 후 클릭
- `find_image_position`: 이미지(아이콘/그림) 위치 탐색 (PyAutoGUI 기본 기능)
- `click_by_image`: 이미지(아이콘/그림) 탐색 후 클릭

### AI 화면 분석 / 동적 요소 제어
- `analyze_app_screen`: 현재 앱 구성요소(UIA) + 화면 상태 + keyword 좌표(UIA/OCR) 출력
- `click_app_keyword`: keyword 기반으로 좌표를 찾고 즉시 클릭
- `check_app_screen_state`: 로그인/메인 화면 여부 등 상태 플래그 확인
- `find_app_icon_target`: 사전 정의된 아이콘 메타(config/icon_registry.yaml)로 좌표 탐색
- `click_app_icon_target`: 사전 정의된 아이콘 좌표 탐색 후 클릭

### 소스 오픈
- `open_source_by_rule_search`: 단축키→아이콘 클릭→검색어 입력으로 소스 열기

## 지능형 자동화 (Two-Layer LLM)

이 프로젝트는 복잡한 시나리오 대응을 위해 2단계 LLM 아키텍처를 지원합니다.

### 1. 계층 개요
- **Planner (상위 LLM)**: GPT-4o 등 API 기반 모델을 사용하여 대안 및 단계별 계획 수립
- **Executor (하위 LLM)**: 로컬 Function-Gemma 모델을 사용하여 정밀한 도구 호출 및 파라미터 추출
- **LangGraph**: 이 두 계층을 연결하여 상태 유지 및 흐름 제어

### 2. 실행 방법
1. **MCP 서버 시작**: `python mcp_server.py --transport http`
2. **Gemma API 시작**: `python gemma_serving.py` (8001 포트)
3. **자동화 그래프 실행**: `python automation_graph.py`

## 파인튜닝 (Finetuning)

Gemma 모델의 도구 호출 능력 및 파라미터 추출 성능을 개선하기 위한 파이프라인을 제공합니다. `finetuning/` 디렉토리를 확인하세요.

- **데이터 준비**: `python finetuning/prepare_dataset.py` (시나리오 기반 데이터셋 생성)
- **학습 실행**: `python finetuning/finetune_gemma.py` (QLoRA 기반 학습)

## 핵심 원칙

### 1. 계층 분리
```
Tool 함수 → Action 호출만
Action → UI 조합, 업무 로직
UI → pywinauto 조작만
```

### 2. sleep() 사용 금지
```python
# ❌ 잘못된 예
time.sleep(5)

# ✅ 올바른 예
wait_until(
    condition=lambda: element.exists(),
    timeout=10,
    timeout_message="요소 대기 시간 초과"
)
```

### 3. 좌표 클릭 금지
```python
# ❌ 잘못된 예
click(x=100, y=200)

# ✅ 올바른 예
element = window.child_window(auto_id="btnLogin")
element.click()
```

### 4. 예외 래핑
```python
# ❌ 잘못된 예
raise ElementNotFoundError  # pywinauto 예외 그대로

# ✅ 올바른 예
raise LoginError(
    reason="로그인 버튼을 찾을 수 없습니다",
    cause=original_error
)
```

### 5. Locator 외부화
```python
# ❌ 잘못된 예 (Tool 내부에 locator)
window.child_window(auto_id="txtUsername")

# ✅ 올바른 예 (locator.yaml 사용)
locator = session.get_locator("login_window", "username_input")
window.child_window(**locator)
```

## 새 애플리케이션 적용 가이드

1. **config/app_config.yaml 수정**
   - 실행 파일 경로 설정
   - 타임아웃 값 조정

2. **config/locator.yaml 수정**
   - UI Spy/Inspect.exe로 auto_id 확인
   - 윈도우별 요소 locator 정의

3. **ui/ 클래스 확장**
   - 필요한 윈도우 클래스 추가
   - BaseWindow 상속

4. **actions/ 확장**
   - 업무별 Action 클래스 추가
   - UI 클래스 조합

5. **tools/ 확장**
   - FastMCP tool 함수 추가
   - 명확한 docstring 작성

## 라이선스

MIT License


streamlit run streamlit_app.py
python mcp_server.py
python gemma_serving.py
npx @modelcontextprotocol/inspector