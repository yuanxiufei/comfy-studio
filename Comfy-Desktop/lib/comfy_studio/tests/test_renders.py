"""宿主侧渲染目录层（``comfy_studio.renders``）的单元测试。

引擎**不必在运行**：这里拿一个记下调用参数的假 hub 顶住 :class:`McpHub`，把"读进来的结构
对不对、错误算哪一族、参数有没有原样搬过去"钉死。真跨进程那条在 ``test_host_e2e.py``
（它 spawn 真的引擎 MCP server，**顺带就能验出工具名写错**）。

跑法::

    cd Comfy-Desktop/lib
    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest discover -s comfy_studio/tests
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from typing import Any

from comfy_studio.mcp.client import McpTool
from comfy_studio.mcp.config import ENGINE_SERVER_NAME
from comfy_studio.renders import LIST_RENDERS_TOOL, RENDER_TOOL, RenderCatalog, RendersError
from comfy_studio.rpc import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from comfy_studio.server import StudioHost
from comfy_studio.skills import SkillCatalog, SkillsError

#: 一条**真形状**的目标（键名照引擎 ``RenderTarget.to_json`` + ``render_listing`` 补的 file_exists）。
TARGET = {
    "id": "video-draft",
    "title": "视频试片",
    "description": "试片：先花小钱看运镜对不对",
    "file": "08_视频试片.json",
    "tags": ["视频"],
    "params": [
        {"name": "prompt", "type": "string", "required": True, "default": None, "description": "提示词"},
    ],
    "file_exists": False,
}


def _listing(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"workflows_dir": "D:/workflows", "note": None, "targets": [dict(TARGET)]}
    payload.update(overrides)
    return payload


def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    """MCP ``tools/call`` 的返回形状（见 ``mcp/result.py`` 的文件头）。"""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


class FakeHub:
    """只实现渲染目录用到的两件事：``tools`` 与 ``call_tool``。"""

    def __init__(
        self,
        result: Any = None,
        *,
        tools: tuple[str, ...] = (LIST_RENDERS_TOOL, RENDER_TOOL),
    ) -> None:
        self.tools = [
            McpTool(server=ENGINE_SERVER_NAME, name=name, description="", input_schema={})
            for name in tools
        ]
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any], cancel: Any = None) -> Any:
        self.calls.append((name, arguments))
        return self.result


def _filled(payload: dict[str, Any]) -> RenderCatalog:
    """用一份清单把目录填好（省得每个用例都写一遍 asyncio.run）。"""
    catalog = RenderCatalog(FakeHub(_tool_result(payload)))  # type: ignore[arg-type]
    asyncio.run(catalog.refresh())
    return catalog


class RefreshTests(unittest.TestCase):
    def test_listing_is_read_through_with_the_directory_and_the_note(self) -> None:
        """引擎报的工作流目录与那句"目录不在"的解释都要一路上来（面板就靠它说明白）。"""
        hub = FakeHub(
            _tool_result(_listing(note="这个目录不存在；可以用 COMFY_STUDIO_WORKFLOWS_DIR 指定它"))
        )
        catalog = RenderCatalog(hub)  # type: ignore[arg-type]
        targets = asyncio.run(catalog.refresh())
        self.assertEqual([t.id for t in targets], ["video-draft"])
        self.assertEqual(catalog.workflows_dir, "D:/workflows")
        self.assertIn("COMFY_STUDIO_WORKFLOWS_DIR", catalog.note or "")
        # 请求本身是"空参数调 comfy_list_renders"
        self.assertEqual(hub.calls, [(f"{ENGINE_SERVER_NAME}__{LIST_RENDERS_TOOL}", {})])

    def test_a_missing_workflow_file_is_kept_as_a_lie_detector(self) -> None:
        """``file_exists=False`` 不许被默认成 True —— 那正是"假装这张能跑"。

        它一路要到面板上（``fileExists``），所以这里对着 to_json 也断言一次。
        """
        catalog = _filled(_listing())
        self.assertIs(catalog.get("video-draft").file_exists, False)
        self.assertIs(catalog.get("video-draft").to_json()["fileExists"], False)

    def test_contract_drift_is_loud(self) -> None:
        """引擎回的**结构**不对就报错，不静默兜底成空表/空目录。

        每种错法都单独断言过：面板上"没有目标"与"接口读坏了"必须是两句不同的话。
        """
        cases = {
            "不是对象": [1, 2],
            "workflows_dir": _listing(workflows_dir=None),
            "note": _listing(note=7),
            "targets": _listing(targets={"video-draft": TARGET}),
            "file_exists": _listing(targets=[{**TARGET, "file_exists": None}]),
            "重复": _listing(targets=[dict(TARGET), dict(TARGET)]),
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(RendersError) as caught:
                    asyncio.run(RenderCatalog(FakeHub(_tool_result(payload))).refresh())  # type: ignore[arg-type]
                self.assertIn(LIST_RENDERS_TOOL, str(caught.exception))

    def test_param_shape_is_the_skill_one(self) -> None:
        """参数形状走的是 skills 那份解析器：键名与 skill 逐字相同，面板只认一套字段。"""
        param = _filled(_listing()).get("video-draft").to_json()["params"][0]
        self.assertEqual(
            set(param), {"name", "type", "required", "default", "description", "hasDefault"}
        )

    def test_param_shape_drift_is_loud_too(self) -> None:
        """参数缺字段（引擎那边形状变了）也要响，不能静静少一个键。"""
        with self.assertRaises(RendersError):
            _filled(_listing(targets=[{**TARGET, "params": [{"name": "prompt"}]}]))


class LookupTests(unittest.TestCase):
    def test_before_refresh_it_says_to_refresh(self) -> None:
        catalog = RenderCatalog(FakeHub(_tool_result(_listing())))  # type: ignore[arg-type]
        with self.assertRaises(RendersError) as caught:
            catalog.get("video-draft")
        self.assertIn("refresh", str(caught.exception))

    def test_unknown_target_lists_the_ones_we_have(self) -> None:
        with self.assertRaises(RendersError) as caught:
            _filled(_listing()).get("看板")
        self.assertIn("video-draft", str(caught.exception))

    def test_missing_tool_names_the_server_and_the_alternative(self) -> None:
        """引擎没这把工具时要说清是哪个 server、手里有哪些 —— 别回一张空表。"""
        hub = FakeHub(_tool_result(_listing()), tools=("comfy_run_skill",))
        with self.assertRaises(RendersError) as caught:
            asyncio.run(RenderCatalog(hub).refresh())  # type: ignore[arg-type]
        self.assertIn(ENGINE_SERVER_NAME, str(caught.exception))
        self.assertIn("comfy_run_skill", str(caught.exception))

    def test_empty_hub_says_the_server_is_not_started(self) -> None:
        """一个工具都没有是最常见的启动期事故；说法要与 skills 那边**逐字一致**。"""
        empty = FakeHub(_tool_result(_listing()), tools=())
        with self.assertRaises(RendersError) as caught:
            asyncio.run(RenderCatalog(empty).refresh())  # type: ignore[arg-type]
        self.assertIn("MCP server 还没 start()", str(caught.exception))

        # skills 那边走的是同一个解析器（resolve_tool）：两处口径必须一样 —— 这条就是那次
        # 收拢的守卫，谁再把 _tool 抄一份、话就散了。
        with self.assertRaises(SkillsError) as skills_caught:
            SkillCatalog(empty)._tool(LIST_RENDERS_TOOL)  # type: ignore[arg-type]
        self.assertEqual(str(skills_caught.exception), str(caught.exception))


class RunTests(unittest.TestCase):
    def _ran(self, result: Any, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        hub = FakeHub(_tool_result(_listing()))
        catalog = RenderCatalog(hub)  # type: ignore[arg-type]
        asyncio.run(catalog.refresh())  # 先有目录
        hub.result = result  # refresh 之后换成**这一跑**的结果
        hub.calls.clear()
        run = asyncio.run(catalog.run("video-draft", {"prompt": "一只猫"}, **kwargs))
        _name, arguments = hub.calls[0]
        return run, arguments

    def test_every_argument_is_carried_over_as_the_engine_wants_it(self) -> None:
        """``images`` 是 Path 也搬成字符串、``output_dir`` 同理：引擎收的是路径字符串。"""
        images = [Path("D:/material/first.png"), Path("D:/material/last.png")]
        out = Path("D:/out/shot-001")
        run, arguments = self._ran(
            _tool_result({"target": "video-draft", "notes": ["时长按图上帧数折算"]}),
            images=images,
            duration_sec=5,
            output_dir=out,
        )
        self.assertFalse(run.is_error)
        self.assertEqual(run.target_id, "video-draft")
        self.assertEqual(
            arguments,
            {
                "target_id": "video-draft",
                "params": {"prompt": "一只猫"},
                # 期望值自己走一遍 str()：Windows 上 Path 会规整成反斜杠，写死正斜杠只会在
                # 一台机器上绿。
                "images": [str(path) for path in images],
                "duration_sec": 5,
                "output_dir": str(out),
            },
        )
        # 组装期的让步在 data 里带着走（面板照原样显示）
        self.assertEqual(run.data["notes"], ["时长按图上帧数折算"])

    def test_unspecified_optionals_are_not_sent_at_all(self) -> None:
        """没给的项就不出现在参数里：引擎那边"没给"与"给了空值"是两件事。"""
        _run, arguments = self._ran(_tool_result({"target": "video-draft"}))
        self.assertEqual(set(arguments), {"target_id", "params"})

    def test_a_tool_error_is_a_result_not_an_exception(self) -> None:
        """显存不够这种**执行**失败落在 ``is_error`` 上（面板照原样显示），不当协议错误。"""
        run, _arguments = self._ran(_tool_result("CUDA out of memory", is_error=True))
        self.assertTrue(run.is_error)
        self.assertIn("out of memory", run.text)

    def test_the_host_does_not_second_guess_the_engines_rules(self) -> None:
        """时长 0 这种**规则**问题由引擎挡（组装期唯一说了算的地方），宿主不拦、原样搬过去。

        宿主拦一道就等于规则有了两份：两边哪天不一致，面板看到的说法会随路径变。
        """
        run, arguments = self._ran(_tool_result("时长要正数", is_error=True), duration_sec=0)
        self.assertEqual(arguments["duration_sec"], 0)
        self.assertTrue(run.is_error, "拦不拦是引擎的事，但结果该怎么显示还是怎么显示")


class HostRpcTests(unittest.IsolatedAsyncioTestCase):
    """``renders/list`` 与 ``renders/run`` 这两条 RPC（面板真正打的入口）。"""

    def _host(self, *, mounted: bool, result: Any = None) -> tuple[StudioHost, FakeHub]:
        hub = FakeHub(result)
        host = StudioHost(
            hub,  # type: ignore[arg-type]
            SkillCatalog(hub),  # type: ignore[arg-type]
            renders=RenderCatalog(hub) if mounted else None,  # type: ignore[arg-type]
        )
        return host, hub

    async def test_list_reports_directory_note_and_targets(self) -> None:
        host, _hub = self._host(mounted=True, result=_tool_result(_listing()))
        payload = await host.renders_list({}, None)  # type: ignore[arg-type]
        self.assertEqual(payload["workflows_dir"], "D:/workflows")
        self.assertIsNone(payload["note"])
        self.assertEqual([t["id"] for t in payload["targets"]], ["video-draft"])
        self.assertIs(payload["targets"][0]["fileExists"], False)

    async def test_not_mounted_says_so_instead_of_an_empty_table(self) -> None:
        """宿主没挂渲染目录时明说 —— 空表会被读成"这台机器没配任何目标"。"""
        host, _hub = self._host(mounted=False)
        with self.assertRaises(RpcError) as caught:
            await host.renders_list({}, None)  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, INTERNAL_ERROR)
        self.assertIn("渲染目录", str(caught.exception))

    async def test_run_needs_a_target_id(self) -> None:
        host, _hub = self._host(mounted=True)
        with self.assertRaises(RpcError) as caught:
            await host.renders_run({}, None)  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, INVALID_PARAMS)

    async def test_run_rejects_an_images_string(self) -> None:
        """只给一条字符串是最常见的手滑：当场按参数错误挡掉，不送进引擎去跑。"""
        host, _hub = self._host(mounted=True)
        with self.assertRaises(RpcError) as caught:
            await host.renders_run({"target_id": "video-draft", "images": "a.png"}, None)  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, INVALID_PARAMS)

    async def test_run_rejects_a_non_numeric_duration_and_a_blank_output_dir(self) -> None:
        host, _hub = self._host(mounted=True)
        for args in ({"duration_sec": "5"}, {"output_dir": "  "}):
            with self.subTest(args=args):
                with self.assertRaises(RpcError) as caught:
                    await host.renders_run({"target_id": "video-draft", **args}, None)  # type: ignore[arg-type]
                self.assertEqual(caught.exception.code, INVALID_PARAMS)

    async def test_unknown_target_is_a_param_error_that_lists_the_alternatives(self) -> None:
        host, _hub = self._host(mounted=True, result=_tool_result(_listing()))
        await host.renders_list({}, None)  # type: ignore[arg-type]
        with self.assertRaises(RpcError) as caught:
            await host.renders_run({"target_id": "看板"}, None)  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, INVALID_PARAMS)
        self.assertIn("video-draft", str(caught.exception))

    async def test_a_successful_run_comes_back_as_the_run_json(self) -> None:
        host, hub = self._host(mounted=True, result=_tool_result(_listing()))
        await host.renders_list({}, None)  # type: ignore[arg-type]
        hub.result = _tool_result({"target": "video-draft"})
        payload = await host.renders_run({"target_id": "video-draft", "params": {"prompt": "x"}}, None)  # type: ignore[arg-type]
        self.assertEqual(payload["target_id"], "video-draft")
        self.assertIs(payload["isError"], False)


if __name__ == "__main__":
    unittest.main()
