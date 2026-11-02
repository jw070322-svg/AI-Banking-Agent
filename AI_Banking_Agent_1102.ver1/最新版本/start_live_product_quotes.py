"""8805 UI baseline with additive official product quotes beside scoring NAV."""
import argparse
from pathlib import Path
from start import prepare_node


def main():
    prepare_node()
    # 演示入口必须自己把本地模型拉起来：此前只有 start.py 会启动，
    # 8807 打开后连接面板一直是“连接暂不可用”。
    from first_agent.local_ai_bootstrap import ensure_local_model
    ai = ensure_local_model()
    print(f"本地模型：{ai['message']}（{ai['state']}）", flush=True)
    if ai['state'] not in ('already_ready', 'started'):
        print(f"  原因：{ai['detail']}", flush=True)
    from live_products.runtime import LiveProductService, make_server
    root = Path(__file__).parent
    parser = argparse.ArgumentParser(description='产品行情版（保留8805整理版UI）')
    parser.add_argument('--port', type=int, default=8807)
    parser.add_argument('--db', default=str(root / 'runtime/product-quotes.sqlite3'))
    parser.add_argument('--review-db')
    args = parser.parse_args()
    (root / 'runtime').mkdir(parents=True, exist_ok=True)
    server = make_server(LiveProductService(args.db, review_db=args.review_db), port=args.port)
    print(f'产品行情版：http://127.0.0.1:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
