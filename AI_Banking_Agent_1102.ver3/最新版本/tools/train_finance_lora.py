"""Offline, local LoRA experiment on the installed Qwen GGUF, with term-level holdout.

Run with the dedicated training Python after installing torch, transformers, peft,
accelerate, gguf and safetensors. This never uploads data or replaces llama.cpp.
Evaluation loss is not a factual accuracy or safety certification.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json, math, random, sys
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import LoraConfig, get_peft_model

ROOT=Path(__file__).resolve().parents[1]
GGUF=Path(r'F:\AI_Banking\local-ai\qwen2.5-0.5b-instruct-q4_k_m.gguf')
EXPECTED='74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db'
SYSTEM='你是金融知识助手。只解释通用术语；不编造实时数据或收益承诺，不代替交易确认。'
random.seed(42);torch.manual_seed(42)
parser=argparse.ArgumentParser()
parser.add_argument('--max-train',type=int,default=0,help='0 means all training examples')
parser.add_argument('--max-eval',type=int,default=0,help='0 means all holdout examples')
parser.add_argument('--epochs',type=int,default=2)
parser.add_argument('--run-name',default='pilot',choices=['pilot','full'],help='output slot; never overwrites an earlier run')
options=parser.parse_args()
OUT=ROOT/'training'/('lora-finance-qwen05b' if options.run_name=='pilot' else 'lora-finance-qwen05b-full')
REPORT=ROOT/'reports'/('finance-lora-training.json' if options.run_name=='pilot' else 'finance-lora-training-full.json')
if min(options.max_train,options.max_eval)<0 or not 1<=options.epochs<=5:raise ValueError('训练参数无效')
if not GGUF.is_file() or hashlib.sha256(GGUF.read_bytes()).hexdigest()!=EXPECTED:
    raise RuntimeError('本地 GGUF 不存在或摘要不符')
DEVICE='cuda' if torch.cuda.is_available() else 'cpu'
if DEVICE=='cpu':torch.set_num_threads(min(8,torch.get_num_threads()))
if OUT.exists():raise RuntimeError('输出目录已存在，保留已有训练结果，不覆盖')
def records(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
train=records(ROOT/'training/train.jsonl');holdout=records(ROOT/'training/holdout.jsonl')
if not train or not holdout or {r['term'] for r in train}&{r['term'] for r in holdout}:
    raise RuntimeError('训练集和按术语分组的保留集为空或有重叠')
all_train_count,all_holdout_count=len(train),len(holdout)
random.shuffle(train);random.shuffle(holdout)
if options.max_train:train=train[:options.max_train]
if options.max_eval:holdout=holdout[:options.max_eval]
print('Loading locally installed GGUF; no model or data upload',flush=True)
tok=AutoTokenizer.from_pretrained(str(GGUF.parent),gguf_file=GGUF.name,local_files_only=True)
model=AutoModelForCausalLM.from_pretrained(str(GGUF.parent),gguf_file=GGUF.name,
    local_files_only=True,torch_dtype=torch.float16 if DEVICE=='cuda' else torch.float32).to(DEVICE)
model.config.use_cache=False

def tensors(row):
    messages=[{'role':'system','content':SYSTEM},{'role':'user','content':row['question']}]
    prefix=tok.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
    suffix=row['answer']+(tok.eos_token or '<|im_end|>')
    prompt_ids=tok(prefix,add_special_tokens=False)['input_ids']
    answer_ids=tok(suffix,add_special_tokens=False)['input_ids']
    ids=(prompt_ids+answer_ids)[:384];labels=([-100]*len(prompt_ids)+answer_ids)[:384]
    if not any(x!=-100 for x in labels):raise RuntimeError('答案超出上下文限制')
    return torch.tensor([ids],device=DEVICE),torch.tensor([labels],device=DEVICE)

def evaluate():
    model.eval();weighted=0.;count=0
    with torch.no_grad():
        for row in holdout:
            ids,labels=tensors(row);n=int((labels[:,1:]!=-100).sum().item())
            value=model(input_ids=ids,labels=labels).loss.item()
            if not math.isfinite(value):raise RuntimeError('保留集损失非有限值')
            weighted+=value*n;count+=n
    return {'mean_token_loss':weighted/count,'tokens':count,'examples':len(holdout)}

before=evaluate();print('holdout before',before,flush=True)
model=get_peft_model(model,LoraConfig(r=8,lora_alpha=16,lora_dropout=0.05,bias='none',
    task_type='CAUSAL_LM',target_modules=['q_proj','v_proj']))
params=[p for p in model.parameters() if p.requires_grad]
if not params:raise RuntimeError('没有可训练的 LoRA 参数')
optimizer=torch.optim.AdamW(params,lr=0.0001);losses=[];steps=0
model.train();optimizer.zero_grad(set_to_none=True)
for epoch in range(options.epochs):
    order=list(train);random.shuffle(order)
    for i,row in enumerate(order):
        ids,labels=tensors(row);loss=model(input_ids=ids,labels=labels).loss
        if not torch.isfinite(loss):raise RuntimeError('训练损失非有限值')
        (loss/8).backward();losses.append(float(loss.detach()))
        if (i+1)%8==0 or i+1==len(order):
            torch.nn.utils.clip_grad_norm_(params,1.0);optimizer.step();optimizer.zero_grad(set_to_none=True);steps+=1
            print('optimizer step',steps,'sample',i+1,'/',len(order),flush=True)
    print('epoch',epoch+1,'optimizer_steps',steps,'mean_loss',sum(losses[-len(order):])/len(order),flush=True)
after=evaluate();OUT.mkdir(parents=True)
model.save_pretrained(OUT,safe_serialization=True);tok.save_pretrained(OUT)
report={'at':datetime.now(timezone.utc).isoformat(),'status':'trained_experiment_not_deployed',
        'base_model':'Qwen2.5-0.5B-Instruct Q4_K_M GGUF dequantized for training',
        'base_sha256':EXPECTED,'training_device':torch.cuda.get_device_name(0) if DEVICE=='cuda' else 'CPU','seed':42,
        'training_examples':len(train),'holdout_examples':len(holdout),'available_training_examples':all_train_count,
        'available_holdout_examples':all_holdout_count,'epochs':options.epochs,'optimizer_steps':steps,
        'trainable_parameters':sum(p.numel() for p in params),'holdout_before':before,'holdout_after':after,
        'holdout_loss_improved':after['mean_token_loss']<before['mean_token_loss'],
        'safety_or_factual_accuracy_certified':False,'deployed_to_llama_cpp':False,
        'adapter_path':str(OUT),'training_data':'original general educational summaries; no customer data'}
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
