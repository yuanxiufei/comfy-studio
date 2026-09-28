"""内建 MCP server 的启动参数（`mcp/config.py`）—— 宿主与引擎那份之间的分工全落在这里。

这两个用例都盯着同一类事：**同一个能力只许有一套**。工具表是把各 server 的工具按
`<server>__<tool>` 拼起来的，名字撞了不会报错、只会让模型在两套里随便挑一套用，
所以只能在装配参数这一层把它验住（真跑一遍的那份在 `test_host_e2e.py` 里）。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfy_studio.mcp.client import McpError, McpTool
from comfy_studio.mcp.config import (
    ENGINE_NO_WEB_ENV,
    ENGINE_NO_WEB_VALUE,
    ENGINE_SERVER_NAME,
    collect_servers,
    engine_server,
    engine_web_tools,
    parse_extra_servers,
)


def _comfyui_dir(root: Path) -> Path:
    """给出一个"看起来像 ComfyUI"的目录（引擎 server 只要求 custom_nodes 在）。"""
    (root / "custom_nodes").mkdir(parents=True, exist_ok=True)
    return root


class EngineServerTests(unittest.TestCase):
    def test_builtin_server_is_told_not_to_do_web_itself(self) -> None:
        """内建那条固定带 `COMFY_NO_WEB=1`：面板那条对话的联网只由宿主出网。

        不带这一条时引擎那份会照旧挂上自己那三张，面板的工具表里就同时有 `web__*` 与
        `comfy-studio__web__*` 两套：模型在两套里随便挑，两套各有各的环境变量与后端，
        "搜不到"时该看哪份配置成了说不清的事；更要紧的是 `--no-web` 只关得掉宿主那三张。
        """
        with tempfile.TemporaryDirectory() as tmp:
            server = engine_server(_comfyui_dir(Path(tmp)))
        self.assertEqual(server.name, ENGINE_SERVER_NAME)
        self.assertEqual(server.env[ENGINE_NO_WEB_ENV], ENGINE_NO_WEB_VALUE)
        # 是"替它关掉"而不是"看环境里写没写"：谁在外头设了 COMFY_NO_WEB=0 都不该漏进来，
        # 否则同一个开关在两条路径上得到两种结果，等于没有约定。
        with mock.patch.dict(os.environ, {ENGINE_NO_WEB_ENV: "0"}, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                server = engine_server(_comfyui_dir(Path(tmp)))
        self.assertEqual(server.env[ENGINE_NO_WEB_ENV], ENGINE_NO_WEB_VALUE)
        # 引擎 HTTP 地址默认是本机 8188（ComfyUI 自己的默认端口），给了就用给的。
        self.assertEqual(server.env["COMFY_URL"], "http://127.0.0.1:8188")
        with tempfile.TemporaryDirectory() as tmp:
            server = engine_server(_comfyui_dir(Path(tmp)), comfy_url="http://127.0.0.1:9000")
        self.assertEqual(server.env["COMFY_URL"], "http://127.0.0.1:9000")
        # 联网那一条是**唯一**的例外，别的环境变量一个都不替用户编。
        self.assertEqual(set(server.env), {"COMFY_URL", ENGINE_NO_WEB_ENV})

    def test_missing_custom_nodes_is_an_error_not_a_silent_empty_table(self) -> None:
        """目录里没有 `custom_nodes` 就直接报错：不假装拉起来了、也不回一张空表。"""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(McpError) as caught:
                engine_server(Path(tmp))
        self.assertIn("custom_nodes", str(caught.exception))


class ExtraServersTests(unittest.TestCase):
    def test_extra_server_may_not_take_the_builtin_name(self) -> None:
        """用户自定义 server 不许占用内建名：占了就是两条同前缀的工具，名字分不出来。"""
        raw = f'[{{"name": "{ENGINE_SERVER_NAME}", "command": "python"}}]'
        with self.assertRaises(McpError) as caught:
            parse_extra_servers(raw)
        self.assertIn(ENGINE_SERVER_NAME, str(caught.exception))

    def test_extra_servers_come_after_the_builtin_one(self) -> None:
        raw = '[{"name": "other", "command": "python", "args": ["-m", "other"]}]'
        with tempfile.TemporaryDirectory() as tmp:
            servers = collect_servers(_comfyui_dir(Path(tmp)), extra_raw=raw)
        self.assertEqual([s.name for s in servers], [ENGINE_SERVER_NAME, "other"])


class EngineWebLeakTests(unittest.TestCase):
    """内建 server 名下冒出联网工具时能不能被指出（`server.py` 启动日志直接问这个函数）。

    这一问的分量在于**没有别的地方会响**：名字对不上时引擎只是照旧挂上自己那三张，没有
    任何报错，面板里就多出一套同能力工具。真跑一遍的那份仍在 `test_host_e2e.py` 里。
    """

    @staticmethod
    def _tool(server: str, name: str) -> McpTool:
        return McpTool(server=server, name=name, description="", input_schema={})

    def test_quiet_when_the_engine_keeps_its_hands_off(self) -> None:
        """正常情况是空表 —— 宿主自己那三张不能算漏：它们该在（server 是 `web`）。"""
        tools = [self._tool(ENGINE_SERVER_NAME, "comfy_submit_workflow")]
        tools += [self._tool("web", name) for name in ("search", "fetch", "crawl")]
        self.assertEqual(engine_web_tools(tools), [])

    def test_engine_side_web_tools_are_reported_by_their_qualified_name(self) -> None:
        """报了就要报成模型看到的那个名字：用户拿着它才找得到面板里多出来的那条。"""
        tools = [
            self._tool(ENGINE_SERVER_NAME, "comfy_submit_workflow"),
            self._tool(ENGINE_SERVER_NAME, "web__search"),
            self._tool(ENGINE_SERVER_NAME, "web__crawl"),
        ]
        self.assertEqual(
            engine_web_tools(tools),
            ["comfy-studio__web__crawl", "comfy-studio__web__search"],
        )

    def test_other_servers_are_not_policed(self) -> None:
        """别的 server 挂什么工具不关这里的事：只看内建那个 server 名下。"""
        self.assertEqual(engine_web_tools([self._tool("other", "web__search")]), [])


class StartupWarningIsWiredTests(unittest.TestCase):
    """启动那声警告得真的接在启动路径上。

    这个自检唯一的产出是一行 stderr：函数测得再细，**接线被删掉**也不会有任何用例变红 ——
    守卫要盯着接线，不能只盯着函数。
    """

    def test_server_asks_the_question_at_startup(self) -> None:
        # 用文件自身定位，不写盘符：换台机器照样找得到 server.py。
        source = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        self.assertIn("engine_web_tools(hub.tools)", source)


if __name__ == "__main__":
    unittest.main()
