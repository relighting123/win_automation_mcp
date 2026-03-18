import streamlit as st
import requests
import json
import re
import time
import os
from datetime import datetime
from openai import OpenAI

# 페이지 설정
st.set_page_config(
    page_title="Windows Automation with Internal LLM",
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
api_base_url = st.sidebar.text_input("LLM API Base URL", "https://api.openai.com/v1")
api_key = st.sidebar.text_input("API Key", type="password")
model_name = st.sidebar.text_input("Model Name", "gpt-4o")

if st.sidebar.button("Clear Chat"):
    st.session_state.messages = [
        st.session_state.messages[0]
    ]
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("""
### How to use
1. MCP 서버를 실행하세요 (`python mcp_server.py`)
2. API 설정(URL, Key, Model)을 입력하세요.
3. 원하는 작업을 입력하세요. (예: '메모장에 오늘 날짜 써줘')
""")

def get_mcp_tools():
    """MCP 서버에서 사용 가능한 도구 목록을 가져옵니다."""
    try:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json"
        }
        
        # 1. 초기화 (initialize) 요청
        init_payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "streamlit-client", "version": "1.0.0"}
            }
        }
        init_res = requests.post(mcp_url, json=init_payload, headers=headers, timeout=5)
        session_id = init_res.headers.get("mcp-session-id")
        
        if not session_id:
            return []
            
        headers["mcp-session-id"] = session_id
        
        # 2. 도구 목록 요청
        tools_payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1
        }
        res = requests.post(mcp_url, json=tools_payload, headers=headers, timeout=5)
        
        if res.status_code == 200:
            # SSE 스트림 파싱
            for line in res.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith("data: "):
                        data = json.loads(decoded[6:])
                        if "result" in data and "tools" in data["result"]:
                            # OpenAI 형식에 맞게 변환
                            openai_tools = []
                            for tool in data["result"]["tools"]:
                                openai_tools.append({
                                    "type": "function",
                                    "function": {
                                        "name": tool["name"],
                                        "description": tool["description"],
                                        "parameters": tool["inputSchema"]
                                    }
                                })
                            return openai_tools
        return []
    except Exception as e:
        st.error(f"Failed to fetch tools: {e}")
        return []

def call_mcp_tool(name, arguments):
    """MCP 서버의 도구를 실행합니다."""
    try:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json"
        }
        
        # 1. 초기화
        init_payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "streamlit-client", "version": "1.0.0"}
            }
        }
        init_res = requests.post(mcp_url, json=init_payload, headers=headers, timeout=5)
        session_id = init_res.headers.get("mcp-session-id")
        
        if not session_id:
            return {"error": "Failed to get session ID"}
            
        headers["mcp-session-id"] = session_id
        
        # 2. 초기화 완료 알림
        requests.post(mcp_url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers, timeout=2)
            
        # 3. 도구 호출
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": int(time.time())
        }
        
        response = requests.post(mcp_url, json=payload, headers=headers, timeout=30, stream=True)
        
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith("data: "):
                        res_json = json.loads(decoded[6:])
                        if "result" in res_json:
                            return res_json["result"]
        return {"error": f"Status {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}

st.title("🦾 Windows Automation Chat")
st.markdown("사내 LLM 또는 OpenAI 모델을 사용하여 Windows를 제어하세요.")

# 채팅 메시지 표시
for message in st.session_state.messages:
    if message["role"] == "system":
        continue
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 사용자 입력 처리
if prompt := st.chat_input("Windows에게 시킬 일을 입력하세요..."):
    if not api_key:
        st.error("API Key가 필요합니다. 사이드바에 입력해주세요.")
        st.stop()
        
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # OpenAI 클라이언트 초기화 (사용자 설정 URL 사용)
    client = OpenAI(api_key=api_key, base_url=api_base_url)
    
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        MAX_ITERATIONS = 10
        iteration = 0
        
        while iteration < MAX_ITERATIONS:
            iteration += 1
            
            # 모든 도구 가져오기
            tools = get_mcp_tools()
            
            # LLM 호출 (비-스트리밍 방식)
            chat_completion = client.chat.completions.create(
                messages=st.session_state.messages,
                model=model_name,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                temperature=0.1,
                stream=False
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
