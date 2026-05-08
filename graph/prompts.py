import os
import re

def load_integrated_guide():
    """
    guide.md 파일을 파싱하여 프롬프트 및 가이드 정보를 딕셔너리로 반환합니다.
    """
    data = {
        "prompts": {},
        "mode_instructions": {},
        "allowed_paths": []
    }
    
    file_path = os.path.join(os.path.dirname(__file__), "guide.md")
    if not os.path.exists(file_path):
        return data

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. 메인 섹션 (#) 파싱
    sections = re.split(r'^#\s+', content, flags=re.MULTILINE)
    for section in sections:
        if not section.strip():
            continue
        
        lines = section.split('\n')
        title = lines[0].strip()
        body = '\n'.join(lines[1:]).strip()

        if title == "MODE_INSTRUCTIONS":
            # 하위 섹션 (##) 파싱
            sub_sections = re.split(r'^##\s+', body, flags=re.MULTILINE)
            for sub in sub_sections:
                if not sub.strip():
                    continue
                sub_lines = sub.split('\n')
                sub_title = sub_lines[0].strip()
                sub_body = '\n'.join(sub_lines[1:]).strip()
                data["mode_instructions"][sub_title] = sub_body
        elif title == "OPERATION_GUIDE":
            # 파일 경로 추출 (file_path: ...)
            paths = re.findall(r'\*\*file_path\*\*:\s*([^\n]+)', body)
            if not paths:
                # 볼드체가 아닐 경우도 대비
                paths = re.findall(r'file_path:\s*([^\n]+)', body)
            data["allowed_paths"] = [p.strip() for p in paths]
        else:
            data["prompts"][title] = body
            
    return data

# 가이드 로드
_GUIDE_DATA = load_integrated_guide()

# 개별 변수 익스포트 (기존 코드 호환성)
PLANNER_SYSTEM_PROMPT = _GUIDE_DATA["prompts"].get("PLANNER_SYSTEM_PROMPT", "")
ANALYST_SYSTEM_PROMPT = _GUIDE_DATA["prompts"].get("ANALYST_SYSTEM_PROMPT", "")
EXTRACTOR_SYSTEM_PROMPT = _GUIDE_DATA["prompts"].get("EXTRACTOR_SYSTEM_PROMPT", "")
MODE_INSTRUCTIONS = _GUIDE_DATA["mode_instructions"]

# 가이드 정보 (추가 제공용)
OPERATION_GUIDE_TEXT = next((v for k, v in _GUIDE_DATA["prompts"].items() if "OPERATION_GUIDE" in k), "")
ALLOWED_PATHS = _GUIDE_DATA["allowed_paths"]
