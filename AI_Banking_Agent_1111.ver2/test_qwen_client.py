"""qwen_client 的假服务器测试：协议、解析、修复与回退路径全部本地验证。

假服务器只模拟 OpenAI 形状的最小响应；这些测试不依赖真实模型，
也不是模型评测——真实基线见 evaluate_gold_set.py。
"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from qwen_client import QwenClient, QwenClientError

VALID = {"service_categories": ["生日餐厅"], "public_keywords": ["生日餐厅"],
         "constraints": [], "needs_clarification": False, "evidence_spans": ["生日"]}


def chat_response(content):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 1}}


class ScriptedHandler(BaseHTTPRequestHandler):
    """按测试注入的脚本逐次响应；记录请求供断言。"""

    server_version = "FakeQwen/1"

    def log_message(self, *args):  # 静默
        pass

    def _reply(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            if self.headers.get("Authorization") != "Bearer test-key":
                return self._reply({"error": "unauthorized"}, 401)
            return self._reply({"data": [{"id": "banking-qwen2.5-0.5b"}]})
        return self._reply({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.requests.append(request)
        script = self.server.script
        if not script:
            return self._reply({"error": "no scripted response"}, 500)
        item = script.pop(0)
        if isinstance(item, int):          # HTTP 错误码
            return self._reply({"error": "scripted"}, item)
        if isinstance(item, Exception):    # 模拟断连
            raise item
        if isinstance(item, dict) and "choices" not in item:  # 缺 choices 的坏响应
            return self._reply(item)
        return self._reply(item)


class FakeServerTestCase(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedHandler)
        self.server.requests = []
        self.server.script = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = QwenClient(base_url=f"http://127.0.0.1:{self.server.server_port}",
                                 key="test-key", timeout=5)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()


class ProbeTests(FakeServerTestCase):
    def test_probe_ok(self):
        probe = self.client.probe()
        self.assertTrue(probe["ok"])
        self.assertEqual(probe["models"], ["banking-qwen2.5-0.5b"])

    def test_probe_auth_failure(self):
        self.client._key = "wrong-key"
        probe = self.client.probe()
        self.assertFalse(probe["ok"])
        self.assertIn("401", probe["reason"])

    def test_probe_service_down(self):
        port = self.server.server_port
        self.server.shutdown()
        client = QwenClient(base_url=f"http://127.0.0.1:{port}", key="test-key", timeout=2)
        probe = client.probe()
        self.assertFalse(probe["ok"])
        self.assertIn("不可达", probe["reason"])


class ExtractTests(FakeServerTestCase):
    def test_plain_json_ok_and_request_hygiene(self):
        self.server.script = [chat_response(json.dumps(VALID, ensure_ascii=False))]
        result = self.client.extract("生日聚餐")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["raw_parse_ok"])
        self.assertFalse(result["repair_used"])
        self.assertEqual(result["parsed"]["public_keywords"], ["生日餐厅"])
        self.assertEqual(result["evidence"], {"valid": ["生日"], "invalid": []})
        request = self.server.requests[0]
        self.assertEqual(request["temperature"], 0)
        sent = json.dumps(request, ensure_ascii=False)
        # 城市与预算绝不进入请求：模型无权改写
        self.assertNotIn("杭州", sent)
        self.assertNotIn("600", sent)
        self.assertNotIn("budget", sent)
        self.assertIn("生日聚餐", sent)  # 只发送事件原文

    def test_fenced_json_repaired_once(self):
        fenced = "```json\n" + json.dumps(VALID, ensure_ascii=False) + "\n```"
        self.server.script = [chat_response(fenced),
                              chat_response(json.dumps(VALID, ensure_ascii=False))]
        result = self.client.extract("生日聚餐")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["repair_used"])
        self.assertEqual(len(self.server.requests), 2)
        # 修复请求保留原始助手输出，要求纯JSON
        self.assertEqual(self.server.requests[1]["messages"][-2]["role"], "assistant")
        self.assertIn("纯JSON", self.server.requests[1]["messages"][-1]["content"])

    def test_invalid_after_repair_falls_back(self):
        self.server.script = [chat_response("抱歉我不会"),
                              chat_response("还是不会")]
        result = self.client.extract("生日聚餐")
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("一次格式修复后仍无效", result["reason"])
        self.assertIsNone(result["parsed"])

    def test_schema_violation_triggers_repair_path(self):
        extra_field = dict(VALID, __extra__=1)
        self.server.script = [chat_response(json.dumps(extra_field, ensure_ascii=False)),
                              chat_response(json.dumps(VALID, ensure_ascii=False))]
        result = self.client.extract("生日聚餐")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["repair_used"])

    def test_invalid_evidence_span_is_flagged_not_silently_dropped(self):
        bad_span = dict(VALID, evidence_spans=["生日", "不存在的片段"])
        self.server.script = [chat_response(json.dumps(bad_span, ensure_ascii=False))]
        result = self.client.extract("生日聚餐")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["evidence"]["valid"], ["生日"])
        self.assertEqual(result["evidence"]["invalid"], ["不存在的片段"])

    def test_out_of_vocabulary_keyword_flagged(self):
        # 模拟模型把事件原文回显进关键词（隐私风险场景）
        echo = dict(VALID, public_keywords=["特殊需求", "生日餐厅"])
        self.server.script = [chat_response(json.dumps(echo, ensure_ascii=False))]
        result = self.client.extract("特殊需求")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["out_of_vocabulary"], ["特殊需求"])

    def test_in_vocabulary_keyword_not_flagged(self):
        self.server.script = [chat_response(json.dumps(VALID, ensure_ascii=False))]
        result = self.client.extract("生日聚餐")
        self.assertEqual(result["out_of_vocabulary"], [])

    def test_service_error_is_unavailable(self):
        self.server.script = [500]
        result = self.client.extract("生日聚餐")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("500", result["reason"])

    def test_empty_event_needs_no_network(self):
        result = self.client.extract("  ")
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(self.server.requests, [])

    def test_repetition_loop_output_skips_repair(self):
        # 基线评测实测风险：重复循环长输出会使修复请求超上下文（HTTP 400）
        loop = '{"service_categories": ["蛋糕", ' + '"蛋糕", ' * 900 + '"蛋糕"]}'
        self.assertGreater(len(loop), 4000)
        self.server.script = [chat_response(loop)]
        result = self.client.extract("亲子聚餐")
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("跳过修复", result["reason"])
        self.assertEqual(len(self.server.requests), 1)  # 未发修复请求

    def test_request_bounds_generation(self):
        self.server.script = [chat_response(json.dumps(VALID, ensure_ascii=False))]
        self.client.extract("生日聚餐")
        request = self.server.requests[0]
        self.assertEqual(request["max_tokens"], 512)  # 防重复循环耗尽上下文

    def test_missing_key_file_reported_as_unavailable(self):
        client = QwenClient(base_url="http://127.0.0.1:1", key_file="Z:/no/such.key")
        probe = client.probe()  # 探针契约：返回状态，不抛错
        self.assertFalse(probe["ok"])
        self.assertIn("缺少本地密钥文件", probe["reason"])
        result = client.extract("生日聚餐")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("缺少本地密钥文件", result["reason"])


if __name__ == "__main__":
    unittest.main()
