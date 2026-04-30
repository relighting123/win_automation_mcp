# -*- coding: utf-8 -*-
import streamlit as st
import requests
import json
import re
import time
import os
import sys
from datetime import datetime
from openai import OpenAI
import asyncio

# 로컬 모듈 임포트를 위해 현재 디렉토리를 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from langgraph_agent import create_mcp_agent
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from core.llm_config import get_llm_settings, get_mcp_settings

# 공통 LLM 설정 로드 (config/app_config.yaml 우선)
llm_settings = get_llm_settings()
DEFAULT_LLM_API_BASE_URL = llm_settings["base_url"]
DEFAULT_LLM_API_KEY = llm_settings["api_key"]
DEFAULT_LLM_MODEL_NAME = llm_settings["model"]
DEFAULT_MCP_URL = get_mcp_settings()["base_url"]

# 페이지 설정
st.set_page_config(
    page_title="Windows Automation with Internal LLM",
    page_icon="🦾",
    layout="wide"
)

# 기본 시스템 프롬프트 정의
system_content = (
    "당신은 Windows 자동화를 도와주는 유용한 비서입니다.\n"
    "사용자의 요청을 수행하기 위해 필요한 도구들을 적절히 호출하세요.\n"
    "여러 단계가 필요한 경우 한 번에 하나씩 도구를 호출하여 순차적으로 작업을 수행할 수 있습니다.\n"
    "도구 실행 결과가 나오면 이를 바탕으로 다음 단계를 결정하세요.\n"
    "모든 작업이 완료되면 사용자에게 한국어로 최종 결과를 요약해서 보고하세요."
)

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": system_content}
    ]
else:
    # 기존 세션이 있는 경우에도 시스템 프롬프트는 최신 버전으로 유지 (ASCII 오류 방지)
    if st.session_state.messages and st.session_state.messages[0]["role"] == "system":
        st.session_state.messages[0]["content"] = system_content

# 사이드바 설정
st.sidebar.title("Configuration")
mcp_url = st.sidebar.text_input("MCP Server URL", DEFAULT_MCP_URL)
api_base_url = st.sidebar.text_input("LLM API Base URL", DEFAULT_LLM_API_BASE_URL)
api_key = st.sidebar.text_input("API Key", value=DEFAULT_LLM_API_KEY, type="password")
model_name = st.sidebar.text_input("Model Name", DEFAULT_LLM_MODEL_NAME)
use_langgraph = st.sidebar.toggle("Use LangGraph Workflow", value=True, help="컴플렉스 워크플로우를 위해 LangGraph를 사용합니다.")
st.sidebar.caption("기본값은 config/app_config.yaml의 llm/mcp 설정을 사용하며, 필요 시 입력창에서 임시 override할 수 있습니다.")

if st.sidebar.button("Clear Chat"):
    st.session_state.messages = [
        st.session_state.messages[0]
    ]
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("""
### How to use
1. MCP 서버를 실행하세요 (`python mcp_server.py`)
2. 사내 OpenAI 호환 API 설정(URL, Key, Model)을 입력하세요.
3. 원하는 작업을 입력하세요. (예: '메모장에 오늘 날짜 써줘')
""")

@st.cache_data(ttl=600)  # 10분간 캐시 유지
def get_mcp_tools(mcp_url):
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
        init_res = requests.post(mcp_url, json=init_payload, headers=headers, timeout=15)
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
        res = requests.post(mcp_url, json=tools_payload, headers=headers, timeout=15)
        
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
        # 캐시가 실패하는 경우를 대비해 에러 로그만 남기고 빈 리스트 반환
        print(f"Failed to fetch tools: {e}")
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
        init_res = requests.post(mcp_url, json=init_payload, headers=headers, timeout=15)
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
        
        response = requests.post(mcp_url, json=payload, headers=headers, timeout=60, stream=True)
        
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

st.title("🦾 Windows Automation")
st.markdown("사내 LLM 또는 LangGraph를 사용하여 Windows를 제어하고 자동화하세요.")

# 세션 상태에 메뉴얼 계획 저장공간 초기화
if "manual_plan" not in st.session_state:
    st.session_state.manual_plan = []

tab1, tab2 = st.tabs(["💬 Chat Automation", "🏗️ Manual Workflow Designer"])

