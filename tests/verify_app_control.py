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
    find_element_by_title_or_uid,
    find_element_by_auto_id,
    find_element_by_ocr
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    print("\n--- Testing find_element_by_title_or_uid ---")
    try:
        print("Finding 'Notepad++'...")
        res = await find_element_by_title_or_uid(keyword="Notepad++")
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error: {e}")

    print("\n--- Testing find_element_by_auto_id ---")
    try:
        print("Finding auto_id 'MenuBar'...")
        res = await find_element_by_auto_id(auto_id="MenuBar")
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error: {e}")

    print("\n--- Testing find_element_by_ocr ---")
    try:
        print("Finding OCR keyword 'File'...")
        res = await find_element_by_ocr(keyword="File")
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
