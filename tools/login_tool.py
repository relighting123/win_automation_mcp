"""
FastMCP 로그인 Tool 정의

LLM이 호출할 수 있는 로그인 관련 도구들을 정의합니다.
Tool 함수는 Actions 계층만 호출하며, pywinauto를 직접 사용하지 않습니다.

주의:
- Tool 함수 안에 UI locator를 작성하지 않습니다
- Tool 함수 안에 LLM 판단 로직을 넣지 않습니다
- pywinauto 직접 호출을 금지합니다
"""

import logging
from typing import Optional, Any

from actions.login_action import LoginAction, LoginResponse, get_login_action
from errors.automation_error import AutomationError

logger = logging.getLogger(__name__)


def register_login_tools(mcp: Any) -> None:
    """
    FastMCP 서버에 로그인 관련 도구 등록
    
    Args:
        mcp: FastMCP 서버 인스턴스
    """
    
    @mcp.tool()
    async def login(
        username: str,
        password: str,
        remember_me: bool = False
    ) -> dict:
        """
        애플리케이션에 로그인합니다.
        
        이 도구는 대상 Windows 애플리케이션에 사용자 인증을 수행합니다.
        로그인 윈도우에 사용자명과 비밀번호를 입력하고 로그인 버튼을 클릭합니다.
        
        Args:
            username: 로그인할 사용자명
            password: 사용자 비밀번호
            remember_me: 자동 로그인 옵션 활성화 여부 (기본: False)
        
        Returns:
            dict: 로그인 결과
                - is_success (bool): 로그인 성공 여부
                - result (str): 결과 상태 (success, invalid_credentials, timeout 등)
                - message (str): 결과 메시지
                - username (str): 로그인 시도한 사용자명
                - error_detail (str, optional): 오류 상세 정보
        
        Examples:
            >>> await login("admin", "password123")
            {"is_success": True, "result": "success", "message": "로그인에 성공했습니다", ...}
            
            >>> await login("user", "wrong_password")
            {"is_success": False, "result": "invalid_credentials", "message": "로그인 실패: 잘못된 자격 증명", ...}
        """
        try:
            action = get_login_action()
            from actions.login_action import LoginResult, LoginResponse
            
            # 1. 로그인 윈도우 대기 (Atomic Action)
            timeout = 30.0 # 기본 대기 시간
            if not action.wait_for_login_window(timeout=timeout):
                return {
                    "is_success": False,
                    "result": "timeout",
                    "message": "로그인 윈도우가 나타나지 않았습니다",
                    "username": username
                }
            
            # 2. 로그인 준비 (Atomic Action - 입력 필드 초기화 등)
            if not action.prepare_login(timeout=5.0):
                return {
                    "is_success": False,
                    "result": "error",
                    "message": "로그인 화면 준비 실패",
                    "username": username
                }
            
            # 3. 로그인 정보 입력 및 실행 (Atomic Action)
            if not action.perform_login_inputs(
                username=username,
                password=password,
                remember_me=remember_me
            ):
                return {
                    "is_success": False,
                    "result": "error",
                    "message": "로그인 정보 입력 실패",
                    "username": username
                }
            
            # 4. 결과 확인 (Atomic Action)
            response: LoginResponse = action.check_result(username, timeout=timeout)
            
            result = response.to_dict()
            logger.info(f"[Tool] login 결과: {result['result']}")
            
            return result
            
        except AutomationError as e:
            logger.error(f"[Tool] login 오류: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": str(e),
                "username": username,
                "error_detail": e.to_dict() if hasattr(e, "to_dict") else str(e)
            }
        except Exception as e:
            logger.error(f"[Tool] login 예외: {e}")
            return {
                "is_success": False,
                "result": "error",
                "message": f"로그인 중 오류 발생: {e}",
                "username": username,
                "error_detail": str(e)
            }
    
    @mcp.tool()
    async def logout() -> dict:
        """
        현재 로그인된 세션에서 로그아웃합니다.
        
        애플리케이션의 로그아웃 기능을 실행하여 현재 세션을 종료합니다.
        로그아웃 후에는 다시 login 도구를 사용하여 로그인해야 합니다.
        
        Returns:
            dict: 로그아웃 결과
                - success (bool): 로그아웃 성공 여부
                - message (str): 결과 메시지
        
        Examples:
            >>> await logout()
            {"success": True, "message": "로그아웃 완료"}
        """
        logger.info("[Tool] logout 호출")
        
        try:
            action = get_login_action()
            success = action.logout()
            
            result = {
                "success": success,
                "message": "로그아웃 완료" if success else "로그아웃 실패"
            }
            logger.info(f"[Tool] logout 결과: {result}")
            
            return result
            
        except AutomationError as e:
            logger.error(f"[Tool] logout 오류: {e}")
            return {
                "success": False,
                "message": str(e),
                "error_detail": e.to_dict() if hasattr(e, "to_dict") else str(e)
            }
        except Exception as e:
            logger.error(f"[Tool] logout 예외: {e}")
            return {
                "success": False,
                "message": f"로그아웃 중 오류 발생: {e}",
                "error_detail": str(e)
            }
    
    @mcp.tool()
    async def check_login_status() -> dict:
        """
        현재 로그인 상태를 확인합니다.
        
        애플리케이션이 현재 로그인된 상태인지 확인합니다.
        로그인 윈도우가 표시되면 미로그인 상태, 메인 윈도우가 표시되면 로그인 상태입니다.
        
        Returns:
            dict: 상태 정보
                - is_logged_in (bool): 로그인 상태 여부
                - message (str): 상태 설명
        
        Examples:
            >>> await check_login_status()
            {"is_logged_in": True, "message": "현재 로그인 상태입니다"}
            
            >>> await check_login_status()
            {"is_logged_in": False, "message": "로그인이 필요합니다"}
        """
        logger.info("[Tool] check_login_status 호출")
        
        try:
            action = get_login_action()
            is_logged_in = action.is_logged_in()
            
            result = {
                "is_logged_in": is_logged_in,
                "message": "현재 로그인 상태입니다" if is_logged_in else "로그인이 필요합니다"
            }
            logger.info(f"[Tool] check_login_status 결과: {result}")
            
            return result
            
        except AutomationError as e:
            logger.error(f"[Tool] check_login_status 오류: {e}")
            return {
                "is_logged_in": False,
                "message": f"상태 확인 실패: {e}",
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"[Tool] check_login_status 예외: {e}")
            return {
                "is_logged_in": False,
                "message": f"상태 확인 중 오류 발생: {e}",
                "error": str(e)
            }
    
    @mcp.tool()
    async def wait_for_login_window(timeout: float = 30.0) -> dict:
        """
        로그인 윈도우가 나타날 때까지 대기합니다.
        
        애플리케이션 실행 후 로그인 윈도우가 나타날 때까지 대기합니다.
        이 도구는 애플리케이션 시작 직후나 로그아웃 후 사용합니다.
        
        Args:
            timeout: 최대 대기 시간 (초, 기본: 30초)
        
        Returns:
            dict: 대기 결과
                - found (bool): 로그인 윈도우 발견 여부
                - message (str): 결과 메시지
        
        Examples:
            >>> await wait_for_login_window(timeout=10)
            {"found": True, "message": "로그인 윈도우가 나타났습니다"}
        """
        logger.info(f"[Tool] wait_for_login_window 호출: timeout={timeout}")
        
        try:
            action = get_login_action()
            found = action.wait_for_login_window(timeout=timeout)
            
            result = {
                "found": found,
                "message": "로그인 윈도우가 나타났습니다" if found else "로그인 윈도우를 찾을 수 없습니다"
            }
            logger.info(f"[Tool] wait_for_login_window 결과: {result}")
            
            return result
            
        except Exception as e:
            logger.error(f"[Tool] wait_for_login_window 예외: {e}")
            return {
                "found": False,
                "message": f"대기 중 오류 발생: {e}",
                "error": str(e)
            }
    
    logger.info("로그인 도구 등록 완료: login, logout, check_login_status, wait_for_login_window")