with tab1:
    # 기존 채팅 메시지 표시
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

        # OpenAI 클라이언트 초기화
        client = OpenAI(api_key=api_key, base_url=api_base_url)
        
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            
            # 모든 도구 가져오기
            tools = get_mcp_tools(mcp_url)
            
            # --- 워크플로우 명령어 감지 로직 추가 ---
            workspaces_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            save_dir = os.path.join(workspaces_dir, "saved_workflows")
            
            manual_plan_to_use = []
            is_workflow_trigger = False
            
            # "run flow001", "flow001 실행해줘" 등의 패턴 매칭
            trigger_patterns = [
                r"(?:run|실행)\s+([a-zA-Z0-9_-]+)", # run 이름, 실행 이름
                r"([a-zA-Z0-9_-]+)\s+(?:실행|run)"  # 이름 실행, 이름 run
            ]
            
            for pattern in trigger_patterns:
                match = re.search(pattern, prompt, re.IGNORECASE)
                if match:
                    wf_name = match.group(1)
                    filepath = os.path.join(save_dir, f"{wf_name}.json")
                    if os.path.exists(filepath):
                        try:
                            with open(filepath, "r", encoding="utf-8") as f:
                                manual_plan_to_use = json.load(f)
                            is_workflow_trigger = True
                            
                            # --- 파라미터(placeholder) 처리 로직 추가 ---
                            plan_str = json.dumps(manual_plan_to_use, ensure_ascii=False)
                            placeholders = re.findall(r"\{\{([a-zA-Z0-9_-]+)\}\}", plan_str)
                            
                            if placeholders:
                                placeholders = list(set(placeholders)) # 중복 제거
                                st.write(f"🔍 워크플로우 파라미터 감지: {', '.join(placeholders)}")
                                
                                # LLM을 사용하여 값 추출
                                extract_client = OpenAI(api_key=api_key, base_url=api_base_url)
                                extract_prompt = f"""
전달된 사용자 요청에서 아래 변수들에 매칭될 값을 추출하여 JSON 형식으로 응답하세요.
변수 목록: {', '.join(placeholders)}

[사용자 요청]
{prompt}

응답 형식: {{"변수명": "값", ...}}
만약 매칭되는 값이 없다면 빈 문자열("")을 넣으세요.
"""
                                try:
                                    extract_res = extract_client.chat.completions.create(
                                        messages=[{"role": "user", "content": extract_prompt}],
                                        model=model_name,
                                        temperature=0
                                    )
                                    values_json = extract_res.choices[0].message.content
                                    # JSON 추출 로직 (마크다운 대응)
                                    if "```json" in values_json:
                                        values_json = values_json.split("```json")[1].split("```")[0].strip()
                                    elif "```" in values_json:
                                        values_json = values_json.split("```")[1].split("```")[0].strip()
                                    
                                    extracted_values = json.loads(values_json)
                                    st.write(f"📥 추출된 값: {extracted_values}")
                                    
                                    # 시퀀스 내의 플레이스홀더 치환
                                    for key, val in extracted_values.items():
                                        plan_str = plan_str.replace(f"{{{{{key}}}}}", str(val))
                                    
                                    manual_plan_to_use = json.loads(plan_str)
                                except Exception as e:
                                    st.error(f"Parameter Extraction Error: {e}")
                            # ------------------------------------------

                            st.info(f"📁 저장된 워크플로우 '{wf_name}'를 로드했습니다. ({len(manual_plan_to_use)}단계)")
                            break
                        except Exception as e:
                            st.error(f"Workflow Load Error: {e}")
            # ----------------------------------------
            
            if use_langgraph:
                # LangGraph 기반 워크플로우 실행
                with st.status("Initializing LangGraph Workflow...", expanded=True) as status:
                    try:
                        app = create_mcp_agent(
                            api_key=api_key,
                            base_url=api_base_url,
                            model_name=model_name,
                            tools_metadata=tools,
                            call_tool_func=call_mcp_tool
                        )
                        
                        lc_messages = []
                        for m in st.session_state.messages:
                            if m["role"] == "user":
                                lc_messages.append(HumanMessage(content=m["content"]))
                            elif m["role"] == "assistant" and m["content"]:
                                lc_messages.append(AIMessage(content=m["content"]))
                            elif m["role"] == "system":
                                lc_messages.append(SystemMessage(content=m["content"]))
                        
                        inputs = {
                            "messages": lc_messages,
                            "input": prompt,
                            "current_step": 0,
                            "plan": manual_plan_to_use if is_workflow_trigger else [],
                            "results": []
                        }
                        
                        final_msg = ""
                        for event in app.stream(inputs, stream_mode="values"):
                            if "messages" in event:
                                last_msg = event["messages"][-1]
                                if isinstance(last_msg, AIMessage) and last_msg.content:
                                    st.write(f"📝 {last_msg.content}")
                            
                            if "final_response" in event and event["final_response"]:
                                final_msg = event["final_response"]
                                message_placeholder.markdown(final_msg)
                        
                        if not final_msg:
                            final_msg = "작업이 완료되었습니다."
                            message_placeholder.markdown(final_msg)
                            
                        st.session_state.messages.append({"role": "assistant", "content": final_msg})
                        status.update(label="Workflow Completed", state="complete")
                    except Exception as e:
                        st.error(f"LangGraph Error: {e}")
                        status.update(label="Workflow Failed", state="error")
            else:
                # 기존 루프 기반 실행 (생략 가능하지만 유지)
                MAX_ITERATIONS = 10
                iteration = 0
                while iteration < MAX_ITERATIONS:
                    iteration += 1
                    chat_completion = client.chat.completions.create(
                        messages=st.session_state.messages,
                        model=model_name,
                        tools=tools if tools else None,
                        tool_choice="auto" if tools else "none",
                        temperature=0.1,
                        stream=False
                    )
                    response_message = chat_completion.choices[0].message
                    tool_calls = response_message.tool_calls
                    if response_message.content:
                        full_response += response_message.content
                        message_placeholder.markdown(full_response)
                    
                    msg_to_append = {"role": "assistant", "content": response_message.content}
                    if tool_calls:
                        msg_to_append["tool_calls"] = [{"id": t.id, "type": "function", "function": {"name": t.function.name, "arguments": t.function.arguments}} for t in tool_calls]
                    st.session_state.messages.append(msg_to_append)
                    
                    if not tool_calls: break
                    for tool_call in tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)
                        with st.status(f"Executing: {function_name}...", expanded=False) as status:
                            result = call_mcp_tool(function_name, function_args)
                            status.update(label=f"Completed: {function_name}", state="complete")
                        st.session_state.messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": json.dumps(result, ensure_ascii=False)})
                if iteration >= MAX_ITERATIONS: st.warning("Maximum iterations reached.")

