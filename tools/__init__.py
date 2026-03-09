# Tools module - FastMCP tool definitions
from .app_tool import register_app_tools
from .desktop_tool import register_desktop_tools
from .login_tool import register_login_tools
from .run_tool import register_run_tools
from .source_open_tool import register_source_open_tools

__all__ = [
    "register_desktop_tools",
    "register_login_tools",
    "register_run_tools",
    "register_app_tools",
    "register_source_open_tools",
]
