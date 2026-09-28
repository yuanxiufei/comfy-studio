"""从一页 HTML 里挑出"正文那一块"—— 拿走导航、页脚、侧栏、评论。

**为什么需要它**：``web__fetch`` 原本把整页文本丢给模型（``comfy_studio.web.html_to_text``
只管去标签），而真实网页里正文常只占三成：剩下的导航、页脚、侧栏、"相关推荐""热门标签"
全是链接 —— 模型每读一页都要为这些付上下文钱，还容易被带跑。这里按**内容密度 + 链接密度**
给每个节点打分，把低分的整棵子树剪掉。

**打分公式的出处**：crawl4ai 的 ``PruningContentFilter``（参考仓库
``crawl4ai/crawl4ai/content_filter_strategy.py``，2026-09-28 读的那一版）。照抄的定量事实：

* 判定阈值 ``0.48``（``PruningContentFilter.threshold`` 默认值）；
* 五项指标权重 ``text_density 0.4`` / ``link_density 0.2`` / ``tag_weight 0.2`` /
  ``class_id_weight 0.1`` / ``text_length 0.1``（``metric_weights``，和恰为 1.0）；
* 标签权重表 ``tag_weights``（见 :data:`TAG_WEIGHTS`，表外标签取 ``0.5``）；
* 负向正则（见 :data:`NEGATIVE_PATTERN`）：命中 ``class`` 或 ``id`` 各扣 ``0.5``，且
  **加权前先 ``max(0, ...)`` 夹住**（它 ``_compute_composite_score`` 里的写法）；
* 先整块删掉的标签（``excluded_tags``，见 :data:`EXCLUDED_TAGS`）；
* 三个指标：``text_density = 文本长度 / 内部 HTML 长度``；
  ``link_density = 1 - 直接子链接文本长度 / 文本长度``（它用 ``find_all("a", recursive=False)``，
  **只数直接子节点**）；``text_length = ln(文本长度 + 1)``，**不归一化**，长节点天然占优 ——
  这是它的设计，不是抄漏了；
* 剪枝顺序：从 ``body`` **自顶向下**，本节点分低于阈值就丢掉整棵，否则递归进子节点。

**与 crawl4ai 的三处偏离，都是本仓条件决定的**：

1. **不引依赖**：它用 BeautifulSoup / lxml 建树，这里用标准库 :mod:`html.parser` 自己搭一棵
   极简 DOM。它的 ``tag_len`` 取 ``encode_contents()`` 的 UTF-8 字节数，这里取"自序列化后的
   UTF-8 字节数" —— 差在空白与属性顺序上，量级一致。
2. **加了一道保底**：它允许 ``filter_content`` 返回空，由调用方兜。这里不行 —— ``web__fetch``
   回一片空白，模型会当成"这页没内容"，那是最坏的一种错。所以剪得只剩一点时回退到
   "只删已知整块噪声、不按分数剪"的那一版（见 :func:`main_text`）。
3. **不做它的 ``min_word_threshold`` 与 preserve 白名单**（它默认也没开）：没有需求，
   加了只是多一份没人用的开关。

**它替不掉的东西**：靠 JS 渲染的页面（正文在 ``<script>`` 里）这里一律读不到 —— 那是要浏览器的
事，不在本模块范围内。
"""

from __future__ import annotations

import math
import re
from html.parser import HTMLParser
from typing import Iterator
from urllib.parse import urljoin

#: 判定阈值。照抄 crawl4ai ``PruningContentFilter.threshold`` 默认值。
PRUNE_THRESHOLD = 0.48

#: 五项指标权重。照抄 ``metric_weights``。
METRIC_WEIGHTS: dict[str, float] = {
    "text_density": 0.4,
    "link_density": 0.2,
    "tag_weight": 0.2,
    "class_id_weight": 0.1,
    "text_length": 0.1,
}

