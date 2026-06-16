def register_app_mgmt_tools(*args, **kwargs):
    from .app_mgmt_tool import register_app_mgmt_tools as _register_app_mgmt_tools

    return _register_app_mgmt_tools(*args, **kwargs)


def register_app_control_tools(*args, **kwargs):
    from .app_control_tool import register_app_control_tools as _register_app_control_tools

    return _register_app_control_tools(*args, **kwargs)


def register_skill_tools(*args, **kwargs):
    from .skill_tool import register_skill_tools as _register_skill_tools

    return _register_skill_tools(*args, **kwargs)


def register_data_analysis_tools(*args, **kwargs):
    from .data_analysis_tool import register_data_analysis_tools as _register_data_analysis_tools

    return _register_data_analysis_tools(*args, **kwargs)


def register_source_edit_tools(*args, **kwargs):
    from .source_edit_tool import register_source_edit_tools as _register_source_edit_tools

    return _register_source_edit_tools(*args, **kwargs)


def register_url_fetch_tools(*args, **kwargs):
    from .url_fetch_tool import register_url_fetch_tools as _register_url_fetch_tools

    return _register_url_fetch_tools(*args, **kwargs)


def register_chrome_url_fetch_tools(*args, **kwargs):
    from .chrome_url_fetch_tool import register_chrome_url_fetch_tools as _register

    return _register(*args, **kwargs)


__all__ = [
    "register_app_control_tools",
    "register_app_mgmt_tools",
    "register_data_analysis_tools",
    "register_source_edit_tools",
    "register_skill_tools",
    "register_url_fetch_tools",
    "register_chrome_url_fetch_tools",
]
