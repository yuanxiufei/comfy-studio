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
from ..skills.render import RENDER_TARGETS, WORKFLOWS_ENV, find_target
from ..web import WebFetcher
from .support import RENDER_DOC, RENDER_OBJECT_INFO, FakeEngine, FakeLLM
from .test_tools import GENERIC_TOOLS

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
        # 没配模型也要带着联网那几个字段：形状不随别的字段变，调用方不必写两套读法。
        self.assertIn("web_backend", body)

        with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "qwen"}, clear=True):
            status, body = await self.json_of("get", "/comfy-studio/agent/config")
        self.assertEqual(status, 200)
        self.assertEqual(body["model"], "qwen")
        # 从工具表算，不写死数字：加了通用工具却忘了改这里的数字，正是最容易被忽略的谎报。
        self.assertEqual(body["tool_count"], len(GENERIC_TOOLS) + 1 + 3, "通用工具 + 每 skill 一个 + 联网 3 把")

    def test_the_panel_handle_is_a_real_fetcher_and_is_reused(self) -> None:
        """取回来必须是**真句柄**，而且取第二次得是同一个（进程级共用一份）。

        这条盯的是一个真踩过的坑：缓存变量与取值函数同名时，``def`` 会把缓存那个格子换成
        函数对象，于是 ``is None`` 永远不成立、缓存永远不建，取回来的"句柄"其实是函数本身。
        它不会在装配阶段报错（工具表照样齐、``web=True`` 照样报对了），要等**模型真去搜一次**
        才炸 —— 所以只能在这里把它钉住：类型对 + 同一个对象。
        """
        self.addCleanup(setattr, routes, "_fetcher", routes._fetcher)
        routes._fetcher = None
        with mock.patch.dict(os.environ, {}, clear=True):
            handle = routes._web_fetcher()
        self.assertIsInstance(handle, WebFetcher, "取回来的不是句柄，是别的东西（比如函数）")
        self.assertIs(routes._web_fetcher(), handle, "第二次取得是同一份，不能每次新建")

    def test_the_handle_is_not_cached_when_web_is_off(self) -> None:
        """关着联网就每次回 ``None``：不能"建过一次就一直给"，那等于开关失效。"""
        self.addCleanup(setattr, routes, "_fetcher", routes._fetcher)
        routes._fetcher = None
        with mock.patch.dict(os.environ, {"COMFY_NO_WEB": "1"}, clear=True):
            self.assertIsNone(routes._web_fetcher())
            self.assertIsNone(routes._fetcher, "关了就不该建句柄")

    async def test_agent_config_reports_which_search_path_it_takes(self) -> None:
        """``agent/config`` 说的联网那一档，字段与宿主侧 ``host/info`` 一一对应。

        两处各报一份是因为**这是两个进程、两份环境**，但话必须是同一套：
        键名一致，前端才能照着同一句话画；"搜出来太少"时第一个要看的就是这条。

        注意这里的句柄是**进程级缓存**（:func:`routes._web_fetcher`）：环境变量只在第一次
        建句柄时读一次。这正是引擎要的语义 —— 它的环境是启动时给的，跑起来不会变 ——
        但写用例时得自己把那份缓存清掉，否则验的只是"上一条用例留下的那个后端"。
        """
        self.addCleanup(setattr, routes, "_fetcher", routes._fetcher)
        cases = [
            ({}, True, "bing", "https://www.bing.com/search", None),
            ({"COMFY_NO_WEB": "1"}, False, None, None, None),
            # 走自建实例时**不报**必应那条入口：它根本没被请求过，报出去等于说
            # "面板写走必应、实际走的是自建实例"，用户会照着那句话去查必应。
            ({"COMFY_SEARXNG_URL": "http://127.0.0.1:8888"}, True, "searxng", None, "http://127.0.0.1:8888"),
        ]
        for environ, web, backend, search_url, searxng_url in cases:
            with self.subTest(environ=environ):
                routes._fetcher = None  # 清缓存：不然读到的是上一条用例建的句柄
                with mock.patch.dict(
                    os.environ, {**environ, "COMFY_STUDIO_LLM_MODEL": "qwen"}, clear=True
                ):
                    status, body = await self.json_of("get", "/comfy-studio/agent/config")
                self.assertEqual(status, 200, body)
                self.assertIs(body["web"], web)
                self.assertEqual(body["web_backend"], backend)
                self.assertEqual(body["web_search_url"], search_url)
                self.assertEqual(body["web_searxng_url"], searxng_url)

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

    async def test_agent_chat_can_really_search_the_web_from_the_panel(self) -> None:
        """模型在面板里真去搜一次：句柄 → 工具表 → 工具调用这整条线都得通。

        这是"缓存变量与函数同名"那个坑真正炸掉的地方 —— 装配阶段一切正常（工具表齐、
        ``web=True`` 也报对了），要等**真去搜**才炸成 500。所以这里不假造工具、也不假造
        工具表，只把**一次网络往返**换掉（``WebFetcher.search``）：路由那层取到的句柄
        必须是个真句柄，才接得住这次调用。
        """
        self.addCleanup(setattr, routes, "_fetcher", routes._fetcher)
        routes._fetcher = None
        seen: list[tuple[str, int]] = []

        async def fake_search(self: WebFetcher, query: Any, *, limit: int) -> dict[str, Any]:
            seen.append((query, limit))
            return {
                "query": query,
                "backend": "bing",
                "page_url": "https://www.bing.com/search?q=x",
                "results": [
                    {"title": "装法", "url": "https://example.test/a", "snippet": "先装管理器"}
                ],
            }

        self.llm = FakeLLM(
            [
                ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(id="c1", name="web__search", arguments={"query": "插件怎么装", "limit": 3})
                    ],
                ),
                reply("搜到了：先装管理器"),
            ]
        )
        with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "qwen"}, clear=True):
            with mock.patch.object(routes, "OpenAIChatClient", lambda _config: self.llm):
                with mock.patch.object(WebFetcher, "search", fake_search):
                    response = await self.client.post(
                        "/comfy-studio/agent/chat", json={"message": "插件怎么装"}
                    )
                    text = await response.text()

        self.assertEqual(response.status, 200)
        self.assertEqual(seen, [("插件怎么装", 3)], "搜索得真走到句柄上，参数原样带下去")
        self.assertIn("装法", text, "搜到的标题要进工具结果，模型才看得见")
        self.assertNotIn("event: error", text)

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


