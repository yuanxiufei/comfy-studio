"""面板用的 HTTP 契约：状态码、错误体、SSE 帧。

真身是挂在引擎 aiohttp app 上的路由，这里用一个假的 ``server`` 模块顶替
``PromptServer.instance.routes``，并用假引擎/假模型客户端把两端都掐断。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from .. import routes
from ..agent.types import ChatMessage, ToolCall
from ..engine import EngineError
from .support import FakeEngine, FakeLLM

WORKFLOW_BODY = {"params": {"ckpt_name": "a.safetensors", "positive": "一只猫", "seed": 7}}


def reply(text: str = "") -> ChatMessage:
    return ChatMessage(role="assistant", content=text)


class RouteContractTest(unittest.IsolatedAsyncioTestCase):
    engine: FakeEngine

    async def asyncSetUp(self) -> None:
        self.engine = FakeEngine()
        self.table = self._install_fake_server()
        # 用户 skill 目录钉在临时目录里：否则会读到开发机上真实的 skill，
        # 断言"列表里只有随包那一个"就成了看运气。
        self._tmpdir = tempfile.TemporaryDirectory(prefix="comfy-studio-routes-")
        self.addCleanup(self._tmpdir.cleanup)
        self.user_skills = Path(self._tmpdir.name, "skills")
        patcher = mock.patch.object(routes, "user_skills_dir", lambda: self.user_skills)
        patcher.start()
        self.addCleanup(patcher.stop)

        # 路由在注册时就把引擎闭包进 handler，所以 patch 只要覆盖注册那一刻
        with mock.patch.object(routes, "get_engine", lambda *a, **k: self.engine):
            routes.register_routes()
        routes._sessions.clear()
        routes._registry = None
        routes._skill_stamp = None

        app = web.Application()
        app.add_routes(self.table)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        routes._sessions.clear()
        if getattr(sys.modules.get("server"), "_comfy_studio_test_fake", False):
            sys.modules.pop("server", None)

    @staticmethod
    def _install_fake_server() -> web.RouteTableDef:
        """造一个带 ``PromptServer.instance.routes`` 的假 server 模块。"""
        table = web.RouteTableDef()
        module = types.ModuleType("server")
        module.PromptServer = SimpleNamespace(instance=SimpleNamespace(routes=table, number=0))
        module._comfy_studio_test_fake = True  # type: ignore[attr-defined]
        sys.modules["server"] = module
        return table

    # ---- 通用断言 --------------------------------------------------------

    async def json_of(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        response = await getattr(self.client, method)(path, **kwargs)
        try:
            body = await response.json()
        except Exception:  # noqa: BLE001 - 非 JSON 时保留原文，交给断言的失败信息
            body = await response.text()
        return response.status, body

    # ---- 用例 ------------------------------------------------------------

    async def test_skills_endpoint_describes_the_param_table(self) -> None:
        status, body = await self.json_of("get", "/comfy-studio/skills")
        self.assertEqual(status, 200)
        self.assertTrue(body["skills_dir"])
        self.assertEqual(body["user_skills_dir"], str(self.user_skills), "用户目录要如实报出来")
        self.assertEqual([s["id"] for s in body["skills"]], ["text-to-image"])
        self.assertTrue(body["skills"][0]["file"].endswith("text-to-image.json"))
        params = {p["name"]: p for p in body["skills"][0]["params"]}
        self.assertIs(params["ckpt_name"]["required"], True)
        self.assertIsNone(params["positive"]["default"])
        self.assertIn("list_models", params["ckpt_name"]["description"], "随包 skill 的提示词是给模型看的")
        self.assertTrue(params["positive"]["description"].strip(), "没有 description 的参数应由 hint() 兜底")
        self.assertIn("image", body["skills"][0]["tags"])

    async def test_models_endpoint_reports_the_folder_and_errors(self) -> None:
        self.engine.object_info_map["CheckpointLoaderSimple"] = {
            "input": {"required": {"ckpt_name": [["a.safetensors"]]}}
        }
        status, body = await self.json_of("get", "/comfy-studio/models")
        self.assertEqual((status, body), (200, {"folder": "checkpoints", "models": ["a.safetensors"]}))

        status, body = await self.json_of("get", "/comfy-studio/models?folder=nope")
        self.assertEqual(status, 400)
        self.assertIn("未知 folder: nope", body["error"])

    async def test_queue_and_interrupt_hit_the_engine(self) -> None:
        self.engine.queue_snapshot = {"queue_running": [[1, "p1"]], "queue_pending": []}
        self.assertEqual(await self.json_of("get", "/comfy-studio/queue"), (200, self.engine.queue_snapshot))

        self.assertEqual(await self.json_of("post", "/comfy-studio/interrupt"), (200, {"ok": True}))
        self.assertEqual(self.engine.interrupts, 1)

    async def test_a_new_user_skill_shows_up_without_a_restart(self) -> None:
        """用户在对话里存下一个 skill 后，同一个进程的接口立刻能看到（也就能跑）。"""
        from ..skills import validate_skill
        from ..skills.store import write_skill

        document = {
            "id": "from-chat",
            "title": "对话里存的",
            "description": "存完立刻能被列出来、被调用",
            "workflow": {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a.safetensors"}}},
            "params": [{"name": "ckpt_name", "type": "string", "node": "4", "field": "ckpt_name"}],
        }
        write_skill(validate_skill(document, "mem"), self.user_skills)

        status, body = await self.json_of("get", "/comfy-studio/skills")
        self.assertEqual(status, 200)
        self.assertEqual([s["id"] for s in body["skills"]], ["text-to-image", "from-chat"])

        status, body = await self.json_of(
            "post", "/comfy-studio/skills/from-chat/run", json={"params": {"ckpt_name": "b.safetensors"}}
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.engine.submitted[0]["4"]["inputs"]["ckpt_name"], "b.safetensors")

    async def test_a_broken_skill_file_says_so_instead_of_listing_nothing(self) -> None:
        self.user_skills.mkdir(parents=True, exist_ok=True)
        (self.user_skills / "broken.json").write_text("{ 不是 JSON", encoding="utf-8")
        status, body = await self.json_of("get", "/comfy-studio/skills")
        self.assertEqual(status, 500)
        self.assertIn("不是合法 JSON", body["error"])

    async def test_run_skill_returns_images(self) -> None:
        status, body = await self.json_of("post", "/comfy-studio/skills/text-to-image/run", json=WORKFLOW_BODY)
        self.assertEqual(status, 200)
        self.assertEqual(body["prompt_id"], "prompt-1")
        self.assertTrue(body["images"][0]["url"].startswith("http://engine.test/view?"))
        self.assertEqual(self.engine.submitted[0]["3"]["inputs"]["seed"], 7)

    async def test_run_skill_error_paths(self) -> None:
        status, body = await self.json_of("post", "/comfy-studio/skills/nope/run", json=WORKFLOW_BODY)
        self.assertEqual((status, body), (404, {"error": "没有 skill nope"}))

        response = await self.client.post("/comfy-studio/skills/text-to-image/run", data="{ 不是 JSON")
        self.assertEqual(response.status, 400)
        self.assertIn("不是合法 JSON", (await response.json())["error"])

        status, body = await self.json_of(
            "post", "/comfy-studio/skills/text-to-image/run", json={"params": ["a.safetensors"]}
        )
        self.assertEqual(status, 400)
        self.assertIn("params 必须是对象", body["error"])

        status, body = await self.json_of("post", "/comfy-studio/skills/text-to-image/run", json={})
        self.assertEqual(status, 400)
        self.assertIn("缺少必填参数", body["error"])

        status, body = await self.json_of("post", "/comfy-studio/skills/text-to-image/run", json=WORKFLOW_BODY)
        self.assertEqual(status, 200)
        self.assertEqual(len(self.engine.submitted), 1, "前几种失败都不该提交工作流")

    async def test_run_skill_engine_failure_is_500(self) -> None:
        async def boom(_workflow: dict[str, Any]) -> str:
            raise EngineError("队列满了")

        with mock.patch.object(self.engine, "submit", boom):
            status, body = await self.json_of("post", "/comfy-studio/skills/text-to-image/run", json=WORKFLOW_BODY)
        self.assertEqual(status, 500)
        self.assertEqual(body["error"], "队列满了")

    async def test_agent_config_reports_why_it_is_unconfigured(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            status, body = await self.json_of("get", "/comfy-studio/agent/config")
        self.assertEqual(status, 200)
        self.assertIs(body["configured"], False)
        self.assertIn("COMFY_STUDIO_LLM_MODEL", body["reason"])

        with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "qwen"}, clear=True):
            status, body = await self.json_of("get", "/comfy-studio/agent/config")
        self.assertEqual(status, 200)
        self.assertEqual(body["model"], "qwen")
        self.assertEqual(body["tool_count"], 9, "8 个通用工具 + 每 skill 一个")

    async def test_agent_chat_validates_input_and_llm_config(self) -> None:
        for body in ({}, {"message": "   "}, {"message": 3}):
            with self.subTest(body=body):
                status, payload = await self.json_of("post", "/comfy-studio/agent/chat", json=body)
                self.assertEqual(status, 400)
                self.assertIn("message", payload["error"])

        with mock.patch.dict(os.environ, {}, clear=True):
            status, payload = await self.json_of(
                "post", "/comfy-studio/agent/chat", json={"message": "你好", "session_id": "未配置"}
            )
        self.assertEqual(status, 503)
        self.assertIn("COMFY_STUDIO_LLM_MODEL", payload["error"])
        self.assertEqual(routes._sessions, {}, "模型没配好时不该留下半个会话")

    async def test_agent_chat_streams_sse_frames(self) -> None:
        self.llm = FakeLLM(
            [
                ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="skill__text-to-image",
                            arguments={"ckpt_name": "a.safetensors", "positive": "一只猫", "seed": 7},
                        )
                    ],
                ),
                reply("画好了"),
            ]
        )
        with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "qwen"}, clear=True):
            with mock.patch.object(routes, "OpenAIChatClient", lambda _config: self.llm):
                response = await self.client.post("/comfy-studio/agent/chat", json={"message": "画只猫"})
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "text/event-stream; charset=utf-8")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                text = await response.text()

        events = [
            line.split(": ", 1)[1]
            for line in text.splitlines()
            if line.startswith("event: ")
        ]
        self.assertEqual(events, ["start", "tool_call", "tool_result", "final", "done"])
        self.assertIn('"text": "画好了"', text)
        payload = json.loads(text.split("event: tool_call\ndata: ", 1)[1].split("\n\n", 1)[0])
        self.assertEqual(payload["name"], "skill__text-to-image")
        self.assertEqual(self.engine.submitted[0]["6"]["inputs"]["text"], "一只猫")

    async def test_agent_chat_reports_model_failure_as_an_error_frame(self) -> None:
        class BrokenLLM:
            async def complete(self, *_args: Any, **_kwargs: Any) -> ChatMessage:
                raise routes.LLMError("模型连不上")

            async def close(self) -> None:
                return None

        with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "qwen"}, clear=True):
            with mock.patch.object(routes, "OpenAIChatClient", lambda _config: BrokenLLM()):
                response = await self.client.post("/comfy-studio/agent/chat", json={"message": "你好"})
                text = await response.text()
        self.assertEqual(response.status, 200, "SSE 已经开始，失败只能走 error 帧")
        self.assertIn("event: error", text)
        self.assertIn("LLMError: 模型连不上", text)

    async def test_agent_chat_keeps_sessions_apart_and_evicts_the_oldest(self) -> None:
        llm = FakeLLM([reply("一"), reply("二"), reply("三")])
        with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "qwen"}, clear=True):
            with mock.patch.object(routes, "OpenAIChatClient", lambda _config: llm):
                with mock.patch.object(routes, "MAX_SESSIONS", 2):
                    self.assertEqual(routes.MAX_SESSIONS, 2)
                    await (await self.client.post("/comfy-studio/agent/chat", json={"message": "a", "session_id": "s1"})).text()
                    await (await self.client.post("/comfy-studio/agent/chat", json={"message": "b", "session_id": "s2"})).text()
                    self.assertEqual(sorted(routes._sessions), ["s1", "s2"])

                    oldest = routes._sessions["s1"]
                    await (await self.client.post("/comfy-studio/agent/chat", json={"message": "c", "session_id": "s3"})).text()
                    self.assertEqual(sorted(routes._sessions), ["s2", "s3"])
                    self.assertEqual(oldest.messages, [], "被淘汰的会话要清掉历史，别把上下文留在内存里")


if __name__ == "__main__":
    unittest.main()
