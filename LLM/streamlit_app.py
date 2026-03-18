import streamlit as st
import requests
import json
import re
import time
import os
from datetime import datetime
from groq import Groq

# 페이지 설정
st.set_page_config(
    page_title="Windows Automation with Groq",
    page_icon="🦾",
    layout="wide"
)

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": """당신은 Windows 자동화를 도와주는 유용한 비서입니다. 
사용자의 요청을 수행하기 위해 필요한 도구들을 적절히 호출하세요.
여러 단계가 필요한 경우 한 번에 하나씩 도구를 호출하여 순차적으로 작업을 수행할 수 있습니다.
도구 실행 결과가 나오면 이를 바탕으로 다음 단계를 결정하세요. 
모든 작업이 완료되면 사용자에게 한국어로 최종 결과를 요약해서 보고하세요."""}
    ]

# 사이드바 설정
st.sidebar.title("Configuration")
mcp_url = st.sidebar.text_input("MCP Server URL", "http://localhost:8000/mcp")
groq_api_key = st.sidebar.text_input("Groq API Key", type="password")
model_name = st.sidebar.selectbox("Model", ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"], index=0)

if st.sidebar.button("Clear Chat"):
    st.session_state.messages = [
        st.session_state.messages[0]
    ]
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("""
### How to use
1. MCP 서버를 실행하세요 (`python mcp_server.py`)
2. Groq API Key를 입력하세요.
3. 원하는 작업을 입력하세요. (예: '메모장에 오늘 날짜 써줘')
""")

def _parse_mcp_jsonrpc_response(response):
    """
    MCP JSON-RPC 응답을 파싱합니다.
    서버가 JSON 또는 SSE(text/event-stream)로 응답하는 경우를 모두 처리합니다.
    """
    content_type = response.headers.get("Content-Type", "")

    if "text/event-stream" in content_type:
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            stripped = line.strip()

            # SSE 메타 라인(event:, id:, :)
            if (
                stripped.startswith(":")
                or stripped.startswith("event:")
                or stripped.startswith("id:")
            ):
                continue

            if not stripped.startswith("data:"):
                continue

            payload = stripped.split(":", 1)[1].strip()
            if not payload or payload == "[DONE]":
                continue

            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if "error" in parsed:
                error_obj = parsed["error"]
                message = error_obj.get("message") if isinstance(error_obj, dict) else str(error_obj)
                raise RuntimeError(f"MCP error: {message}")

            if "result" in parsed:
                return parsed["result"]

        raise RuntimeError("MCP SSE 응답에서 result를 찾지 못했습니다.")

    # application/json 응답 처리
    parsed = response.json()
    if "error" in parsed:
        error_obj = parsed["error"]
        message = error_obj.get("message") if isinstance(error_obj, dict) else str(error_obj)
        raise RuntimeError(f"MCP error: {message}")
    return parsed.get("result", {})


def _initialize_mcp_session_headers():
    """
    MCP initialize -> notifications/initialized 순서로 세션을 연 뒤,
    후속 요청에 사용할 헤더를 반환합니다.
    """
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    init_payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "streamlit-client", "version": "1.0.0"},
        },
    }
    init_res = requests.post(mcp_url, json=init_payload, headers=headers, timeout=10)
    init_res.raise_for_status()

    session_id = init_res.headers.get("mcp-session-id")
    if not session_id:
        raise RuntimeError("initialize 응답에서 mcp-session-id를 받지 못했습니다.")

    headers["mcp-session-id"] = session_id

    # 일부 MCP 서버는 initialized 알림이 없으면 tools/list가 대기 상태가 될 수 있음
    initialized_payload = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }
    requests.post(mcp_url, json=initialized_payload, headers=headers, timeout=5)

    return headers


def get_mcp_tools():
    """MCP 서버에서 사용 가능한 도구 목록을 가져옵니다."""
    try:
        headers = _initialize_mcp_session_headers()

        # 도구 목록 요청
        tools_payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": int(time.time() * 1000),
        }

        with requests.post(
            mcp_url,
            json=tools_payload,
            headers=headers,
            timeout=(5, 30),
            stream=True,
        ) as res:
            res.raise_for_status()
            result = _parse_mcp_jsonrpc_response(res)

        tools = result.get("tools", []) if isinstance(result, dict) else []

        # Groq 형식으로 변환
        groq_tools = []
        for tool in tools:
            groq_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                }
            )
        return groq_tools
    except Exception as e:
        st.error(f"Failed to fetch tools: {e}")
        return []


def call_mcp_tool(name, arguments):
    """MCP 서버의 도구를 실행합니다."""
    try:
        headers = _initialize_mcp_session_headers()

        # 도구 호출
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": int(time.time() * 1000),
        }

        with requests.post(
            mcp_url,
            json=payload,
            headers=headers,
            timeout=(5, 60),
            stream=True,
        ) as response:
            response.raise_for_status()
            return _parse_mcp_jsonrpc_response(response)
    except Exception as e:
        return {"error": str(e)}

st.title("🦾 Groq Windows Automation Chat")
st.markdown("Groq 모델을 사용하여 Windows를 제어하세요.")

# 채팅 메시지 표시
for message in st.session_state.messages:
    if message["role"] == "system":
        continue
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 사용자 입력 처리
if prompt := st.chat_input("Windows에게 시킬 일을 입력하세요..."):
    if not groq_api_key:
        st.error("Groq API Key가 필요합니다. 사이드바에 입력해주세요.")
        st.stop()
        
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    client = Groq(api_key=groq_api_key)
    
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        MAX_ITERATIONS = 10
        iteration = 0
        
        while iteration < MAX_ITERATIONS:
            iteration += 1
            
            # 모든 도구 가져오기
            tools = get_mcp_tools()
            
            # Groq 호출
            chat_completion = client.chat.completions.create(
                messages=st.session_state.messages,
                model=model_name,
                tools=tools,
                tool_choice="auto",
                temperature=0.1
            )
            
            response_message = chat_completion.choices[0].message
            tool_calls = response_message.tool_calls
            
            if response_message.content:
                full_response += response_message.content
                message_placeholder.markdown(full_response)
            
            # 응답을 메시지 히스토리에 추가
            # 도구 호출이 있는 경우 content가 None일 수 있으므로 처리
            msg_to_append = {
                "role": "assistant",
                "content": response_message.content
            }
            if tool_calls:
                msg_to_append["tool_calls"] = [
                    {
                        "id": t.id,
                        "type": "function",
                        "function": {
                            "name": t.function.name,
                            "arguments": t.function.arguments
                        }
                    } for t in tool_calls
                ]
            st.session_state.messages.append(msg_to_append)
            
            if not tool_calls:
                break
                
            # 도구 실행
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                with st.status(f"Executing: {function_name}...", expanded=False) as status:
                    st.write(f"Arguments: {function_args}")
                    result = call_mcp_tool(function_name, function_args)
                    st.write("Result:", result)
                    status.update(label=f"Completed: {function_name}", state="complete")
                    
                st.session_state.messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(result, ensure_ascii=False)
                })
        
        if iteration >= MAX_ITERATIONS:
            st.warning("Maximum iterations reached.")
