"""``robots.txt`` 的最小解析与判定 —— 纯函数，**不碰网络**。

**为什么要它**：``web__crawl`` 会自己顺着链接往下走，"抓多少页"不再由模型逐次决定，而是由
一次调用决定 —— 那就必须自己先问一句"这站允许我走哪里"。逮着链接就抓的爬虫既不礼貌，
也容易被封掉整个 IP，而封了以后 ``web__fetch`` 也没法用了。

**实现的取舍**（说清边界，免得被当成完整实现）：

* 只实现 ``User-agent`` / ``Disallow`` / ``Allow`` 三条（外加注释与空行）。``Sitemap`` /
  ``Crawl-delay`` / ``Request-rate`` 一律忽略 —— 前两个对"读几页文档"没用，``Crawl-delay``
  则被 :data:`comfy_studio.web._CRAWL_CONCURRENCY` 那个并发上限覆盖了。
* 通配符 ``*`` 与结尾 ``$`` **支持**（Google 的扩展，现在绝大多数站都按它写）。
* 组匹配只认 ``User-agent: *``。用"我们自己的 UA 名"去匹配是不可靠的：``robots.txt`` 里的
  名字是爬虫**自称**的名字，而 ``web__fetch`` 用的是浏览器 UA（见
  :data:`comfy_studio.web.USER_AGENT` 那段），按它匹配等于放弃 ``*`` 组、
  变成"什么规则都没读到" —— 比老老实实按 ``*`` 办更糟。
* **取不到 robots.txt**（404 / 连不上）一律当"全都允许"。这是通行做法（RFC 9309 也说
  "不可达"不构成禁止），而且反过来说"取不到就整站封禁"会让那些压根没写 robots.txt 的站
  （多数个人文档站就是这样）完全用不了。

判定用的是 Google 那套"**最长匹配优先**"：命中的规则里取 pattern 最长的；长度相同时
``Allow`` 赢。
"""

from __future__ import annotations

import re

#: ``Disallow:`` / ``Allow:`` 后面的值 -> 正则。``*`` 是通配，结尾 ``$`` 是锚定。
def _compile(rule: str) -> re.Pattern[str] | None:
    value = rule.strip()
    if value == "":
        return None
    body = re.escape(value).replace(r"\*", ".*")
    # ``re.escape`` 会把 ``$`` 转义成 ``\$``；只有出现在**结尾**才是锚定符。
    if body.endswith(r"\$"):
        body = body[:-2] + "$"
    return re.compile("^" + body)


class RobotsRules:
    """一组已解析的规则。:meth:`parse` 建，:meth:`allows` 问。"""

    __slots__ = ("_rules",)

    def __init__(self, rules: list[tuple[bool, re.Pattern[str], int]] | None = None) -> None:
        # 每项是 (是否允许, 编译好的正则, 该规则的字符长度) —— 长度用于"最长匹配优先"。
        self._rules: list[tuple[bool, re.Pattern[str], int]] = rules or []

    @classmethod
    def parse(cls, text: str, *, user_agent: str = "*") -> "RobotsRules":
        """解析 ``robots.txt`` 文本。空文本 -> 全允许（等于"没有规则"）。"""
        rules: list[tuple[bool, re.Pattern[str], int]] = []
        applies = False
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, _, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()

            if field == "user-agent":
                # 一条 ``User-agent`` 起一个新组；只有 ``*``（或显式给了同名 agent）的组才算数。
                applies = value == "*" or value.lower() == user_agent.lower()
                continue
            if not applies:
                continue
            if field == "disallow":
                # ``Disallow:`` 空值表示"不限制任何路径"，规范这么写，不是笔误。
                compiled = _compile(value)
                if compiled is not None:
                    rules.append((False, compiled, len(value)))
            elif field == "allow":
                compiled = _compile(value)
                if compiled is not None:
                    rules.append((True, compiled, len(value)))
        return cls(rules)

    def allows(self, path: str) -> bool:
        """这条路径允许抓吗。没有规则命中就允许。"""
        if not path:
            path = "/"
        if not path.startswith("/"):
            path = "/" + path
        best_length = -1
        best_allow = True
        for allow, pattern, length in self._rules:
            if not pattern.match(path):
                continue
            # 更长的规则赢；一样长时 Allow 赢（Google 规则，不是"后写的赢"）。
            if length > best_length or (length == best_length and allow and not best_allow):
                best_length = length
                best_allow = allow
        return best_allow

    def allows_url(self, url: str) -> bool:
        """按完整地址判（只取其中的路径与查询串）。"""
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        return self.allows(target)

    def __len__(self) -> int:
        return len(self._rules)


__all__ = ["RobotsRules"]
