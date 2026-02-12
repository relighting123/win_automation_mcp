# Errors module - Custom exception classes
from .automation_error import (
    AutomationError,
    ConnectionError,
    ElementNotFoundError,
    ActionFailedError,
    TimeoutError,
    LoginError,
    SessionError,
)

__all__ = [
    "AutomationError",
    "ConnectionError",
    "ElementNotFoundError",
    "ActionFailedError",
    "TimeoutError",
    "LoginError",
    "SessionError",
]
