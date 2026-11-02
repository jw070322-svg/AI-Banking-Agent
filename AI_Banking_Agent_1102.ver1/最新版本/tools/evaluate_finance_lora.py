"""Offline exploratory generation comparison; outputs require human review."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json, random
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

ROOT = Path(__file__).resolve().parents[1]
GGUF = Path(r'F:\AI_Banking\local-ai\qwen2.5-0.5b-instruct-q4_k_m.gguf')
EXPECTED = '74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db'
SYSTEM = '你是金融知识助手。只解释通用术语；不编造实时数据或收益承诺，不代替交易确认。'
parser = argparse.ArgumentParser()
parser.add_argument('--run-name', default='pilot', choices=['pilot','full'])
options = parser.parse_args()
adapter_path = ROOT / 'training' / ('lora-finance-qwen05b' if options.run_name == 'pilot' else 'lora-finance-qwen05b-full')
report_path = ROOT / 'reports' / ('finance-lora-generation.json' if options.run_name == 'pilot' else 'finance-lora-generation-full.json')
if hashlib.sha256(GGUF.read_bytes()).hexdigest() != EXPECTED:
    raise RuntimeError('基底文件摘要不匹配')
torch.set_num_threads(min(8, torch.get_num_threads()))
records = lambda name: [json.loads(line) for line in (ROOT / 'training' / name).read_text(encoding='utf-8').splitlines() if line.strip()]
train, holdout = records('train.jsonl'), records('holdout.jsonl')
rng = random.Random(42)
rng.shuffle(train); rng.shuffle(holdout)
examples = holdout[:3]
print('Loading base model for held-out generation comparison', flush=True)
tokenizer = AutoTokenizer.from_pretrained(str(GGUF.parent), gguf_file=GGUF.name, local_files_only=True)
base = AutoModelForCausalLM.from_pretrained(str(GGUF.parent), gguf_file=GGUF.name, local_files_only=True, torch_dtype=torch.float32)
model = PeftModel.from_pretrained(base, adapter_path, is_trainable=False)
model.eval()
results = []
for row in examples:
    prompt = tokenizer.apply_chat_template([{'role':'system','content':SYSTEM},{'role':'user','content':row['question']}], tokenize=False, add_generation_prompt=True)
    encoded = tokenizer(prompt, return_tensors='pt', add_special_tokens=False)
    item = {'term':row['term'], 'question':row['question'], 'reference':row['answer']}
    for label in ('base', 'adapter'):
        with torch.no_grad():
            if label == 'base':
                with model.disable_adapter():
                    out = model.generate(**encoded, max_new_tokens=80, do_sample=False, pad_token_id=tokenizer.eos_token_id)
            else:
                out = model.generate(**encoded, max_new_tokens=80, do_sample=False, pad_token_id=tokenizer.eos_token_id)
        item[label] = tokenizer.decode(out[0][encoded['input_ids'].shape[1]:], skip_special_tokens=True)
        print(label, row['term'], item[label], flush=True)
    results.append(item)
report = {'at':datetime.now(timezone.utc).isoformat(),'status':'exploratory_requires_human_review','examples':results,'scope':'three held-out prompts; no automatic factual or safety certification'}
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
