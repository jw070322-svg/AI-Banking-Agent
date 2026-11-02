"""New entry point; leaves all existing application and RAG source files intact."""
from pathlib import Path
import argparse
from start import prepare_node
from first_agent.service import AgentService
from first_agent.rag_additions import AdditiveRAGService
from first_agent import server as http_server


def create_service(db_path=None):
    prepare_node()
    service=AgentService(db_path)
    service.rag=AdditiveRAGService(service.rag)
    return service


def main():
    parser=argparse.ArgumentParser(description='原RAG优先 + TF-IDF增量检索')
    parser.add_argument('--port',type=int,default=8799)
    parser.add_argument('--db',default=str(Path(__file__).resolve().parent/'runtime'/'rag-additive.sqlite3'))
    args=parser.parse_args()
    http_server.APP_VERSION='AI_Banking_Agent_1028.ver1'
    http_server.SESSION_COOKIE='banking_session_1028_v1'
    app=http_server.make_server(create_service(args.db),port=args.port)
    print(f'Additive RAG banking demo: http://127.0.0.1:{app.server_port}',flush=True)
    try:app.serve_forever()
    except KeyboardInterrupt:pass
    finally:app.server_close()


if __name__=='__main__':main()
