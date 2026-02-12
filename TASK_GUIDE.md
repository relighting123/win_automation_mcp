# Task 추가 가이드 (예시 포함)

이 프로젝트에서 "task"는 **MCP tool**을 의미합니다.  
추가 흐름은 **UI → Action → Tool → 등록** 순서입니다.

## 예시: 특정 RGB 찾고 마우스 우클릭
UIA로 접근이 어려운 경우에만 사용하는 방식입니다.  
픽셀 기반이므로 해상도/테마/스케일링에 민감합니다.

### 1) (선택) 의존성 추가
픽셀 탐색을 위해 `pyautogui`와 `Pillow`를 사용한다고 가정합니다.

```txt
# requirements.txt
pyautogui>=0.9.54
Pillow>=10.0.0
```

### 2) Action 추가
`actions/`에 업무 로직을 추가합니다. (예: `actions/color_click_action.py`)

```python
from typing import Iterable
import pyautogui


class ColorClickAction:
    def __init__(self, rgb: tuple[int, int, int], tolerance: int = 5):
        self.rgb = rgb
        self.tolerance = tolerance

    def _match(self, pixel: Iterable[int]) -> bool:
        return all(abs(p - t) <= self.tolerance for p, t in zip(pixel, self.rgb))

    def find_and_right_click(self) -> dict:
        screenshot = pyautogui.screenshot()
        width, height = screenshot.size
        pixels = screenshot.load()

        for y in range(height):
            for x in range(width):
                if self._match(pixels[x, y]):
                    pyautogui.moveTo(x, y)
                    pyautogui.click(button="right")
                    return {"result": "success", "x": x, "y": y}

        return {"result": "not_found", "message": "RGB not found"}
```

### 3) Tool 추가
`tools/`에 MCP tool 함수를 추가합니다. (예: `tools/color_click_tool.py`)

```python
from typing import Any
from actions.color_click_action import ColorClickAction


def register_color_click_tools(mcp: Any) -> None:
    @mcp.tool()
    def right_click_by_rgb(r: int, g: int, b: int, tolerance: int = 5) -> dict:
        """
        화면에서 특정 RGB 픽셀을 찾아 마우스를 이동한 후 우클릭합니다.

        Args:
            r (int): Red (0~255)
            g (int): Green (0~255)
            b (int): Blue (0~255)
            tolerance (int): RGB 허용 오차
        """
        action = ColorClickAction((r, g, b), tolerance)
        return action.find_and_right_click()
```

### 4) Tool 등록
`mcp_server.py`의 `register_all_tools()`에 등록을 추가합니다.

```python
from tools.color_click_tool import register_color_click_tools

def register_all_tools() -> None:
    # ... 기존 도구 등록
    register_color_click_tools(mcp)
```

### 5) 실행/테스트
- 서버 실행: `python mcp_server.py`
- Cursor에서 `MCP: Run Tool` → `right_click_by_rgb` 호출

---

## 체크리스트
- `locator.yaml`에 요소 추가했는지
- `UI → Action → Tool` 계층 분리가 지켜졌는지
- Tool docstring이 명확한지
- `register_all_tools()`에 등록했는지

