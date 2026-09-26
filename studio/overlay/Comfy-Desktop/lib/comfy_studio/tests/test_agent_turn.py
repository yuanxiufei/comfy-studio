"""一轮对话的取消、并行与重试行为。

全部用假件（假 hub + 假模型 + 本地 aiohttp 测试服务），不起 MCP 子进程——这些是宿主
内部的行为，用假件才能精确摆出"工具跑到一半被取消""后发的先回"这种局面；
"真的跑起来"那部分归 ``test_host_e2e``。
"""

from __future__ import annotations

import asyncio
import json
import unittest
from functools import partial
from typing import Any
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestServer

from comfy_studio.agent import (
    AgentSession,
    ChatMessage,
    LLMConfig,
    LLMError,
    OpenAIChatClient,
    ToolCall,
)
from comfy_studio.cancel import CancelToken, Cancelled, race
from comfy_studio.mcp import McpHub, McpServerConfig, McpStdioClient, McpTool
from comfy_studio.server import DEFAULT_SESSION, StudioHost
from comfy_studio.skills import SkillCatalog


def _tool(name: str) -> McpTool:
    return McpTool(server="fake", name=name, description=f"假工具 {name}", input_schema={"type": "object"})


def _wants(*names: str) -> ChatMessage:
    """造一条"模型要这几个工具"的 assistant 消息。"""
    return ChatMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id=f"call_{index}", name=name, arguments={}) for index, name in enumerate(names)],
    )


def _text(value: str) -> dict[str, Any]:
    """MCP 的 ``tools/call`` 结果形状。"""
    return {"content": [{"type": "text", "text": value}]}


class FakeHub:
    """只实现 AgentSession 用到的那一小块：``call_tool``。

    ``behaviour`` 是 ``{工具名: 异步函数 (arguments, cancel) -> 结果}``。顺带记下并发
    高水位，用来验证"真的并行"而不是串着等。
    """

    def __init__(self, behaviour: dict[str, Any] | None = None) -> None:
        self.behaviour = behaviour or {}
        self.started: list[str] = []
        self.live = 0
        self.high_water = 0

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel: Any = None
    ) -> dict[str, Any]:
        self.started.append(name)
        self.live += 1
        self.high_water = max(self.high_water, self.live)
        try:
            return await self.behaviour[name](arguments, cancel)
        finally:
            self.live -= 1


class ScriptedLLM:
    """按脚本吐回复的假模型；脚本用完了就报错（测试里不该走到那一步）。"""

    def __init__(self, *replies: ChatMessage) -> None:
        self.replies = list(replies)

    async def close(self) -> None:
        # AgentSession.close() 会关客户端；假模型没有连接要关，但方法得在。
        return None

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        cancel: CancelToken | None = None,
        on_retry: Any = None,
    ) -> ChatMessage:
        if not self.replies:
            raise LLMError(f"假模型没有更多回复了（历史 {len(messages)} 条）")
        return self.replies.pop(0)


class TurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_mid_tool_keeps_history_paired(self):
        """工具跑到一半被取消：每个 tool_call 都要补上结果，会话还能接着用。

        这是取消里最容易做错的一步——OpenAI 的形状要求 assistant 的每个 tool_call
        都有对应的 tool 消息，缺一条下一轮请求就是非法的。
        """
        both_started = asyncio.Event()

        async def hang(_arguments: dict[str, Any], cancel: Any) -> dict[str, Any]:
            if len(hub.started) >= 2:
                both_started.set()
            # 与 McpStdioClient._request 一样靠 race 放弃，令牌才真的拦得住它
            await race(partial(asyncio.sleep, 30), cancel, what="假工具")
            return _text("来晚了")

        hub = FakeHub({"a": hang, "b": hang})
        session = AgentSession(
            hub, [_tool("a"), _tool("b")], llm=ScriptedLLM(_wants("a", "b")), max_steps=2, max_parallel_tools=2
        )
        events: list[dict[str, Any]] = []

        async def on_event(event: Any) -> None:
            events.append(event.to_json())

        cancel = CancelToken()
        turn = asyncio.create_task(session.ask("两个一起跑", on_event, cancel))
        await asyncio.wait_for(both_started.wait(), timeout=5)
        cancel.cancel("用户中止")
        with self.assertRaises(Cancelled):
            await asyncio.wait_for(turn, timeout=5)

        self.assertEqual([m.role for m in session.messages], ["system", "user", "assistant", "tool", "tool"])
        call_ids = [call.id for call in session.messages[2].tool_calls]
        self.assertEqual([m.tool_call_id for m in session.messages[3:]], call_ids)
        for message in session.messages[3:]:
            self.assertTrue(str(message.content).startswith("ERROR: 用户中止"), message.content)
        # 两个工具都收到了 tool_result 事件，界面上的卡片不会一直转圈
        self.assertEqual(len([e for e in events if e["type"] == "tool_result"]), 2)

    async def test_not_dispatched_calls_also_get_results(self):
        """并发上限 1 时取消：没派出去的那个也要补结果，不能只在历史里留个空的 tool_call。"""
        first_started = asyncio.Event()

        async def hang(_arguments: dict[str, Any], cancel: Any) -> dict[str, Any]:
            first_started.set()
            await race(partial(asyncio.sleep, 30), cancel, what="假工具")
            return _text("来晚了")

        hub = FakeHub({"a": hang, "b": hang})
        session = AgentSession(
            hub, [_tool("a"), _tool("b")], llm=ScriptedLLM(_wants("a", "b")), max_steps=2, max_parallel_tools=1
        )
        cancel = CancelToken()
        turn = asyncio.create_task(session.ask("两个一起跑", None, cancel))
        await asyncio.wait_for(first_started.wait(), timeout=5)
        cancel.cancel("用户中止")
        with self.assertRaises(Cancelled):
            await asyncio.wait_for(turn, timeout=5)

        self.assertEqual(hub.started, ["a"])  # b 压根没派出去
        tools = [m for m in session.messages if m.role == "tool"]
        self.assertEqual(len(tools), 2)
        self.assertIn("已中止", str(tools[0].content))
        self.assertIn("未执行", str(tools[1].content))

    async def test_parallel_tools_run_concurrently_and_commit_in_model_order(self):
        """三个工具并行跑（上限 2），但落账顺序必须是**模型给的顺序**，不是完成顺序。"""

        async def slow(_arguments: dict[str, Any], _cancel: Any) -> dict[str, Any]:
            await asyncio.sleep(0.08)
            return _text("慢的那条")

        async def quick(_arguments: dict[str, Any], _cancel: Any) -> dict[str, Any]:
            await asyncio.sleep(0.01)
            return _text("快的那条")

        hub = FakeHub({"slow": slow, "quick": quick, "mid": quick})
        session = AgentSession(
            hub,
            [_tool("slow"), _tool("quick"), _tool("mid")],
            llm=ScriptedLLM(_wants("slow", "quick", "mid"), ChatMessage(role="assistant", content="好了")),
            max_parallel_tools=2,
        )
        answer = await session.ask("三个一起来")

        self.assertEqual(answer, "好了")
        # 高水位正好等于上限：既真的并行了（>1），也没超过上限
        self.assertEqual(hub.high_water, 2)
        self.assertEqual(hub.started[:2], ["slow", "quick"])
        tools = [m for m in session.messages if m.role == "tool"]
        self.assertEqual([str(m.content) for m in tools], ["慢的那条", "快的那条", "快的那条"])


def _ok(text: str = "好的") -> str:
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]})