class RenderRouteTest(RouteContractTest):
    """渲染路由：与 MCP 的 comfy_list_renders / comfy_render 同一套组装，别长出两套口径。"""

    def workflows_with(self, target_id: str = "video-interpolate") -> Path:
        """把工作流目录换成临时目录，并只放指定的那一张。"""
        tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-render-routes-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name, "workflows")
        root.mkdir()
        (root / find_target(target_id).file).write_text(json.dumps(RENDER_DOC), encoding="utf-8")
        env = mock.patch.dict(os.environ, {WORKFLOWS_ENV: str(root)})
        env.start()
        self.addCleanup(env.stop)
        return root

    async def test_renders_endpoint_lists_targets_and_flags_missing_files(self) -> None:
        root = self.workflows_with()
        status, body = await self.json_of("get", "/comfy-studio/renders")
        self.assertEqual(status, 200)
        self.assertEqual(body["workflows_dir"], str(root))
        self.assertIsNone(body["note"])
        by_id = {item["id"]: item for item in body["targets"]}
        self.assertEqual(sorted(by_id), sorted(target.id for target in RENDER_TARGETS))
        self.assertIs(by_id["video-interpolate"]["file_exists"], True)
        self.assertIs(by_id["video-draft"]["file_exists"], False, "缺的图要如实标出来，别假装列出来的都能跑")
        self.assertIs(by_id["video-draft"]["reference_images"], True)
        self.assertNotIn("reference_images", by_id["video-interpolate"])

    async def test_renders_endpoint_says_so_when_the_directory_is_gone(self) -> None:
        with mock.patch.dict(os.environ, {WORKFLOWS_ENV: str(Path(self._tmpdir.name, "没有这个目录"))}):
            status, body = await self.json_of("get", "/comfy-studio/renders")
        self.assertEqual(status, 200)
        self.assertIn(WORKFLOWS_ENV, body["note"])
        self.assertEqual(len(body["targets"]), len(RENDER_TARGETS))

    async def test_render_route_runs_the_target(self) -> None:
        self.workflows_with()
        self.engine.object_info_map = dict(RENDER_OBJECT_INFO)
        status, body = await self.json_of(
            "post", "/comfy-studio/renders/video-interpolate/run", json={"params": {"file": "in.mp4"}}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["prompt_id"], "prompt-1")
        self.assertEqual(body["target"], "video-interpolate")
        self.assertEqual(len(self.engine.submitted), 1)
        self.assertEqual(self.engine.submitted[0]["1"]["inputs"]["file"], "in.mp4")

    async def test_render_route_rejects_bad_input_without_submitting(self) -> None:
        self.workflows_with()
        status, body = await self.json_of("post", "/comfy-studio/renders/没有这个目标/run", json={})
        self.assertEqual(status, 400, body)
        self.assertIn("video-draft", json.dumps(body, ensure_ascii=False), "目标名写错要列出可用的")

        status, body = await self.json_of("post", "/comfy-studio/renders/video-draft/run", json={"images": "a.png"})
        self.assertEqual(status, 400, body)
        self.assertIn("images", json.dumps(body, ensure_ascii=False))

        status, body = await self.json_of("post", "/comfy-studio/renders/video-draft/run", json={"duration_sec": 0})
        self.assertEqual(status, 400, f"{body} —— 时长要正数这条规则住在组装期，路由不该自己另写一份")

        self.assertEqual(self.engine.submitted, [], "输入不成立就不该提交任何东西")

    async def test_render_route_reports_a_missing_workflow_file(self) -> None:
        self.workflows_with()  # 只放了 08 那一张
        status, body = await self.json_of("post", "/comfy-studio/renders/video-draft/run", json={"prompt": "x"})
        self.assertEqual(status, 400, body)
        self.assertIn(WORKFLOWS_ENV, json.dumps(body, ensure_ascii=False))
        self.assertEqual(self.engine.submitted, [])


if __name__ == "__main__":
    unittest.main()
