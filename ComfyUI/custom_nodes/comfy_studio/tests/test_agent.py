"""agent 层：对话循环、工具结果的压缩、模型客户端的解析与报错。"""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from ..agent import (
    AgentError,
    AgentSession,
    LLMConfig,
    LLMError,
    OpenAIChatClient,
    tool_result_text,
    tool_schemas,
)
from ..agent.types import ChatMessage, ToolCall, user_message
from ..mcp.tools import Tool, error_result, text_result
from .support import FakeEngine, FakeLLM, record_events


def echo_tool(sink: list[dict[str, Any]] | None = None) -> Tool:
    async def handler(args: dict[str, Any]) -> Any:
        if sink is not None:
            sink.append(args)
        return text_result({"echo": args.get("text")})

    return Tool(name="echo", description="回显", input_schema={"type": "object", "properties": {}}, handler=handler)


def reply(text: str = "") -> ChatMessage:
    return ChatMessage(role="assistant", content=text)


def tool_reply(msg_id: str, name: str, arguments: dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id=msg_id, name=name, arguments=arguments)],
    )


class ToolResultTextTest(unittest.TestCase):
    def test_strings_pass_through(self) -> None:
        self.assertEqual(tool_result_text("纯文本"), "纯文本")

    def test_mcp_content_blocks_are_joined(self) -> None:
        result = {"content": [{"type": "text", "text": "第一段"}, {"type": "text", "text": "第二段"}]}
        self.assertEqual(tool_result_text(result), "第一段\n第二段")

    def test_is_error_is_marked_for_the_model(self) -> None:
        self.assertEqual(tool_result_text(error_result(ValueError("坏了"))), "ERROR: ValueError: 坏了")

    def test_other_shapes_are_dumped_as_json(self) -> None:
        self.assertEqual(tool_result_text({"ok": True}), '{"ok": true}')
        self.assertIn("content", tool_result_text({"content": []}))


class ToolSchemasTest(unittest.TestCase):
    def test_follows_the_openai_function_shape(self) -> None:
        schemas = tool_schemas([echo_tool()])
        self.assertEqual(schemas[0]["type"], "function")
        function = schemas[0]["function"]
        self.assertEqual(function["name"], "echo")
        self.assertEqual(function["description"], "回显")
        self.assertEqual(function["parameters"]["type"], "object")