class RetryTests(unittest.IsolatedAsyncioTestCase):
    """重试策略打在真的 aiohttp 上（本地测试服务）：验退避、Retry-After 与不可重试分类。"""

    async def asyncSetUp(self) -> None:
        self.requests = 0
        self.script: list[tuple[int, str, dict[str, str]]] = []
        app = web.Application()
        app.router.add_post("/v1/chat/completions", self._completions)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = OpenAIChatClient(
            LLMConfig(base_url=f"{self.server.make_url('/v1')}".rstrip("/"), model="fake", timeout=3.0)
        )

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.close()

    def _queue(self, status: int, body: str, headers: dict[str, str] | None = None) -> None:
        self.script.append((status, body, headers or {}))

    async def _completions(self, _request: web.Request) -> web.Response:
        self.requests += 1
        status, body, headers = self.script.pop(0) if self.script else (200, _ok(), {})
        if status == 0:  # 挂着不回：用来验取消能把在飞的请求真的断掉
            await asyncio.sleep(2)
        return web.Response(status=status, text=body, headers=headers)

    async def _ask(self, on_retry: Any = None) -> ChatMessage:
        return await self.client.complete([ChatMessage(role="user", content="在吗")], on_retry=on_retry)

    async def test_retries_server_errors_then_succeeds(self) -> None:
        self._queue(500, "boom")
        self._queue(503, "still down")
        seen: list[tuple[int, int, float, str]] = []

        async def on_retry(attempt: int, total: int, delay: float, reason: str) -> None:
            seen.append((attempt, total, delay, reason))

        reply = await self._ask(on_retry)

        self.assertEqual(self.requests, 3)
        self.assertEqual(reply.content, "好的")
        self.assertEqual([entry[0] for entry in seen], [1, 2])
        self.assertEqual([entry[1] for entry in seen], [5, 5])
        self.assertTrue(all(entry[2] > 0 for entry in seen), seen)
        self.assertIn("500", seen[0][3])
        self.assertIn("503", seen[1][3])

    async def test_honours_retry_after_header(self) -> None:
        self._queue(429, "slow down", {"Retry-After": "0.01"})
        seen: list[tuple[int, int, float, str]] = []

        async def on_retry(attempt: int, total: int, delay: float, reason: str) -> None:
            seen.append((attempt, total, delay, reason))

        await self._ask(on_retry)

        self.assertEqual(self.requests, 2)
        # 服务端说了等 0.01 秒就听它的，不再叠我们自己的退避
        self.assertEqual(seen[0][2], 0.01)

    async def test_auth_error_is_not_retried(self) -> None:
        self._queue(401, "bad key")
        with self.assertRaises(LLMError) as caught:
            await self._ask()
        self.assertEqual(self.requests, 1)
        self.assertFalse(caught.exception.retryable)

    async def test_empty_answer_is_retried(self) -> None:
        self._queue(200, json.dumps({"choices": [{"message": {"role": "assistant", "content": ""}}]}))
        reply = await self._ask()
        self.assertEqual(self.requests, 2)
        self.assertEqual(reply.content, "好的")

    async def test_cancel_aborts_in_flight_request(self) -> None:
        """取消要**真的断开**在飞的 HTTP 请求，而不是只把结果丢掉。"""
        self._queue(0, "")  # 挂着不回
        cancel = CancelToken()
        turn = asyncio.create_task(
            self.client.complete([ChatMessage(role="user", content="在吗")], cancel=cancel)
        )
        await asyncio.sleep(0.05)  # 让它真的把请求发出去
        cancel.cancel()
        with self.assertRaises(Cancelled):
            await asyncio.wait_for(turn, timeout=2)


class AbandonTests(unittest.IsolatedAsyncioTestCase):
    """``_abandon`` 是白盒：只是为了钉住发给引擎的那条通知的**形状**。

    MCP 的 ``notifications/cancelled`` 要带 ``requestId`` 才能对上号，写错了不会报错、
    只会静默地停不掉对面的活——所以值一份直接的断言。
    """

    async def test_abandon_sends_cancelled_notification(self) -> None:
        client = McpStdioClient(McpServerConfig(name="fake", command="python"))
        sent: list[tuple[str, dict[str, Any]]] = []

        async def fake_notify(method: str, params: dict[str, Any]) -> None:
            sent.append((method, params))

        with mock.patch.object(client, "_notify", fake_notify):
            client._proc = mock.Mock(returncode=None)
            client._pending[7] = asyncio.get_running_loop().create_future()
            await client._abandon(7, "tools/call", "客户端取消")

        self.assertEqual(
            sent, [("notifications/cancelled", {"requestId": 7, "reason": "tools/call: 客户端取消"})]
        )
        self.assertNotIn(7, client._pending)

    async def test_abandon_is_quiet_when_process_is_gone(self) -> None:
        """进程已经死了就别再往管道里写：发不出去不该盖掉真正的原因（取消/超时）。"""
        client = McpStdioClient(McpServerConfig(name="fake", command="python"))
        client._proc = mock.Mock(returncode=1)
        await client._abandon(8, "tools/call", "客户端取消")
        self.assertNotIn(8, client._pending)


