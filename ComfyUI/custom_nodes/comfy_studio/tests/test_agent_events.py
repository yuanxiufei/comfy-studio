"""两侧 agent 事件契约的守卫：事件名与载荷键是**跨语言**的契约，改一边漏一边不会报错。

两侧各有一份 ``agent/loop.py``，事件类型和载荷键在那儿是**硬编码的实参字面量**（不是共享
常量），而这两份东西各自喂一个消费方：

* 宿主侧的事件经 ``channel.py`` 转成 ``agent/event`` 通知，进桌面壳的 TS 面板 ——
  ``Comfy-Desktop/src/main/lib/comfyStudioChatContentScript.ts`` 的 ``onEvent`` 按 ``type``
  一支一支地分派，载荷按 ``params.text`` / ``params.id`` / ``params.name`` 取。
* 引擎侧的事件由 ``routes.py`` 直接把 ``evt.type`` 当 SSE 事件名、``evt.data`` 当数据发出去。

于是"改一边漏一边"是没有声音的：把 ``tool_result`` 改成 ``toolResult``，前端那支分派从此
不匹配 —— 界面上只是少画一块，没有异常、没有报错，**TS 那边的 vitest 也管不到 Python 的
改名**；给一边的载荷加个键、或改个键名，另一边与前端仍按老键取，``undefined`` 就这么进了
界面。这个文件盯三件事：

1. 两侧各自发出的事件类型，就是契约里那几个（多一个、少一个都报，见 ``ENGINE_`` / ``HOST_``）；
2. 同名事件的载荷键逐字相同（同一个类型在两处发的键不一样，前端只能取到一半）；
3. 上面这两条依赖的抽取（:func:`event_shapes`）**自己是不是瞎的** —— 抽不出来的形状直接报错，
   而不是少看几个构造点还照样绿（见 :class:`EventShapesSelfCheckTest`）。

清单**故意不是"两侧完全一致"**：宿主那份多了 ``retry`` 与 ``assistant``（它有重试回调与中间
文本，引擎那份没有），所以两边各有一份"该发哪些"的名单，而不是拿一边去卡另一边。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import cast

from .support import host_module_dir

PACKAGE_DIR = Path(__file__).resolve().parents[1]  # .../custom_nodes/comfy_studio
HOST_DIR = host_module_dir()
LOOP_REL = ("agent", "loop.py")

#: 事件类型 → 载荷键。键是从两侧 ``agent/loop.py`` 的 ``AgentEvent(...)`` 实参字面量里读出来的；
#: 消费方是 TS 面板的 ``onEvent``：``tool_call`` 交给 ``addToolCall(params)``（读 id/name/arguments），
#: ``tool_result`` 交给 ``addToolResult``（读 id/name/text），``retry`` 读 attempt/total/delay。
PAYLOAD_KEYS: dict[str, frozenset[str]] = {
    "final": frozenset({"text"}),
    "assistant": frozenset({"text"}),
    "tool_call": frozenset({"id", "name", "arguments"}),
    "tool_result": frozenset({"id", "name", "text"}),
    "retry": frozenset({"attempt", "total", "delay", "reason"}),
}

#: 引擎侧该发的类型：它没有重试回调，也不发中途的 assistant 文本（见其 ``ask``）。
ENGINE_EVENT_TYPES = frozenset({"final", "tool_call", "tool_result"})

#: 宿主侧该发的类型：比引擎侧多 ``retry`` 与 ``assistant``。
HOST_EVENT_TYPES = frozenset({"final", "assistant", "tool_call", "tool_result", "retry"})


def event_shapes(source: str, where: str) -> tuple[dict[str, frozenset[str]], int]:
    """抽出所有 ``AgentEvent("类型", {载荷键…})``，返回 (类型 → 键集合, 构造点个数)。

    用 ``ast`` 而不是正则：``retry`` 那条的 dict 跨了四行，正则漏掉一个事件以后，守卫就只剩
    "看着剩下那几个"却照样绿。抽不出来的形状**直接报错**而不是跳过那个调用点 —— 那说明事件
    改成用变量拼了，此刻这个守卫是瞎的，得先把写法改回去或把抽取逻辑跟上。
    """
    tree = ast.parse(source)
    shapes: dict[str, frozenset[str]] = {}
    calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "AgentEvent"):
            continue
        if len(node.args) < 2:
            raise AssertionError(f"{where}:{node.lineno} 的 AgentEvent 少了实参（要 (类型, 载荷)）")
        calls += 1
        kind, payload = node.args[0], node.args[1]
        if not (isinstance(kind, ast.Constant) and isinstance(kind.value, str)):
            raise AssertionError(
                f"{where}:{node.lineno} 的事件类型不是字符串字面量 —— 守卫抽不出来了，"
                "要么改回字面量，要么把 event_shapes 的抽取逻辑跟上"
            )
        if not isinstance(payload, ast.Dict):
            raise AssertionError(
                f"{where}:{node.lineno} 的载荷不是 dict 字面量 —— 守卫抽不出来，"
                "要么改回字面量，要么把 event_shapes 的抽取逻辑跟上"
            )
        keys: set[str] = set()
        for key in payload.keys:
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                raise AssertionError(f"{where}:{node.lineno} 的载荷里有非字面量键，守卫抽不出来")
            keys.add(key.value)
        shape = frozenset(keys)
        known = shapes.get(kind.value)
        if known is not None and known != shape:
            raise AssertionError(
                f"{where}: 同名事件 {kind.value!r} 在两处发的载荷键不一致："
                f"{sorted(known)} vs {sorted(shape)} —— 前端只按一套键取，另一处会取到 undefined"
            )
        shapes[kind.value] = shape
    return shapes, calls


def _read_loop(package: Path) -> tuple[dict[str, frozenset[str]], int]:
    path = package.joinpath(*LOOP_REL)
    return event_shapes(path.read_text(encoding="utf-8"), str(path))


class EventShapesSelfCheckTest(unittest.TestCase):
    """抽取自己的用例：拿编出来的源码把每条判断走一遍（不需要宿主落点，永远跑）。

    :class:`EngineAgentEventTest` / :class:`SharedAgentEventTest` 比的是仓库里那两份文件的
    "现在长什么样"，一次抽取就把它们判绿。**抽取钝了也一样绿** —— 少认一个构造点、把某个事件
    漏掉，报出来的还是 OK，而漂移从那一刻起没人盯着。所以这里不依赖任何真实文件。
    """

    def test_a_payload_spanning_several_lines_is_read(self) -> None:
        """``retry`` 那条的载荷跨四行 —— 按行/正则抽的写法会整个漏掉它（漏了就少一个报警点）。"""
        source = (
            "async def ask(on_event):\n"
            "    await on_event(\n"
            "        AgentEvent(\n"
            '            "retry",\n'
            "            {\n"
            '                "attempt": attempt,\n'
            '                "total": total,\n'
            '                "delay": delay,\n'
            '                "reason": reason,\n'
            "            },\n"
            "        )\n"
            "    )\n"
        )
        shapes, calls = event_shapes(source, "synthetic.py")
        self.assertEqual(calls, 1)
        self.assertEqual(shapes["retry"], PAYLOAD_KEYS["retry"])

    def test_only_the_agent_event_calls_are_counted(self) -> None:
        """别的调用不算构造点：混进一个 ``ChatMessage(...)`` 不该把计数抬起来。"""
        source = (
            'AgentEvent("final", {"text": answer})\n'
            'ChatMessage(role="assistant", content="喂")\n'
        )
        shapes, calls = event_shapes(source, "synthetic.py")
        self.assertEqual(calls, 1)
        self.assertEqual(frozenset(shapes), {"final"})

    def test_the_same_name_with_different_keys_in_one_file_is_reported(self) -> None:
        """同一个文件里同名事件发的键不一样：前端只按一套取，另一处就是 ``undefined``。"""
        source = (
            'AgentEvent("tool_result", {"id": call.id, "name": call.name, "text": out})\n'
            'AgentEvent("tool_result", {"id": call.id, "name": call.name, "output": out})\n'
        )
        with self.assertRaises(AssertionError) as caught:
            event_shapes(source, "synthetic.py")
        self.assertIn("tool_result", str(caught.exception))

    def test_a_drifting_extraction_is_an_error_not_a_smaller_list(self) -> None:
        """改成用变量拼之后**当面报错**：此刻这个守卫是瞎的，不能装作只看到了剩下的那几个。"""
        for source, why in (
            ('AgentEvent(kind, {"text": text})\n', "事件类型不是字面量"),
            ('AgentEvent("final", payload)\n', "载荷不是 dict 字面量"),
            ('AgentEvent("final", {key: text})\n', "载荷里有非字面量键"),
            ('AgentEvent("final")\n', "少了实参"),
        ):
            with self.subTest(why=why):
                with self.assertRaises(AssertionError):
                    event_shapes(source, "synthetic.py")

    def test_two_sides_that_drift_apart_do_not_look_alike(self) -> None:
        """守卫的全部力气就在这一比上：改了一边之后，两侧的抽取值必须**看得出差别**。"""
        mine, _ = event_shapes('AgentEvent("tool_result", {"id": i, "name": n, "text": t})\n', "mine.py")
        theirs, _ = event_shapes(
            'AgentEvent("tool_result", {"id": i, "name": n, "output": t})\n', "theirs.py"
        )
        self.assertNotEqual(mine["tool_result"], theirs["tool_result"])
        renamed, _ = event_shapes(
            'AgentEvent("toolResult", {"id": i, "name": n, "text": t})\n', "renamed.py"
        )
        self.assertNotEqual(frozenset(mine), frozenset(renamed))


class EngineAgentEventTest(unittest.TestCase):
    """引擎侧那份的事件（不需要宿主落点，永远跑）：类型与载荷键都还在契约上。"""

    def test_engine_events_stay_on_the_contract(self) -> None:
        shapes, calls = _read_loop(PACKAGE_DIR)
        self.assertGreaterEqual(
            calls,
            3,
            "只抽到这么少的 AgentEvent 构造点 —— 多半是这个守卫的抽取逻辑瞎了，而不是事件变少了",
        )
        self.assertEqual(
            frozenset(shapes),
            ENGINE_EVENT_TYPES,
            f"引擎侧发出的事件类型变了：{sorted(shapes)}。前端那支分派不认新名字时不会报错、"
            "只是不画 —— 确实要新增的话，前端 onEvent 与本文件的 PAYLOAD_KEYS 一起改",
        )
        for kind, keys in sorted(shapes.items()):
            self.assertEqual(keys, PAYLOAD_KEYS[kind], f"引擎侧的 {kind} 载荷键与契约不符")


@unittest.skipUnless(
    HOST_DIR is not None,
    "找不到宿主侧落点 Comfy-Desktop/lib/comfy_studio（引擎被单独安装时属于正常情况）",
)
class SharedAgentEventTest(unittest.TestCase):
    """宿主侧的事件、以及两侧同名事件的载荷（改了一边，另一边会一直是老样子）。"""

    def test_host_events_stay_on_the_contract(self) -> None:
        shapes, calls = _read_loop(cast(Path, HOST_DIR))
        self.assertGreaterEqual(calls, 3, "只抽到这么少的 AgentEvent 构造点 —— 抽取逻辑多半瞎了")
        self.assertEqual(
            frozenset(shapes),
            HOST_EVENT_TYPES,
            f"宿主侧发出的事件类型变了：{sorted(shapes)} —— 面板的 onEvent 少认一支就是少画一块",
        )
        for kind, keys in sorted(shapes.items()):
            self.assertEqual(keys, PAYLOAD_KEYS[kind], f"宿主侧的 {kind} 载荷键与契约不符")

    def test_both_sides_send_the_same_thing_under_the_same_name(self) -> None:
        """两侧都有的类型，载荷键必须逐字相同 —— 这是"改一边漏一边"最直接的报警器。"""
        engine, _ = _read_loop(PACKAGE_DIR)
        host, _ = _read_loop(cast(Path, HOST_DIR))
        shared = sorted(set(engine) & set(host))
        self.assertEqual(
            shared,
            sorted(ENGINE_EVENT_TYPES),
            "两侧共有的类型不该少于引擎侧那份（引擎侧是子集：它没有 retry 与中途文本）",
        )
        for kind in shared:
            self.assertEqual(engine[kind], host[kind], f"两侧的 {kind} 载荷键不一致")


if __name__ == "__main__":
    unittest.main()
