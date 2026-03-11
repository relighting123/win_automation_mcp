import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import PeftModel
import uvicorn
import json
import os
import re
import time
import requests

app = FastAPI(title="Function-Gemma Local Serving API")

# 모델 경로 및 LoRA 경로 (스크립트 위치 기준 절대 경로로 설정)
script_dir = os.path.dirname(os.path.abspath(__file__))
MODEL_ID = os.path.join(script_dir, "model")
LORA_ID = os.path.join(script_dir, "gemma-windows-automation-lora")

print(f"Loading base model: {MODEL_ID}...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    device_map="auto",
    torch_dtype=torch.bfloat16,
)

if os.path.exists(LORA_ID):
    print(f"Loading LoRA adapter: {LORA_ID}...")
    model = PeftModel.from_pretrained(model, LORA_ID)
    print("LoRA adapter merged successfully.")
else:
    print("No LoRA adapter found, using base model.")

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
# Gemma 모델의 경우 pad_token이 명시적으로 설정되지 않은 경우 EOS 토큰을 사용하도록 설정
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
print("Model and tokenizer loaded successfully.")

class ChatMessage(BaseModel):
    role: str
    content: str

class ToolCallRequest(BaseModel):
    messages: List[ChatMessage]
    tools: Optional[List[Dict[str, Any]]] = None
    temperature: float = 0.1

# MCP 서버의 통합 도구 정의 목록
MCP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "launch_application",
            "description": "Start or launch a new Windows application. Use this only when the application is NOT currently running.",
            "parameters": {
                "type": "object",
                "properties": {
                    "executable_path": {"type": "string", "description": "Path to the executable file (e.g., notepad, calc, chrome)"},
                    "wait_for_window": {"type": "boolean", "description": "Whether to wait for the main window to appear (default: True)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "connect_to_application",
            "description": "이미 실행 중인 애플리케이션에 연결합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {"type": "integer", "description": "프로세스 ID"},
                    "window_title": {"type": "string", "description": "윈도우 제목"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_application",
            "description": "Close or terminate the currently running target application. Use this when the user wants to exit, quit, or stop the program.",
            "parameters": {
                "type": "object",
                "properties": {
                    "force": {"type": "boolean", "description": "Whether to force kill the process (default: False)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "restart_application",
            "description": "애플리케이션을 재시작합니다."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_connection_status",
            "description": "현재 애플리케이션 연결 상태를 확인합니다."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_app_screen",
            "description": "현재 앱 화면 상태를 분석하고 keyword 좌표(UIA/OCR)를 반환합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "탐색할 키워드"},
                    "auto_click_keyword": {"type": "boolean", "description": "키워드 타겟 자동 클릭 여부"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click_app_keyword",
            "description": "키워드 기반으로 좌표를 찾고 즉시 클릭합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "클릭할 키워드 텍스트"},
                    "button": {"type": "string", "description": "left/right/middle"}
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_app_screen_state",
            "description": "현재 active window 기준 화면 상태 플래그를 확인합니다."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_app_icon_target",
            "description": "사전 정의된 아이콘 메타데이터로 좌표(x,y)를 탐색합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "icon_name": {"type": "string", "description": "아이콘 이름"},
                    "keyword": {"type": "string", "description": "아이콘 키워드"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click_app_icon_target",
            "description": "사전 정의된 아이콘 좌표를 탐색한 뒤 클릭합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "icon_name": {"type": "string", "description": "아이콘 이름"},
                    "keyword": {"type": "string", "description": "아이콘 키워드"},
                    "button": {"type": "string", "description": "left/right/middle"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "right_click_by_rgb",
            "description": "화면에서 특정 RGB 픽셀을 찾아 우클릭합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "r": {"type": "integer", "description": "Red (0-255)"},
                    "g": {"type": "integer", "description": "Green (0-255)"},
                    "b": {"type": "integer", "description": "Blue (0-255)"},
                    "tolerance": {"type": "integer", "description": "허용 오차"}
                },
                "required": ["r", "g", "b"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "press_app_shortcut",
            "description": "현재 앱에 단축키를 입력합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "shortcut": {"type": "string", "description": "예: ctrl+s, enter"}
                },
                "required": ["shortcut"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_app_text",
            "description": "현재 포커스 위치에 텍스트를 입력합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "submit_shortcut": {"type": "string"}
                },
                "required": ["text"]
            }
        }
    }
]

# MCP 서버 URL (기본값)
MCP_URL = "http://localhost:8000/mcp"

def call_mcp_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """MCP 서버에 도구 호출 요청을 보냅니다."""
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments
        },
        "id": int(time.time())
    }
    
    try:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json"
        }
        
        # 1. 초기화 (initialize) 요청 - 세션 ID 획득 및 세션 활성화
        init_payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "gemma-serving", "version": "1.0.0"}
            }
        }
        init_res = requests.post(MCP_URL, json=init_payload, headers=headers, timeout=10)
        session_id = init_res.headers.get("mcp-session-id")
        
        if not session_id:
            return {"error": "Failed to get session ID from MCP server", "status": init_res.status_code}
            
        headers["mcp-session-id"] = session_id
        
        # 2. 초기화 완료 알림 (initialized notification)
        init_done_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        requests.post(MCP_URL, json=init_done_payload, headers=headers, timeout=5)
            
        # 3. 실제 도구 호출 수행
        response = requests.post(MCP_URL, json=payload, headers=headers, timeout=30, stream=True)
        
        if response.status_code == 200:
            full_result = ""
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith("data: "):
                        data_str = decoded_line[6:]
                        try:
                            result_json = json.loads(data_str)
                            # JSON-RPC 결과 또는 에러 체크
                            if "result" in result_json:
                                return result_json["result"]
                            return result_json
                        except json.JSONDecodeError:
                            full_result += data_str
            
            if full_result:
                try:
                    return json.loads(full_result)
                except:
                    return {"raw_result": full_result}
            return {"error": "No data received from SSE stream"}
        else:
            return {"error": f"Status {response.status_code}", "detail": response.text}
    except Exception as e:
        return {"error": "Connection failed", "detail": str(e)}

