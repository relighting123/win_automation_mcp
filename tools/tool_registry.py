from typing import Callable, Dict


def get_skill_tool_registry() -> Dict[str, Callable]:
    """SequenceSkill에서 사용할 MCP tool 호출 맵을 반환합니다."""
    from tools.app_control_tool import (
        click_app_by_attr,
        click_app_by_keyword,
        click_app_by_text,
        click_app_position,
        click_at_focus,
        find_app_by_ocr,
        get_app_coords_by_attr,
        highlight_app_by_attr,
        press_app_shortcut,
        right_click_at_focus,
        type_app_text,
    )
    from tools.app_mgmt_tool import (
        close_application,
        close_window,
        connect_to_application,
        generate_locators,
        get_connection_status,
        launch_application,
        restart_application,
    )
    from tools.data_analysis_tool import read_clipboard_as_dataframe
    from tools.oracle_db_tool import query_oracle_db
    from tools.source_edit_tool import find_text_in_file, replace_text_in_file

    return {
        # app_mgmt_tool
        "launch_application": launch_application,
        "connect_to_application": connect_to_application,
        "close_window": close_window,
        "close_application": close_application,
        "restart_application": restart_application,
        "get_connection_status": get_connection_status,
        "generate_locators": generate_locators,
        # app_control_tool
        "find_app_by_ocr": find_app_by_ocr,
        "click_app_by_text": click_app_by_text,
        "type_app_text": type_app_text,
        "press_app_shortcut": press_app_shortcut,
        "click_at_focus": click_at_focus,
        "right_click_at_focus": right_click_at_focus,
        "click_app_position": click_app_position,
        "click_app_by_keyword": click_app_by_keyword,
        "click_app_by_attr": click_app_by_attr,
        "highlight_app_by_attr": highlight_app_by_attr,
        "get_app_coords_by_attr": get_app_coords_by_attr,
        # data_analysis_tool
        "read_clipboard_as_dataframe": read_clipboard_as_dataframe,
        # source_edit_tool
        "find_text_in_file": find_text_in_file,
        "replace_text_in_file": replace_text_in_file,
        # oracle_db_tool
        "query_oracle_db": query_oracle_db,
    }
