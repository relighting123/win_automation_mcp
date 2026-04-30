def register_app_mgmt_tools(*args, **kwargs):
    from .app_mgmt_tool import register_app_mgmt_tools as _register_app_mgmt_tools

    return _register_app_mgmt_tools(*args, **kwargs)


def register_app_control_tools(*args, **kwargs):
    from .app_control_tool import register_app_control_tools as _register_app_control_tools

    return _register_app_control_tools(*args, **kwargs)


def register_skill_tools(*args, **kwargs):
    from .skill_tool import register_skill_tools as _register_skill_tools

    return _register_skill_tools(*args, **kwargs)


__all__ = ["register_app_control_tools", "register_app_mgmt_tools", "register_skill_tools"]
