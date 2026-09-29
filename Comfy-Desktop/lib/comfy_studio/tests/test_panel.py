"""``comfy_studio.panel`` 的单元测试（纯本地：不拉子进程、不连模型）。

跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_panel -v
"""

from __future__ import annotations

import unittest

from comfy_studio.panel import (
    CONTEXT_KEYS,
    MAX_VALUE_CHARS,
    PanelContextError,
    describe_context,
    parse_context,
)


class ParseContextTests(unittest.TestCase):
    def test_nothing_selected_is_an_empty_mapping(self) -> None:
        # 缺这个键 / 显式 null / 空对象，三者是同一个意思：面板上什么都没选。
        # **老的请求形状（只有 text 与 session_id）走的就是这一条**，所以它必须不报错。
        for value in (None, {}):
            with self.subTest(value=value):
                self.assertEqual(parse_context(value), {})

    def test_the_four_known_keys_pass_through(self) -> None:
        parsed = parse_context(
            {
                "workflow": "01_角色定妆板_Qwen2512.json",
                "workflows_dir": "D:/comfy/user/default/workflows/AIGC中国风漫剧",
                "project": "我在大唐卖奶茶",
                "novel": "长夜.txt",
            }
        )
        self.assertEqual(
            parsed,
            {
                "workflow": "01_角色定妆板_Qwen2512.json",
                "workflows_dir": "D:/comfy/user/default/workflows/AIGC中国风漫剧",
                "project": "我在大唐卖奶茶",
                "novel": "长夜.txt",
            },
        )

    def test_the_order_follows_context_keys(self) -> None:
        # 段的排版（哪一行在前）就是靠这个顺序定下来的：dict 的插入顺序等于 CONTEXT_KEYS 的顺序，
        # 与面板传过来的键序无关 —— 否则同一份选中态在两次请求里会拼出两段不一样的提示词，
        # 而"每次都一样"正是 AgentSession 不重建 messages[0]（前缀缓存）的前提。
        parsed = parse_context({"novel": "长夜.txt", "workflow": "a.json"})
        self.assertEqual(list(parsed), ["workflow", "novel"])
        self.assertEqual(CONTEXT_KEYS[:2], ("workflow", "workflows_dir"))

    def test_a_blank_value_counts_as_not_picked(self) -> None:
        self.assertEqual(parse_context({"workflow": "   ", "project": ""}), {})

    def test_values_are_trimmed(self) -> None:
        self.assertEqual(parse_context({"project": "  我在大唐卖奶茶  "}), {"project": "我在大唐卖奶茶"})

    def test_an_unknown_key_is_refused_loudly(self) -> None:
        # 打错一个键名却静默丢掉，等于"设了却不生效"：面板那边看着一切正常，模型这边什么都没有。
        with self.assertRaises(PanelContextError) as caught:
            parse_context({"workflows": "a.json"})
        self.assertIn("workflows", str(caught.exception))
        self.assertIn("workflow", str(caught.exception), "报错要说清认的是哪些键")

    def test_a_non_mapping_is_refused(self) -> None:
        for bad in ("a.json", ["a.json"], 7, True):
            with self.subTest(bad=bad):
                with self.assertRaises(PanelContextError):
                    parse_context(bad)

    def test_a_non_string_value_is_refused(self) -> None:
        # 形状对不上的值不能悄悄放过：面板那边是个字符串，这边收到 7 —— 说明中间有人改错了。
        with self.assertRaises(PanelContextError) as caught:
            parse_context({"workflow": 7})
        self.assertIn("context.workflow", str(caught.exception))

    def test_an_overlong_value_is_refused_rather_than_cut(self) -> None:
        # 截半个文件名交给模型，它会拿着半个名字去调工具，然后收到"没有这份工作流"。
        with self.assertRaises(PanelContextError) as caught:
            parse_context({"workflow": "a" * (MAX_VALUE_CHARS + 1)})
        self.assertIn(str(MAX_VALUE_CHARS), str(caught.exception))

    def test_the_boundary_value_still_passes(self) -> None:
        self.assertEqual(
            parse_context({"workflow": "a" * MAX_VALUE_CHARS}),
            {"workflow": "a" * MAX_VALUE_CHARS},
        )

    def test_the_error_says_where_it_came_from(self) -> None:
        with self.assertRaises(PanelContextError) as caught:
            parse_context(7, where="agent/chat 的 context")
        self.assertIn("agent/chat 的 context", str(caught.exception))


class DescribeContextTests(unittest.TestCase):
    def test_nothing_selected_describes_nothing(self) -> None:
        # 空串是"一段都别插"的信号：默认助手 + 没挂记忆 + 面板上没选东西时，
        # 拼出来的人设必须与 DEFAULT_SYSTEM_PROMPT 一个字不差（见 test_agents_tools.py）。
        self.assertEqual(describe_context({}), "")

    def test_it_names_each_picked_thing(self) -> None:
        text = describe_context({"workflow": "a.json", "workflows_dir": "D:/wf", "project": "我在大唐卖奶茶"})
        self.assertTrue(text.startswith("【面板上此刻选中的东西】"))
        self.assertIn("- 工作流：a.json", text)
        self.assertIn("- 工作流目录：D:/wf", text)
        self.assertIn("- 项目：我在大唐卖奶茶", text)
        self.assertNotIn("原文", text, "没选的那几样一个字都不该出现")

    def test_it_says_this_is_scenery_not_an_instruction(self) -> None:
        # 这一段最要紧的两个约束：它不是用户的话，别拿它自己开工。少了这句，
        # 面板上开着一份图就可能变成"它自己跑起来了"。
        text = describe_context({"workflow": "a.json"})
        self.assertIn("不是他对你说的话", text)
        self.assertIn("别自己拿这几样开工", text)

    def test_the_lines_keep_the_canonical_order(self) -> None:
        text = describe_context(
            {
                "novel": "长夜.txt",
                "project": "我在大唐卖奶茶",
                "workflows_dir": "D:/wf",
                "workflow": "a.json",
            }
        )
        self.assertLess(text.index("- 工作流："), text.index("- 工作流目录："))
        self.assertLess(text.index("- 工作流目录："), text.index("- 项目："))
        self.assertLess(text.index("- 项目："), text.index("- 原文："))

    def test_the_same_selection_always_reads_the_same(self) -> None:
        # 同一份选中态必须拼出逐字一样的一段：AgentSession 靠"与上一轮一样就不动 messages[0]"
        # 保住本地服务的前缀缓存，而人设是**每轮重算**的（见 agent/loop.py 的 ask）。
        picked = {"workflow": "a.json", "project": "我在大唐卖奶茶"}
        self.assertEqual(describe_context(picked), describe_context(dict(picked)))


if __name__ == "__main__":
    unittest.main()
