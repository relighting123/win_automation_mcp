
import asyncio
import logging
import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from actions.app_ui_action import get_app_ui_action

async def verify_fix():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
    action = get_app_ui_action()
    
    print("\n--- Testing find_text_position('파일') ---")
    # This should now succeed via UIA first
    result = await action.find_text_position("파일", timeout=3.0)
    
    if result.is_success:
        print(f"SUCCESS: Found '파일' at ({result.x}, {result.y})")
        print(f"Matched Text: {result.matched_text}")
    else:
        print(f"FAILURE: {result.result} - {result.message}")

    print("\n--- Testing with a non-existent text (Timeout check) ---")
    start_time = asyncio.get_event_loop().time()
    result_fail = await action.find_text_position("존재하지않는텍스트123", timeout=1.0)
    end_time = asyncio.get_event_loop().time()
    
    print(f"Result: {result_fail.result} - {result_fail.message}")
    print(f"Duration: {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(verify_fix())