#: 标签权重。照抄 ``tag_weights``；表外的取 :data:`_DEFAULT_TAG_WEIGHT`。
TAG_WEIGHTS: dict[str, float] = {
    "div": 0.5,
    "p": 1.0,
    "article": 1.5,
    "section": 1.0,
    "span": 0.3,
    "li": 0.5,
    "ul": 0.5,
    "ol": 0.5,
    "h1": 1.2,
    "h2": 1.1,
    "h3": 1.0,
    "h4": 0.9,
    "h5": 0.8,
    "h6": 0.7,
}
_DEFAULT_TAG_WEIGHT = 0.5

#: class / id 的负向模式。照抄 ``RelevantContentFilter.negative_patterns``。
NEGATIVE_PATTERN = re.compile(
    r"nav|footer|header|sidebar|ads|comment|promo|advert|social|share", re.IGNORECASE
)

#: 剪枝前整块删掉的标签。照抄 ``RelevantContentFilter.excluded_tags``。
EXCLUDED_TAGS = frozenset(
    {"nav", "footer", "header", "aside", "script", "style", "form", "iframe", "noscript"}
)

#: 没有闭合标签的元素：建树时不入栈（否则后面所有内容都会变成它的孩子）。
VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)

#: 隐式闭合：键是**刚打开的标签**，值是"栈里正开着这些就先关掉"。
#:
#: HTML 允许省略结束标签（``<p>a<p>b``、``<li>x<li>y``），真网页里遍地都是。不处理的话整页
#: 会退化成一个巨型 ``<p>``，剪枝打分就失去意义。只覆盖最常见的几组，不求完整 —— 漏掉的情形
#: 最坏也只是树形状怪一点，不影响"取文本"这件事。
_AUTO_CLOSE: dict[str, frozenset[str]] = {
    "p": frozenset(
        {
            "p", "div", "ul", "ol", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6",
            "section", "article", "blockquote", "pre", "form", "hr",
        }
    ),
    "li": frozenset({"li", "p"}),
    "dt": frozenset({"dt", "dd"}),
    "dd": frozenset({"dt", "dd"}),
    "td": frozenset({"td", "th", "tr"}),
    "th": frozenset({"td", "th", "tr"}),
    "tr": frozenset({"tr", "td", "th"}),
    "option": frozenset({"option"}),
    "a": frozenset({"a"}),
}

#: 渲染文本时前后换行的标签（保住段落感）。与 ``comfy_studio.web._BLOCK_BREAK`` 同一口径。
_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "caption", "dd", "details",
        "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1",
        "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
        "pre", "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead",
        "tr", "ul",
    }
)

#: 剪枝结果短于这么多字符就认为"剪坏了"，回退到不按分数剪的那一版。
#:
#: 200 是**拍的**，没有实测依据；取它的理由：比"正文总得有一两段"这个最低预期还低一些，
#: 宁可少回退，也别把大量短页面都退化成"整页噪声"。嫌回退太频繁就调这里，
#: **别动剪枝阈值** —— 那个是 crawl4ai 的值。
_FALLBACK_MIN_CHARS = 200


class Node:
    """极简 DOM 节点：标签名、属性、孩子（``Node`` 或纯文本 ``str``）。

    刻意不做：兄弟指针、命名空间、CSS 选择器 —— 取正文用不上。
    """

    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(
        self,
        tag: str,
        attrs: dict[str, str] | None = None,
        parent: "Node | None" = None,
    ) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list["Node | str"] = []
        self.parent = parent

    def __repr__(self) -> str:  # pragma: no cover - 只为人读日志
        return f"<Node {self.tag} children={len(self.children)}>"

    def elements(self) -> Iterator["Node"]:
        """直接子元素（跳过纯文本）。"""
        for child in self.children:
            if isinstance(child, Node):
                yield child

    def text(self) -> str:
        """节点下**全部**文本。

        与 BeautifulSoup 的 ``get_text(strip=True)`` 对齐：每个文本片段各自 ``strip()``
        **之后拼接、不插分隔符** —— 打分公式里的 ``text_len`` 就是它，换一种拼法数值就变了。
        """
        return "".join(_iter_texts(self))

    def direct_link_text_len(self) -> int:
        """所有**直接子** ``<a>`` 的文本长度之和。

        对齐 ``node.find_all("a", recursive=False)``：只数直接子节点。递归数会把整站导航
        算进内层节点的链接密度里，那是另一套算法。
        """
        total = 0
        for child in self.children:
            if isinstance(child, Node) and child.tag == "a":
                total += len(child.text())
        return total

    def find(self, tag: str) -> "Node | None":
        """深度优先找第一个同名后代（含自身），找不到返回 ``None``。"""
        if self.tag == tag:
            return self
        for child in self.children:
            if isinstance(child, Node):
                found = child.find(tag)
                if found is not None:
                    return found
        return None


