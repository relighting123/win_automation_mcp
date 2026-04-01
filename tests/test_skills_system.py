import asyncio
import os
import sys
import subprocess
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.append(str(Path(__file__).resolve().parent.parent))

from actions.app_ui_action import get_app_ui_action
from core.app_session import AppSession

async def test_skills_system():
    print("--- Skill-Based AI Automation Verification ---")
    
    # 1. 메모장 실행
    print("메모장 시작 시도...")
    subprocess.Popen("notepad.exe")
    await asyncio.sleep(4) # 충분히 대기
    
    session = AppSession.get_instance()
    session.config["application"]["executable_path"] = "notepad.exe"
    session.config["application"]["process_name"] = "notepad.exe"
    
    print("메모장 연결 및 포커스 시도...")
    try:
        session.connect(path="notepad.exe")
    except Exception:
        # 제목으로 재시도 (ko/en 공통)
        try:
            session.connect(title_re=".*")
        except:
            print("연결 실패")
            return

    action = get_app_ui_action()
    
    # 윈도우 탐색 재시도 루프
    for i in range(5):
        print(f"윈도우 탐색 시도 {i+1}/5...")
        action.ensure_focus()
        state = action.get_screen_state_flags()
        if state.get("active_window_detected") and state.get("active_window_title"):
            print(f"윈도우 탐지 성공: '{state.get('active_window_title')}'")
            break
        await asyncio.sleep(2)
    
    # 2. 스킬 목록 확인
    skills = action._load_skills()
    print(f"로드된 스킬 목록: {[s['name'] for s in skills]}")
    
    if not skills:
        print("에러: 로드된 스킬이 없습니다. skills/ 폴더를 확인하세요.")
        return

    # 3. AI 가이드 실행 (자동 매칭 및 실행)
    print("AI Guidance 실행 (가장 적절한 스킬 탐색 중)...")
    result = await action.run_ai_guidance()
    
    if result.get("matched"):
        print(f"매칭된 스킬: {result['skill']}")
        print(f"실행 단계: {result['execution'].get('steps', [])}")
        print("검증 성공!")
    else:
        print(f"매칭 실패: {result.get('message')}")
        print(f"현재 윈도우 타이틀: '{action.get_screen_state_flags().get('active_window_title')}'")

if __name__ == "__main__":
    asyncio.run(test_skills_system())
