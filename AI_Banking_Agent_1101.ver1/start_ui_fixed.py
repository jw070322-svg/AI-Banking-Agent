"""Run the ver2 UI over the unchanged 1030 relay banking service."""
import argparse
from pathlib import Path
from start import prepare_node


def main():
    prepare_node()
    from relay_additions.runtime import RelayService
    from ui_fix.server import make_server
    parser=argparse.ArgumentParser(description='1030 ver2 UI修复版')
    parser.add_argument('--port',type=int,default=8805)
    parser.add_argument('--db',default=str(Path(__file__).parent/'runtime/ui-fixed.sqlite3'))
    parser.add_argument('--review-db')
    args=parser.parse_args()
    server=make_server(RelayService(args.db,review_db=args.review_db),port=args.port)
    print(f'UI修复版：http://127.0.0.1:{server.server_port}/',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__':main()
