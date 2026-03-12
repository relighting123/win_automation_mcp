import yaml
import logging
from pathlib import Path
from typing import Dict, Any
import sys

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.app_session import AppSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def extract_window_info(window_spec: Any) -> Dict[str, Any]:
    """윈도우 기본 정보 추출"""
    wrapper = window_spec.wrapper_object()
    return {
        "title": wrapper.window_text(),
        "control_type": wrapper.control_type(),
        "auto_id": wrapper.automation_id()
    }

def extract_elements(window_spec: Any) -> Dict[str, Any]:
    """주요 UI 요소 추출"""
    elements = {}
    # 주요 컨트롤 타입 정의
    target_types = ["Button", "Edit", "Text", "CheckBox", "ComboBox", "MenuItem", "DataGrid", "Tree"]
    
    wrapper = window_spec.wrapper_object()
    children = wrapper.descendants()
    
    for child in children:
        c_type = child.control_type()
        auto_id = child.automation_id()
        name = child.window_text()
        
        if c_type in target_types and auto_id:
            # 중복 방지를 위해 auto_id를 키의 일부로 사용하거나 이름을 생성
            element_key = auto_id.lower().replace(" ", "_")
            if not element_key:
                element_key = f"{c_type.lower()}_{len(elements)}"
                
            elements[element_key] = {
                "auto_id": auto_id,
                "control_type": c_type,
                "description": f"{name} ({c_type})" if name else f"{c_type}"
            }
            
    return elements

def update_locator_yaml(window_type: str, window_info: Dict[str, Any], elements: Dict[str, Any]):
    """locator.yaml 업데이트"""
    locator_path = project_root / "config" / "locator.yaml"
    print(f"DEBUG: Attempting to update {locator_path}")
    
    if locator_path.exists():
        with open(locator_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        print(f"DEBUG: File not found, creating new one: {locator_path}")
        data = {}
        
    data[window_type] = {
        "window": window_info,
        "elements": elements
    }
    
    with open(locator_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
    print(f"SUCCESS: Updated {window_type} in {locator_path}")
    logger.info(f"Updated {locator_path} with {window_type}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate UI Locators for the target application")
    parser.add_argument(
        "--type",
        default=None,
        help="저장할 윈도우 키 이름 (기본: active_window)",
    )
    args = parser.parse_args()
    
    print(f"DEBUG: Project Root identified as: {project_root}")
    
    session = AppSession.get_instance()
    try:
        print(f"DEBUG: Connecting to application defined in app_config.yaml...")
        session.connect()
        print(f"DEBUG: Connected to app successfully.")
    except Exception as e:
        print(f"ERROR: Failed to connect to application: {e}")
        return

    try:
        windows = session.app.windows()
        print(f"DEBUG: Found {len(windows)} windows for the application.")
        
        if not windows:
            print("ERROR: No windows found for the target application.")
            return
            
        target_window = None
        for i, win in enumerate(windows):
            title = win.window_text()
            visible = win.is_visible()
            print(f"DEBUG: Window {i}: Title='{title}', Visible={visible}")
            if visible and target_window is None:
                target_window = win
        
        if not target_window:
            target_window = windows[0]
            
        window_info = extract_window_info(target_window)
        print(f"DEBUG: Target Window Info: {window_info}")
        
        # 윈도우 타입 결정
        win_type = args.type
        if not win_type:
            win_type = "active_window"
                
        print(f"DEBUG: Using window type: {win_type}")
        
        elements = extract_elements(target_window)
        print(f"DEBUG: Extracted {len(elements)} elements.")
        
        update_locator_yaml(win_type, window_info, elements)
        
    except Exception as e:
        print(f"ERROR: Exception during extraction: {e}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
