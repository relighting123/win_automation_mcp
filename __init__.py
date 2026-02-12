# win_mcp - FastMCP 기반 Windows 자동화 서버
"""
FastMCP + pywinauto 기반 Windows 프로그램 자동화 서버

아키텍처:
    LLM → FastMCP Server → Tools → Actions → UI → pywinauto

계층 구조:
    - tools/: FastMCP tool 정의 (업무 의미 단위 인터페이스)
    - actions/: 업무 로직 구현 (UI 조합)
    - ui/: Page Object Pattern 기반 UI 접근
    - core/: pywinauto 래퍼 및 유틸리티
"""

__version__ = "1.0.0"
__author__ = "Windows Automation Team"
