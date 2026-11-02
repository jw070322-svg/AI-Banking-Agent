"""Local-only, single-ledger web + Guardian entry point."""
from pathlib import Path
import argparse
import os
from first_agent.local_ai_bootstrap import ensure_local_model, auth_enforced
from start import prepare_node

def main():
    prepare_node()
    from security_integration.runtime import IntegratedService,make_server
    p=argparse.ArgumentParser(description='安全主链整合版（本地模拟）')
    p.add_argument('--port',type=int,default=8808)
    p.add_argument('--db',default=str(Path(__file__).parent/'runtime/security-integrated.sqlite3'))
    p.add_argument('--review-db')
    a=p.parse_args()
    if os.name == 'nt':
        from first_agent.reviewer_model import ensure_reviewer_model
        ensure_reviewer_model()
        status = ensure_local_model()
        if status['state'] not in ('started', 'already_ready') or not auth_enforced()['enforced']:
            raise SystemExit(f"本地模型未就绪或鉴权失败。{status['message']}。{status['detail']}")
        print(f"本地模型已就绪（{status['state']}，金融 LoRA 已挂载）", flush=True)
    service=IntegratedService(a.db,review_db=a.review_db)
    server=make_server(service,port=a.port)
    print(f'安全主链整合版：http://127.0.0.1:{server.server_port}/',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
