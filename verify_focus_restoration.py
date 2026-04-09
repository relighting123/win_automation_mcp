import asyncio
import sys
import logging
import time
import yaml
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.append(str(Path(__file__).resolve().parent.parent))

from actions.app_ui_action import get_app_ui_action
from core.app_session import AppSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_focus():
    """
    구성된 애플리케이션의 최소화 복구 및 포커스 기능 검증
    """
    session = AppSession.get_instance()
    config = session.config
    exe_path = config.get("application", {}).get("executable_path", "notepad.exe")
    
    logger.info(f"대상 애플리케이션: {exe_path}")
    
    # 1. 애플리케이션 연결 (이미 실행 중이라 가정하거나 실행 시도)
    try:
        session.connect()
    except Exception:
        import subprocess
        logger.info(f"애플리케이션 실행 시도: {exe_path}")
        subprocess.Popen([exe_path])
        await asyncio.sleep(3)
        session.connect()
    
    action = get_app_ui_action()
    
    # 2. 최소화 시뮬레이션
    wrapper = action._pick_target_window()
    if wrapper:
        logger.info(f"윈도우 '{action._safe_call(wrapper.window_text, 'unknown')}'를 최소화합니다.")
        wrapper.minimize()
        await asyncio.sleep(1)
    else:
        logger.error("대상 윈도우를 찾지 못했습니다.")
        return False

    # 3. ensure_focus() 호출하여 복구 및 포커스 확인
    logger.info("ensure_focus()를 호출하여 복구를 시도합니다.")
    res = action.ensure_focus()
    logger.info(f"결과: {res.to_dict()}")
    
    if not res.is_success:
        logger.error("focus 실패")
        return False

    # 4. 시각적 확인을 위해 대기
    await asyncio.sleep(1)

    # 5. 간단한 UI 동작 확인 (메뉴 등)
    # Notepad++ "파일" 메뉴는 UIA로 탐색 가능
    logger.info("UI 동작 테스트: '파일' 메뉴 탐색")
    # '파일' 텍스트를 찾아 클릭 대신 위치만 확인
    find_res = await action.find_text_position(text="파일", language="kor")
    logger.info(f"탐색 결과: {find_res.to_dict()}")
    
    if find_res.is_success:
        # 클릭까지 시도해봄 (메뉴가 열리는지 확인)
        logger.info("'파일' 메뉴 클릭 시도")
        click_res = action.click_position(x=find_res.x, y=find_res.y)
        logger.info(f"클릭 결과: {click_res.to_dict()}")
        
        if click_res.is_success:
            logger.info("포커스 및 UI 조작 검증 성공!")
            return True
    
    logger.error("UI 조작 검증 실패")
    return False

if __name__ == "__main__":
    success = asyncio.run(verify_focus())
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
