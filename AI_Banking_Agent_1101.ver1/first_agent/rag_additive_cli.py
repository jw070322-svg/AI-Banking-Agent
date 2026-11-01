"""Read-only CLI for the additive RAG and the optional new-script contract."""
from pathlib import Path
import argparse, json
from .vendor.rag.service import RAGService
from .rag_additions import AdditiveRAGService, compatibility_response

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('question')
    parser.add_argument('--top-k',type=int,default=3)
    parser.add_argument('--as-of')
    parser.add_argument('--compat',action='store_true')
    args=parser.parse_args()
    rag=AdditiveRAGService(RAGService(Path(__file__).resolve().parents[1]/'knowledge/index.json'))
    result=rag.ask(args.question,args.top_k,as_of=args.as_of)
    if args.compat:result=compatibility_response(result,args.top_k)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
