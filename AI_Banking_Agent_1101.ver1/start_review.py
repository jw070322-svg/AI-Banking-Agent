"""Run the 1029 RAG/security review additions on the original shared ledger."""
from pathlib import Path
import argparse
from start import prepare_node

def main():
    prepare_node()
    from review_additions.runtime import ReviewService, make_server
    parser = argparse.ArgumentParser(description='启动安全评测续作版')
    parser.add_argument('--port', type=int, default=8802)
    parser.add_argument('--db', default=str(Path(__file__).parent / 'runtime/review.sqlite3'))
    parser.add_argument('--review-db', help='显式启用本地已审核知识版本；无版本则拒答，不回退未审核资料')
    args = parser.parse_args()
    service = ReviewService(args.db)
    if args.review_db:
        from review_additions.live_knowledge import LiveKnowledge
        service.rag.live_knowledge = LiveKnowledge(args.review_db)
    app = make_server(service, port=args.port)
    print(f'安全评测续作版：http://127.0.0.1:{app.server_port}/', flush=True)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.server_close()

if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError) as exc:
        raise SystemExit('启动未完成：请确认 Python、Node.js 已安装，且8802端口未被其他程序占用。详情：' + str(exc))
