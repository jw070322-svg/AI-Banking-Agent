"""Start the local integrated demo, using installed Node or a bundled Codex runtime."""
from pathlib import Path
import os, shutil, subprocess, sys

def prepare_node():
    node=shutil.which('node')
    if not node:
        root=Path.home()/'Library/Application Support/Codex/artifact-sessions/runtime-generations'
        candidates=sorted(root.glob('*/runtime/bin/node')) if root.exists() else []
        node=str(candidates[-1]) if candidates else None
    if not node:
        raise RuntimeError('需要 Node.js 18或以上。请安装后重新打开启动脚本。')
    version=subprocess.check_output([node,'--version'],text=True).strip()
    if int(version.lstrip('v').split('.')[0])<18:raise RuntimeError('Node.js版本过低，需要18或以上。')
    os.environ['PATH']=str(Path(node).parent)+os.pathsep+os.environ.get('PATH','')
    return node

if __name__=='__main__':
    try:
        if sys.version_info<(3,9):raise RuntimeError('需要 Python 3.9或以上。')
        prepare_node()
        os.chdir(Path(__file__).resolve().parent)
        # 共用引导：不再吞掉启动器输出，也不再用 10 秒盲杀。
        from first_agent.local_ai_bootstrap import ensure_local_model
        ai = ensure_local_model()
        print(f"本地模型：{ai['message']}（{ai['state']}）", flush=True)
        if ai['state'] not in ('already_ready', 'started'):
            print(f"  原因：{ai['detail']}", flush=True)
            for pid in ai.get('listening_pids') or []:
                print(f"  占用 8797 的进程：PID {pid}", flush=True)
        from first_agent.server import main
        if '--port' not in sys.argv:sys.argv.extend(['--port','8798'])
        main()
    except (RuntimeError, OSError) as exc:
        print('启动失败：'+str(exc),file=sys.stderr)
        sys.exit(1)
