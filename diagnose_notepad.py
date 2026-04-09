
import asyncio
import logging
import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from actions.app_ui_action import get_app_ui_action

async def diagnose_find_text():
    logging.basicConfig(level=logging.INFO)
    action = get_app_ui_action()
    
    print("--- 1. UIA Check ---")
    components, hits, window = action._collect_uia_components(keyword="파일")
    if hits:
        print(f"UIA found '파일' at: x={hits[0]['x']}, y={hits[0]['y']}")
        print(f"Control Type: {hits[0]['control_type']}, Title: {hits[0]['title']}")
    else:
        print("UIA did NOT find '파일'")

    print("\n--- 2. OCR Check (English - Default) ---")
    res_eng = await action.find_text_position("파일", language="eng", timeout=2.0)
    if res_eng.is_success:
        print(f"OCR (eng) found '파일' at: x={res_eng.x}, y={res_eng.y}")
    else:
        print(f"OCR (eng) failed: {res_eng.message}")

    print("\n--- 3. OCR Check (Korean) ---")
    res_kor = await action.find_text_position("파일", language="kor", timeout=2.0)
    if res_kor.is_success:
        print(f"OCR (kor) found '파일' at: x={res_kor.x}, y={res_kor.y}")
    else:
        print(f"OCR (kor) failed: {res_kor.message}")

if __name__ == "__main__":
    asyncio.run(diagnose_find_text())
