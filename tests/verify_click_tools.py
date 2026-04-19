import asyncio
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tools.app_control_tool import (
    click_element_by_title,
    click_element_by_uid
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    print("\n--- Testing click_element_by_title ---")
    try:
        # Notepad++ 윈도우 제목을 찾아 클릭 (포커스용)
        print("Clicking 'Notepad++' window title...")
        res = await click_element_by_title(keyword="Notepad++", match_mode="contains")
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error: {e}")

    print("\n--- Testing click_element_by_uid ---")
    try:
        # Notepad++의 MenuBar AutomationId 등을 시도 (환경에 따라 다를 수 있음)
        print("Clicking UID 'MenuBar' (Notepad++ specific)...")
        res = await click_element_by_uid(uid="MenuBar")
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
