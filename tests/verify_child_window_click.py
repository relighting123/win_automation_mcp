import asyncio
import sys
import os
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.append(str(Path(__file__).resolve().parent.parent))

from actions.app_ui_action import get_app_ui_action
from core.app_session import AppSession

async def main():
    # Notepad++가 실행 중이라고 가정
    # auto_id="Close" 또는 title="닫기" 버튼을 찾아 클릭하는 테스트
    
    action = get_app_ui_action()
    
    print("Testing click_child_window with auto_id='Close' and control_type='Button'...")
    # 실제 환경에서는 Notepad++의 닫기 버튼 auto_id가 다를 수 있으나, 예시로 구현된 로직 확인용
    result = action.click_child_window(auto_id="Close", control_type="Button", timeout=2.0)
    print(f"Result: {result.to_dict()}")

if __name__ == "__main__":
    asyncio.run(main())
