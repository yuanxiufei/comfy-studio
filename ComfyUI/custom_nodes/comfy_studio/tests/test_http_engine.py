"""``HttpEngine`` 怎么问模型清单：上游 ``/models`` 与 ``/models/{folder}`` 两条路由。

这两条路由是引擎后来才加的（``ComfyUI/server.py`` 的 ``list_model_types`` / ``get_models``），
老引擎上没有，所以 :meth:`HttpEngine.list_models` 里留了退路：没有 ``/models`` 就退回读节点
下拉枚举。于是 ``/models/{folder}`` 的 404 有**两种**含义——"这个类别本机没注册"与"这台
引擎压根没有这条路由"——只能靠 ``/models`` 在不在来分辨。这段分支全靠状态码，肉眼看不出来，
所以这里真起一个 aiohttp 假引擎把它摁住测。

跑法（引擎 venv，cwd 在 ``custom_nodes``）::

    python -m unittest discover -s comfy_studio/tests -t .
"""

from __future__ import annotations

import unittest
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

from ..engine import MODEL_PROBES, EngineError
from ..engine.http import HttpEngine

#: ``/models`` 的原样回包；用它当默认值 = "这台引擎没有这条路由"。
_NO_MODELS_ROUTE = object()


class FakeComfy:
    """只有三条路由的假引擎：``/models``、``/models/{folder}``、``/object_info/{node}``。

    ``models`` 给什么就原样回什么（非 list 用来试形状检查，``_NO_MODELS_ROUTE`` 表示没这条
    路由）；``files`` 是 类别名 → 原样回包；``nodes`` 是 节点类名 → ``INPUT_TYPES()`` 风格的
    定义，老引擎的退路要读它。
    """

    def __init__(
        self,
        *,
        models: Any = _NO_MODELS_ROUTE,
        files: dict[str, Any] | None = None,
        nodes: dict[str, Any] | None = None,
        models_status: int = 200,
        cancels: dict[str, Any] | None = None,
        has_cancel_route: bool = True,
    ) -> None:
        self.models = models
        self.files = files or {}
        self.nodes = nodes or {}
        self.models_status = models_status
        #: job_id → 原样回包；值是 ``(状态码, 正文)`` 时用来试错误状态。
        self.cancels = cancels or {}
        #: False = 模拟"没有这条取消路由"的老引擎。
        self.has_cancel_route = has_cancel_route
        #: 服务端实际收到的 ``/models/{folder}`` 里的类别名（验证客户端有没有做 URL 编码）。
        self.asked: list[str] = []
        #: 服务端实际收到的 ``/api/jobs/{job_id}/cancel`` 里的 job_id（同上）。
        self.cancel_asked: list[str] = []

    def table(self) -> web.RouteTableDef:
        table = web.RouteTableDef()

        if self.models is not _NO_MODELS_ROUTE:

            async def models(_request: web.Request) -> web.Response:
                if self.models_status != 200:
                    return web.Response(status=self.models_status, text="boom")
                return web.json_response(self.models)

            table.get("/models")(models)

        async def files(request: web.Request) -> web.Response:
            folder = request.match_info["folder"]
            self.asked.append(folder)
            if folder not in self.files:
                return web.Response(status=404, text="no such folder")
            return web.json_response(self.files[folder])

        async def object_info(request: web.Request) -> web.Response:
            node = request.match_info["node"]
            value = self.nodes.get(node)
            if value is None:
                # 上游对不认识的节点回的就是空的 {}（200），不是 404 —— 见
                # ``ComfyUI/server.py`` 的 get_object_info_node。
                return web.json_response({})
            return web.json_response({node: value})

        if self.has_cancel_route:

            async def cancel(request: web.Request) -> web.Response:
                job_id = request.match_info["job_id"]
                self.cancel_asked.append(job_id)
                payload = self.cancels.get(job_id, {"cancelled": True})
                if isinstance(payload, tuple):
                    status, body = payload
                    return web.json_response(body, status=status)
                return web.json_response(payload)

            # 上游把它注册在 /api 前缀下（``ComfyUI/server.py`` 的 cancel_job_by_id），
            # 所以这里也照原样挂，正好顺带验证客户端没自作主张去掉前缀。
            table.post("/api/jobs/{job_id}/cancel")(cancel)

        table.get("/models/{folder}")(files)
        table.get("/object_info/{node}")(object_info)
        return table


