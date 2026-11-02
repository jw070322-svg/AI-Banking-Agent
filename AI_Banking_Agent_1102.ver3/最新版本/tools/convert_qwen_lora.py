"""Convert this project's Qwen2 q/v PEFT LoRA only; reject other architectures."""
from pathlib import Path
import json, re
import gguf
from safetensors import safe_open

root=Path(__file__).resolve().parents[1]
source=root/'training/lora-finance-qwen05b-full'
config=json.loads((source/'adapter_config.json').read_text(encoding='utf-8'))
if config['r'] != 8 or config['lora_alpha'] != 16 or set(config['target_modules']) != {'q_proj','v_proj'}:
    raise ValueError('Unsupported adapter configuration')
out=source/'adapter-qwen2.gguf'
if out.exists(): raise ValueError('Refusing to overwrite existing adapter')
writer=gguf.GGUFWriter(out,'qwen2')
writer.add_type(gguf.GGUFType.ADAPTER)
writer.add_string(gguf.Keys.Adapter.TYPE,'lora')
writer.add_float32(gguf.Keys.Adapter.LORA_ALPHA,16.0)
mapping=gguf.get_tensor_name_map(gguf.MODEL_ARCH.QWEN2,24)
with safe_open(source/'adapter_model.safetensors',framework='np') as f:
    keys=list(f.keys())
    if len(keys)!=96: raise ValueError('Unexpected tensor count')
    for key in keys:
        match=re.fullmatch(r'base_model\.model\.(model\.layers\.(\d+)\.self_attn\.(?:q_proj|v_proj))\.lora_([AB])\.weight',key)
        if not match or int(match[2])>=24: raise ValueError('Unexpected tensor: '+key)
        name=mapping.get_name(match[1]+'.weight',try_suffixes=('.weight',))
        if not name: raise ValueError('Unmapped tensor: '+key)
        tensor=f.get_tensor(key)
        if tensor.ndim!=2 or (tensor.shape[0] if match[3]=='A' else tensor.shape[1])!=8: raise ValueError('Unexpected LoRA shape')
        writer.add_tensor(name+'.lora_'+match[3].lower(),tensor)
writer.write_header_to_file();writer.write_kv_data_to_file();writer.write_tensors_to_file();writer.close()
print('Converted',len(keys),'tensors to',out)
