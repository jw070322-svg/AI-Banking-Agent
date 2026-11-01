#!/bin/zsh
cd -- "$(dirname -- "$0")"
echo "安全自评增强版（本地模拟）：http://127.0.0.1:8808/"
python3 -X utf8 start_security_integrated.py
read "?服务已停止，按回车关闭窗口。"
