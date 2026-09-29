"""面板选中态：用户眼前那块面板**此刻选中了什么** → 一段给模型看的环境说明。

**为什么单开这一层**：面板上的工作流下拉、左边点开的项目与原文，都是"用户眼前的东西"，
而 ``agent/chat`` 从前只接一段话（见 :meth:`comfy_studio.server.StudioHost.agent_chat`）：
模型不知道用户在下拉里选的是哪一份图，于是"改一下这个"里的"这个"只能靠猜 —— 面板那一行
（``comfyStudioChatContentScript.ts`` 的 ``workflowToChat``）会把文件名写进话里，但用户
自己打"改一下这个"、或者换了选中项却没打字时，模型手里什么都没有。

**为什么不拼进用户那句话**：那是引用块（``composeQuotes``）的做法，它有它的道理（所见即所发）。
但选中态不是用户打的字，也不该出现在对话气泡里 —— 它是**环境事实**，与"你现在是谁"
"你记得什么"同一类，所以由 :meth:`comfy_studio.server.StudioHost._prompt_source` 每轮
重算时插进人设段。**代价如实写**：选中变了人设就变，本地推理服务的前缀缓存那一轮要重
prefill 一次（``agent/loop.py`` 的 ``ask`` 靠"逐字一样就不重建 messages[0]"省下来的正是
这一次）；换下拉是低频动作，而没变时那次重建不会发生。

**为什么键名对不上时当场报错**：打错一个键名却静默不生效，比报错难查得多（同
:mod:`comfy_studio.mcp.tools` 里那几条参数校验、以及 ``mcp/config.py`` 那段环境变量的口径）。
面板是唯一的调用方，报错只会在开发期出现。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "CONTEXT_KEYS",
    "MAX_VALUE_CHARS",
    "PanelContextError",
    "describe_context",
    "parse_context",
]


class PanelContextError(ValueError):
    """面板传来的 context 形状不对。报错要说清是哪个键、以及该是什么样。"""


#: 认得的键，**顺序就是段里那几行的顺序**（工作流打头：它是这几样里最常用的一个）。
CONTEXT_KEYS: tuple[str, ...] = ("workflow", "workflows_dir", "project", "novel")

#: 每个值最多留多少字符。面板报的是文件名 / 目录名 / 项目名，正常几十字；给这么宽是为了
#: 不误伤长路径，同时挡住"有人把一整份文件塞进这个字段"。**超了当场报错而不是截断**：
#: 截半个文件名交给模型，它会拿着半个名字去调工具，然后收到"没有这份工作流"—— 那比报错难查。
MAX_VALUE_CHARS = 200

#: 段里每行的名字。键是给程序用的，标签是给模型看的 —— 改一处要记得另一处。
_LABELS = {
    "workflow": "工作流",
    "workflows_dir": "工作流目录",
    "project": "项目",
    "novel": "原文",
}


def parse_context(value: Any, *, where: str = "agent/chat") -> dict[str, str]:
    """校验并收拾 ``agent/chat`` 的 ``context`` 参数，只回"真选了的那几项"。

    ``None`` / 缺这个键 / 空对象都回空字典（调用方据此"一段都不插"，老形状一字不变）；
    值是空白字符串的键直接跳过（等价于没选）；其余的错都当场抛。
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PanelContextError(
            f"{where} 的 context 必须是对象（{{…}}），给的是 {type(value).__name__}"
        )
    unknown = sorted(str(key) for key in value if key not in CONTEXT_KEYS)
    if unknown:
        raise PanelContextError(
            f"{where} 的 context 里有不认识的键：{'、'.join(unknown)}；"
            f"只认 {'、'.join(CONTEXT_KEYS)}"
        )
    out: dict[str, str] = {}
    for key in CONTEXT_KEYS:
        if key not in value:
            continue
        item = value[key]
        if not isinstance(item, str):
            raise PanelContextError(
                f"{where} 的 context.{key} 必须是字符串，给的是 {type(item).__name__}"
            )
        text = item.strip()
        if text == "":
            continue
        if len(text) > MAX_VALUE_CHARS:
            raise PanelContextError(
                f"{where} 的 context.{key} 有 {len(text)} 个字符（上限 {MAX_VALUE_CHARS}）："
                f"这里只该放文件名 / 目录名 / 项目名，不是整份文件的内容"
            )
        out[key] = text
    return out


def describe_context(context: Mapping[str, str]) -> str:
    """把选中的几样拼成一段。空的时候回空串 —— 调用方据此"一段都不插"。

    两个口径写死在段里，因为它们是模型最容易搞错的两件事：

    1. 这是**界面状态**，不是用户的指令 —— 他在话里点了别的名字，以他说的为准；
    2. 他没点名时也别拿这几样自己开工："面板上开着什么"与"我要你做什么"是两件事，
       混起来就成了"我只是点开看了一眼，它自己跑起来了"。
    """
    lines = [f"- {_LABELS[key]}：{context[key]}" for key in CONTEXT_KEYS if context.get(key)]
    if not lines:
        return ""
    return (
        "【面板上此刻选中的东西】用户面前那块 ComfyStudio 面板现在选的是：\n"
        + "\n".join(lines)
        + "\n这几行只是那块面板的样子，**不是他对你说的话**：他在话里点了别的工作流 / 项目，"
        "就以他说的为准；他没点名，也别自己拿这几样开工。"
    )
