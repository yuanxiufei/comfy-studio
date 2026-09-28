"""联网这一层共用的异常。

**为什么单开一个文件**：``WebError`` 原本就定义在 :mod:`comfy_studio.web` 里。搜索解析要拆到
:mod:`comfy_studio.websearch`（纯函数、好单测），而它照样得抛**同一类**错误；``websearch`` 直接
``from .web import WebError`` 就成循环 import（``web`` 反过来要用 ``websearch``）。所以把类提到
这里，两边都从这儿拿。

对外**没有任何变化**：``from comfy_studio.web import WebError`` 照样能用 ——
:mod:`comfy_studio.web` 会把它原样再导出一遍。
"""

from __future__ import annotations


class WebError(RuntimeError):
    """联网这一层的错误：网址不合法 / 落在禁区、连不上、对方回错、页面读不出来。

    与 :class:`~comfy_studio.memory.MemoryStoreError` 同一个口径：**说得清楚**比"返回空
    结果"有用得多。工具层会把它翻成 ``isError`` 文本交给模型。
    """


__all__ = ["WebError"]
