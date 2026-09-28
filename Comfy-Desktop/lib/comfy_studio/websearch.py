"""搜索结果的解析、归一、去重与重排 —— 全是纯函数，**不碰网络**。

**为什么从 ``web.py`` 拆出来**：这些逻辑与"发 HTTP 请求"没关系，拆开以后可以离线单测
（喂一份真响应，断言解析结果），也不用为了测一个正则去搭假会话。``web.py`` 保留 IO 与工具层。

**两种后端的响应都在这里落地**：

* 必应 RSS（默认后端）：``<item>`` 里的 ``<title>`` / ``<link>`` / ``<description>`` / ``<pubDate>``。
  字段位置是**外部事实**，照着 2026-09-28 真拿回来的那份写（样本在 ``tests/test_web.py``
  的 ``BING_RSS_SAMPLE``）。
* SearXNG 的 ``/search?format=json``（可选后端）：字段名照参考仓库的读取代码 ——
  ``searxng-mcp/src/types.ts`` 的 ``SearxResult`` / ``SearxResponse``：结果是
  ``results[].{title, url, content, engine, engines, publishedDate}``，另有 ``answers`` /
  ``infoboxes`` / ``corrections`` / ``suggestions`` 四样旁路信息。它那段注释说得明白：
  "these shapes vary a bit across versions (answers/corrections have been both strings and
  objects)" —— 所以下面解析这两种形状时**都认**，而不是挑一种。

**新鲜度分与重排的出处**：searxng-mcp 的 ``recencyScore`` 与 ``rerank``
（``searxng-mcp/src/reranker.ts``；权重默认值见 ``searxng-mcp/src/config.ts`` 的
``RERANK_RECENCY_WEIGHT``）。它算的是 ``exp(-ageDays / 90)``，缺失 / 解不出来 / **未来**日期
一律 0（0 是"不参与"，不是"很旧"）。这里的两处偏离都写在各自函数上。

**必应中文站的 ``<pubDate>`` 是中文的**（``周日, 27 9月 2026 20:23:00 GMT``），
``email.utils`` 解不了 —— 见 :func:`parse_date`。
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from .weberror import WebError

#: 去标签用的正则（摘要清洗与 :func:`plain_text` 共用）。
_TAG = re.compile(r"<[^>]+>")

#: 有 DTD / 实体声明就不给解析：标准库的 ElementTree **会展开内部实体**，而这份 XML 是外面
#: 送来的，嵌套实体正是"billion laughs"那类内存炸弹。真 feed 里这两种声明一个都没有
#: （实测那份开头就是 ``<?xml version="1.0" encoding="utf-8" ?><rss version="2.0">``），
#: 所以看到就直接报错，而不是"先解析看看"。
_XML_DECLARATION = re.compile(r"<!(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)

#: 开头长得像 HTML 的东西。**这一条排在实体检查前面**：实测必应回壳页时给的就是
#: ``<!DOCTYPE html>`` 开头的一整页，而它也会命中上面那条 DTD 正则 —— 先报"实体炸弹"会把
#: 最常见的那个故障说成一句看不懂的话，不如直说"拿回来的不是 XML"。
_HTML_LIKE = re.compile(r"^\s*(?:<!doctype\s+html|<html)\b", re.IGNORECASE)

#: 中文 RFC 822 日期（必应中文站给的形状）：``周日, 27 9月 2026 20:23:00 GMT``。
_DATE_CN = re.compile(
    r"^(?:周|星期)[一二三四五六日天]\s*[,，]?\s*"
    r"(\d{1,2})\s*(\d{1,2})月\s*(\d{4})\s+"
    r"(\d{1,2}):(\d{2}):(\d{2})"
    r"(?:\s*(GMT|UTC|([+-]\d{2}):?(\d{2})))?$"
)


def plain_text(fragment: str) -> str:
    """一小段 HTML -> 一行纯文本（去标签、解实体、把空白折成一个空格）。"""
    text = _TAG.sub(" ", fragment)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(text: str) -> datetime | None:
    """搜索结果里的日期字符串 -> 带时区的 ``datetime``（一律归到 UTC）；解不出来回 ``None``。

    三种形状都见过，挨个试：

    1. **ISO 8601** —— SearXNG 的 ``publishedDate`` 多是这种（``2026-09-27T20:23:00Z``，也有
       只给日期的 ``2026-09-27``）；``fromisoformat`` 吃不下结尾的 ``Z``（3.10 及更早），
       所以先换成 ``+00:00``。
    2. **RFC 822 英文** —— ``Sun, 27 Sep 2026 20:23:00 GMT``，RSS 的标准写法，交给
       :func:`~email.utils.parsedate_to_datetime`。
    3. **RFC 822 中文** —— ``周日, 27 9月 2026 20:23:00 GMT``。这是**必应中文站的实际输出**
       （样本在 ``tests/test_web.py``），``parsedate_to_datetime`` 对它返回 ``None``
       （月份是"9月"而它只认英文缩写），所以单独认一遍。

    **解不出来就回 ``None``**，不抛：日期只是用来加权的，缺了不该让整次搜索失败。
    """
    if not isinstance(text, str) or text.strip() == "":
        return None
    raw = text.strip()

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is not None:
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    match = _DATE_CN.match(raw)
    if match is None:
        return None
    day, month, year, hour, minute, second, _zone_name, offset_h, offset_m = match.groups()
    offset = timezone.utc
    if offset_h and offset_m:
        # 只在出现显式数字偏移时用它；GMT/UTC 与"没有时区"都按 UTC 算（必应给的就是 GMT）。
        sign = -1 if offset_h.startswith("-") else 1
        offset = timezone(sign * timedelta(hours=abs(int(offset_h)), minutes=int(offset_m)))
    try:
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second), tzinfo=offset
        )
    except ValueError:
        return None


def parse_rss_results(xml_text: str, limit: int) -> list[dict[str, Any]]:
    """从必应 RSS 里抠出 ``(标题, 网址, 摘要, 发布时间)``，**保持 feed 里的顺序**。

    三个刻意的取舍：

    * **``<title>`` / ``<description>`` 里的标签要再洗一遍，而且得先把子标签的文本捞全**
      （见 :func:`_item_text`）。RSS 的 ``<description>`` 常带 ``<b>`` 之类的 HTML 片段，模型
      读的是纯文本，所以走 :func:`plain_text` 而不是原样给 —— 否则模型会学着一堆
      ``<strong>`` 说话。
    * **缺 ``<title>`` 或缺 ``<link>`` 的条目直接跳过**，不硬凑一条只有半截的"结果"。整份
      一条都凑不出时**报错**（由调用方 :meth:`comfy_studio.web.WebFetcher.search` 负责），
      不当成"没搜到"。
    * **顺序不动**。"哪条更该排前面"是重排（:func:`rerank`）的事，解析只管照着 feed 抠；
      把两件事混在一起，就没法单独测"解析对不对"了。
    """
    if _HTML_LIKE.match(xml_text):
        raise WebError(
            "拿回来的不是搜索结果的 XML，而是一整页 HTML —— 多半是必应改了入口，"
            "或者这次被挡成了不带结果的壳页（实测就会这样）。这条路径的取数格式在 "
            "comfy_studio/web.py 的 BING_SEARCH_FORMAT。"
        )
    if _XML_DECLARATION.search(xml_text):
        raise WebError(
            "这份 XML 带 DTD / 实体声明，不给解析（标准库解析器会展开内部实体，"
            "嵌套起来就是内存炸弹）。真 feed 里不会有这两种声明，所以更像拿错了东西。"
        )
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as err:
        raise WebError(f"搜索结果是 XML，但解析不了：{err}") from err

    results: list[dict[str, Any]] = []
    for item in root.iter("item"):
        url = _item_text(item, "link").strip()
        name = plain_text(_item_text(item, "title"))
        if not url or not name:
            continue
        results.append(
            {
                "title": name,
                "url": url,
                "snippet": plain_text(_item_text(item, "description")),
                "published": _item_text(item, "pubDate").strip(),
                "engines": ["bing"],
            }
        )
        if len(results) >= limit:
            break
    return results


def _item_text(item: Any, tag: str) -> str:
    """取一个条目的某个子标签的**全部**文本（含子标签、以及子标签后面的尾巴）。

    **不能用 ``findtext``**：它只回 ``element.text``，也就是第一个子元素**之前**那一段。
    于是 ``<description>看 <b>这里</b> 那里</description>`` 会被静默截成"看" —— 不报错、
    不空手，就是少字，最难发现的那种。RSS 摘要里带行内标签是常态，所以这里走 ``itertext``。
    """
    node = item.find(tag)
    if node is None:
        return ""
    return "".join(node.itertext())


def parse_searxng_results(payload: Any, limit: int) -> list[dict[str, Any]]:
    """SearXNG 的 ``/search?format=json`` 响应 -> 与 :func:`parse_rss_results` 同一形状。

    字段名照 ``searxng-mcp/src/types.ts`` 的 ``SearxResult``：``title`` / ``url`` / ``content``
    （摘要）/ ``engine`` / ``engines``（同一结果被哪些引擎认出来）/ ``publishedDate``。

    形状不对（不是 object、没有 ``results`` 列表）就**报错**：那说明这个地址根本不是 SearXNG，
    或者它没开 JSON 格式 —— 两种情况都该让用户看到确切原因，而不是回一份空结果。
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise WebError(
            "这个地址回的不是 SearXNG 的 JSON —— 要么它不是 SearXNG，要么它的 settings.yml 里"
            "没把 json 加进 search.formats（默认只开 html）。"
        )
    results: list[dict[str, Any]] = []
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        title = item.get("title")
        if not isinstance(url, str) or not url.strip():
            continue
        if not isinstance(title, str) or title.strip() == "":
            continue
        engines = item.get("engines")
        if not isinstance(engines, list):
            engine = item.get("engine")
            engines = [engine] if isinstance(engine, str) and engine else []
        results.append(
            {
                "title": plain_text(title),
                "url": url.strip(),
                "snippet": plain_text(item.get("content") or ""),
                "published": (
                    item.get("publishedDate")
                    if isinstance(item.get("publishedDate"), str)
                    else ""
                ),
                "engines": [name for name in engines if isinstance(name, str)],
            }
        )
        if len(results) >= limit:
            break
    return results


