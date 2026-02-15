import streamlit as st
import requests
import json
import re
import time
from datetime import datetime

# 페이지 설정
st.set_page_config(
    page_title="Gemma Windows Automation",
    page_icon="🤖",
    layout="wide"
)

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": "당신은 Windows 자동화를 도와주는 유용한 비서입니다. 사용자의 요청에 따라 적절한 도구를 호출하여 작업을 수행하세요."}
    ]

# 사이드바 설정
st.sidebar.title("Configuration")
mcp_url = st.sidebar.text_input("MCP Server URL", "http://localhost:8000/mcp")
gemma_url = st.sidebar.text_input("Gemma API URL", "http://localhost:8001/v1/chat/completions")

if st.sidebar.button("Clear Chat"):
    st.session_state.messages = [
        {"role": "system", "content": "당신은 Windows 자동화를 도와주는 유용한 비서입니다. 사용자의 요청에 따라 적절한 도구를 호출하여 작업을 수행하세요."}
    ]
    st.rerun()

st.title("🤖 Gemma Windows Automation Chat")
st.markdown("Gemma 모델과 대화하며 Windows 명령을 내리세요. (예: '메모장 켜줘')")

# 도구 정의
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "launch_application",
            "description": "대상 Windows 애플리케이션을 실행합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "executable_path": {
                        "type": "string",
                        "description": "실행 파일 경로 (예: notepad, calc, chrome). 지정하지 않으면 기본 경로 사용."
                    },
                    "wait_for_window": {
                        "type": "boolean",
                        "description": "윈도우가 나타날 때까지 대기 여부 (기본: True)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "애플리케이션 내의 데이터를 검색합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "검색할 텍스트"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# 이전에 있던 call_mcp_tool, parse_tool_calls 함수는 백엔드로 이동하여 삭제되었습니다.

# 채팅 메시지 표시
for message in st.session_state.messages:
    if message["role"] == "system":
        continue
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 사용자 입력 처리
if prompt := st.chat_input("Windows에게 시킬 일을 입력하세요..."):
    # 사용자 메시지 표시
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Gemma 호출
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            payload = {
                "messages": st.session_state.messages,
                "tools": TOOLS,
                "temperature": 0.1
            }
            
            response = requests.post(gemma_url, json=payload, timeout=60)
            response.raise_for_status()
            
            result = response.json()
            assistant_message = result['choices'][0]['message']
            full_response = assistant_message.get('content', '')
            
            message_placeholder.markdown(full_response)
            
            # 디버그용: 원본 응답 표시
            with st.expander("Show raw response (Debug)"):
                st.code(full_response)
            
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
            # 백엔드에서 수행된 도구 실행 결과 표시
            execution_results = result.get('execution_results', [])
            if execution_results:
                for exec_info in execution_results:
                    call = exec_info.get('call', {})
                    tool_name = call.get('name')
                    tool_args = call.get('arguments', {})
                    tool_result = exec_info.get('result', {})
                    
                    with st.status(f"Tool Executed: {tool_name}", expanded=True) as status:
                        st.write(f"**Arguments:** {tool_args}")
                        st.write("**Execution Result (Backend):**", tool_result)
                        status.update(label=f"Tool {tool_name} execution complete (Processed by Backend)", state="complete", expanded=False)
            
        except Exception as e:
            st.error(f"Error: {e}")
