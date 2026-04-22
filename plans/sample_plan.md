# Sample Automation Plan

아래 JSON 배열이 실행 plan입니다. 각 step은 정의된 순서대로 실행됩니다.

```json
[
  {
    "tool": "launch_application",
    "args": {
      "executable_path": "notepad.exe"
    }
  },
  {
    "tool": "type_app_text",
    "args": {
      "text": "plan md 기반 순차 실행 테스트"
    }
  }
]
```