def searxng_extras(payload: Any) -> dict[str, Any]:
    """SearXNG 的旁路信息：直接答案 / 信息框 / 拼写纠正 / 搜索建议。

    形状照 ``searxng-mcp/src/types.ts`` 的 ``SearxResponse`` 与 ``SearxMeta``。它那儿的注释
    明说 answers 与 corrections "have been both strings and objects"（版本之间两种都出现过），
    所以两种形状都认。

    **为什么值得单独捞出来**：这些比十条普通结果更值钱。有些查询（"某软件现在的版本是多少"、
    "光速是多少"）SearXNG 直接从计算器 / Wikidata 给出答案，模型拿到就不用再点开任何链接。
    ``corrections`` 也有用：它是在说"你拼错了，其实想问这个"。

    返回值里**空的那几样不放进去**（省模型的 token）；四样全空就回空 dict。
    """
    if not isinstance(payload, dict):
        return {}

    answers: list[dict[str, str]] = []
    for raw in payload.get("answers") or []:
        if isinstance(raw, str):
            if raw.strip():
                answers.append({"answer": plain_text(raw), "url": ""})
        elif isinstance(raw, dict):
            text = raw.get("answer") or raw.get("content") or ""
            if isinstance(text, str) and text.strip():
                answers.append({"answer": plain_text(text), "url": str(raw.get("url") or "")})

    infoboxes: list[dict[str, str]] = []
    for raw in payload.get("infoboxes") or []:
        if not isinstance(raw, dict):
            continue
        content = raw.get("content")
        if not isinstance(content, str) or content.strip() == "":
            continue
        links = raw.get("urls")
        first = links[0] if isinstance(links, list) and links and isinstance(links[0], dict) else {}
        infoboxes.append(
            {
                "title": plain_text(str(raw.get("infobox") or "")),
                "content": plain_text(content),
                "url": str(first.get("url") or ""),
            }
        )

    corrections: list[str] = []
    for raw in payload.get("corrections") or []:
        if isinstance(raw, str) and raw.strip():
            corrections.append(plain_text(raw))
        elif isinstance(raw, dict) and isinstance(raw.get("title"), str) and raw["title"].strip():
            corrections.append(plain_text(raw["title"]))

    suggestions = [
        plain_text(item)
        for item in (payload.get("suggestions") or [])
        if isinstance(item, str) and item.strip()
    ]

    extras: dict[str, Any] = {}
    for key, value in (
        ("answers", answers),
        ("infoboxes", infoboxes),
        ("corrections", corrections),
        ("suggestions", suggestions),
    ):
        if value:
            extras[key] = value
    return extras


