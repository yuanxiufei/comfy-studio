"""桌面侧 comfy-studio 宿主的端到端测试（真进程、真 MCP 子进程）。

跑法（引擎 venv 的 python，从本文件所在处往上一级就是 comfy_studio 包）::

    cd Comfy-Desktop/lib
    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest discover -s comfy_studio/tests -v

它需要**同一仓库里的 ComfyUI 检出**（默认是 ../../.. 下的 ComfyUI），因为
宿主本身要 spawn 引擎那个 MCP server；引擎**不必在运行**——这里只碰不依赖
运行中引擎的工具（列 skill / 工具表 / 会话协议）。缺 ComfyUI 或 venv 时整组跳过，
不会假装通过。

模型侧用本地假服务顶上：第一轮回一个 tool_call 去调 ``comfy_list_skills``，
第二轮回最终文本。这样能在不联网、不花钱的前提下验证「agent 真的走了 MCP 工具」。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
COMFYUI_DIR = REPO_ROOT / "ComfyUI"
LIB_DIR = REPO_ROOT / "Comfy-Desktop" / "lib"
VENV_PYTHON = COMFYUI_DIR / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
ENGINE_PACKAGE = COMFYUI_DIR / "custom_nodes" / "comfy_studio"

TIMEOUT = 90.0
SKILLS_TIMEOUT = 180.0


class _FakeCompletions(BaseHTTPRequestHandler):
    """假 chat completions 服务：先要工具、再给结论；顺带提供 ``GET /models``。"""

    #: 每次 chat completions 请求体里的 model（验证切换真的落到了请求上）。
    seen_models: list[str] = []
    lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的接口
        if self.path.rstrip("/").endswith("/models"):
            self._json(
                {
                    "object": "list",
                    "data": [{"id": name} for name in ("fake-model", "other-model", "third-model")],
                }
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的接口
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        with self.lock:
            self.seen_models.append(str(body.get("model")))

        messages = body.get("messages") or []
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        if tool_messages:
            count = len(json.loads(tool_messages[0]["content"]))
            message = {"role": "assistant", "content": f"本机有 {count} 个 skill"}
        else:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "comfy-studio__comfy_list_skills",
                            "arguments": "{}",
                        },
                    }
                ],
            }
        self._json({"choices": [{"index": 0, "message": message}]})

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@unittest.skipUnless(
    VENV_PYTHON.exists() and (ENGINE_PACKAGE / "mcp" / "server.py").exists(),
    f"需要 {VENV_PYTHON} 与 {ENGINE_PACKAGE}（先跑仓库根的 npm run setup）",
)
class StudioHostE2ETest(unittest.TestCase):
    llm: ThreadingHTTPServer
    proc: subprocess.Popen
    lines: list[dict]
    lock: threading.Lock

    @classmethod
    def setUpClass(cls) -> None:
        cls.lines = []
        cls.lock = threading.Lock()
        cls.llm = ThreadingHTTPServer(("127.0.0.1", 0), _FakeCompletions)
        threading.Thread(target=cls.llm.serve_forever, daemon=True).start()
        port = cls.llm.server_address[1]

        # cwd 必须是包父目录，`-m comfy_studio` 才找得到包。
        cls.proc = subprocess.Popen(
            [
                str(VENV_PYTHON),
                "-X",
                "utf8",
                "-m",
                "comfy_studio",
                "--comfyui-dir",
                str(COMFYUI_DIR),
            ],
            cwd=str(LIB_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env={
                **os.environ,
                "COMFY_STUDIO_LLM_MODEL": "fake-model",
                "COMFY_STUDIO_LLM_BASE_URL": f"http://127.0.0.1:{port}/v1",
            },
        )
        threading.Thread(target=cls._pump_stdout, daemon=True).start()
        threading.Thread(target=cls._pump_stderr, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.proc.stdin is not None and not cls.proc.stdin.closed:
            cls.proc.stdin.close()  # 关 stdin ⇒ 宿主见 EOF 自行退出
        try:
            cls.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.llm.shutdown()

    @classmethod
    def _pump_stdout(cls) -> None:
        assert cls.proc.stdout is not None
        for line in cls.proc.stdout:
            text = line.strip()
            if not text:
                continue
            with cls.lock:
                cls.lines.append(json.loads(text))

    @classmethod
    def _pump_stderr(cls) -> None:
        assert cls.proc.stderr is not None
        for line in cls.proc.stderr:
            sys.stderr.write("[host] " + line)

    # ---- 工具 -----------------------------------------------------------

    def call(self, request_id: int, method: str, params: dict | None = None, timeout: float = TIMEOUT) -> dict:
        assert self.proc.stdin is not None
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            + "\n"
        )
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for message in self.lines:
                    if message.get("id") == request_id:
                        return message
            time.sleep(0.05)
        self.fail(f"{method} 超时")

    def notifications(self, request_id: int) -> list[dict]:
        with self.lock:
            return [
                m
                for m in self.lines
                if m.get("method") == "agent/event" and m.get("params", {}).get("requestId") == request_id
            ]

    # ---- 用例 -----------------------------------------------------------

    def test_01_host_info_lists_methods(self) -> None:
        info = self.call(1, "host/info").get("result", {})
        self.assertEqual(info.get("name"), "comfy-studio-desktop")
        self.assertIn("agent/chat", info.get("methods", []))
        self.assertIn("skills/run", info.get("methods", []))

    def test_02_tools_are_namespaced_by_server(self) -> None:
        tools = self.call(2, "mcp/tools").get("result", {}).get("tools", [])
        names = [t["qualified_name"] for t in tools]
        self.assertIn("comfy-studio__comfy_list_skills", names)
        self.assertTrue(all(t["server"] == "comfy-studio" for t in tools), names)

    def test_03_skills_catalog_comes_from_the_engine(self) -> None:
        skills = self.call(3, "skills/list", timeout=SKILLS_TIMEOUT).get("result", {}).get("skills")
        self.assertIsInstance(skills, list)
        self.assertGreater(len(skills), 0, "引擎的示例 skill 没读到")
        first = skills[0]
        self.assertIsInstance(first.get("id"), str)
        self.assertIsInstance(first.get("params"), list)

    def test_04_servers_report_liveness(self) -> None:
        servers = self.call(4, "mcp/servers").get("result", {}).get("servers", [])
        self.assertTrue(servers)
        self.assertIs(servers[0].get("alive"), True)

    def test_05_agent_config_never_leaks_the_key(self) -> None:
        config = self.call(5, "agent/config").get("result", {})
        self.assertIs(config.get("configured"), True)
        self.assertEqual(config.get("model"), "fake-model")
        self.assertNotIn("api_key", config)
        self.assertTrue(config.get("tools"))

    def test_06_unknown_method_is_minus_32601(self) -> None:
        response = self.call(6, "nope/nope")
        self.assertEqual(response.get("error", {}).get("code"), -32601)

    def test_07_missing_params_is_minus_32602(self) -> None:
        response = self.call(7, "skills/run", {"params": {}})
        self.assertEqual(response.get("error", {}).get("code"), -32602)

    def test_08_unknown_skill_is_minus_32602(self) -> None:
        response = self.call(8, "skills/run", {"skill_id": "no-such-skill", "params": {}})
        self.assertEqual(response.get("error", {}).get("code"), -32602)

    def test_09_agent_chat_really_calls_the_mcp_tool(self) -> None:
        chat = self.call(9, "agent/chat", {"text": "本机有哪些 skill？"}, timeout=SKILLS_TIMEOUT)
        self.assertTrue(chat.get("result", {}).get("text", "").startswith("本机有"), chat)

        events = self.notifications(9)
        types = [e["params"]["type"] for e in events]
        self.assertIn("tool_call", types)
        self.assertIn("tool_result", types)

        call_event = next(e for e in events if e["params"]["type"] == "tool_call")
        self.assertEqual(call_event["params"]["name"], "comfy-studio__comfy_list_skills")
        result_event = next(e for e in events if e["params"]["type"] == "tool_result")
        self.assertTrue(result_event["params"]["text"].strip().startswith("["))

    def test_10_reset_reports_whether_a_session_existed(self) -> None:
        first = self.call(10, "agent/reset", {"session_id": "default"}).get("result", {})
        self.assertIs(first.get("reset"), True)
        second = self.call(11, "agent/reset", {"session_id": "ghost"}).get("result", {})
        self.assertIs(second.get("reset"), False)

    def test_11_agent_models_lists_the_endpoint_catalog(self) -> None:
        result = self.call(12, "agent/models").get("result", {})
        self.assertEqual(result.get("source"), "endpoint", result)
        self.assertIsNone(result.get("error"))
        self.assertEqual(result.get("current"), "fake-model")
        self.assertIn("other-model", result.get("models", []))

    def test_12_switching_the_model_reaches_sessions_and_requests(self) -> None:
        switched = self.call(13, "agent/model", {"model": "other-model"}).get("result", {})
        self.assertIs(switched.get("changed"), True)
        self.assertEqual(switched.get("model"), "other-model")
        # test_09 建的那个 default 会话要当场换上，而不是等下一个新会话
        self.assertIn("default", switched.get("applied", []), switched)
        self.assertEqual(switched.get("skipped"), [])

        with _FakeCompletions.lock:
            _FakeCompletions.seen_models.clear()
        self.call(14, "agent/chat", {"text": "换个模型再问一遍"}, timeout=SKILLS_TIMEOUT)
        with _FakeCompletions.lock:
            seen = list(_FakeCompletions.seen_models)
        self.assertTrue(seen, "没收到任何 chat completions 请求")
        self.assertEqual(set(seen), {"other-model"}, seen)

        # 配置接口与读接口也要跟着走
        self.assertEqual(self.call(15, "agent/config").get("result", {}).get("model"), "other-model")
        read = self.call(16, "agent/model").get("result", {})
        self.assertEqual(read.get("model"), "other-model")
        self.assertIs(read.get("changed"), False)

    def test_13_bad_model_name_is_minus_32602(self) -> None:
        for bad in ("", "   ", 7, ["a"]):
            response = self.call(17, "agent/model", {"model": bad})
            self.assertEqual(response.get("error", {}).get("code"), -32602, response)
        # 被拒的值不该改掉当前模型
        self.assertEqual(self.call(18, "agent/model").get("result", {}).get("model"), "other-model")


if __name__ == "__main__":
    unittest.main()
