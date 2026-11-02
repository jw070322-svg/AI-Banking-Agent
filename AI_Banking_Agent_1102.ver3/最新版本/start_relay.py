"""1030 additive continuation; Python UTF-8 mode is enabled by the launcher."""
import argparse
from pathlib import Path
from start import prepare_node


def main():
    prepare_node()
    from relay_additions.runtime import RelayService, make_server
    parser = argparse.ArgumentParser(description='启动1030接力验收版')
    parser.add_argument('--port', type=int, default=8803)
    parser.add_argument('--db', default=str(Path(__file__).parent / 'runtime/relay.sqlite3'))
    parser.add_argument('--review-db', help='启用已审核知识模式；无发布版本则拒答')
    args = parser.parse_args()
    service = RelayService(args.db, review_db=args.review_db)
    app = make_server(service, port=args.port)
    print(f'1030接力验收版：http://127.0.0.1:{app.server_port}/', flush=True)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.server_close()


if __name__ == '__main__':
    main()
