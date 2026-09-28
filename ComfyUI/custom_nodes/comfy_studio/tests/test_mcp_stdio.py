"""MCP stdio server 的进程级测试：真起 ``python -m comfy_studio.mcp`` 喂 JSON-RPC。

用引擎自己的 venv 解释器（缺了整组跳过），但**不需要引擎在跑**：
用到的都是不依赖运行中引擎的方法（initialize / tools/list / 参数校验失败 / 协议错误 / 存 skill）。
skill 目录用 ``COMFY_SKILLS_DIR`` 指向一个临时目录，顺带验证这个覆盖点生效；
用户 skill 目录用 ``COMFY_USER_SKILLS_DIR`` 指向另一个临时目录 —— 否则这条用例会去读写
开发机上真实的 ``~/.comfy-studio/skills``。

这里同时守住一条协议纪律：stdout 上只能出现 JSON-RPC 报文，一切诊断都走 stderr。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]  # .../custom_nodes/comfy_studio
CUSTOM_NODES_DIR = PACKAGE_DIR.parent
COMFYUI_DIR = CUSTOM_NODES_DIR.parent
VENV_PYTHON = COMFYUI_DIR / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")

TIMEOUT = 60.0


@unittest.skipUnless(
    VENV_PYTHON.exists(),
    f"需要引擎 venv 的解释器 {VENV_PYTHON}（先跑仓库根的 npm run setup）",
)
class McpStdioTest(unittest.TestCase):
    proc: subprocess.Popen
    lines: list[dict]
    stderr_lines: list[str]
    lock: threading.Lock
    skills_dir: str
    user_skills_dir: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.lines = []
        cls.stderr_lines = []
        cls.lock = threading.Lock()

        # 临时 skill 目录：把随包那份拷过去改个 id，用来验证 COMFY_SKILLS_DIR 覆盖
        cls._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-skills-")
        cls.skills_dir = str(Path(cls._tmp.name, "builtin"))
        Path(cls.skills_dir).mkdir()
        source = PACKAGE_DIR / "skills" / "workflows" / "text-to-image.json"
        doc = json.loads(source.read_text(encoding="utf-8"))
        doc["id"] = "demo-e2e"
        doc["title"] = "端到端示例"
        Path(cls.skills_dir, "demo-e2e.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

        # 用户目录也钉在临时目录里（存 skill 的用例要落盘）
        cls.user_skills_dir = str(Path(cls._tmp.name, "user"))

        # cwd 必须是包的父目录，`-m comfy_studio.mcp` 才找得到包
        cls.proc = subprocess.Popen(
            [str(VENV_PYTHON), "-X", "utf8", "-m", "comfy_studio.mcp"],
            cwd=str(CUSTOM_NODES_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env={
                **os.environ,
                "COMFY_SKILLS_DIR": cls.skills_dir,
                "COMFY_USER_SKILLS_DIR": cls.user_skills_dir,
            },
        )
        threading.Thread(target=cls._pump_stdout, daemon=True).start()
        threading.Thread(target=cls._pump_stderr, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.proc.stdin is not None and not cls.proc.stdin.closed:
            cls.proc.stdin.close()  # 关 stdin ⇒ server 读到 EOF 退出
        try:
            cls.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls._tmp.cleanup()

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
            with cls.lock:
                cls.stderr_lines.append(line.rstrip("\n"))

    # ---- 工具 -----------------------------------------------------------

    def send(self, payload: object, request_id: int | None = None) -> None:
        assert self.proc.stdin is not None
        if isinstance(payload, str):
            line = payload
        else:
            message = {"jsonrpc": "2.0", **payload}  # type: ignore[dict-item]
            if request_id is not None:
                message["id"] = request_id  # type: ignore[assignment]
            line = json.dumps(message, ensure_ascii=False)
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def call(self, request_id: int, method: str, params: dict | None = None) -> dict:
        self.send({"method": method, "params": params or {}}, request_id)
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            with self.lock:
                for message in self.lines:
                    if message.get("id") == request_id:
                        return message
            time.sleep(0.05)
        self.fail(f"{method} 超时")

    def stderr_text(self) -> str:
        with self.lock:
            return "\n".join(self.stderr_lines)

    # ---- 用例 -----------------------------------------------------------

    def test_01_initialize_reports_protocol_and_server_info(self) -> None:
        result = self.call(1, "initialize", {"protocolVersion": "2024-11-05"}).get("result", {})
        self.assertEqual(result.get("protocolVersion"), "2024-11-05")
        self.assertEqual(result.get("serverInfo", {}).get("name"), "comfy-studio")
        self.assertIn("tools", result.get("capabilities", {}))

    def test_02_tools_list_matches_the_configured_skill_dir(self) -> None:
        tools = self.call(2, "tools/list").get("result", {}).get("tools", [])
        names = [t["name"] for t in tools]
        self.assertIn("comfy_list_skills", names)
        self.assertIn("comfy_run_skill", names)
        self.assertIn("comfy_save_skill", names)
        self.assertIn("skill__demo-e2e", names, "COMFY_SKILLS_DIR 里的 skill 没被加载")
        plain = next(t for t in tools if t["name"] == "skill__demo-e2e")
        self.assertEqual(plain["inputSchema"]["type"], "object")
        self.assertIn("ckpt_name", plain["inputSchema"]["properties"])

        # 联网那三把默认就挂（没设 COMFY_NO_WEB）：外部 client 拿到的工具表里必须看得见它们，
        # 否则"引擎侧也能联网"这句话只存在于代码里。
        self.assertEqual(
            [n for n in names if n.startswith("web__")], ["web__search", "web__fetch", "web__crawl"]
        )
        for name in ("web__search", "web__fetch", "web__crawl"):
            schema = next(t for t in tools if t["name"] == name)["inputSchema"]
            self.assertEqual(schema["type"], "object")
        self.assertEqual(
            next(t for t in tools if t["name"] == "web__search")["inputSchema"]["required"], ["query"]
        )

    def test_02b_blocked_url_is_an_is_error_result_without_touching_the_network(self) -> None:
        """真让它抓一个禁区地址：应当如实报错，而不是超时或抛异常上来。

        这里**不需要联网**：``127.0.0.1`` 在本机 / 内网闸门那一关就被挡下，请求根本不出门。
        """
        response = self.call(
            20, "tools/call", {"name": "web__fetch", "arguments": {"url": "http://127.0.0.1/admin"}}
        )
        self.assertNotIn("error", response, "抓取失败应当是 isError 结果，不是协议错误")
        result = response.get("result", {})
        self.assertIs(result.get("isError"), True)
        self.assertIn("127.0.0.1", result["content"][0]["text"])

    def test_03_tools_call_returns_text_content(self) -> None:
        result = self.call(3, "tools/call", {"name": "comfy_list_skills", "arguments": {}}).get("result", {})
        self.assertNotIn("isError", result)
        skills = json.loads(result["content"][0]["text"])
        self.assertEqual([s["id"] for s in skills], ["demo-e2e"])

    def test_04_unknown_tool_is_a_protocol_error(self) -> None:
        response = self.call(4, "tools/call", {"name": "nope", "arguments": {}})
        self.assertEqual(response.get("error", {}).get("code"), -32602)
        self.assertIn("未知工具 nope", response["error"]["message"])

    def test_05_tool_failure_is_an_is_error_result(self) -> None:
        response = self.call(5, "tools/call", {"name": "comfy_run_skill", "arguments": {"skill_id": "nope"}})
        self.assertNotIn("error", response)
        result = response.get("result", {})
        self.assertIs(result.get("isError"), True)
        self.assertIn("没有 skill nope", result["content"][0]["text"])

        missing = self.call(6, "tools/call", {"name": "comfy_get_history", "arguments": {}})
        self.assertIs(missing.get("result", {}).get("isError"), True)
        self.assertIn("prompt_id", missing["result"]["content"][0]["text"])

    def test_06_unknown_method_and_bad_params_use_the_standard_codes(self) -> None:
        self.assertEqual(self.call(7, "nope/nope").get("error", {}).get("code"), -32601)
        self.assertEqual(self.call(8, "tools/call", {"arguments": {}}).get("error", {}).get("code"), -32602)

    def test_07_broken_json_does_not_kill_the_server(self) -> None:
        self.send("{ 这不是 JSON")
        response = self.call(9, "ping")
        self.assertIn("result", response)
        with self.lock:
            parse_errors = [m for m in self.lines if m.get("error", {}).get("code") == -32700]
        self.assertTrue(parse_errors, "畸形输入应该回 -32700")

    def test_08_notifications_get_no_reply(self) -> None:
        time.sleep(0.3)  # 等前面用例的最后一包落地，免得算进下面的增量
        with self.lock:
            before = len(self.lines)

        self.send({"method": "notifications/initialized", "params": {}})
        time.sleep(0.4)

        with self.lock:
            added = self.lines[before:]
        self.assertEqual(added, [], f"notification 不该有回包，却收到 {added}")
        self.assertIn("result", self.call(10, "ping"), "收到 notification 后 server 应继续工作")

    def test_09_saving_a_skill_lands_on_disk_and_shows_up_at_once(self) -> None:
        """真起进程存一个 skill：文件落在用户目录里，同一进程的列表/取名接口立刻认得它。"""
        document = {
            "id": "saved-here",
            "title": "现场存的",
            "description": "验证存完立刻可用",
            "workflow": {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a.safetensors"}}},
            "params": [{"name": "ckpt_name", "type": "string", "node": "4", "field": "ckpt_name"}],
        }
        result = self.call(11, "tools/call", {"name": "comfy_save_skill", "arguments": document}).get("result", {})
        self.assertNotIn("isError", result)
        saved = json.loads(result["content"][0]["text"])
        self.assertEqual(saved["id"], "saved-here")
        self.assertTrue(Path(self.user_skills_dir, "saved-here.json").is_file())

        listed = self.call(12, "tools/call", {"name": "comfy_list_skills", "arguments": {}}).get("result", {})
        ids = [s["id"] for s in json.loads(listed["content"][0]["text"])]
        self.assertIn("saved-here", ids)

        # 已经存过的 id 不会被下一次调用悄悄覆盖
        again = self.call(13, "tools/call", {"name": "comfy_save_skill", "arguments": document}).get("result", {})
        self.assertIs(again.get("isError"), True)
        self.assertIn("overwrite", again["content"][0]["text"])

        # 就绪横幅里要能看到用户目录 —— 用户得知道自己的东西存在哪
        self.assertIn(self.user_skills_dir, self.stderr_text())

    def test_10_stdout_stays_protocol_only(self) -> None:
        with self.lock:
            lines = list(self.lines)
        self.assertTrue(lines, "没收到任何报文")
        for message in lines:
            self.assertEqual(message.get("jsonrpc"), "2.0", message)
            if message.get("id") is None:
                # 只有「整行不是 JSON」这一种情况才会出现没有 id 的错误回包
                self.assertEqual(message.get("error", {}).get("code"), -32700, message)
            else:
                self.assertIsInstance(message["id"], int, message)
        # 就绪横幅走的是 stderr：这条路断了的话 stdout 会被污染成非 JSON
        banner = self.stderr_text()
        self.assertIn("MCP stdio 就绪", banner)
        # 横幅里要明说走哪条搜索路（这里没设 COMFY_SEARXNG_URL，所以是必应那条不用部署的）。
        # "能不能上网"在三把工具是否出现里已经验过了，这条验的是"日志里说不说得清"。
        self.assertIn("联网: 开（必应 RSS）", banner)


@unittest.skipUnless(
    VENV_PYTHON.exists(),
    f"需要引擎 venv 的解释器 {VENV_PYTHON}（先跑仓库根的 npm run setup）",
)
class McpStdioNoWebTest(unittest.TestCase):
    """``COMFY_NO_WEB=1`` 时联网那三把应当**一把都不挂**，其余工具照旧。

    单测里验的是 ``web_enabled()`` 这个函数；这里验的是"环境变量真能一路走到工具表" ——
    中间隔着 ``serve_stdio`` 建不建句柄、``create_server`` 传不传下去，哪一环断了都只有
    真起进程才看得出来。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-noweb-")
        # skill 目录必须是"存在且至少有一个 .json"：目录不存在、或者空目录，server 都会
        # 直接起不来（这是它的明规矩，不是这条用例要验的东西），所以随手拷一份随包 skill 进去。
        builtin = Path(cls._tmp.name, "builtin")
        builtin.mkdir()
        Path(cls._tmp.name, "user").mkdir()
        shutil.copy(
            PACKAGE_DIR / "skills" / "workflows" / "text-to-image.json", builtin / "demo.json"
        )
        cls.proc = subprocess.Popen(
            [str(VENV_PYTHON), "-X", "utf8", "-m", "comfy_studio.mcp"],
            cwd=str(CUSTOM_NODES_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env={
                **os.environ,
                "COMFY_NO_WEB": "1",
                "COMFY_SKILLS_DIR": str(Path(cls._tmp.name, "builtin")),
                "COMFY_USER_SKILLS_DIR": str(Path(cls._tmp.name, "user")),
            },
        )
        cls.lines: list[dict] = []
        cls.stderr_lines: list[str] = []
        cls.lock = threading.Lock()
        threading.Thread(target=cls._pump_stdout, daemon=True).start()
        threading.Thread(target=cls._pump_stderr, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.proc.stdin is not None and not cls.proc.stdin.closed:
            cls.proc.stdin.close()
        try:
            cls.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls._tmp.cleanup()

    @classmethod
    def _pump_stdout(cls) -> None:
        assert cls.proc.stdout is not None
        for line in cls.proc.stdout:
            text = line.strip()
            if text:
                with cls.lock:
                    cls.lines.append(json.loads(text))

    @classmethod
    def _pump_stderr(cls) -> None:
        assert cls.proc.stderr is not None
        for line in cls.proc.stderr:
            with cls.lock:
                cls.stderr_lines.append(line.rstrip("\n"))

    def test_web_tools_are_absent_but_the_rest_stay(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + TIMEOUT
        names: list[str] = []
        while time.time() < deadline and not names:
            with self.lock:
                for message in self.lines:
                    if message.get("id") == 1:
                        names = [t["name"] for t in message["result"]["tools"]]
            time.sleep(0.05)
        with self.lock:
            stderr_tail = "\n".join(self.stderr_lines[-20:])
        self.assertTrue(names, f"tools/list 超时；stderr 尾部:\n{stderr_tail}")
        self.assertEqual([n for n in names if n.startswith("web__")], [], "COMFY_NO_WEB 没生效")
        self.assertIn("comfy_list_models", names, "关掉联网不该连本地工具一起没了")
        # 横幅也得照实说：工具表里没有了、日志里还写着"联网: 开"，等于留了一句骗人的话。
        self.assertIn("联网: 关（COMFY_NO_WEB）", stderr_tail)


if __name__ == "__main__":
    unittest.main()
