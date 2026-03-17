import os
import sys
import time
import logging
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.append(str(Path(__file__).resolve().parent.parent))

from actions.app_ui_action import get_app_ui_action
from core.app_session import AppSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_focus():
    """
    윈도우 포커스 및 복구 기능 검증
    메모장(Notepad)을 대상으로 테스트합니다.
    """
    session = AppSession.get_instance()
    
    # 1. 메모장 실행 확인 및 연결
    logger.info("메모장 실행 및 연결 시도...")
    try:
        # 이미 실행 중인 메모장이 있는지 확인
        session.connect(path="notepad.exe")
    except Exception:
        # 없으면 실행
        import subprocess
        subprocess.Popen(["notepad.exe"])
        time.sleep(2)
        session.connect(path="notepad.exe")

    action = get_app_ui_action()
    
    # 세션에서 윈도우 가져오기
    app = session.app
    main_window = app.top_window()
    
    try:
        # 2. 윈도우 최소화
        logger.info("윈도우를 최소화합니다.")
        main_window.minimize()
        time.sleep(1)
        
        if not main_window.is_minimized():
            logger.error("윈도우 최소화 실패")
            return False
        
        # 3. ensure_focus 호출
        logger.info("ensure_focus() 호출하여 복구 및 포커스 시도...")
        result = action.ensure_focus()
        logger.info(f"결과: {result.result}, 메시지: {result.message}")
        
        # 4. 상태 검증
        if main_window.is_minimized():
            logger.error("검증 실패: 윈도우가 여전히 최소화 상태입니다.")
            return False
        
        logger.info("검증 성공: 윈도우가 복구되었습니다.")
        return True

    finally:
        # 정리 (선택사항: 메모장 종료)
        # main_window.close()
        pass

if __name__ == "__main__":
    success = verify_focus()
    if success:
        print("\n[SUCCESS] Window focus verification passed!")
        sys.exit(0)
    else:
        print("\n[FAILURE] Window focus verification failed!")
        sys.exit(1)