class _EngineTestCase(unittest.IsolatedAsyncioTestCase):
    """起一个假引擎并把 HttpEngine 接上去（模型清单与取消两组用例共用）。"""

    async def start(self, fake: FakeComfy) -> HttpEngine:
        app = web.Application()
        app.add_routes(fake.table())
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        engine = HttpEngine(f"http://127.0.0.1:{server.port}", request_timeout=5.0)
        self.addAsyncCleanup(engine.close)
        return engine


class HttpModelListTest(_EngineTestCase):

    async def test_it_reads_the_folder_set_and_the_files(self) -> None:
        fake = FakeComfy(
            models=["checkpoints", "loras", "f5_tts"],
            files={"f5_tts": ["voice.safetensors"]},
        )
        engine = await self.start(fake)

        self.assertEqual(await engine.list_model_folders(), ["checkpoints", "loras", "f5_tts"])
        # 第三方节点注册的目录照列不误（引擎那边有没有白名单不关这里的事）
        self.assertEqual(await engine.list_models("f5_tts"), ["voice.safetensors"])

        listed = await engine.list_model_folders()
        listed.append("nope")
        self.assertEqual(await engine.list_model_folders(), ["checkpoints", "loras", "f5_tts"], "回的该是副本")

    async def test_the_folder_name_is_url_encoded(self) -> None:
        # 类别名是引擎给的，可能带空格、# 这类字符；不编码的话 # 会被当成片段截掉，
        # 请求就打到别的路径上去了。
        fake = FakeComfy(models=["f5 tts", "a#b"], files={"f5 tts": ["v.ckpt"], "a#b": ["w.ckpt"]})
        engine = await self.start(fake)

        self.assertEqual(await engine.list_models("f5 tts"), ["v.ckpt"])
        self.assertEqual(await engine.list_models("a#b"), ["w.ckpt"])
        self.assertEqual(fake.asked, ["f5 tts", "a#b"])

    async def test_legacy_folder_names_fall_back_to_the_new_ones(self) -> None:
        # 上游 /models/{folder} 不认老名字（直接拿它查 folder_names_and_paths），而
        # folder_paths.get_filename_list 认（走 map_legacy）—— 两条路得答一样，所以
        # 404 时用新名字再问一次。
        fake = FakeComfy(
            models=["diffusion_models", "text_encoders"],
            files={"diffusion_models": ["sd15.safetensors"]},
        )
        engine = await self.start(fake)

        self.assertEqual(await engine.list_models("unet"), ["sd15.safetensors"])
        self.assertEqual(fake.asked, ["unet", "diffusion_models"])

        with self.assertRaises(EngineError) as ctx:  # 别名也没注册：照实报，并点出试过的老名字
            await engine.list_models("clip")
        self.assertIn("本机没有注册模型类别 clip（老名字 text_encoders 也没有）", str(ctx.exception))

    async def test_an_unregistered_folder_names_the_available_ones(self) -> None:
        fake = FakeComfy(models=["checkpoints", "loras"], files={"loras": ["a.safetensors"]})
        engine = await self.start(fake)

        with self.assertRaises(EngineError) as ctx:
            await engine.list_models("nope")
        self.assertIn("本机没有注册模型类别 nope", str(ctx.exception))
        self.assertIn("checkpoints, loras", str(ctx.exception))
        self.assertNotIn("未知 folder", str(ctx.exception), "引擎新到有 /models 了，不该再退回探测法")

    async def test_an_engine_without_the_route_falls_back_to_node_enums(self) -> None:
        """老引擎：两条路由都没有，只能读节点下拉枚举，类别也只剩探测表那几类。

        这里 ``files`` 是空的 ⇒ ``/models/{folder}`` 也 404，模拟"两条路由都没有"。
        """
        fake = FakeComfy(
            files={},
            nodes={
                "LoraLoader": {
                    "input": {"required": {"lora_name": [["a.safetensors", "b.ckpt"]]}}
                }
            },
        )
        engine = await self.start(fake)

        self.assertEqual(await engine.list_model_folders(), list(MODEL_PROBES))
        self.assertEqual(await engine.list_models("loras"), ["a.safetensors", "b.ckpt"])

        with self.assertRaises(EngineError) as ctx:
            await engine.list_models("vae")
        self.assertIn("节点 VAELoader 不存在", str(ctx.exception))

        with self.assertRaises(EngineError) as ctx:
            await engine.list_models("nope")
        self.assertIn("未知 folder: nope", str(ctx.exception))

    async def test_unexpected_shapes_and_statuses_are_reported(self) -> None:
        for payload in ({"checkpoints": []}, ["checkpoints", 3], "checkpoints"):
            with self.subTest(models=payload):
                engine = await self.start(FakeComfy(models=payload))
                with self.assertRaises(EngineError) as ctx:
                    await engine.list_model_folders()
                self.assertIn("/models 返回了意外内容", str(ctx.exception))

        engine = await self.start(FakeComfy(models=["checkpoints"], files={"checkpoints": [1, 2]}))
        with self.assertRaises(EngineError) as ctx:
            await engine.list_models("checkpoints")
        self.assertIn("返回了意外内容", str(ctx.exception))

        engine = await self.start(FakeComfy(models=[], models_status=500))
        with self.assertRaises(EngineError) as ctx:
            await engine.list_model_folders()
        self.assertIn("GET /models 返回 500", str(ctx.exception))


