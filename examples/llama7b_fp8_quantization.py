import torch
from datasets import load_dataset
from transformers import AutoTokenizer

from sparseml.modifiers import GPTQModifier
from sparseml.transformers import SparseAutoModelForCausalLM, oneshot


model_stub = "meta-llama/Meta-Llama-3-8B-Instruct"
output_dir = "Meta-Llama-3-8B-Instruct-FP8-Compressed"
num_calibration_samples = 512

tokenizer = AutoTokenizer.from_pretrained(model_stub, use_fast=True)
tokenizer.pad_token = tokenizer.eos_token


def preprocess(batch):
    text = tokenizer.apply_chat_template(batch["messages"], tokenize=False)
    tokenized = tokenizer(text, padding=True, truncation=True, max_length=2048)
    return tokenized


ds = load_dataset("mgoin/ultrachat_2k", split="train_sft")
examples = ds.map(preprocess, remove_columns=ds.column_names)

recipe = GPTQModifier(targets=["Linear"], scheme="FP8", ignore=["lm_head"])

model = SparseAutoModelForCausalLM.from_pretrained(
    model_stub, torch_dtype=torch.bfloat16, device_map="auto"
)

oneshot(
    model=model,
    dataset=examples,
    recipe=recipe,
    output_dir=output_dir,
    num_calibration_samples=num_calibration_samples,
    save_compressed=True,
)
