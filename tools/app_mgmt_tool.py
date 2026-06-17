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
from core.launch_paths import LAUNCH_TARGET_KEYS, canonicalize_launch_arg_keys, resolve_launch_paths
from errors.automation_error import ConnectionError

logger = logging.getLogger(__name__)


async def launch_application(
    argument_path: Optional[str] = None,
    exec_path: Optional[str] = None,
    file_path: Optional[str] = None,
    path: Optional[str] = None,
    connect_path: Optional[str] = None,
    window_title: Optional[str] = None,
    window_title_re: Optional[str] = None,
    wait_for_window: bool = True,
    reopen_data_file: bool = False,
) -> dict:
    """
    대상 Windows 애플리케이션 또는 데이터 파일을 실행합니다.

    지정된 경로의 애플리케이션(.exe)을 실행하거나, 데이터 파일(.rul, .txt 등)을 관련 프로그램으로 엽니다.
    file_path가 없으면 config의 connect_path exe를 실행합니다.

    Args:
        file_path: 열 데이터 파일 경로 (.rul 등) 또는 실행 파일
        argument_path: file_path 별칭 (스킬 YAML / graph 호환)
        exec_path: file_path 별칭
        path: file_path 별칭
        connect_path: pywinauto가 붙을 exe 경로 (데이터 파일 실행 시 필수)
        window_title: (데이터 파일 실행 시) 연결할 윈도우 제목
        window_title_re: (데이터 파일 실행 시) 연결할 윈도우 제목 정규식
        wait_for_window: 윈도우가 나타날 때까지 대기 여부 (기본: True)
        reopen_data_file: 이미 연결된 상태에서도 동일 .rul 파일을 다시 열지 (기본: False)
    """
    raw_args = canonicalize_launch_arg_keys({
        "argument_path": argument_path,
        "exec_path": exec_path,
        "file_path": file_path,
        "path": path,
        "connect_path": connect_path,
        "window_title": window_title,
        "window_title_re": window_title_re,
        "wait_for_window": wait_for_window,
    })

    try:
        launcher = get_launcher()
        app_config = launcher._session.config.get("application", {})
        target_path, resolved_connect_path, _ = resolve_launch_paths(
            raw_args,
            app_config.get("connect_path"),
        )

        logger.info(
            "[Tool] launch_application 호출: target=%s, connect_path=%s, aliases=%s",
            target_path,
            resolved_connect_path,
            {k: raw_args.get(k) for k in LAUNCH_TARGET_KEYS if raw_args.get(k)},
        )

        if target_path and not launcher._session._is_executable_path(target_path):
            logger.info(
                "[Tool] launch_application 데이터 파일 모드: file=%s, connect_exe=%s",
                target_path,
                resolved_connect_path,
            )

        launcher.launch(
            path=target_path,
            wait_for_ready=wait_for_window,
            connect_path=resolved_connect_path,
            title=window_title,
            title_re=window_title_re,
            reopen_data_file=reopen_data_file,
        )

        # 윈도우 포커스 확보 시도 (동일 .rul 재오픈을 건너뛴 경우는 이미 포커스 복원됨)
        if not launcher.session._skipped_data_file_reopen:
            from actions.app_ui_action import get_app_ui_action

            action = get_app_ui_action()
            action.ensure_focus()

        process_info = launcher.get_process_info()

        message = "애플리케이션이 실행되었습니다"
        if launcher.session.is_connected and launcher.session._skipped_data_file_reopen:
            message = "이미 연결된 애플리케이션에 포커스를 복원했습니다"

        result = {
            "success": True,
            "message": message,
            "process_info": process_info,
            "skipped_data_file_reopen": launcher.session._skipped_data_file_reopen,
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
    connect_path: Optional[str] = None,
) -> dict:
    """
    이미 실행 중인 애플리케이션에 연결합니다.

    실행 중인 애플리케이션의 프로세스 ID 또는 윈도우 제목으로 연결합니다.
    새로 실행하지 않고 기존 인스턴스에 연결할 때 사용합니다.
    """
    logger.info(
        "[Tool] connect_to_application 호출: pid=%s, title=%s, title_re=%s, connect_path=%s",
        process_id,
        window_title,
        window_title_re,
        connect_path,
    )

    try:
        launcher = get_launcher()
        config_path = connect_path or launcher._session._resolve_connect_executable_path()

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


async def close_window(
    window_target: str = "auto",
    child_window_title: Optional[str] = None,
    child_window_auto_id: Optional[str] = None,
    child_window_match_mode: str = "contains",
    case_sensitive: bool = False,
    timeout: Optional[float] = None,
    wait_for_close: bool = True,
    allow_invisible_children: bool = False,
) -> dict:
    """
    특정 윈도우(주로 child dialog)를 닫습니다.

    title bar X 버튼이 UIA로 클릭되지 않을 때 WM_CLOSE로 닫을 수 있습니다.
    Find 같은 child dialog를 닫을 때 사용합니다.

    Args:
        window_target: auto|top|child — 닫을 윈도우 범위
        child_window_title: child 윈도우 제목 (예: "Find")
        child_window_auto_id: child 윈도우 AutomationId
        child_window_match_mode: exact|contains — child 제목 매칭 방식
        case_sensitive: 제목 대소문자 구분 여부
        timeout: 닫힘 대기 시간(초, 기본 5.0)
        wait_for_close: 닫힘까지 대기 여부 (기본 True)
        allow_invisible_children: 보이지 않는 child도 탐색할지 여부
    """
    logger.info(
        "[Tool] close_window 호출: child_window_title=%s, child_window_auto_id=%s, window_target=%s",
        child_window_title,
        child_window_auto_id,
        window_target,
    )

    try:
        from actions.app_ui_action import get_app_ui_action

        action = get_app_ui_action()
        result = action.close_window(
            window_target=window_target,
            child_window_title=child_window_title,
            child_window_auto_id=child_window_auto_id,
            child_window_match_mode=child_window_match_mode,
            case_sensitive=case_sensitive,
            timeout=timeout,
            wait_for_close=wait_for_close,
            allow_invisible_children=allow_invisible_children,
        )
        payload = result.to_dict()
        logger.info(
            "[Tool] close_window 결과: success=%s, result=%s, message=%s",
            payload.get("is_success"),
            payload.get("result"),
            payload.get("message"),
        )
        return json.dumps(payload, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Tool] close_window 예외: {e}")
        return json.dumps(
            {
                "success": False,
                "result": "error",
                "message": f"윈도우 닫기 실패: {e}",
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
    mcp.tool()(close_window)
    mcp.tool()(close_application)
    mcp.tool()(restart_application)
    mcp.tool()(get_connection_status)
    mcp.tool()(generate_locators)

    logger.info(
        "애플리케이션 관리 도구 등록 완료: launch_application, connect_to_application, "
        "close_window, close_application, restart_application, get_connection_status, generate_locators"
    )