def canonical_url(url: str) -> str:
    """去重用的规范化键：主机名与 scheme 小写、去掉 fragment、去掉末尾斜杠。

    **刻意不做的事**：不排序查询参数（少数站上参数顺序有意义）、不剥 ``www.``
    （``www.example.com`` 与 ``example.com`` 确实是两台主机）、不跟跳转（那要联网）。
    宁可漏掉几个重复，也别把两条**不同**的结果折成一条 —— 少给模型一条线索，
    比给它一条错的强。
    """
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), (parts.hostname or "").lower(), path, parts.query, ""))


def dedupe(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 :func:`canonical_url` 去重，**保留先出现的那条**。

    出处：searxng-mcp 合并"原查询 + 扩展查询"的结果时就是进一个 ``Set`` 保首个
    （``searxng-mcp/src/search.ts`` 的 merge 段，按 ``r.url`` 原样比较）。这里把键换成
    规范化网址，因为同一个页面换后端 / 换引擎回来时会带上不同的尾斜杠与 fragment。

    被丢掉的那条**不会白丢**：它的引擎名并进保留项的 ``engines``（那是"这条结果被哪几个引擎
    同时认出来"的信号），保留项缺摘要或日期时也用它补。
    """
    kept: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for item in results:
        key = canonical_url(str(item.get("url", "")))
        head = seen.get(key)
        if head is not None:
            names = list(head.get("engines") or [])
            for name in item.get("engines") or []:
                if name not in names:
                    names.append(name)
            head["engines"] = names
            for field in ("snippet", "published"):
                if not head.get(field) and item.get(field):
                    head[field] = item[field]
            continue
        copy = dict(item)
        seen[key] = copy
        kept.append(copy)
    return kept


#: 新鲜度衰减的时间常数（天）。照抄 searxng-mcp ``recencyScore`` 里的 ``/ 90``。
#:
#: 注意它是**时间常数**不是半衰期：90 天前的分是 ``1/e ≈ 0.37``，真正的半衰期是
#: ``90 * ln2 ≈ 62`` 天。命名照这个事实写，免得以后有人按"半衰期"去改。
RECENCY_TAU_DAYS = 90.0

#: 新鲜度分的加权。照抄 searxng-mcp ``config.ts`` 的 ``RERANK_RECENCY_WEIGHT`` 默认值 0.15。
RECENCY_WEIGHT = 0.15


def recency_score(date_text: str, *, now: datetime | None = None) -> float:
    """新鲜度分 ``exp(-ageDays / 90)``，落在 ``(0, 1]``。

    照抄 searxng-mcp 的 ``recencyScore``（``searxng-mcp/src/reranker.ts``）：**缺失 / 解不出来 /
    未来日期一律返回 0**。0 的含义是"不参与加权"（中性），不是"很旧"（惩罚）——
    它连未来日期都归到 0，就是不肯让"时间看起来新"这件事自己变成加分项。
    """
    moment = parse_date(date_text)
    if moment is None:
        return 0.0
    current = now or datetime.now(timezone.utc)
    age_days = (current - moment).total_seconds() / 86400.0
    if age_days < 0:
        return 0.0
    return math.exp(-age_days / RECENCY_TAU_DAYS)


def rerank(results: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """按"相关性 + 新鲜度"重排后取前 ``limit`` 条。

    出处与**偏离**（这条偏离必须说清楚）：

    * 出处：searxng-mcp 的 ``rerank`` 算 ``relevance_score + RERANK_RECENCY_WEIGHT *
      recencyScore(publishedDate)``，其中 ``relevance_score`` 来自它自带的**交叉编码器**
      （``RERANKER_URL`` 指的外部服务）。
    * 偏离：本仓不引外部服务，所以没有那个分数。相关性改用**上一层已经排好的顺序**当代理：
      ``relevance = (n - rank) / n``（第一条 1.0，最后一条 ``1/n``）。所以新鲜度只起**微调**
      作用 —— 最多挪动约 1.5 个档位，不会把源排序整个推翻。这是有意的：搜索引擎的第一条
      通常确实最相关，无差别按时间排会把相关性丢掉。它那边靠交叉编码器保相关性，
      这边只能靠不改动源顺序来保。

    一条日期都没有时（recency 全是 0），结果与入参**顺序完全一致**。
    """
    count = len(results)
    if count == 0:
        return []
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for rank, item in enumerate(results):
        relevance = (count - rank) / count
        combined = relevance + RECENCY_WEIGHT * recency_score(str(item.get("published") or ""))
        # 带上 rank 是为了让排序**稳定**：分数相同时仍按原顺序，不靠 sort 的偶然行为。
        scored.append((combined, rank, item))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [item for _combined, _rank, item in scored[:limit]]


__all__ = [
    "RECENCY_TAU_DAYS",
    "RECENCY_WEIGHT",
    "canonical_url",
    "dedupe",
    "parse_date",
    "parse_rss_results",
    "parse_searxng_results",
    "plain_text",
    "recency_score",
    "rerank",
    "searxng_extras",
]