class HttpCancelPromptTest(_EngineTestCase):
    """``cancel_prompt``：上游 ``POST /api/jobs/{job_id}/cancel``。

    这是取消一个 skill 时"把活从引擎队列里撤下来"的唯一手段。路由本身是幂等的（已经跑完
    或根本不认识的 id 回 ``{"cancelled": false}``，不是错误），但 **404 是另一回事**：那说明
    这台引擎没有这条路由，不能当成"没撤到"糊过去 —— 否则"已停止"底下那步生成还在跑。
    """

    async def test_it_asks_the_engine_to_cancel_that_exact_job(self) -> None:
        fake = FakeComfy(cancels={"p1": {"cancelled": True}, "p2": {"cancelled": False}})
        engine = await self.start(fake)

        self.assertTrue(await engine.cancel_prompt("p1"))
        self.assertFalse(await engine.cancel_prompt("p2"), "已结束/不认识的 id 回 False，不是错误")
        self.assertEqual(fake.cancel_asked, ["p1", "p2"])

    async def test_the_job_id_is_url_encoded(self) -> None:
        # id 是引擎给的（我们这边提交时用的是 uuid4，但形状不该依赖这一点）：不编码的话
        # "#" 会被当成片段截掉，请求就打到别的路径上去了。
        fake = FakeComfy(cancels={"a#b": {"cancelled": True}})
        engine = await self.start(fake)

        self.assertTrue(await engine.cancel_prompt("a#b"))
        self.assertEqual(fake.cancel_asked, ["a#b"])

    async def test_an_engine_without_the_route_is_reported_not_swallowed(self) -> None:
        engine = await self.start(FakeComfy(has_cancel_route=False))

        with self.assertRaises(EngineError) as ctx:
            await engine.cancel_prompt("p1")
        message = str(ctx.exception)
        self.assertIn("没有 /api/jobs/{job_id}/cancel 路由", message)
        self.assertIn("p1", message, "要说清是哪个 prompt 没撤下来")

    async def test_unexpected_shapes_and_statuses_are_reported(self) -> None:
        engine = await self.start(FakeComfy(cancels={"p1": {"ok": True}}))
        with self.assertRaises(EngineError) as ctx:
            await engine.cancel_prompt("p1")
        self.assertIn("返回了意外内容", str(ctx.exception))

        engine = await self.start(FakeComfy(cancels={"p2": (500, {"error": "boom"})}))
        with self.assertRaises(EngineError) as ctx:
            await engine.cancel_prompt("p2")
        self.assertIn("POST /api/jobs/p2/cancel 返回 500", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
