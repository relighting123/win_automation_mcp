"""
FastMCP 애플리케이션 관리 Tool 정의

LLM이 호출할 수 있는 애플리케이션 실행/종료 관련 도구들을 정의합니다.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from core.app_launcher import get_launcher
from core.app_session import AppSession
from errors.automation_error import ConnectionError

logger = logging.getLogger(__name__)


async def launch_application(
    executable_path: Optional[str] = None,
    wait_for_window: bool = True,
) -> dict:
    """
    대상 Windows 애플리케이션을 실행합니다.

    지정된 경로의 애플리케이션을 실행합니다. 경로를 지정하지 않으면 설정 파일(Notepad++)의
    기본 경로를 우선적으로 사용합니다. 메인 애플리케이션(Notepad++)을 실행하려면
    경로를 생략하는 것이 권장됩니다.

    Args:
        executable_path: 실행 파일 경로 (Notepad++ 외의 특수 앱 실행 시에만 사용)
        wait_for_window: 윈도우가 나타날 때까지 대기 여부 (기본: True)

    Returns:
        dict: 실행 결과
            - success (bool): 실행 성공 여부
            - message (str): 결과 메시지
            - process_info (dict, optional): 프로세스 정보
    """
    logger.info(f"[Tool] launch_application 호출: path={executable_path}, wait={wait_for_window}")

    try:
        launcher = get_launcher()
        # 하드코딩 요구사항: 설정된 경로가 있으면 LLM 인자를 무시하거나 우선함
        config_path = launcher._session.config.get("application", {}).get("executable_path")

        launcher.launch(
            path=config_path,
            wait_for_ready=wait_for_window,
        )

        # 윈도우 포커스 확보 시도 (비전 액션 사용)
        from actions.app_ui_action import get_app_ui_action

        action = get_app_ui_action()
        action.ensure_focus()

        process_info = launcher.get_process_info()

        result = {
            "success": True,
            "message": "애플리케이션이 실행되었습니다",
            "process_info": process_info,
        }
        return json.dumps(result, ensure_ascii=False)

    except ConnectionError as e:
        logger.error(f"[Tool] launch_application 연결 오류: {e}")
        return json.dumps(
            {
                "success": False,
                "message": str(e),
                "error_type": "connection_error",
                "error_detail": e.to_dict() if hasattr(e, "to_dict") else str(e),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[Tool] launch_application 예외: {e}")
        return json.dumps(
            {
                "success": False,
                "message": f"애플리케이션 실행 실패: {e}",
                "error_detail": str(e),
            },
            ensure_ascii=False,
        )


async def connect_to_application(
    process_id: Optional[int] = None,
    window_title: Optional[str] = None,
    window_title_re: Optional[str] = None,
    executable_path: Optional[str] = None,
) -> dict:
    """
    이미 실행 중인 애플리케이션에 연결합니다.

    실행 중인 애플리케이션의 프로세스 ID 또는 윈도우 제목으로 연결합니다.
    새로 실행하지 않고 기존 인스턴스에 연결할 때 사용합니다.
    """
    logger.info(
        "[Tool] connect_to_application 호출: pid=%s, title=%s, title_re=%s, path=%s",
        process_id,
        window_title,
        window_title_re,
        executable_path,
    )

    try:
        launcher = get_launcher()
        # 하드코딩 요구사항: 설정된 경로가 있으면 LLM 인자를 무시하거나 우선함
        config_path = launcher._session.config.get("application", {}).get("executable_path")

        launcher.connect_to_running(
            process_id=process_id,
            title=window_title,
            title_re=window_title_re,
            path=config_path,
        )

        process_info = launcher.get_process_info()

        result = {
            "success": True,
            "message": "애플리케이션에 연결되었습니다",
            "process_info": process_info,
        }
        return json.dumps(result, ensure_ascii=False)

    except ConnectionError as e:
        logger.error(f"[Tool] connect_to_application 연결 오류: {e}")
        return json.dumps(
            {
                "success": False,
                "message": str(e),
                "error_type": "connection_error",
                "error_detail": e.to_dict() if hasattr(e, "to_dict") else str(e),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[Tool] connect_to_application 예외: {e}")
        return json.dumps(
            {
                "success": False,
                "message": f"애플리케이션 연결 실패: {e}",
                "error_detail": str(e),
            },
            ensure_ascii=False,
        )


async def close_application(force: bool = False) -> dict:
    """
    애플리케이션을 종료합니다.

    실행 중인 애플리케이션을 정상 종료하거나 강제 종료합니다.
    정상 종료가 실패하면 자동으로 강제 종료를 시도합니다.
    """
    logger.info(f"[Tool] close_application 호출: force={force}")

    try:
        launcher = get_launcher()
        success = launcher.close(force=force)

        if success:
            message = "애플리케이션이 강제 종료되었습니다" if force else "애플리케이션이 종료되었습니다"
        else:
            message = "애플리케이션 종료에 실패했습니다"

        result = {
            "success": success,
            "message": message,
        }
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Tool] close_application 예외: {e}")
        return json.dumps(
            {
                "success": False,
                "message": f"애플리케이션 종료 실패: {e}",
                "error_detail": str(e),
            },
            ensure_ascii=False,
        )


async def restart_application() -> dict:
    """
    애플리케이션을 재시작합니다.

    현재 실행 중인 애플리케이션을 종료하고 다시 실행합니다.
    오류 복구나 상태 초기화가 필요할 때 사용합니다.
    """
    logger.info("[Tool] restart_application 호출")

    try:
        launcher = get_launcher()
        launcher.restart()

        process_info = launcher.get_process_info()

        result = {
            "success": True,
            "message": "애플리케이션이 재시작되었습니다",
            "process_info": process_info,
        }
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Tool] restart_application 예외: {e}")
        return json.dumps(
            {
                "success": False,
                "message": f"애플리케이션 재시작 실패: {e}",
                "error_detail": str(e),
            },
            ensure_ascii=False,
        )


async def get_connection_status() -> dict:
    """
    현재 애플리케이션 연결 상태를 확인합니다.

    애플리케이션이 연결되어 있는지, 실행 중인지 확인합니다.
    다른 도구를 사용하기 전에 연결 상태를 확인할 때 유용합니다.
    """
    logger.info("[Tool] get_connection_status 호출")

    try:
        session = AppSession.get_instance()
        launcher = get_launcher()

        is_connected = session.is_connected
        state = session.state.value

        result = {
            "is_connected": is_connected,
            "state": state,
        }
        if is_connected:
            result["process_info"] = launcher.get_process_info()

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Tool] get_connection_status 예외: {e}")
        return json.dumps(
            {
                "is_connected": False,
                "state": "error",
                "error": str(e),
            },
            ensure_ascii=False,
        )


async def generate_locators(window_type: Optional[str] = None) -> dict:
    """
    현재 활성화된 윈도우의 UI 요소를 추출하여 locator.yaml을 생성/업데이트합니다.

    대상을 지정하지 않으면 active_window 키로 저장합니다.
    """
    logger.info(f"[Tool] generate_locators 호출: type={window_type}")

    try:
        script_path = Path(__file__).parent.parent / "scripts" / "generate_locators.py"
        cmd = [sys.executable, str(script_path)]
        if window_type:
            cmd.extend(["--type", window_type])

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        return {
            "success": True,
            "message": f"Locator 생성 완료: {window_type or '자동 판단'}",
            "output": result.stdout,
        }
    except subprocess.CalledProcessError as e:
        logger.error(f"[Tool] generate_locators 실패: {e.stderr}")
        return {
            "success": False,
            "message": f"Locator 생성 실패: {e.stderr}",
            "error": str(e),
        }
    except Exception as e:
        logger.error(f"[Tool] generate_locators 예외: {e}")
        return {
            "success": False,
            "message": f"Locator 생성 오류: {e}",
            "error_detail": str(e),
        }


def register_app_mgmt_tools(mcp: Any) -> None:
    """
    FastMCP 서버에 애플리케이션 관리 도구 등록

    Args:
        mcp: FastMCP 서버 인스턴스
    """
    mcp.tool()(launch_application)
    mcp.tool()(connect_to_application)
    mcp.tool()(close_application)
    mcp.tool()(restart_application)
    mcp.tool()(get_connection_status)
    mcp.tool()(generate_locators)

    logger.info(
        "애플리케이션 관리 도구 등록 완료: launch_application, connect_to_application, "
        "close_application, restart_application, get_connection_status, generate_locators"
    )