class _Ctx:
    """RPC 上下文的最小替身：``agent_chat`` 只用到 ``emit``。"""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, method: str, params: dict[str, Any]) -> None:
        self.events.append({"method": method, "params": params})


class ServerCancelTests(unittest.IsolatedAsyncioTestCase):
    """RPC 层（面板真正打的那一层）的取消口径。

    :class:`AgentSession` 自己的取消已由 :class:`TurnTests` 钉住；这里钉的是上层三件事：
    取消后 ``agent/chat`` 怎么**正常**作答、``agent/cancel`` 幂等、宿主退出（面板把 stdin
    关掉）时不会等在飞的一轮上——那一轮最长能等到工具的 1800 秒超时上。
    """

    def _host(self, session: AgentSession) -> StudioHost:
        hub = McpHub([])  # 这里不连引擎：会话是直接塞进去的
        host = StudioHost(hub, SkillCatalog(hub))
        host._sessions[DEFAULT_SESSION] = session
        return host

    def _slow_session(self, started: asyncio.Event) -> AgentSession:
        async def hang(_arguments: dict[str, Any], cancel: Any) -> dict[str, Any]:
            started.set()
            await race(partial(asyncio.sleep, 30), cancel, what="假工具")
            return _text("来晚了")

        hub = FakeHub({"slow": hang})
        return AgentSession(
            hub,
            [_tool("slow")],
            llm=ScriptedLLM(_wants("slow"), ChatMessage(role="assistant", content="不该走到这里")),
            max_steps=2,
        )

    async def test_cancel_answers_cancelled_and_the_session_keeps_going(self) -> None:
        started = asyncio.Event()
        session = self._slow_session(started)
        host = self._host(session)
        ctx = _Ctx()

        turn = asyncio.create_task(host.agent_chat({"text": "跑个慢活"}, ctx))
        await asyncio.wait_for(started.wait(), timeout=5)

        self.assertEqual(
            host.agent_cancel({"session_id": DEFAULT_SESSION}, _Ctx()),
            {"session_id": DEFAULT_SESSION, "cancelled": True},
        )
        result = await asyncio.wait_for(turn, timeout=5)

        # 取消是**正常**结果（不是 -32603）：面板据此把气泡收成"已停止"
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["session_id"], DEFAULT_SESSION)
        self.assertTrue(result["reason"], "停下时得带一句理由，面板要显示")
        self.assertEqual(host._turns, {}, "跑完的轮次不能留在在飞表里")
        # 历史仍然配对，所以同一会话可以直接接着问
        self.assertEqual([m.role for m in session.messages], ["system", "user", "assistant", "tool"])
        self.assertTrue(str(session.messages[-1].content).startswith("ERROR: "), session.messages[-1].content)

        session.llm = ScriptedLLM(ChatMessage(role="assistant", content="接着说"))
        again = await asyncio.wait_for(host.agent_chat({"text": "接着说"}, ctx), timeout=5)
        self.assertEqual(again, {"session_id": DEFAULT_SESSION, "text": "接着说", "cancelled": False})

    async def test_cancel_is_idempotent_when_nothing_is_running(self) -> None:
        host = self._host(self._slow_session(asyncio.Event()))
        self.assertEqual(
            host.agent_cancel({}, _Ctx()), {"session_id": DEFAULT_SESSION, "cancelled": False}
        )

    async def test_close_stops_an_in_flight_turn(self) -> None:
        """面板退出时不能等在飞的一轮上：``close`` 先叫停，这一轮立刻收敛。"""
        started = asyncio.Event()
        session = self._slow_session(started)
        host = self._host(session)
        ctx = _Ctx()

        turn = asyncio.create_task(host.agent_chat({"text": "跑个慢活"}, ctx))
        await asyncio.wait_for(started.wait(), timeout=5)

        await asyncio.wait_for(host.close(), timeout=5)
        result = await asyncio.wait_for(turn, timeout=5)

        self.assertTrue(result["cancelled"])
        self.assertIn("宿主退出", result["reason"])
        self.assertEqual(host._sessions, {})
        self.assertEqual(host._turns, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
