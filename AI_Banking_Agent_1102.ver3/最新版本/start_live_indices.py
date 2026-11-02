"""8805 UI baseline with additive official index source selection."""
import argparse
from pathlib import Path
from start import prepare_node


def main():
    prepare_node()
    # 与 8807 保持一致：对照入口也拉起本地模型，失败原因照样打印。
    from first_agent.local_ai_bootstrap import ensure_local_model
    ai = ensure_local_model()
    print(f"本地模型：{ai['message']}（{ai['state']}）", flush=True)
    if ai['state'] not in ('already_ready', 'started'):
        print(f"  原因：{ai['detail']}", flush=True)
    from live_indices.runtime import LiveIndexService, make_server
    root = Path(__file__).parent
    parser = argparse.ArgumentParser(description='官网指数优先版（保留8805整理版UI）')
    parser.add_argument('--port', type=int, default=8806)
    parser.add_argument('--db', default=str(root / 'runtime/live-indices.sqlite3'))
    parser.add_argument('--review-db')
    args = parser.parse_args()
    server = make_server(LiveIndexService(args.db, review_db=args.review_db), port=args.port)
    print(f'官网指数优先版：http://127.0.0.1:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