def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Gemma의 응답에서 도구 호출을 파싱합니다."""
    tool_calls = []
    
    # 형식 1: <tool_call> 태그 내의 JSON 추출
    json_pattern = r"<tool_call>(.*?)</tool_call>"
    for match in re.finditer(json_pattern, text, re.DOTALL):
        try:
            call_data = json.loads(match.group(1).strip())
            tool_calls.append(call_data)
        except json.JSONDecodeError:
            pass
            
    # 형식 2: <start_function_call> 형식 (Gemma 3 표준)
    gemma3_pattern = r"<start_function_call>call:([a-zA-Z0-9_]+)({.*?})?<end_function_call>"
    for match in re.finditer(gemma3_pattern, text, re.DOTALL):
        name = match.group(1)
        args_str = match.group(2)
        args = {}
        if args_str:
            try:
                # <escape>와 같은 특수 태그 제거 로직이 필요할 수 있음
                args_json = args_str.replace("<escape>", "")
                args = json.loads(args_json)
            except json.JSONDecodeError:
                pass
        tool_calls.append({"name": name, "arguments": args})
        
    return tool_calls

@app.post("/v1/chat/completions")
async def chat_completions(request: ToolCallRequest):
    try:
        # Gemma 3의 도구 호출 형식에 맞게 메시지 구성
        # 힌트: Gemma 3는 특수 토큰과 구조화된 출력을 지원합니다.
        
        chat = []
        for msg in request.messages:
            chat.append({"role": msg.role, "content": msg.content})
            
        # 텐서 준비 (서버에 정의된 MCP_TOOLS 우선 사용)
        actual_tools = request.tools if request.tools is not None else MCP_TOOLS
        inputs = tokenizer.apply_chat_template(
            chat,
            tools=actual_tools,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True
        ).to(model.device)
        
        # 디버깅: 모델에게 전달되는 실제 프롬프트 확인
        full_prompt = tokenizer.decode(inputs["input_ids"][0])
        print("--- DEBUG: FULL PROMPT SENT TO MODEL ---")
        print(full_prompt)
        print("--- DEBUG: END PROMPT ---")
        
        # 생성
        outputs = model.generate(
            **inputs,
            max_new_tokens=1024,
            do_sample=True,
            temperature=request.temperature,
            pad_token_id=tokenizer.pad_token_id
        )
        
        # 디코딩 (입력 부분 제외)
        input_ids = inputs["input_ids"]
        response_ids = outputs[0][input_ids.shape[-1]:]
        response_text = tokenizer.decode(response_ids, skip_special_tokens=True)
        print(f"Generated text: {response_text}")
        
        # 도구 호출 파싱 및 실행
        tool_calls = parse_tool_calls(response_text)
        tool_results = []
        
        if tool_calls:
            print(f"Executing {len(tool_calls)} tool calls...")
            for call in tool_calls:
                name = call.get("name")
                args = call.get("arguments", {})
                print(f"Calling tool: {name} with {args}")
                result = call_mcp_tool(name, args)
                tool_results.append({
                    "call": call,
                    "result": result
                })
        
        # 응답 파싱 및 반환 (OpenAI 호환 포맷 + execution_results 추가)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": response_text,
                        "tool_calls": tool_calls if tool_calls else None
                    },
                    "finish_reason": "stop"
                }
            ],
            "execution_results": tool_results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    # 프로젝트 루트를 Python 경로에 추가 (core 모듈을 찾기 위함)
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
        
    try:
        from core.network_utils import kill_process_on_port
        kill_process_on_port(8001)
    except ImportError:
        print("Warning: Could not import kill_process_on_port. Skipping port cleanup.")
        
    uvicorn.run(app, host="0.0.0.0", port=8001)
