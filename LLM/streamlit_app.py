import streamlit as st
import requests
import json
import time

SYSTEM_PROMPT = """당신은 Windows 자동화를 도와주는 유용한 비서입니다.
사용자의 요청을 수행하기 위해 필요한 도구들을 적절히 호출하세요.
여러 단계가 필요한 경우 한 번에 하나씩 도구를 호출하여 순차적으로 작업을 수행할 수 있습니다.
도구 실행 결과가 나오면 이를 바탕으로 다음 단계를 결정하세요.
모든 작업이 완료되면 사용자에게 한국어로 최종 결과를 요약해서 보고하세요."""

# 페이지 설정
st.set_page_config(
    page_title="Gemma Windows Automation",
    page_icon="🤖",
    layout="wide"
)

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]


def reset_chat() -> None:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]


def build_llm_request(
    provider: str,
    messages: list,
    base_url: str,
    endpoint_url: str,
    api_key: str,
    model: str,
) -> tuple[str, dict, dict]:
    """LLM 호출 URL/헤더/페이로드를 생성합니다."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if provider == "OpenAI-Compatible":
        request_url = f"{base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
        }
    else:
        request_url = endpoint_url
        payload = {
            "messages": messages,
            "temperature": 0.1,
        }
        if model.strip():
            payload["model"] = model.strip()

    return request_url, headers, payload

# 사이드바 설정
st.sidebar.title("Configuration")
mcp_url = st.sidebar.text_input("MCP Server URL", "http://localhost:8000/mcp")
provider = st.sidebar.selectbox(
    "LLM API Provider",
    options=["OpenAI-Compatible", "Custom Endpoint"],
    index=0,
)

if provider == "OpenAI-Compatible":
    base_url = st.sidebar.text_input("Base URL", "http://localhost:8001/v1")
    model_name = st.sidebar.text_input("Model", "google/gemma-3-4b-it")
    api_key = st.sidebar.text_input("API Key", "local-token", type="password")
    endpoint_url = ""
else:
    endpoint_url = st.sidebar.text_input(
        "LLM Endpoint URL",
        "http://localhost:8001/v1/chat/completions",
    )
    model_name = st.sidebar.text_input("Model (optional)", "")
    api_key = st.sidebar.text_input("API Key (optional)", "", type="password")
    base_url = ""

if st.sidebar.button("Clear Chat"):
    reset_chat()
    st.rerun()

st.title("🤖 Gemma Windows Automation Chat")
st.markdown("Gemma 모델과 대화하며 Windows 명령을 내리세요. (예: '메모장 켜줘')")

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

    # Gemma 호출 (에이전트 루프)
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        # 최대 반복 횟수 설정 (무한 루프 방지)
        MAX_ITERATIONS = 5
        iteration = 0
        
        while iteration < MAX_ITERATIONS:
            iteration += 1
            
            try:
                request_url, headers, payload = build_llm_request(
                    provider=provider,
                    messages=st.session_state.messages,
                    base_url=base_url,
                    endpoint_url=endpoint_url,
                    api_key=api_key,
                    model=model_name,
                )

                response = requests.post(
                    request_url,
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                response.raise_for_status()
                
                result = response.json()
                choices = result.get("choices", [])
                if not choices:
                    raise ValueError("LLM 응답에 choices가 없습니다.")

                assistant_message = choices[0].get("message", {})
                content = assistant_message.get("content", "")
                if isinstance(content, list):
                    # 멀티파트 응답(OpenAI 호환)에서 텍스트만 연결
                    text_chunks = [
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    ]
                    content = "".join(text_chunks)
                
                if content:
                    message_placeholder.markdown(content)
                    st.session_state.messages.append({"role": "assistant", "content": content})
                
                # 도구 실행 결과 확인
                execution_results = result.get('execution_results', [])
                
                if not execution_results:
                    # 도구 호출이 없으면 루프 종료
                    break
                    
                # 각 도구 실행 결과를 메시지에 추가하여 다음 턴의 컨텍스트로 제공
                for exec_info in execution_results:
                    call = exec_info.get('call', {})
                    tool_name = call.get('name')
                    tool_args = call.get('arguments', {})
                    tool_result = exec_info.get('result', {})
                    
                    with st.status(f"Tool Executing: {tool_name}", expanded=True) as status:
                        st.write(f"**Arguments:** {tool_args}")
                        st.write("**Execution Result:**", tool_result)
                        status.update(label=f"Tool {tool_name} completed", state="complete", expanded=False)
                    
                    # 도구 결과를 history에 추가 (Gemma가 다음 단계를 결정할 수 있도록)
                    # Gemma 3 형식에 맞춰 content에 결과를 포함시킴
                    result_message = f"Tool '{tool_name}' execution result: {json.dumps(tool_result, ensure_ascii=False)}"
                    st.session_state.messages.append({"role": "user", "content": f"[SYSTEM: {result_message}]"})
                
                # 도구 실행 후 짧은 대기 (데모 시각화용)
                time.sleep(1)
                
            except Exception as e:
                st.error(f"Error: {e}")
                break
        
        if iteration >= MAX_ITERATIONS:
            st.warning("최대 반복 횟수에 도달했습니다.")
