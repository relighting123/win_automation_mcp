import asyncio
import sys
import logging
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.append(str(Path(__file__).resolve().parent.parent))

from actions.app_ui_action import get_app_ui_action
from core.app_session import AppSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_sequence():
    """
    제네릭 시퀀스 실행 기능 검증
    """
    session = AppSession.get_instance()
    
    # 1. 메모장 실행 확인 및 연결
    logger.info("메모장 실행 및 연결 시도...")
    try:
        session.connect(path="notepad.exe")
    except Exception:
        import subprocess
        subprocess.Popen(["notepad.exe"])
        await asyncio.sleep(2)
        session.connect(path="notepad.exe")

    action = get_app_ui_action()
    
    # 시퀀스 정의
    # 1. '파일' 메뉴 클릭
    # 2. 0.5초 대기
    # 3. ESC 눌러 메뉴 닫기
    sequence = [
        {"type": "click_text", "text": "파일", "language": "kor"},
        {"type": "wait", "seconds": 0.5},
        {"type": "press_shortcut", "shortcut": "esc"}
    ]
    
    logger.info("시퀀스 실행 시작...")
    
    # run_app_ui_sequence의 로직을 직접 수행 (도구 호출 시뮬레이션)
    results = []
    for i, step in enumerate(sequence):
        step_type = step.get("type")
        logger.info(f"단계 {i}: {step_type} 실행 중...")
        
        if step_type == "click_text":
            res = await action.find_text_position(text=step["text"], language=step.get("language", "eng"))
            if res.is_success:
                click_res = action.click_position(x=res.x, y=res.y)
                results.append(click_res.is_success)
            else:
                results.append(False)
        elif step_type == "wait":
            await asyncio.sleep(step["seconds"])
            results.append(True)
        elif step_type == "press_shortcut":
            res = action.press_shortcut(step["shortcut"])
            results.append(res.is_success)
            
    if all(results):
        logger.info("시퀀스 검증 성공!")
        return True
    else:
        logger.error(f"시퀀스 검증 실패: {results}")
        return False

if __name__ == "__main__":
    success = asyncio.run(verify_sequence())
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
