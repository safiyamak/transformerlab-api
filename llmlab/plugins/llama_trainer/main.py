# The following comes from
# https://www.philschmid.de/instruction-tune-llama-2

from random import randrange
from string import Template
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments
from peft import LoraConfig, prepare_model_for_kbit_training, get_peft_model
import argparse
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig


use_flash_attention = False

# Get all parameters provided to this script from Transformer Lab
parser = argparse.ArgumentParser()
parser.add_argument('--model_name_or_path', type=str)
parser.add_argument('--data_path', type=str)
parser.add_argument('--output_dir', type=str)
parser.add_argument('--num_train_epochs', type=int)
parser.add_argument('--peft_model_id', type=str)
parser.add_argument('--job_id', type=str)
parser.add_argument('--lora_r', type=int)
parser.add_argument('--lora_alpha', type=int)
parser.add_argument('--lora_dropout', type=float)
parser.add_argument('--learning_rate', type=float)
parser.add_argument('--formatting_template', type=str)
args, unknown = parser.parse_known_args()

print("Arguments:")
print(args)

model_id = args.model_name_or_path
# model_id = "NousResearch/Llama-2-7b-hf"  # non-gated

# Load dataset from the hub
dataset = load_dataset(args.data_path, split="train")

print(f"dataset size: {len(dataset)}")
print(dataset[randrange(len(dataset))])
print("formatting_template: " + args.formatting_template)

# Takes in a template in the form of String.Template from Python's standard library
# https://docs.python.org/3.4/library/string.html#template-strings
# e.g. "$who likes $what"
template = Template(args.formatting_template)


def format_instruction(mapping):
    return template.substitute(mapping)


print("formatted instruction: (example) ")
print(format_instruction(dataset[randrange(len(dataset))]))


bnb_config = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_use_double_quant=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16
)


# Load model and tokenizer
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=bnb_config,
    use_cache=False,
    use_flash_attention_2=use_flash_attention,
    device_map="auto",
)
model.config.pretraining_tp = 1

tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"


# LoRA config based on QLoRA paper
peft_config = LoraConfig(
    lora_alpha=args.lora_alpha,
    lora_dropout=args.lora_dropout,
    r=args.lora_r,
    bias="none",
    task_type="CAUSAL_LM",
)


# prepare model for training
model = prepare_model_for_kbit_training(model)
model = get_peft_model(model, peft_config)


args = TrainingArguments(
    output_dir=args.peft_model_id,
    num_train_epochs=args.num_train_epochs,
    per_device_train_batch_size=6 if use_flash_attention else 4,
    gradient_accumulation_steps=2,
    gradient_checkpointing=True,
    optim="paged_adamw_32bit",
    logging_steps=10,
    save_strategy="epoch",
    learning_rate=args.learning_rate,
    bf16=True,
    tf32=True,
    max_grad_norm=0.3,
    warmup_ratio=0.03,
    lr_scheduler_type="constant",
    disable_tqdm=False  # disable tqdm since with packing values are in correct
)


max_seq_length = 2048  # max sequence length for model and packing of the dataset

trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    peft_config=peft_config,
    max_seq_length=max_seq_length,
    tokenizer=tokenizer,
    packing=True,
    formatting_func=format_instruction,
    args=args,
)


# train
trainer.train()

# save model
trainer.save_model()