with tab2:
    st.header("🏗️ Manual Workflow Designer")
    st.write("사용 가능한 도구를 직접 조합하여 자동화 시퀀스를 만드세요.")
    
    # 1. 도구 정보 가져오기
    tools = get_mcp_tools(mcp_url)
    if not tools:
        st.warning("MCP 서버에서 도구 목록을 가져올 수 없습니다. 서버가 실행 중인지 확인하세요.")
    else:
        tool_names = [t["function"]["name"] for t in tools]
        
        # 2. 새로운 단계 추가 UI
        with st.expander("➕ Add New Step", expanded=True):
            col1, col2 = st.columns([1, 2])
            with col1:
                selected_tool_name = st.selectbox("Select Tool", tool_names)
            
            # 선택된 도구 정보 찾기
            selected_tool = next(t for t in tools if t["function"]["name"] == selected_tool_name)
            
            with col2:
                st.info(f"**Description**: {selected_tool['function']['description']}")
                
            # 인자 입력 폼
            st.write("**Arguments (JSON)**")
            params = selected_tool["function"]["parameters"]
            default_args = {}
            if "properties" in params:
                for prop, details in params["properties"].items():
                    if "default" in details:
                        default_args[prop] = details["default"]
                    elif details.get("type") == "string":
                        default_args[prop] = ""
                    elif details.get("type") == "integer":
                        default_args[prop] = 0
            
            args_input = st.text_area(
                "Tool Arguments", 
                value=json.dumps(default_args, indent=2, ensure_ascii=False),
                height=150,
                key="manual_args_input"
            )
            
            if st.button("Add to Sequence"):
                try:
                    parsed_args = json.loads(args_input)
                    st.session_state.manual_plan.append({
                        "tool": selected_tool_name,
                        "args": parsed_args
                    })
                    st.success(f"Added {selected_tool_name} to sequence.")
                    # st.rerun() # 추가 후 목록 갱신
                except json.JSONDecodeError:
                    st.error("Invalid JSON format in arguments.")

        st.markdown("---")
        
        # 3. 현재 시퀀스 표시
        st.subheader("📋 Current Sequence")
        if not st.session_state.manual_plan:
            st.info("시퀀스가 비어 있습니다. 위에서 단계를 추가하세요.")
        else:
            for i, step in enumerate(st.session_state.manual_plan):
                col_i, col_tool, col_args, col_del = st.columns([0.5, 2, 5, 1])
                with col_i:
                    st.write(f"#{i+1}")
                with col_tool:
                    st.code(step["tool"])
                with col_args:
                    st.code(json.dumps(step["args"], ensure_ascii=False))
                with col_del:
                    if st.button("🗑️", key=f"del_{i}"):
                        st.session_state.manual_plan.pop(i)
                        st.rerun()
            
            col_run, col_clear = st.columns([1, 1])
            with col_run:
                if st.button("🚀 Run Manual Sequence", use_container_width=True):
                    if not api_key:
                        st.error("API Key가 필요합니다. 사이드바에 입력해주세요.")
                    else:
                        st.info("LangGraph Manual Workflow 시작...")
                        # LangGraph 실행
                        try:
                            app = create_mcp_agent(
                                api_key=api_key,
                                base_url=api_base_url,
                                model_name=model_name,
                                tools_metadata=tools,
                                call_tool_func=call_mcp_tool
                            )
                            
                            # 수동 계획으로 입력 구성
                            inputs = {
                                "input": "Manual Sequence Execution",
                                "plan": st.session_state.manual_plan,
                                "current_step": 0,
                                "messages": [],
                                "results": []
                            }
                            
                            with st.status("Executing Manual Sequence...", expanded=True) as status:
                                final_msg = ""
                                for event in app.stream(inputs, stream_mode="values"):
                                    if "messages" in event and event["messages"]:
                                        last_msg = event["messages"][-1]
                                        st.write(f"📝 {last_msg.content}")
                                    
                                    if "final_response" in event and event["final_response"]:
                                        final_msg = event["final_response"]
                                        st.success("Sequence completed!")
                                        st.markdown(f"**Final Result**:\n{final_msg}")
                                
                                status.update(label="Manual Sequence Completed", state="complete")
                        except Exception as e:
                            st.error(f"Execution Error: {e}")

            with col_clear:
                if st.button("🧹 Clear All Steps", use_container_width=True):
                    st.session_state.manual_plan = []
                    st.rerun()

    st.markdown("---")
    st.subheader("💾 Workflow Persistence")
    
    # 워크플로우 저장 디렉토리 설정
    workspaces_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    save_dir = os.path.join(workspaces_dir, "saved_workflows")
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    load_col, save_col = st.columns(2)

    with load_col:
        st.write("**Load Workflow**")
        saved_files = [f for f in os.listdir(save_dir) if f.endswith(".json")]
        if not saved_files:
            st.info("저장된 워크플로우가 없습니다.")
        else:
            selected_file = st.selectbox("Select to Load", saved_files)
            if st.button("📂 Load Selected"):
                try:
                    with open(os.path.join(save_dir, selected_file), "r", encoding="utf-8") as f:
                        st.session_state.manual_plan = json.load(f)
                    st.success(f"'{selected_file}' 로드 완료!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Load Error: {e}")

    with save_col:
        st.write("**Save Workflow**")
        wf_name = st.text_input("Workflow Name", placeholder="my_automation")
        
        btn1, btn2 = st.columns(2)
        with btn1:
            if st.button("💾 Save (JSON)"):
                if not wf_name:
                    st.warning("이름을 입력하세요.")
                elif not st.session_state.manual_plan:
                    st.warning("시퀀스가 비어 있습니다.")
                else:
                    filename = f"{wf_name}.json"
                    filepath = os.path.join(save_dir, filename)
                    try:
                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(st.session_state.manual_plan, f, indent=4, ensure_ascii=False)
                        st.success(f"'{filename}' 저장 완료!")
                    except Exception as e:
                        st.error(f"Save Error: {e}")
        
        with btn2:
            if st.button("📑 Export (MD)"):
                if not wf_name:
                    st.warning("이름을 입력하세요.")
                elif not st.session_state.manual_plan:
                    st.warning("시퀀스가 비어 있습니다.")
                else:
                    filename = f"{wf_name}.md"
                    filepath = os.path.join(save_dir, filename)
                    try:
                        md_content = f"# Workflow: {wf_name}\n\n"
                        md_content += f"**Export Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        md_content += "## 📋 Execution Sequence\n\n"
                        for i, step in enumerate(st.session_state.manual_plan):
                            md_content += f"### Step {i+1}: {step['tool']}\n"
                            md_content += "```json\n"
                            md_content += json.dumps(step["args"], indent=2, ensure_ascii=False)
                            md_content += "\n```\n\n"
                        
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(md_content)
                        st.success(f"'{filename}' 내보내기 완료!")
                    except Exception as e:
                        st.error(f"Export Error: {e}")