def _iter_texts(node: Node) -> Iterator[str]:
    """深度优先吐出每个文本片段的 ``strip()`` 结果（跳过空片段）。"""
    for child in node.children:
        if isinstance(child, str):
            stripped = child.strip()
            if stripped:
                yield stripped
        else:
            yield from _iter_texts(child)


class _TreeBuilder(HTMLParser):
    """把 HTML 喂成一棵 :class:`Node`。

    ``convert_charrefs=True``（默认）让 ``&amp;`` 之类在 ``handle_data`` 里就已还原，与
    ``html.unescape`` 的最终效果一致，省得后面再解一遍。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self._stack: list[Node] = [self.root]

    def _auto_close(self, tag: str) -> None:
        """打开 ``tag`` 之前，按 :data:`_AUTO_CLOSE` 把栈里该关的先关掉。"""
        closable = _AUTO_CLOSE.get(tag)
        if not closable:
            return
        # 从栈顶往下找最近的：只有"正开着"的才关，且要弹到它为止（它上面的都是它的后代）。
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag in closable:
                del self._stack[index:]
                return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._auto_close(tag)
        node = Node(tag, {key: (value or "") for key, value in attrs}, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # ``<br/>`` 这类自闭合写法：建节点但不入栈。
        node = Node(tag, {key: (value or "") for key, value in attrs}, self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        # 找最近的同名开标签；没有就忽略（真网页里配不平的结束标签很多）。
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        # 纯空白文本对取正文没有贡献，却会占掉大量节点 —— 直接丢。
        if data.strip():
            self._stack[-1].children.append(data)

    def handle_comment(self, data: str) -> None:
        """注释整个丢掉：它不属于正文，也没有可读价值。"""


def parse_html(markup: str) -> Node | None:
    """HTML -> 树。**解不出来回 ``None`` 而不是抛**：抓回来的东西什么样都有，
    取正文失败不该让整个抓取跟着失败。"""
    builder = _TreeBuilder()
    try:
        builder.feed(markup)
        builder.close()
    except Exception:  # noqa: BLE001 - html.parser 极少抛，但畸形输入不该冒到这层
        return None
    return builder.root


def body_of(root: Node) -> Node:
    """取 ``<body>``；没有就用整棵树（有些页面片段只有正文、没有 body）。"""
    return root.find("body") or root


def _bytes(text: str) -> int:
    """UTF-8 字节数 —— 打分里的"长度"一律指字节数（crawl4ai 用的是 ``encode_contents()``）。"""
    return len(text.encode("utf-8"))


def _attrs_html(attrs: dict[str, str]) -> str:
    return "".join(f' {key}="{value}"' for key, value in attrs.items())


def serialize(node: Node) -> str:
    """节点的**内部** HTML（不含自身标签）。对齐 BeautifulSoup 的 ``encode_contents()``。"""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
            continue
        parts.append(f"<{child.tag}{_attrs_html(child.attrs)}>")
        if child.tag not in VOID_TAGS:
            parts.append(serialize(child))
            parts.append(f"</{child.tag}>")
    return "".join(parts)


def _measure(node: Node) -> dict[int, tuple[int, int, int]]:
    """一次后序遍历算好每个节点的 ``(text_len, tag_len, link_text_len)``。

    **不能每个节点各自递归去算** —— 那是 O(n²)，几万节点的页面会卡到没法用。自底向上
    一次成型，顺带把这三个量按 ``id(node)`` 存下来给打分用。

    缓存只在**一次剪枝内**有效：剪枝是自顶向下的，算某个子节点的分时它的子树还是完整的，
    算完也不会再回头重算祖先，所以不存在读到过期值的问题。
    """
    out: dict[int, tuple[int, int, int]] = {}

    def walk(n: Node) -> tuple[int, int, int]:
        text_len = 0
        tag_len = 0
        link_text_len = 0
        for child in n.children:
            if isinstance(child, str):
                text_len += len(child.strip())
                tag_len += _bytes(child)
                continue
            child_text, child_tag, _child_link = walk(child)
            text_len += child_text
            tag_len += child_tag + _bytes(f"<{child.tag}{_attrs_html(child.attrs)}>")
            if child.tag not in VOID_TAGS:
                tag_len += _bytes(f"</{child.tag}>")
            if child.tag == "a":
                # 对齐 `find_all("a", recursive=False)`：**只算直接子节点**。
                link_text_len += child_text
        out[id(n)] = (text_len, tag_len, link_text_len)
        return text_len, tag_len, link_text_len

    walk(node)
    return out


def score(node: Node, measures: dict[int, tuple[int, int, int]]) -> float:
    """按 crawl4ai 的四项 + 文本长度项给一个节点打分（各项加权后求平均）。"""
    text_len, tag_len, link_text_len = measures[id(node)]

    total = 0.0
    # 1) 内容密度：正文占内部 HTML 的比例。
    density = text_len / tag_len if tag_len > 0 else 0.0
    total += METRIC_WEIGHTS["text_density"] * density
    # 2) 链接密度：1 减去链接文本占比。**没有文本时按 1 算**（它写的是 ``else 1``），
    #    于是这一项得 0 —— 空节点拿不到"没有链接"的加分。
    link_ratio = link_text_len / text_len if text_len > 0 else 1
    total += METRIC_WEIGHTS["link_density"] * (1 - link_ratio)
    # 3) 标签权重。
    total += METRIC_WEIGHTS["tag_weight"] * TAG_WEIGHTS.get(node.tag, _DEFAULT_TAG_WEIGHT)
    # 4) class / id 负向：命中各扣 0.5，**再用 max(0, ...) 夹住**（所以扣成负数 = 这一项得 0）。
    #    注意它用的是 ``negative_patterns.match``（**从开头匹配**，不是 search）：
    #    ``class="navbar"`` 会命中，``class="site-nav"`` 不会。这里照抄这个语义 ——
    #    改成 search 相当于替它改了判定，效果会变，而变好变坏没人验过。
    penalty = 0.0
    if NEGATIVE_PATTERN.match(node.attrs.get("class", "")):
        penalty -= 0.5
    if NEGATIVE_PATTERN.match(node.attrs.get("id", "")):
        penalty -= 0.5
    total += METRIC_WEIGHTS["class_id_weight"] * max(0.0, penalty)
    # 5) 文本长度：ln(len + 1)，**不归一化**（长节点天然占优，这是它的设计）。
    total += METRIC_WEIGHTS["text_length"] * math.log(text_len + 1)

    return total / sum(METRIC_WEIGHTS.values())


def prune(node: Node, measures: dict[int, tuple[int, int, int]], threshold: float = PRUNE_THRESHOLD) -> None:
    """自顶向下剪：子节点分低于 ``threshold`` 就整棵丢掉，否则递归进它。"""
    kept: list[Node | str] = []
    for child in node.children:
        if isinstance(child, str):
            kept.append(child)
            continue
        if score(child, measures) < threshold:
            continue
        prune(child, measures, threshold)
        kept.append(child)
    node.children = kept


def drop_tags(node: Node, tags: frozenset[str] = EXCLUDED_TAGS) -> None:
    """整棵删掉 ``tags`` 里的标签（``nav`` / ``footer`` / ``script`` ……）。"""
    kept: list[Node | str] = []
    for child in node.children:
        if isinstance(child, str):
            kept.append(child)
            continue
        if child.tag in tags:
            continue
        drop_tags(child, tags)
        kept.append(child)
    node.children = kept


def render_text(node: Node) -> str:
    """树 -> 文本。块级标签处换行，其余折成一个空格，丢掉空行。

    与 ``comfy_studio.web.html_to_text`` 的收口口径一致（同一套空白规则），这样换过来以后
    正文的观感不变，只是噪声少了。
    """
    parts: list[str] = []

    def walk(n: Node) -> None:
        for child in n.children:
            if isinstance(child, str):
                parts.append(child)
                continue
            block = child.tag in _BLOCK_TAGS
            if block:
                parts.append("\n")
            walk(child)
            if block:
                parts.append("\n")

    walk(node)
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in "".join(parts).splitlines()]
    return "\n".join(line for line in lines if line)


def extract(markup: str, *, threshold: float = PRUNE_THRESHOLD) -> tuple[str, str]:
    """一次解析给出 ``(标题, 正文)``。

    只解析一遍：标题与正文都从同一棵树上取（分两次调用就是两次建树，白花时间）。
    """
    root = parse_html(markup)
    if root is None:
        return "", ""
    title_node = root.find("title")
    title = re.sub(r"\s+", " ", title_node.text()).strip() if title_node is not None else ""

    body = body_of(root)
    drop_tags(body)
    plain = render_text(body)
    measures = _measure(body)
    prune(body, measures, threshold)
    main = render_text(body)
    # 保底：剪枝是按"分数"赌的，遇到结构古怪的页面可能把正文也剪没了。那种时候宁可把
    # 噪声一起交出去，也不能回一片空白 —— 空白会被模型读成"这页没有内容"。
    if len(main) < _FALLBACK_MIN_CHARS and len(plain) > len(main):
        return title, plain
    return title, main


def main_text(markup: str, *, threshold: float = PRUNE_THRESHOLD) -> str:
    """只要正文（:func:`extract` 的薄封装，方便测试与单用）。"""
    return extract(markup, threshold=threshold)[1]


def page_title(markup: str) -> str:
    """只要 ``<title>``（同上）。"""
    return extract(markup)[0]


def links(markup: str, base_url: str) -> list[str]:
    """页面里所有 ``<a href>`` 的**绝对**地址（相对地址按 ``base_url`` 补全），按出现顺序。

    只认 ``<a>``：``<link>`` 是样式 / 图标 / 预连接，``<script src>`` 是代码，``<iframe>``
    是另一个文档 —— 都不是"给人读的下一页"。``javascript:`` / ``mailto:`` / ``#锚点``
    这类跟不了的也丢掉（:func:`urljoin` 之后不是 http(s) 就不要）。

    **不认 ``<base href>``**：真站点里极少见，而认它要先扫一遍头部才知道该拿谁当基准 ——
    漏掉的代价只是个别相对链接补错，补错的那种随后会在抓取时自然失败，不会静默出错。
    """
    root = parse_html(markup)
    if root is None:
        return []
    out: list[str] = []
    stack: list[Node] = [root]
    while stack:
        node = stack.pop()
        if node.tag == "a":
            href = (node.attrs.get("href") or "").strip()
            if href:
                absolute = urljoin(base_url, href)
                if absolute.startswith(("http://", "https://")):
                    out.append(absolute)
        # 用栈做深度优先；收集链接不关心先后（调用方本来就要去重），但**同层内的顺序**
        # 会反过来，所以这里按原顺序压栈。
        stack.extend(child for child in reversed(node.children) if isinstance(child, Node))
    return out


__all__ = [
    "EXCLUDED_TAGS",
    "METRIC_WEIGHTS",
    "NEGATIVE_PATTERN",
    "PRUNE_THRESHOLD",
    "TAG_WEIGHTS",
    "Node",
    "body_of",
    "drop_tags",
    "extract",
    "links",
    "main_text",
    "page_title",
    "parse_html",
    "prune",
    "render_text",
    "score",
    "serialize",
]
