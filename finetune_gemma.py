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
from trl import SFTTrainer
import os

# 모델 및 데이터 경로
MODEL_ID = "google/gemma-3-4b-it"
DATA_PATH = "tool_calling_dataset.jsonl"
OUTPUT_DIR = "./gemma-windows-automation-lora"

def main():
    # 1. 토크나이저 로드
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    tokenizer.pad_token = tokenizer.eos_token

    # 2. 데이터셋 로드
    dataset = load_dataset("json", data_files=DATA_PATH, split="train")

    # 3. 모델 양자화 설정 (QLoRA)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16
    )

    # 4. 모델 로드
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
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
    model = get_peft_model(model, lora_config)

    # 6. 학습 인자 설정
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        max_steps=100, # 빠른 테스트를 위해 적은 step으로 설정
        logging_steps=10,
        save_strategy="steps",
        save_steps=50,
        bf16=True,
        push_to_hub=False,
        report_to="none"
    )

    # 7. 트레이너 실행
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=lora_config,
        dataset_text_field="text", # 데이터 구조에 따라 조정 필요
        max_seq_length=1024,
        tokenizer=tokenizer,
        args=training_args,
    )

    print("Starting training...")
    trainer.train()

    # 8. 모델 저장
    trainer.model.save_pretrained(OUTPUT_DIR)
    print(f"Fine-tuning complete. Model saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
泛泛泛
