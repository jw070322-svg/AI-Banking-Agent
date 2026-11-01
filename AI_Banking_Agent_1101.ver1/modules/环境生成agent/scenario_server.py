"""scenario_server.py —— 环境生成 Agent 的最小 HTTP 入口（仅标准库）
=====================================================================

用途：在没有 first_agent 主服务时，本地单独验证
`POST /api/scenarios/generate` 是否符合根目录 API-CONTRACT.md。

启动：
    python scenario_server.py --port 8765

调用：
    curl -s http://127.0.0.1:8765/api/health
    curl -s -X POST http://127.0.0.1:8765/api/scenarios/generate \
         -H "Content-Type: application/json" \
         -H "Idempotency-Key: demo-1" \
         -d "{\"prompt\":\"生成一个疑似重复扣款场景\",\"seed\":7}"

安全边界：
- 只监听 127.0.0.1；
- 校验 Host / Origin，只接受本机来源；
- 响应 `simulated: true`、`ledger_modified: false`，不接触任何真实银行或账本；
- 生产接入时应把 handle_generate 注册到 first_agent/server.py，而不是暴露本脚本。
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from scenario_adapter import handle_generate

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
ALLOWED_ORIGINS = {"http://127.0.0.1", "http://localhost"}

# 契约状态 -> HTTP 状态码（便于主服务/前端区分处理）
STATUS_CODES = {
    "succeeded": HTTPStatus.OK,
    "rejected": HTTPStatus.UNPROCESSABLE_ENTITY,
    "failed": HTTPStatus.INTERNAL_SERVER_ERROR,
}


def _json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _origin_allowed(origin: Optional[str]) -> bool:
    """只允许本机来源。没有 Origin 的请求（curl / 服务端调用）放行。"""
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.hostname in ALLOWED_HOSTS


class ScenarioHandler(BaseHTTPRequestHandler):
    server_version = "ScenarioAgent/1.0"

    # ---- 工具方法 ----
    def _send(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Simulated", "true")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._send(status, {
            "schema_version": "1.0.0",
            "request_id": f"REQ-{uuid.uuid4().hex[:12].upper()}",
            "status": "rejected" if status == HTTPStatus.UNPROCESSABLE_ENTITY else "failed",
            "data": None,
            "error": {"code": code, "message": message},
            "trace": {"server": "scenario_server"},
            "simulated": True,
        })

    def _host_allowed(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ALLOWED_HOSTS

    def _session_id(self) -> str:
        """没有会话系统时使用固定演示会话；有 Cookie 时按 Cookie 隔离幂等键。"""
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "demo_session" and value:
                return value[:64]
        return "demo"

    # ---- 路由 ----
    def do_GET(self) -> None:  # noqa: N802（http.server 规定的名字）
        if not self._host_allowed():
            self._error(HTTPStatus.FORBIDDEN, "HOST_NOT_ALLOWED", "只允许本机访问")
            return
        if self.path == "/api/health":
            self._send(HTTPStatus.OK, {
                "ready": True,
                "persistent": False,
                "mode": "scenario-generator-only",
            })
            return
        self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "接口不存在")

    def do_POST(self) -> None:  # noqa: N802
        started = time.perf_counter()

        if not self._host_allowed() or not _origin_allowed(self.headers.get("Origin")):
            self._error(HTTPStatus.FORBIDDEN, "ORIGIN_NOT_ALLOWED", "只允许本机来源")
            return

        if self.path != "/api/scenarios/generate":
            self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "接口不存在")
            return

        idempotency_key = self.headers.get("Idempotency-Key")
        if not idempotency_key:
            self._error(
                HTTPStatus.BAD_REQUEST, "IDEMPOTENCY_KEY_REQUIRED",
                "POST 请求必须提供 Idempotency-Key",
            )
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "INVALID_BODY", "Content-Length 不合法")
            return
        if length <= 0 or length > 64 * 1024:
            self._error(HTTPStatus.BAD_REQUEST, "INVALID_BODY", "请求体为空或过大")
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "INVALID_JSON", "请求体必须是合法 JSON")
            return

        response = handle_generate(
            payload,
            idempotency_key=idempotency_key,
            session_id=self._session_id(),
        )
        status = response["status"]
        http_status = STATUS_CODES.get(status, HTTPStatus.INTERNAL_SERVER_ERROR)
        if response.get("error", {}) and response["error"].get("code") == "IDEMPOTENCY_CONFLICT":
            http_status = HTTPStatus.CONFLICT

        response.setdefault("trace", {})["server_duration_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )
        self._send(http_status, response)

    def log_message(self, fmt: str, *args: Any) -> None:
        """只记录方法、路径和状态码，不记录请求体（避免日志泄露 prompt）。"""
        print(f"[scenario-server] {self.address_string()} {fmt % args}")


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), ScenarioHandler)
    print(f"环境生成接口已启动：http://{host}:{port}")
    print("  GET  /api/health")
    print("  POST /api/scenarios/generate（必须带 Idempotency-Key）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="环境生成 Agent 本地 HTTP 入口")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.host not in ALLOWED_HOSTS:
        parser.error("只允许监听 127.0.0.1 或 localhost")
    serve(args.host, args.port)
