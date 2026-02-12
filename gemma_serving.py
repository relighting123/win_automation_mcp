import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from transformers import AutoTokenizer, AutoModelForCausalLM
import uvicorn
import json

app = FastAPI(title="Function-Gemma Local Serving API")

# 모델 경로 또는 이름 (Gemma 3 4B IT 추천)
MODEL_ID = "google/gemma-3-4b-it"

print(f"Loading model: {MODEL_ID}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    device_map="auto",
    torch_dtype=torch.bfloat16,
)
print("Model loaded successfully.")

class ChatMessage(BaseModel):
    role: str
    content: str

class ToolCallRequest(BaseModel):
    messages: List[ChatMessage]
    tools: List[Dict[str, Any]]
    temperature: float = 0.1

@app.post("/v1/chat/completions")
async def chat_completions(request: ToolCallRequest):
    try:
        # Gemma 3의 도구 호출 형식에 맞게 메시지 구성
        # 힌트: Gemma 3는 특수 토큰과 구조화된 출력을 지원합니다.
        
        chat = []
        for msg in request.messages:
            chat.append({"role": msg.role, "content": msg.content})
            
        # 텐서 준비
        input_ids = tokenizer.apply_chat_template(
            chat,
            tools=request.tools,
            add_generation_prompt=True,
            return_tensors="pt"
        ).to(model.device)
        
        # 생성
        outputs = model.generate(
            input_ids,
            max_new_tokens=1024,
            do_sample=True,
            temperature=request.temperature,
        )
        
        # 디코딩 (입력 부분 제외)
        response_ids = outputs[0][input_ids.shape[-1]:]
        response_text = tokenizer.decode(response_ids, skip_special_tokens=True)
        
        # 응답 파싱 및 반환 (OpenAI 호환 포맷 흉내)
        # 실제 Gemma 3는 <tool_call> 태그 등을 사용할 수 있음
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": response_text
                    },
                    "finish_reason": "stop"
                }
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