class AgentSessionTest(unittest.IsolatedAsyncioTestCase):
    def session(self, replies: list[Any], tools: list[Tool] | None = None, max_steps: int = 8) -> AgentSession:
        self.llm = FakeLLM(replies)
        return AgentSession(FakeEngine(), tools if tools is not None else [echo_tool()], self.llm, max_steps=max_steps)

    async def test_plain_answer_needs_no_tool(self) -> None:
        session = self.session([reply("你好")])
        events: list[str] = []
        self.assertEqual(await session.ask("在吗", record_events(events)), "你好")
        self.assertEqual(events, ["final"])
        self.assertEqual([m.role for m in session.messages], ["system", "user", "assistant"])
        self.assertEqual(session.messages[1].content, "在吗")

    async def test_tool_call_is_executed_and_fed_back(self) -> None:
        seen: list[dict[str, Any]] = []
        session = self.session(
            [tool_reply("c1", "echo", {"text": "hi"}), reply("说完了")],
            tools=[echo_tool(seen)],
        )
        events: list[str] = []
        self.assertEqual(await session.ask("帮我回显", record_events(events)), "说完了")

        self.assertEqual(seen, [{"text": "hi"}])
        self.assertEqual(events, ["tool_call", "tool_result", "final"])
        roles = [m.role for m in session.messages]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        tool_message = session.messages[3]
        self.assertEqual(tool_message.tool_call_id, "c1")
        self.assertEqual(tool_message.name, "echo")
        self.assertIn('"echo": "hi"', tool_message.content)
        # 第二轮请求里必须带上那条 tool 消息，模型才知道工具跑出什么
        self.assertEqual(self.llm.calls[1][-1].role, "tool")

    async def test_unknown_tool_is_reported_to_the_model(self) -> None:
        session = self.session([tool_reply("c1", "ghost", {}), reply("知道了")])
        self.assertEqual(await session.ask("用 ghost", None), "知道了")
        self.assertTrue(session.messages[3].content.startswith("ERROR: 没有工具 ghost"))

    async def test_failing_tool_does_not_break_the_turn(self) -> None:
        async def boom(_args: dict[str, Any]) -> Any:
            raise ValueError("炸了")

        bad = Tool(name="bad", description="会炸", input_schema={"type": "object", "properties": {}}, handler=boom)
        session = self.session([tool_reply("c1", "bad", {}), reply("那我换个办法")], tools=[bad])
        self.assertEqual(await session.ask("试试", None), "那我换个办法")
        self.assertEqual(session.messages[3].content, "ERROR: ValueError: 炸了")

    async def test_tool_error_result_is_flagged_too(self) -> None:
        async def failing(_args: dict[str, Any]) -> Any:
            return error_result(RuntimeError("引擎不在"))

        tool = Tool(name="f", description="f", input_schema={"type": "object", "properties": {}}, handler=failing)
        session = self.session([tool_reply("c1", "f", {}), reply("好")], tools=[tool])
        await session.ask("跑", None)
        self.assertTrue(session.messages[3].content.startswith("ERROR:"))

    async def test_running_out_of_steps_is_explicit(self) -> None:
        session = self.session([tool_reply("c1", "echo", {}), tool_reply("c2", "echo", {})], max_steps=2)
        with self.assertRaises(AgentError) as ctx:
            await session.ask("一直调工具", None)
        self.assertIn("轮之内", str(ctx.exception))

    async def test_reset_keeps_only_the_system_prompt(self) -> None:
        session = self.session([reply("你好")])
        await session.ask("在吗", None)
        session.reset()
        self.assertEqual([m.role for m in session.messages], ["system"])

    async def test_close_closes_the_model_client(self) -> None:
        session = self.session([reply("你好")])
        await session.close()
        self.assertIs(self.llm.closed, True)


class LLMConfigTest(unittest.TestCase):
    def test_missing_model_is_reported_by_name(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMError) as ctx:
                LLMConfig.from_env()
        self.assertIn("COMFY_STUDIO_LLM_MODEL", str(ctx.exception))

    def test_defaults_and_openai_fallbacks(self) -> None:
        with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "qwen"}, clear=True):
            config = LLMConfig.from_env()
            self.assertEqual(config.base_url, "https://api.openai.com/v1")
            self.assertIsNone(config.api_key)

        with mock.patch.dict(
            os.environ,
            {
                "COMFY_STUDIO_LLM_MODEL": "qwen",
                "OPENAI_BASE_URL": "http://127.0.0.1:11434/v1/",
                "OPENAI_API_KEY": "from-openai",
            },
            clear=True,
        ):
            config = LLMConfig.from_env()
            self.assertEqual(config.base_url, "http://127.0.0.1:11434/v1", "尾部的斜杠要被去掉")
            self.assertEqual(config.api_key, "from-openai")

    def test_studio_specific_env_wins(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "COMFY_STUDIO_LLM_MODEL": "qwen",
                "COMFY_STUDIO_LLM_BASE_URL": "http://local/v1",
                "COMFY_STUDIO_LLM_API_KEY": "own-key",
                "OPENAI_BASE_URL": "http://ignored/v1",
                "OPENAI_API_KEY": "ignored",
            },
            clear=True,
        ):
            config = LLMConfig.from_env()
            self.assertEqual(config.base_url, "http://local/v1")
            self.assertEqual(config.api_key, "own-key")


