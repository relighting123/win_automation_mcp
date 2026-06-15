# chatRTD — Windows Automation Scheduler

Windows 프로그램을 자동화하는 MCP 기반 에이전트입니다.  
`chatRTD` CLI를 실행하면 MCP 서버가 자동으로 시작되고, 자연어로 자동화를 지시할 수 있습니다.

---

## 목차

1. [요구사항](#요구사항)
2. [빠른 시작](#빠른-시작-5분)
3. [설정 파일 상세 설명](#설정-파일-상세-설명)
4. [chatRTD CLI 사용법](#chatrtd-cli-사용법)
5. [자동화 그래프 (`/analyze`)](#자동화-그래프-analyze)
6. [아키텍처 개요](#아키텍처-개요)
7. [라이선스](#라이선스)

---

## 요구사항

| 항목 | 버전 |
|------|------|
| Python | 3.10 이상 |
| OS | Windows 10 / 11 |
| pip | 최신 버전 권장 |

> **주의**: `pywinauto`, `winocr`는 Windows 전용입니다. Linux/macOS에서는 MCP 서버 실행 및 CLI 테스트만 가능합니다.

---

## 빠른 시작 (5분)

### 1단계 — 저장소 클론

```bash
git clone https://github.com/relighting123/win_automation_mcp.git
cd win_automation_mcp
```

### 2단계 — 의존성 설치

```bash
pip install -r requirements.txt
```

> OCR 기능(`winocr`)은 Windows 전용입니다. 설치 중 오류가 나면 `pip install -r requirements.txt --ignore-requires-python`으로 건너뛸 수 있습니다.

### 3단계 — chatRTD 명령어 등록

```bash
pip install -e .
```

이제 터미널 어디서나 `chatRTD`를 실행할 수 있습니다.

### 4단계 — 설정 파일 복사

```bash
copy .env.example .env
copy config\app_config.yaml.example config\app_config.yaml
copy config\skills.yaml.example config\skills.yaml
```

> Linux/macOS: `cp` 사용

### 5단계 — 앱 경로 설정

`config/app_config.yaml`을 열어 자동화할 프로그램 경로를 입력합니다:

```yaml
application:
  executable_path: "C:\\Program Files\\YourApp\\app.exe"
  process_name: "app.exe"
  backend: "uia"
  startup_timeout: 30
```

### 6단계 — API 키 설정

`.env` 파일을 열어 LLM API 키를 입력하거나, `config/app_config.yaml`의 `llm.api_key`에 직접 입력합니다:

```dotenv
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=mixtral-8x7b-32768
```

또는 모델 등록 없이 바로 CLI에서 추가할 수도 있습니다 (7단계 참고).

### 7단계 — chatRTD 실행

```bash
chatRTD
```

MCP 서버가 자동으로 백그라운드에서 시작됩니다.

```
┌─────────────────────────────────────────────────────────┐
│       chatRTD   Automation Scheduler   v0.1.0          │
│   Server : http://localhost:8000/mcp                    │
│   Model  : (none)   /models add 로 등록하세요           │
│   /help 도움말  |  Ctrl+C 종료                          │
└─────────────────────────────────────────────────────────┘
[task] >
```

### 8단계 — 모델 등록 및 선택

```
[task] > /models add groq --api-key sk-xxx --base-url https://api.groq.com/openai/v1 --model mixtral-8x7b-32768
[task] > /models select groq
```

### 9단계 — 첫 자동화 실행

```
[task] > 메모장을 열어서 오늘 날짜를 입력해줘
```

---

## 설정 파일 상세 설명

### `config/app_config.yaml`

```yaml
application:
  executable_path: "C:\\Program Files\\YourApp\\app.exe"  # 실행 파일 경로
  process_name: "app.exe"                                  # 프로세스 이름
  backend: "uia"                                           # pywinauto 백엔드
  startup_timeout: 30                                      # 시작 대기 시간(초)
  automation_speed: "fast"                                 # 자동화 속도

timeouts:
  default_wait: 10       # 기본 UI 대기(초)
  long_wait: 60          # 긴 작업 대기(초)
  short_wait: 3

llm:
  provider: "openai_compatible"
  base_url: "https://api.groq.com/openai/v1"
  model: "mixtral-8x7b-32768"
  api_key: ""            # 비워두고 .env 사용 권장

  profiles:
    execution:           # 경량 실행용 모델
      base_url: "http://localhost:1234/v1"
      model: "gemma-3-4b-it"
    planning:            # 계획 수립용 모델
      base_url: "https://api.openai.com/v1"
      model: "gpt-4.1-mini"
    analysis:            # 분석용 모델
      base_url: "https://api.openai.com/v1"
      model: "gpt-4.1"
    reporting:           # 리포트 생성용 모델
      base_url: "https://api.openai.com/v1"
      model: "gpt-4.1"
```

### `.env`

```dotenv
# MCP 서버 URL
MCP_BASE_URL=http://localhost:8000/mcp

# 기본 LLM 설정
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_MODEL=mixtral-8x7b-32768

# 사내 LLM (있는 경우, OPENAI_* 보다 우선)
INTERNAL_LLM_BASE_URL=
INTERNAL_LLM_API_KEY=
INTERNAL_LLM_MODEL=
```

**우선순위**: `config/app_config.yaml` > 환경변수(`.env`) > 코드 기본값

### `~/.chatRTD/config.json` (CLI 전용)

`/models add`로 등록한 모델들이 여기에 저장됩니다. 직접 편집할 수도 있습니다:

```json
{
  "active_model": "groq",
  "mcp_url": "http://localhost:8000/mcp",
  "models": {
    "groq": {
      "api_key": "sk-xxx",
      "base_url": "https://api.groq.com/openai/v1",
      "model": "mixtral-8x7b-32768"
    },
    "openai": {
      "api_key": "sk-yyy",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-4o"
    }
  }
}
```

---

## chatRTD CLI 사용법

### 실행 옵션

```bash
chatRTD                            # 대화형 (저장된 모델 사용)
chatRTD "메모장에 hello 써줘"      # 단일 명령 실행 후 종료
chatRTD --no-server                # MCP 서버 자동 시작 안 함
chatRTD --server-url http://...    # 이 세션만 MCP URL 변경
chatRTD --model groq               # 이 세션만 모델 변경
chatRTD --api-key sk-xxx           # 이 세션만 API 키 변경
```

### 슬래시 명령어

| 명령어 | 설명 |
|--------|------|
| `/help` | 도움말 출력 |
| `/exit`, `/quit` | 종료 |
| `/clear` | 대화 초기화 |
| `/tools` | 사용 가능한 MCP 도구 목록 |
| `/skills` | 등록된 스킬 목록 |
| `/skill <id>` | 특정 스킬 직접 실행 |
| `/models` | 등록된 모델 목록 및 현재 활성 모델 |
| `/models add <이름> --api-key <키> --base-url <URL> --model <모델>` | 모델 등록 |
| `/models select <이름>` | 활성 모델 전환 |
| `/models remove <이름>` | 모델 삭제 |
| `/config` | MCP URL 등 전역 설정 표시 |
| `/config set mcp-url <URL>` | MCP 서버 URL 변경 |
| `/analyze [모드] <작업>` | LangGraph 자동화 그래프 실행 |

### 실행 예시

```
[task] > /models add groq --api-key sk-xxx --base-url https://api.groq.com/openai/v1 --model mixtral-8x7b-32768
  ✓  groq 등록 완료

[task] > /models select groq
  ✓  Switched to groq  (mixtral-8x7b-32768)

[task] > 메모장 열어서 오늘 날짜 써줘

⠸  Thinking...

── Tool Call ──────────────────────────────────────
  ◆  launch_application  {"executable_path": "notepad.exe"}
     → {"status": "ok", "message": "실행 완료"}
  ◆  type_app_text  {"text": "2026-06-10"}
     → {"status": "ok"}
────────────────────────────────────────────────────

메모장을 열고 오늘 날짜(2026-06-10)를 입력했습니다.
```

---

## 자동화 그래프 (`/analyze`)

복잡한 다단계 자동화는 `/analyze` 명령어로 LangGraph 오케스트레이터를 호출합니다.

### 모드 선택

| 모드 | 설명 |
|------|------|
| `auto` | LLM이 자유롭게 계획 수립 및 개입 |
| `semi` | 순차 실행 + 상황별 LLM 개입 (기본값) |
| `manual` | 질의로 스킬 선택, YAML 단계 엄격 실행 (상황 체크·LLM 인자 추출 생략) |

### 사용법

```
[task] > /analyze 메모장 열어서 오늘 날짜 입력해줘
[task] > /analyze semi 로그인 후 재무 분석 실행하고 결과 내보내기
[task] > /analyze auto 상황을 판단해서 최적의 분석 방법으로 실행해줘
[task] > /analyze manual 로그인 후 데이터 파일 열어줘
```

### 자동화 그래프 아키텍처

```
query
  │
  ▼
┌─────────┐    ┌──────────────────┐    ┌──────────┐
│  plan   │───▶│ check_situation  │───▶│ extract  │
│  (LLM)  │    │  (LLM, semi/auto)│    │  (LLM)   │
└─────────┘    └──────────────────┘    └──────────┘
                                            │
                                            ▼
                                       ┌──────────┐
                                       │   run    │
                                       │  (MCP)   │
                                       └──────────┘
                                            │
                               ┌───────────┤
                               ▼           ▼
                          ┌────────┐  ┌─────────┐
                          │  next  │  │ report  │
                          │  step  │  │  (LLM)  │
                          └────────┘  └─────────┘
```

### 스킬 정의 (`config/skills.yaml`)

```yaml
skills:
  - id: login_skill
    name: "로그인"
    steps:
      - tool: connect_to_application
        args: {}
      - tool: login
        args:
          username: "{{username}}"
          password: "{{password}}"
```

---

## 아키텍처 개요

```
chatRTD CLI
    │  자연어 지시 / /analyze
    ▼
┌──────────────────────────────────────────┐
│           FastMCP Server                 │
│           (mcp_server.py)                │
│  ┌────────────────────────────────────┐  │
│  │         Tools Layer                │  │
│  │  app_tool | desktop_tool | ...     │  │
│  └────────────────────────────────────┘  │
│                    │                     │
│                    ▼                     │
│  ┌────────────────────────────────────┐  │
│  │         Actions Layer              │  │
│  │  login_action | run_action | ...   │  │
│  └────────────────────────────────────┘  │
│                    │                     │
│                    ▼                     │
│  ┌────────────────────────────────────┐  │
│  │          Core Layer                │  │
│  │  app_session | app_launcher | ...  │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
                    │
                    │ pywinauto (backend="uia")
                    ▼
          Windows Application
```

### 프로젝트 구조

```
win_automation_mcp/
├── cli.py                    # chatRTD CLI 진입점
├── mcp_server.py             # FastMCP 서버
├── mcp_client.py             # MCP HTTP 클라이언트
├── pyproject.toml            # 패키지 설정 (chatRTD 명령어 등록)
├── requirements.txt
│
├── config/
│   ├── app_config.yaml.example   # 설정 템플릿 (복사 후 사용)
│   ├── skills.yaml.example       # 스킬 템플릿 (복사 후 사용)
│   └── locator.yaml              # UI 요소 locator
│
├── graph/
│   ├── automation_graph.py   # LangGraph 오케스트레이터
│   ├── nodes.py              # 그래프 노드 구현
│   └── llm_factory.py        # LLM 프로바이더 팩토리
│
├── skills/
│   ├── sequence_skill.py     # 순차 스킬 실행기
│   └── (스킬 폴더들)
│
├── core/
│   ├── app_launcher.py       # 앱 실행/종료 관리
│   ├── app_session.py        # pywinauto 래퍼
│   └── wait_utils.py         # wait/retry 유틸리티
│
├── actions/                  # 업무 로직 구현
├── tools/                    # FastMCP tool 함수 정의
└── errors/                   # 커스텀 예외 클래스
```

---

## MCP 서버만 단독 실행

chatRTD를 사용하지 않고 MCP 서버만 별도로 실행할 수도 있습니다:

```bash
# HTTP 방식 (기본)
python mcp_server.py --transport http --host 127.0.0.1 --port 8000 --path /mcp

# SSE 방식 (파일 변경 시 자동 재시작)
python mcp_server.py --transport sse --port 8000 --reload

# 로그 레벨 지정
python mcp_server.py --log-level DEBUG
```

Claude Desktop, Cursor 등 MCP 클라이언트에서 `http://localhost:8000/mcp`로 연결할 수 있습니다.

---

## 라이선스

MIT License
