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
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from comfy_studio.history import SESSION_SUBDIR
from comfy_studio.server import MAX_SESSIONS

REPO_ROOT = Path(__file__).resolve().parents[4]
COMFYUI_DIR = REPO_ROOT / "ComfyUI"
LIB_DIR = REPO_ROOT / "Comfy-Desktop" / "lib"
VENV_PYTHON = COMFYUI_DIR / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
ENGINE_PACKAGE = COMFYUI_DIR / "custom_nodes" / "comfy_studio"

TIMEOUT = 90.0
SKILLS_TIMEOUT = 180.0


def _last_user_text(messages: list[dict]) -> str:
    """从请求体的对话里取最后一句用户话（判断是不是那次"慢慢来"的请求）。"""
    for item in reversed(messages):
        if item.get("role") == "user":
            return str(item.get("content") or "")
    return ""


def _system_text(messages: list[dict]) -> str:
    """取这次请求的 system 提示词（换智能体之后要能从它身上看出来）。"""
    for item in messages:
        if item.get("role") == "system":
            return str(item.get("content") or "")
    return ""


class _FakeCompletions(BaseHTTPRequestHandler):
    """假 chat completions 服务：先要工具、再给结论；顺带提供 ``GET /models``。"""

    #: 每次 chat completions 请求体里的 model（验证切换真的落到了请求上）。
    seen_models: list[str] = []
    #: 每次请求里的 system 提示词（验证换智能体真的落到了人设上）。
    seen_systems: list[str] = []
    lock = threading.Lock()

    #: 用户话里带这个标记就让这次回答慢慢来：取消用例需要一个**真的在飞**的轮次。
    SLOW_MARKER = "慢慢来"
    SLOW_SECONDS = 6.0

    #: 用户话里带这个标记就让这一轮去调 ``review__ask_user``（审核节点用例）。
    ASK_MARKER = "问我"
    ASK_QUESTION = "用哪套工作流？"

    #: 用户话里带这个标记就让这一轮把一套工作流沉淀成 skill（方法复用用例）。
    SAVE_MARKER = "存下来"
    #: 本地衔接用例：把标记后面那串路径当用户的本地素材，接进引擎的 input。
    FILE_MARKER = "接进来"
    FILE_SUBFOLDER = "refs"
    #: 本地衔接用例的另一半：问本地产出在哪，让这一轮去查 output 目录。
    LOOKUP_MARKER = "产出在哪"
    #: 灵感输入用例：一句话先拆成多步清单交上去等人过目。
    PLAN_MARKER = "一步步来"
    PLAN_GOAL = "把这张图改成赛博朋克海报感"
    #: 故意一步写成对象、一步写成光字符串：验证两种写法都会收成同一种形状。
    PLAN_STEPS = [
        {"title": "先用 SDXL 出一版草稿", "tool": "comfy_run_skill"},
        "再把草稿放大到 2K",
    ]
    #: 长期记忆用例：先说一句"记住…"，下一轮（同一会话）不调工具也该说得出这条偏好。
    REMEMBER_MARKER = "记住这个"
    RECALL_MARKER = "你记得我什么"
    MEMORY_TEXT = "用户喜欢方形构图（1:1）"
    SAVE_SKILL = {
        "id": "e2e-saved",
        "title": "对话里存下来的",
        "description": "验证打磨好的工作流能沉淀成专属 skill",
        "workflow": {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a.safetensors"}}},
        "params": [{"name": "ckpt_name", "type": "string", "node": "4", "field": "ckpt_name", "required": True}],
    }

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
        messages = body.get("messages") or []
        with self.lock:
            self.seen_models.append(str(body.get("model")))
            self.seen_systems.append(_system_text(messages))
        if self.SLOW_MARKER in _last_user_text(messages):
            # 慢回答期间不调工具：整轮就卡在这次模型请求上，取消才有东西可取消。
            time.sleep(self.SLOW_SECONDS)
            self._json(
                {
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": "慢回答也说完啦"}}
                    ]
                }
            )
            return
        if self.SAVE_MARKER in _last_user_text(messages):
            # 方法复用用例：第一轮把工作流交给 comfy_save_skill 存下来，
            # 第二轮（存完了）复述存到了哪个 id。
            tool_messages = [m for m in messages if m.get("role") == "tool"]
            if tool_messages:
                saved = json.loads(tool_messages[0]["content"])
                message = {"role": "assistant", "content": f"存好了，skill id 是 {saved['id']}"}
            else:
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_save",
                            "type": "function",
                            "function": {
                                "name": "comfy-studio__comfy_save_skill",
                                "arguments": json.dumps(self.SAVE_SKILL, ensure_ascii=False),
                            },
                        }
                    ],
                }
        elif self.ASK_MARKER in _last_user_text(messages):
            # 审核节点用例：第一轮要 review__ask_user，把这一轮真停在"等人回答"上；
            # 第二轮（已经拿到回答）把答案原样念出来，好断言它确实被用上了。
            tool_messages = [m for m in messages if m.get("role") == "tool"]
            if tool_messages:
                # 工具回来的 content 就是那段文本（宿主把 MCP 的 content 块摊平过了），
                # 审核工具吐的是 {question, answer}。
                payload = json.loads(tool_messages[0]["content"])
                message = {"role": "assistant", "content": f"用户回答说：{payload['answer']}"}
            else:
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_ask",
                            "type": "function",
                            "function": {
                                "name": "review__ask_user",
                                "arguments": json.dumps(
                                    {"question": self.ASK_QUESTION, "options": ["SDXL", "Flux"]}
                                ),
                            },
                        }
                    ],
                }
        elif self.FILE_MARKER in _last_user_text(messages):
            # 本地衔接用例：第一轮把用户给的本机路径交给 localfiles__import_file，
            # 第二轮把它返回的工作流取值念出来（断言真的能拿去填节点字段）。
            tool_messages = [m for m in messages if m.get("role") == "tool"]
            if tool_messages:
                payload = json.loads(tool_messages[0]["content"])
                message = {"role": "assistant", "content": f"接好了，填 {payload['value']}"}
            else:
                # 标记后面那一整串就是路径（子串切一刀，路径里有空格也不怕）。
                source = _last_user_text(messages).split(self.FILE_MARKER, 1)[1].strip()
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_import",
                            "type": "function",
                            "function": {
                                "name": "localfiles__import_file",
                                "arguments": json.dumps(
                                    {"path": source, "subfolder": self.FILE_SUBFOLDER}
                                ),
                            },
                        }
                    ],
                }
        elif self.LOOKUP_MARKER in _last_user_text(messages):
            # 产出那一侧：第一轮查 output 目录，第二轮把盘上的真实路径念出来。
            tool_messages = [m for m in messages if m.get("role") == "tool"]
            if tool_messages:
                payload = json.loads(tool_messages[0]["content"])
                message = {"role": "assistant", "content": payload["files"][0]["path"]}
            else:
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_list",
                            "type": "function",
                            "function": {
                                "name": "localfiles__list_files",
                                "arguments": json.dumps({"type": "output"}),
                            },
                        }
                    ],
                }
        elif self.PLAN_MARKER in _last_user_text(messages):
            # 灵感输入用例：第一轮把一句想法拆成清单交上去等人点头；点头之后报一次进度
            # （单向通知），最后用文字收尾。
            tool_messages = [m for m in messages if m.get("role") == "tool"]
            verdict = json.loads(tool_messages[0]["content"]) if tool_messages else None
            if verdict is None:
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_plan",
                            "type": "function",
                            "function": {
                                "name": "plan__submit",
                                "arguments": json.dumps(
                                    {
                                        "goal": self.PLAN_GOAL,
                                        "steps": self.PLAN_STEPS,
                                        "notes": "第 2 步放大比较吃显存",
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                }
            elif len(tool_messages) == 1 and verdict.get("approved"):
                # 用户点头了才开工；报进度这一步是单向的，报完还得接着说人话。
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_progress",
                            "type": "function",
                            "function": {
                                "name": "plan__progress",
                                "arguments": json.dumps({"step": 1, "status": "running"}),
                            },
                        }
                    ],
                }
            elif len(tool_messages) == 1:
                message = {"role": "assistant", "content": f"用户要改：{verdict['feedback']}"}
            else:
                message = {"role": "assistant", "content": f"按计划开工（approved={verdict['approved']}）"}
        elif self.REMEMBER_MARKER in _last_user_text(messages):
            # 长期记忆用例的前半：把用户那句话交给 memory__remember 记下来，再念出拿到的 id。
            tool_messages = [m for m in messages if m.get("role") == "tool"]
            if tool_messages:
                payload = json.loads(tool_messages[0]["content"])
                message = {"role": "assistant", "content": f"记住了，id 是 {payload['id']}"}
            else:
                fact = _last_user_text(messages).split(self.REMEMBER_MARKER, 1)[1].strip()
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_remember",
                            "type": "function",
                            "function": {
                                "name": "memory__remember",
                                "arguments": json.dumps(
                                    {"text": fact, "tags": ["偏好"]}, ensure_ascii=False
                                ),
                            },
                        }
                    ],
                }
        elif self.RECALL_MARKER in _last_user_text(messages):
            # 长期记忆用例的后半：这一轮**一个工具都不调**。能说出那条偏好，只可能是宿主
            # 把它拼进了系统提示词；说不出来就老老实实回一句找不到，别编。
            system = next(
                (str(m.get("content") or "") for m in messages if m.get("role") == "system"), ""
            )
            if self.MEMORY_TEXT in system:
                message = {"role": "assistant", "content": self.MEMORY_TEXT}
            else:
                message = {"role": "assistant", "content": "系统提示词里没有这条记忆"}
        else:
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
        # 用户 skill 目录钉在临时目录里：存 skill 的用例会真的落盘，
        # 不能写到开发机上真实的 ~/.comfy-studio/skills 去。
        cls._skills_tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-user-skills-")
        cls.user_skills_dir = cls._skills_tmp.name
        # 本机文件那几张工具会真的往 input/output 目录里读写，所以把这两个目录钉在
        # 临时目录里（对应引擎的 --input-directory / --output-directory），
        # 别去动开发机上真实的 ComfyUI/input、ComfyUI/output。
        cls._files_tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-local-files-")
        cls.files_root = Path(cls._files_tmp.name)
        cls.input_dir = cls.files_root / "input"
        cls.output_dir = cls.files_root / "output"
        cls.output_dir.mkdir(parents=True)
        # 长期记忆默认落在**用户数据目录**（开发机上就是你自己的那份记忆）：这个测试壳
        # 也要记忆是真的落盘，所以给它一个临时目录，别去动真人的记性。
        cls._memory_tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-memory-")
        cls.memory_dir = Path(cls._memory_tmp.name)
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
                # review__ask_user 得有桌面壳接住才成立，而这个测试就是那个壳：
                # 它收下 ask_user 事件，再用 agent/answer 把答案送回去。
                "--review",
                # plan__submit 同理：这张测试壳也当那个面板，接住 plan 事件后用
                # agent/plan_result 把"过 / 改"送回去。
                "--plan",
                # 本机素材/产出那两个目录换成临时目录，别写进仓库里的 ComfyUI 检出。
                "--input-dir",
                str(cls.input_dir),
                "--output-dir",
                str(cls.output_dir),
                # 记忆默认就开着（它是工作台该有的记性），只是把落点换成临时目录。
                "--memory-dir",
                str(cls.memory_dir),
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
                "COMFY_USER_SKILLS_DIR": cls.user_skills_dir,
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
        cls._skills_tmp.cleanup()
        cls._files_tmp.cleanup()
        cls._memory_tmp.cleanup()

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

    def send(self, request_id: int, method: str, params: dict | None = None) -> None:
        """只发不等：取消用例得在这一轮还没结束时插一脚。"""
        assert self.proc.stdin is not None
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            + "\n"
        )
        self.proc.stdin.flush()

    def wait(self, request_id: int, timeout: float = TIMEOUT) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for message in self.lines:
                    if message.get("id") == request_id:
                        return message
            time.sleep(0.05)
        self.fail(f"id={request_id} 超时")

    def call(self, request_id: int, method: str, params: dict | None = None, timeout: float = TIMEOUT) -> dict:
        self.send(request_id, method, params)
        return self.wait(request_id, timeout)

    def notifications(self, request_id: int) -> list[dict]:
        with self.lock:
            return [
                m
                for m in self.lines
                if m.get("method") == "agent/event" and m.get("params", {}).get("requestId") == request_id
            ]

    def wait_for_event(self, request_id: int, event_type: str, timeout: float = TIMEOUT) -> dict:
        """等这一轮推出某类事件。回程工具（ask_user）少了它就永远走不到下一步。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for event in self.notifications(request_id):
                if event["params"]["type"] == event_type:
                    return event
            time.sleep(0.05)
        self.fail(f"id={request_id} 没等到 {event_type} 事件")

    # ---- 用例 -----------------------------------------------------------

    def test_01_host_info_lists_methods(self) -> None:
        info = self.call(1, "host/info").get("result", {})
        self.assertEqual(info.get("name"), "comfy-studio-desktop")
        self.assertIn("agent/chat", info.get("methods", []))
        self.assertIn("skills/run", info.get("methods", []))
        # 状态里如实报出各条回程通道挂没挂：画布没开，审核与计划开了（见启动参数）。
        self.assertIs(info.get("canvas"), False)
        self.assertIs(info.get("review"), True)
        self.assertIs(info.get("plan"), True)
        # 本机文件那几张不用谁接话，只要 --comfyui-dir 给了就挂上。
        self.assertIs(info.get("local_files"), True)
        # 宿主认的素材/产出目录要跟引擎那次启动的参数对得上（这里就是启动时给的临时目录）：
        # 共享存储下引擎拿到的是 Shared/input、Shared/output，宿主不能自己按
        # <comfyui-dir>/input 猜 —— 猜错的话接进去的素材引擎读不到。
        self.assertEqual(info.get("input_dir"), str(self.input_dir.resolve()))
        self.assertEqual(info.get("output_dir"), str(self.output_dir.resolve()))
        # 对话存档默认开着，且跟记忆落在同一个（这里是临时）数据目录下。
        self.assertIs(info.get("history"), True)
        self.assertEqual(info.get("history_dir"), str(self.memory_dir / SESSION_SUBDIR))

    def test_02_tools_are_namespaced_by_server(self) -> None:
        tools = self.call(2, "mcp/tools").get("result", {}).get("tools", [])
        names = [t["qualified_name"] for t in tools]
        self.assertIn("comfy-studio__comfy_list_skills", names)
        self.assertIn("review__ask_user", names)
        self.assertIn("plan__submit", names)
        self.assertIn("plan__progress", names)
        self.assertIn("memory__remember", names)
        self.assertIn("memory__recall", names)
        self.assertIn("memory__forget", names)
        # 每把工具都严格是 <server>__<tool>：回程那条通道（review）也不破例。
        for tool in tools:
            self.assertTrue(tool["qualified_name"].startswith(f"{tool['server']}__"), tool)

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
        by_name = {s["name"]: s for s in servers}
        self.assertIn("comfy-studio", by_name)  # 引擎是子进程
        self.assertEqual(by_name["comfy-studio"]["transport"], "stdio")
        # 审核/画布跑在宿主进程里：报状态时不能拿 stdio 那套字段去套（没有 command），
        # 更不能因此把整个接口打挂。
        self.assertEqual(by_name["review"]["transport"], "in-process")
        self.assertIsNone(by_name["review"]["command"])
        for server in servers:
            self.assertIs(server.get("alive"), True, server)

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

    def test_14_a_running_turn_can_be_cancelled(self) -> None:
        session = "cancel-e2e"
        self.send(21, "agent/chat", {"text": "慢慢来，先别急着答", "session_id": session})
        # 等它真走进模型请求：这时取消掉的才是"正在跑的一轮"。
        time.sleep(1.5)
        stopped = self.call(22, "agent/cancel", {"session_id": session}).get("result", {})
        self.assertIs(stopped.get("cancelled"), True, stopped)

        answer = self.wait(21).get("result", {})
        # 取消不是失败：这一轮回的是正常结果，面板据此把气泡收成"已停止"。
        self.assertNotIn("error", answer, answer)
        self.assertIs(answer.get("cancelled"), True, answer)
        self.assertEqual(answer.get("session_id"), session)

    def test_15_the_session_still_works_after_a_cancel(self) -> None:
        session = "cancel-e2e"
        # 幂等：上一轮早停了，再叫一次只是白叫，不是错误。
        again = self.call(23, "agent/cancel", {"session_id": session}).get("result", {})
        self.assertEqual(again, {"session_id": session, "cancelled": False})

        # 历史配对没被打断：取消完接着说下一句，照常走完工具再回答。
        after = self.call(
            24,
            "agent/chat",
            {"text": "取消之后还能说话吗？", "session_id": session},
            timeout=SKILLS_TIMEOUT,
        )
        self.assertNotIn("error", after, after)
        self.assertTrue(after.get("result", {}).get("text", "").startswith("本机有"), after)

    def test_16_ask_user_waits_for_a_human_and_the_answer_comes_back(self) -> None:
        """审核节点：这一轮会**真的停住**等人回答，答完接着跑完。"""
        session = "review-e2e"
        self.send(25, "agent/chat", {"text": "先问我一个方向再动手", "session_id": session})

        # 宿主推到面板上的是 ask_user：问题、选项，外加一个能对上的 call_id。
        ask = self.wait_for_event(25, "ask_user")
        self.assertEqual(ask["params"]["question"], _FakeCompletions.ASK_QUESTION)
        self.assertEqual(ask["params"]["options"], ["SDXL", "Flux"])
        call_id = ask["params"]["call_id"]
        self.assertTrue(str(call_id).startswith("ask-"), ask)

        # 还没人回答：这一轮就该停在那儿，不能自己往下跑。
        with self.lock:
            ended_early = any(m.get("id") == 25 for m in self.lines)
        self.assertFalse(ended_early, "还没人回答，这一轮不该已经结束")

        delivered = self.call(26, "agent/answer", {"call_id": call_id, "answer": "SDXL"})
        self.assertIs(delivered.get("result", {}).get("delivered"), True, delivered)

        # 整条信封都要看：只看 result 会把错误回包看成"空回答"，白瞎一次定位。
        reply = self.wait(25, SKILLS_TIMEOUT)
        self.assertNotIn("error", reply, reply)
        self.assertIn("用户回答说：SDXL", reply.get("result", {}).get("text", ""), reply)

        # 幂等：同一张卡片再答一次只是白答——人答晚了不是错误。
        late = self.call(27, "agent/answer", {"call_id": call_id, "answer": "Flux"})
        self.assertIs(late.get("result", {}).get("delivered"), False, late)

        # 空回答不算回答：挡住它，别让沉默被当成"随便你"。
        empty = self.call(28, "agent/answer", {"call_id": call_id, "answer": "   "})
        self.assertEqual(empty.get("error", {}).get("code"), -32602, empty)


    def test_17_a_workflow_from_the_chat_can_be_saved_as_a_skill(self) -> None:
        """方法复用：对话里打磨好的工作流当场沉淀成专属 skill，之后直接复用。"""
        reply = self.call(
            29,
            "agent/chat",
            {"text": "这套调好了，帮我存下来", "session_id": "save-e2e"},
            timeout=SKILLS_TIMEOUT,
        )
        self.assertNotIn("error", reply, reply)
        self.assertEqual(reply.get("result", {}).get("text", ""), "存好了，skill id 是 e2e-saved")

        # 面板要能看见这次沉淀（事件流里就是一次普通的工具调用）
        calls = [
            e["params"]["name"]
            for e in self.notifications(29)
            if e["params"].get("type") == "tool_call"
        ]
        self.assertIn("comfy-studio__comfy_save_skill", calls, calls)

        # 关键：**同一个引擎进程**里它立刻可复用 —— 不用重启、不用重建工具表。
        listed = self.call(30, "skills/list", timeout=SKILLS_TIMEOUT).get("result", {}).get("skills", [])
        saved = next((s for s in listed if s["id"] == "e2e-saved"), None)
        self.assertIsNotNone(saved, [s["id"] for s in listed])
        self.assertEqual(saved["title"], _FakeCompletions.SAVE_SKILL["title"])
        self.assertEqual([p["name"] for p in saved["params"]], ["ckpt_name"])

        # 落到用户目录里（下次启动还认得），而不是随包那份
        path = Path(self.user_skills_dir, "e2e-saved.json")
        self.assertTrue(path.is_file(), path)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["id"], "e2e-saved")


    def test_18_local_file_in_and_local_output_path_out(self) -> None:
        """本地衔接：用户指的本机素材真的进了 input；产出能换算回盘上的路径。"""
        source = self.files_root / "ref.png"
        source.write_bytes(b"\x89PNG-ref")

        reply = self.call(
            31,
            "agent/chat",
            {"text": f"把这张图接进来 {source}", "session_id": "files-e2e"},
        )
        self.assertNotIn("error", reply, reply)
        # 拿回来的 value 是工作流里能填的那种相对名，不是磁盘绝对路径。
        self.assertEqual(reply.get("result", {}).get("text", ""), "接好了，填 refs/ref.png")

        landed = self.input_dir / "refs" / "ref.png"
        self.assertTrue(landed.is_file(), landed)
        self.assertEqual(landed.read_bytes(), b"\x89PNG-ref")

        calls = [
            e["params"]["name"]
            for e in self.notifications(31)
            if e["params"].get("type") == "tool_call"
        ]
        self.assertIn("localfiles__import_file", calls, calls)

        # 另一半：问产出在哪，宿主回的是 output 目录里的真实路径（引擎只给 filename）。
        # 另起一个会话：假模型是按"对话里有没有 tool 消息"分轮的，接着上一个会话跑会把
        # 上一次 import 的返回值当成这一轮的工具结果。
        produced = self.output_dir / "out-0001.png"
        produced.write_bytes(b"\x89PNG-out")
        reply = self.call(
            32,
            "agent/chat",
            {"text": "刚才的产出在哪", "session_id": "lookup-e2e"},
        )
        self.assertNotIn("error", reply, reply)
        self.assertEqual(reply.get("result", {}).get("text", ""), str(produced))

    def test_19_a_one_liner_becomes_a_plan_the_user_confirms(self) -> None:
        """灵感输入：一句想法先拆成多步清单等人过目；点头后逐步播报进度。"""
        session = "plan-e2e"
        self.send(
            33,
            "agent/chat",
            {"text": "一步步来，把这张图做成赛博朋克海报", "session_id": session},
        )

        # 宿主推到面板上的是一张清单：要做什么、分几步、每步打算用哪把工具。
        plan = self.wait_for_event(33, "plan")
        self.assertEqual(plan["params"]["goal"], _FakeCompletions.PLAN_GOAL)
        self.assertEqual(
            [s["title"] for s in plan["params"]["steps"]],
            ["先用 SDXL 出一版草稿", "再把草稿放大到 2K"],
        )
        # 一步是对象、一步是光字符串，收下来形状要一样，面板才不用分情况画。
        self.assertEqual(plan["params"]["steps"][0]["tool"], "comfy_run_skill")
        self.assertEqual(plan["params"]["steps"][1]["tool"], None)
        self.assertEqual(plan["params"]["notes"], "第 2 步放大比较吃显存")
        call_id = plan["params"]["call_id"]
        self.assertTrue(str(call_id).startswith("plan-"), plan)

        # 还没人过目：这一轮就该停在那儿，不能自己往下跑。
        with self.lock:
            ended_early = any(m.get("id") == 33 for m in self.lines)
        self.assertFalse(ended_early, "还没人过目，这一轮不该已经结束")

        # 否掉却不说改哪里 = 让模型瞎猜：挡住了，而且不算回过话（这一轮还在等）。
        silent = self.call(
            34, "agent/plan_result", {"call_id": call_id, "approved": False, "feedback": "   "}
        )
        self.assertEqual(silent.get("error", {}).get("code"), -32602, silent)
        with self.lock:
            still_waiting = not any(m.get("id") == 33 for m in self.lines)
        self.assertTrue(still_waiting, "被挡下的回话不该把这一轮放走")

        delivered = self.call(35, "agent/plan_result", {"call_id": call_id, "approved": True})
        self.assertIs(delivered.get("result", {}).get("delivered"), True, delivered)

        reply = self.wait(33, SKILLS_TIMEOUT)
        self.assertNotIn("error", reply, reply)
        # 用户的态度真的回到了模型手里，而不是被吞掉。
        self.assertIn("approved=True", reply.get("result", {}).get("text", ""), reply)

        # 进度是单向通知：面板收得到，但它不建 future，不会再把这一轮卡住。
        progress = self.wait_for_event(33, "plan_progress")
        self.assertEqual(progress["params"]["step"], 1)
        self.assertEqual(progress["params"]["status"], "running")

        # 幂等：这一轮早不等了，晚了再点一遍只是白点，不是错误。
        late = self.call(36, "agent/plan_result", {"call_id": call_id, "approved": True})
        self.assertIs(late.get("result", {}).get("delivered"), False, late)

    def test_20_the_assistant_remembers_the_user_across_turns(self) -> None:
        """长期记忆：这一轮记下的偏好，下一轮不必查、也照样认得（且在盘上找得到）。"""
        memory_file = self.memory_dir / "memory.json"
        self.assertFalse(memory_file.exists(), "跑之前不该有记忆文件")

        session = "memory-e2e"
        self.send(
            37,
            "agent/chat",
            {
                "text": f"{_FakeCompletions.REMEMBER_MARKER} {_FakeCompletions.MEMORY_TEXT}",
                "session_id": session,
            },
        )
        reply = self.wait(37, SKILLS_TIMEOUT)
        self.assertNotIn("error", reply, reply)
        # 模型真的调到了 memory__remember（工具表里那一栏是真的），并且拿到了 id。
        self.assertIn("记住了", reply.get("result", {}).get("text", ""), reply)

        # 落了盘：宿主换个进程再开，这份记忆还在（这里直接读那份文件）。
        self.assertTrue(memory_file.exists(), f"没写出记忆文件：{memory_file}")
        raw = json.loads(memory_file.read_text(encoding="utf-8"))
        self.assertEqual([e["text"] for e in raw["entries"]], [_FakeCompletions.MEMORY_TEXT])
        self.assertEqual(raw["entries"][0]["tags"], ["偏好"])

        # 宿主如实报出记忆放在哪、有几条 —— 面板与用户都能知道自己的记性存在哪。
        info = self.call(38, "host/info", {}).get("result", {})
        self.assertIs(info.get("memory"), True)
        self.assertEqual(info.get("memory_file"), str(memory_file))
        self.assertEqual(info.get("memory_entries"), 1)
        self.assertIsNone(info.get("memory_error"))

        # 同一会话接着问：这一轮**一个工具都不调**（假模型不会调），能说出那条偏好只可能
        # 因为宿主把它拼进了系统提示词 —— "每轮重算人设"这条路真的通了。
        self.send(39, "agent/chat", {"text": _FakeCompletions.RECALL_MARKER, "session_id": session})
        second = self.wait(39, SKILLS_TIMEOUT)
        self.assertNotIn("error", second, second)
        self.assertEqual(second.get("result", {}).get("text", ""), _FakeCompletions.MEMORY_TEXT)
        calls = [
            e["params"]["name"]
            for e in self.notifications(39)
            if e["params"].get("type") == "tool_call"
        ]
        self.assertEqual(calls, [], "这一轮不该有任何工具调用：记忆是从提示词里知道的")

    def test_21_the_conversation_survives_on_disk(self) -> None:
        """对话存档：一轮跑完就落盘，面板什么时候来问都能拿回同一套条目。"""
        # 同时只有 8 个会话槽，所以这里接着用上一个用例的会话 —— 对存档来说一轮就是一轮。
        session = "memory-e2e"
        ask = "帮我把这张图放大两倍"
        self.send(40, "agent/chat", {"text": ask, "session_id": session})
        reply = self.wait(40, SKILLS_TIMEOUT)
        self.assertNotIn("error", reply, reply)

        # 盘上真的留下了这个会话的对话（不是只在那个进程的内存里）。
        archive_dir = self.memory_dir / SESSION_SUBDIR
        bodies = [json.loads(path.read_text(encoding="utf-8")) for path in archive_dir.glob("*.json")]
        mine = [body for body in bodies if body.get("session_id") == session]
        self.assertEqual(len(mine), 1, f"没写出这个会话的存档：{bodies}")
        roles = [m["role"] for m in mine[0]["messages"]]
        self.assertEqual(roles[0], "user")
        self.assertEqual(roles[-1], "assistant")
        self.assertNotIn("system", roles, "人设每轮重算，不该进存档")
        # 这一轮的问话在存档里（前后几轮的也在，只失一条就说明写盘丢了尾巴）。
        asked = [m["content"] for m in mine[0]["messages"] if m["role"] == "user"]
        self.assertEqual(asked[-1], ask)

        # 面板要的那些条目由宿主现算，形状与实时事件一套，拿到就能画。
        history = self.call(41, "agent/history", {"session_id": session}).get("result", {})
        self.assertEqual(history.get("session_id"), session)
        # 会话还活着就先用它手里的那份，且内存里的是全长、没有裁过。
        self.assertEqual(history.get("source"), "session")
        self.assertEqual(history.get("dropped"), 0)
        entries = history.get("entries", [])
        self.assertEqual(entries[0].get("type"), "user")
        self.assertEqual(entries[-1].get("type"), "assistant")
        self.assertEqual([e["text"] for e in entries if e.get("type") == "user"][-1], ask)

    def test_22_sessions_can_be_listed_and_closed(self) -> None:
        """面板那两下：看清单（``agent/sessions``）、关掉一段（``agent/close``）。

        关掉**不等于**清掉：对话留在盘上，同一个 id 再问一句会被喂回来接着聊 —— 这是它敢
        在 ``--no-history`` 那一档之外当"腾位子"手段的前提。
        """
        session = "sessions-e2e"
        asked = "先开一段自己的对话"
        opened = self.call(42, "agent/chat", {"text": asked, "session_id": session}, timeout=SKILLS_TIMEOUT)
        self.assertNotIn("error", opened, opened)

        listing = self.call(43, "agent/sessions").get("result", {})
        rows = {row.get("session_id"): row for row in listing.get("sessions", [])}
        self.assertIn(session, rows, listing)
        mine = rows[session]
        self.assertIs(mine.get("live"), True)
        self.assertIs(mine.get("busy"), False)
        self.assertEqual(mine.get("title"), asked, mine)
        self.assertGreater(mine.get("messages"), 1)
        self.assertEqual(listing.get("max_sessions"), MAX_SESSIONS)
        self.assertIs(listing.get("history"), True)

        closed = self.call(44, "agent/close", {"session_id": session}).get("result", {})
        self.assertIs(closed.get("closed"), True, closed)
        self.assertIs(closed.get("history_kept"), True, closed)

        # 位子真腾出来了：清单里那一段还在，但已经不活着了（下次会被从存档喂回来）。
        rows = {
            row.get("session_id"): row
            for row in self.call(45, "agent/sessions").get("result", {}).get("sessions", [])
        }
        self.assertIs(rows[session].get("live"), False, "关掉之后不该还活着")

        # 再关一次不是错误：结果就是"它本来也没开着"（用户连点两下不该吃个红字）。
        again = self.call(46, "agent/close", {"session_id": session}).get("result", {})
        self.assertIs(again.get("closed"), False, again)

        # 对话没丢：接着说一句，宿主该把存档喂回来再答（这一轮照常走完工具再回话）。
        back = self.call(
            47,
            "agent/chat",
            {"text": "关掉之后还认得刚才那段吗？", "session_id": session},
            timeout=SKILLS_TIMEOUT,
        )
        self.assertNotIn("error", back, back)
        answer = back.get("result", {})
        self.assertEqual(answer.get("session_id"), session)
        self.assertTrue(answer.get("text"), answer)

        # 又聊起来 = 又开了一段，位子重新占上。
        rows = {
            row.get("session_id"): row
            for row in self.call(48, "agent/sessions").get("result", {}).get("sessions", [])
        }
        self.assertIs(rows[session].get("live"), True, "说话之后它又该活着")

    def test_23_agents_can_be_listed_and_switched(self) -> None:
        """面板那个下拉：``agent/agents`` 给清单，``agent/agent`` 换人。

        换的是**人设里的角色段** —— 工具表没动、历史也没动，所以要验两件事：清单长得对，
        以及下一轮请求的 system 里真的带上了这个角色的活儿。
        """
        listing = self.call(200, "agent/agents").get("result", {})
        self.assertEqual(listing.get("current"), "general", listing)
        self.assertIsNone(listing.get("missing"))
        self.assertTrue(listing.get("dir"), "得告诉用户文件往哪放")
        agents = {agent["id"]: agent for agent in listing.get("agents", [])}
        self.assertIn("general", agents)
        self.assertIn("storyboard", agents)
        self.assertEqual(agents["storyboard"]["name"], "分镜导演助手")
        self.assertIs(agents["storyboard"]["builtin"], True)
        # 人设正文（prompt）不往面板搬：清单只说有哪些、叫什么。
        self.assertTrue(all("prompt" not in agent for agent in agents.values()))

        switched = self.call(201, "agent/agent", {"agent": "storyboard"}).get("result", {})
        self.assertIs(switched.get("changed"), True, switched)
        self.assertEqual(switched.get("name"), "分镜导演助手")
        read = self.call(202, "agent/agent").get("result", {})
        self.assertEqual(read.get("agent"), "storyboard")
        self.assertIs(read.get("changed"), False)

        # 真的落到了人设上：下一轮请求的 system 里带着这个角色的活儿。
        with _FakeCompletions.lock:
            _FakeCompletions.seen_systems.clear()
        self.call(
            203,
            "agent/chat",
            {"text": "把这段拆成分镜", "session_id": "agents-e2e"},
            timeout=SKILLS_TIMEOUT,
        )
        with _FakeCompletions.lock:
            systems = list(_FakeCompletions.seen_systems)
        self.assertTrue(systems, "没收到任何 chat completions 请求")
        self.assertIn("分镜导演", systems[0])

        # 切回通用助手，别让后面的用例踩着一份角色设定跑。
        back = self.call(204, "agent/agent", {"agent": "general"}).get("result", {})
        self.assertIs(back.get("changed"), True, back)

    def test_24_bad_agent_name_is_minus_32602(self) -> None:
        for bad in ("no-such", "", "   ", 7, ["a"]):
            response = self.call(210, "agent/agent", {"agent": bad})
            self.assertEqual(response.get("error", {}).get("code"), -32602, response)
        # 被拒的值不该改掉当前选择
        self.assertEqual(self.call(211, "agent/agent").get("result", {}).get("agent"), "general")


if __name__ == "__main__":
    unittest.main()