class ChatClientTest(unittest.IsolatedAsyncioTestCase):
    """对着本地假 chat completions 服务验解析与报错，不联网。"""

    async def asyncSetUp(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: list[tuple[int, Any]] = []

        async def handler(request: web.Request) -> web.Response:
            self.requests.append({"headers": dict(request.headers), "body": await request.json()})
            status, payload = self.responses.pop(0)
            if isinstance(payload, str):
                return web.Response(status=status, text=payload, content_type="text/plain")
            return web.json_response(payload, status=status)

        app = web.Application()
        app.router.add_post("/v1/chat/completions", handler)
        self.server = TestClient(TestServer(app))
        await self.server.start_server()
        self.client = OpenAIChatClient(
            LLMConfig(base_url=str(self.server.make_url("/v1")).rstrip("/"), model="fake", api_key="secret")
        )

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.close()

    def script(self, message: dict[str, Any], status: int = 200) -> None:
        self.responses.append((status, {"choices": [{"index": 0, "message": message}]}))

    async def test_payload_and_authorization_header(self) -> None:
        self.script({"role": "assistant", "content": "你好"})
        tools = [{"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}]
        result = await self.client.complete([user_message("在吗")], tools)

        self.assertEqual(result.content, "你好")
        self.assertEqual(result.tool_calls, [])
        sent = self.requests[0]
        self.assertEqual(sent["body"]["model"], "fake")
        self.assertEqual(sent["body"]["messages"], [{"role": "user", "content": "在吗"}])
        self.assertEqual(sent["body"]["tools"], tools)
        self.assertEqual(sent["body"]["tool_choice"], "auto")
        self.assertEqual(sent["headers"].get("Authorization"), "Bearer secret")

    async def test_no_tools_means_no_tools_key(self) -> None:
        self.script({"role": "assistant", "content": "好"})
        await self.client.complete([user_message("hi")])
        self.assertNotIn("tools", self.requests[0]["body"])
        self.assertNotIn("tool_choice", self.requests[0]["body"])

    async def test_tool_calls_are_parsed(self) -> None:
        self.script(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "a", "arguments": '{"n": 1}'}},
                    {"function": {"name": "b", "arguments": {"n": 2}}},
                    {"id": "c3", "function": {"name": "c", "arguments": ""}},
                ],
            }
        )
        result = await self.client.complete([user_message("hi")], [])
        self.assertEqual(result.content, "", "content 为 null 时要归一成空串")
        self.assertEqual([c.id for c in result.tool_calls], ["c1", "call_1", "c3"])
        self.assertEqual([c.arguments for c in result.tool_calls], [{"n": 1}, {"n": 2}, {}])

    async def test_http_error_is_reported_with_status(self) -> None:
        self.responses.append((500, "炸了"))
        with self.assertRaises(LLMError) as ctx:
            await self.client.complete([user_message("hi")])
        self.assertIn("500", str(ctx.exception))
        self.assertIn("炸了", str(ctx.exception))

    async def test_non_json_and_missing_choices(self) -> None:
        self.responses.append((200, "<html>不是 JSON</html>"))
        with self.assertRaises(LLMError) as ctx:
            await self.client.complete([user_message("hi")])
        self.assertIn("不是 JSON", str(ctx.exception))

        self.responses.append((200, {"choices": []}))
        with self.assertRaises(LLMError) as ctx:
            await self.client.complete([user_message("hi")])
        self.assertIn("没有 choices", str(ctx.exception))

    async def test_broken_tool_calls_are_reported(self) -> None:
        cases: list[tuple[dict[str, Any], str]] = [
            ({"function": {"name": "a", "arguments": "{不是 JSON"}}, "不是合法 JSON"),
            ({"id": "c", "function": {"arguments": "{}"}}, "没有函数名"),
            ({"id": "c", "function": {"name": "a", "arguments": 3}}, "参数类型不支持"),
        ]
        for raw, fragment in cases:
            with self.subTest(fragment):
                self.script({"role": "assistant", "content": "", "tool_calls": [raw]})
                with self.assertRaises(LLMError) as ctx:
                    await self.client.complete([user_message("hi")], [])
                self.assertIn(fragment, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
