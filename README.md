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
│   └── locator.yaml        # (옵션) UI 요소 locator
│
├── core/
│   ├── app_launcher.py     # 애플리케이션 실행/종료 관리
│   ├── app_session.py      # pywinauto Application 래퍼
│   └── wait_utils.py       # wait/retry 유틸리티
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
  - 화면 상태 판단은 active window 기준으로 처리
  - LLM을 위한 명확한 docstring 제공

### 2. Actions Layer (actions/)
- **역할**: 업무 로직 구현
- **원칙**:
  - UI를 조합하여 하나의 업무 수행
  - 조건 분기, 재시도 로직 포함
  - 업무 수준 예외 발생
  - UI 객체 직접 생성 가능

### 3. Core Layer (core/)
- **역할**: pywinauto 래퍼 및 유틸리티
- **원칙**:
  - pywinauto Application 직접 래핑
  - 재연결/재시작 가능 구조
  - 설정 파일 관리
  - wait/retry 공통 유틸리티

## 설치

```bash
# 의존성 설치
pip install -r requirements.txt

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
active_window:
  window:
    title: "Target App"
    control_type: "Window"
  elements:
    submit_button:
      auto_id: "btnSubmit"
      control_type: "Button"
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

# SSE 전송 방식 (파일 변경 시 자동 재시작 포함)
python mcp_server.py --transport sse --port 8000 --reload
```

## 사용 가능한 도구

### 애플리케이션 관리 (app_mgmt_tool)
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

### UI 시각 제어 (ui_vision_tool)
- `click_app_child_window`: `auto_id`, `control_type`, `title` 등의 속성을 사용하여 요소를 직접 찾아 클릭합니다. `window_target(auto|top|child)`, `child_window_title`, `child_window_match_mode` 옵션으로 탐색 루트를 지정할 수 있습니다. (`draw_outline` 옵션 지원)
- `highlight_app_child_window`: 클릭 없이 특정 요소를 찾아 화면에 강조(outline) 표시합니다.
- `click_app_element`: UIA 요소 또는 OCR 텍스트를 찾아 클릭합니다.

### 소스 오픈
- `open_source_by_rule_search`: 단축키→아이콘 클릭→검색어 입력으로 소스 열기

## 단순 자동화 실행 (Plan 파일 기반 LangGraph)

`automation_graph.py`는 복잡한 플래너 없이, **정의된 순서의 plan을 그대로 실행**합니다.

### 1. Plan 파일 형식 (`.md`)
`plans/sample_plan.md`처럼 JSON 배열을 markdown 코드블록에 넣어 작성합니다.

```json
[
  {"tool": "launch_application", "args": {"executable_path": "notepad.exe"}},
  {"tool": "type_app_text", "args": {"text": "안녕하세요"}}
]
```

### 2. 실행 방법
1. **MCP 서버 시작**: `python mcp_server.py --transport http`
2. **Plan 지정 후 실행**:
   ```bash
   export AUTOMATION_PLAN_MD="plans/sample_plan.md"
   python automation_graph.py
   ```

기본값:
- `MCP_BASE_URL`: `http://localhost:8000/mcp`
- `AUTOMATION_PLAN_MD`: `plans/sample_plan.md`

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
raise AutomationError(
    message="필수 버튼을 찾을 수 없습니다",
    cause=original_error
)
```

### 5. Locator 외부화
```python
# ❌ 잘못된 예 (Tool 내부에 locator)
window.child_window(auto_id="txtUsername")

# ✅ 올바른 예 (locator.yaml 사용)
locator = session.get_locator("active_window", "submit_button")
window.child_window(**locator)
```

## 새 애플리케이션 적용 가이드

1. **config/app_config.yaml 수정**
   - 실행 파일 경로 설정
   - 타임아웃 값 조정


3. **actions/ 확장**
   - active window 기반 Action 클래스 추가
   - OCR/UIA/좌표 로직 조합

4. **tools/ 확장**
   - FastMCP tool 함수 추가
   - 명확한 docstring 작성

## 라이선스

MIT License


streamlit run LLM/streamlit_app.py
python mcp_server.py
python gemma_serving.py
npx @modelcontextprotocol/inspector

## LLM/MCP 설정 통합 관리 (`config/app_config.yaml`)

LLM/MCP 연결 정보는 `config/app_config.yaml`에서 공통 관리합니다.
`automation_graph.py`와 `LLM/streamlit_app.py`가 동일 설정을 기본값으로 사용합니다.

### Dual-LLM 구조 (Gemma + 외부 LLM)

이 프로젝트는 **역할별 LLM 분리**를 지원합니다.

| 역할 | 용도 | 권장 LLM |
| --- | --- | --- |
| `reasoning` | 계획 수립, 상황 분석, 클립보드/리포트 분석 | 외부 LLM (Groq, OpenAI 호환 API 등) |
| `task` | 파라미터 추출, 스킬 ID 매핑 같이 단순 변환 작업 | 로컬에서 서빙되는 Gemma 등 경량/파인튜닝 LLM |

```yaml
mcp:
  base_url: "http://localhost:8000/mcp"

llm:
  reasoning:
    provider: "openai"
    base_url: "https://api.groq.com/openai/v1"
    model: "openai/gpt-oss-120b"
    api_key: ""
    structured_output_method: "function_calling"
    temperature: 0

  task:
    provider: "gemma"
    base_url: "http://localhost:8001/v1"   # vLLM/Ollama 등 OpenAI 호환 endpoint
    model: "google/gemma-3-4b-it"
    api_key: ""
    structured_output_method: "json_mode"  # Gemma 는 OpenAI tools 미지원 → json_mode 권장
    temperature: 0
```

#### Gemma 가 OpenAI provider 와 다르다는 점에 대한 해결

Gemma 를 vLLM / Ollama / llama.cpp 같은 OpenAI 호환 서버로 띄워 사용할 경우,
`tools` / function calling 을 정식 지원하지 않는 경우가 많습니다.
`core/llm_factory.py` 의 `RoleLLM.with_structured_output()` 은 다음 순서로 자동
fallback 하여 이 차이를 흡수합니다.

1. provider 가 `gemma` 이면 `json_mode` → `json_schema` 를 먼저 시도
2. 그래도 실패하면 **JSON Schema 를 프롬프트에 주입하고 응답에서 JSON 만 추출**하는
   `_JsonPromptStructuredLLM` 으로 최종 fallback

따라서 그래프 노드 코드(`graph/nodes.py`)는 OpenAI 모델과 Gemma 모델 모두에서
같은 인터페이스(`with_structured_output(...)`)로 동작합니다.

#### Fallback 우선순위

- MCP Base URL: `app_config.yaml.mcp.base_url` → `MCP_BASE_URL` → `http://localhost:8000/mcp`
- Reasoning LLM 필드: `app_config.yaml.llm.reasoning.*` → `app_config.yaml.llm.*` (legacy)
  → `REASONING_LLM_*` env → `INTERNAL_LLM_*` env → `OPENAI_*` env → 하드코딩 기본값
- Task LLM 필드: `app_config.yaml.llm.task.*` → `app_config.yaml.llm.*` (legacy)
  → `TASK_LLM_*` env → `INTERNAL_LLM_*` env → `OPENAI_*` env → 하드코딩 기본값 (Gemma)

> 보안상 `api_key` 는 빈 문자열로 두고 환경변수로 주입하는 것을 권장합니다.
> 한쪽 LLM 만 설정해도 동작하며, `task` 가 비어 있으면 `reasoning` LLM 이 양쪽에 사용됩니다.