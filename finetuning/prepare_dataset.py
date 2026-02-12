import json
import random
from typing import List, Dict, Any

# 정의된 도구 목록 (MCP 서버 기반)
TOOLS = [
    {
        "name": "launch_program",
        "description": "Windows 프로그램을 실행합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "program_name": {"type": "string", "description": "실행할 프로그램 이름 (예: notepad, calc, chrome)"}
            },
            "required": ["program_name"]
        }
    },
    {
        "name": "type_text",
        "description": "활성화된 창에 텍스트를 입력합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "입력할 텍스트 내용"},
                "clear_first": {"type": "boolean", "description": "입력 전 기존 텍스트 삭제 여부"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "save_file",
        "description": "현재 문서를 파일로 저장합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "저장할 파일의 전체 경로"}
            },
            "required": ["file_path"]
        }
    }
]

# 시나리오 생성 함수
def generate_scenarios() -> List[Dict[str, Any]]:
    scenarios = []
    
    # 예시 1: 메모장 실행
    scenarios.append({
        "messages": [
            {"role": "user", "content": "메모장 하나 열어줘."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"name": "launch_program", "arguments": {"program_name": "notepad"}}
            ]}
        ]
    })
    
    # 예시 2: 텍스트 입력
    scenarios.append({
        "messages": [
            {"role": "user", "content": "여기에 '안녕하세요'라고 입력해."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"name": "type_text", "arguments": {"text": "안녕하세요", "clear_first": False}}
            ]}
        ]
    })
    
    # 예시 3: 자동 저장
    scenarios.append({
        "messages": [
            {"role": "user", "content": "C:\\temp\\test.txt 경로에 저장해줘."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"name": "save_file", "arguments": {"file_path": "C:\\temp\\test.txt"}}
            ]}
        ]
    })

    return scenarios

def save_dataset(filename: str, scenarios: List[Dict[str, Any]]):
    with open(filename, 'w', encoding='utf-8') as f:
        for scenario in scenarios:
            f.write(json.dumps(scenario, ensure_ascii=False) + '\n')

if __name__ == "__main__":
    dataset = generate_scenarios()
    save_dataset("tool_calling_dataset.jsonl", dataset)
    print(f"Generated {len(dataset)} scenarios in tool_calling_dataset.jsonl")
泛泛泛
