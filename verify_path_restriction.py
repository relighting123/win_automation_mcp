
import asyncio
import logging
import sys
import os
import psutil

# Add the project root to sys.path
sys.path.append(os.getcwd())

from actions.app_ui_action import get_app_ui_action
from core.app_session import AppSession

async def verify_restriction():
    logging.basicConfig(level=logging.INFO)
    session = AppSession.get_instance()
    action = get_app_ui_action(session)
    
    config = session.config
    target_path = config.get("application", {}).get("executable_path")
    print(f"Target Path from Config: {target_path}")

    print("\n--- Testing _pick_target_window() ---")
    wrapper = action._pick_target_window()
    if wrapper:
        pid = wrapper.element_info.process_id
        proc = psutil.Process(pid)
        actual_path = proc.exe()
        print(f"Picked Window Title: {wrapper.window_text()}")
        print(f"Actual Process Path: {actual_path}")
        
        if actual_path.lower().replace('/', '\\') == target_path.lower().replace('/', '\\'):
            print("SUCCESS: Picked window matches target path.")
        else:
            print("FAILURE: Picked window DOES NOT match target path!")
    else:
        print("No target window found (This might be expected if the app is not running)")

    print("\n--- Testing with find_text_position('File') ---")
    # Even if it finds 'File' in Antigravity, it should now ignore it if it's not the correct process.
    result = await action.find_text_position("File", timeout=2.0)
    if result.is_success:
        print(f"Found 'File' at ({result.x}, {result.y})")
        # Check if this position belongs to the correct window
        # (This is harder to check without actual clicking but logs should show path matching)
    else:
        print(f"Result: {result.result} - {result.message}")

if __name__ == "__main__":
    asyncio.run(verify_restriction())
