import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    pipeline,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer, SFTConfig
import os

# 모델 및 데이터 경로
MODEL_ID = "./model"
DATA_PATH = "tool_calling_dataset.jsonl"
OUTPUT_DIR = "./gemma-windows-automation-lora"

def main():
    # 1. 토크나이저 로드 (Fast Tokenizer의 regex 오류 우회를 위해 use_fast=False 사용)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=False)
    tokenizer.pad_token = tokenizer.eos_token

    # 2. 데이터셋 로드
    dataset = load_dataset("json", data_files=DATA_PATH, split="train")

    # 3. 모델 양자화 및 데이터 타입 설정
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    bnb_config = None
    compute_dtype = torch.float32
    
    if device == "cuda":
        compute_dtype = torch.float16 # bf16 미지원 대비 fp16 사용
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=compute_dtype
        )

    # 4. 모델 로드
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=bnb_config,
        device_map="auto" if device == "cuda" else None,
        dtype=compute_dtype,
    )
    if device == "cuda":
        model = prepare_model_for_kbit_training(model)

    # 5. LoRA 설정
    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "o_proj", "k_proj", "v_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )
    # SFTTrainer가 내부적으로 get_peft_model을 수행하므로 직접 호출은 생략합니다.

    # 6. 학습 인자 설정
    training_args = SFTConfig(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=1 if device == "cpu" else 2,
        gradient_accumulation_steps=8 if device == "cpu" else 4,
        learning_rate=2e-4,
        max_steps=10, # CPU에서는 매우 느리므로 테스트용으로 축소
        logging_steps=1,
        save_strategy="no",
        bf16=False,
        fp16=(device == "cuda"),
        push_to_hub=False,
        report_to="none",
        use_cpu=(device == "cpu"),
        max_length=1024,
    )

    # 7. 트레이너 실행
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        
        peft_config=lora_config,
        processing_class=tokenizer,
        args=training_args,
    )

    print("Starting training...")
    trainer.train()

    # 8. 모델 저장
    trainer.model.save_pretrained(OUTPUT_DIR)
    print(f"Fine-tuning complete. Model saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
