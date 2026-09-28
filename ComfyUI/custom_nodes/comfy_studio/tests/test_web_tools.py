"""引擎侧的联网工具：工具表怎么挂、失败了长什么样、开关认哪些值。

**算法本身**（正文抽取、搜索结果去重重排、robots 匹配）的用例在宿主侧那份
``Comfy-Desktop/lib/comfy_studio/tests/test_web.py`` 里 —— 那四个纯算法模块是两边逐字相同（行尾
不计，理由见 ``SharedModuleDriftTest.test_shared_modules_are_identical``）的副本，用例也就没
必要抄两份。这个文件盯的是**引擎侧独有的那部分**：装配、开关、与 MCP 协议
的形状对接，外加一条"副本没被改歪"的守卫（见 :class:`SharedModuleDriftTest`）。
工具表在真进程里的样子（含环境变量开关）由 ``test_mcp_stdio.py`` 端到端守。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import Any

from ..mcp.server import web_banner_note
from ..mcp.tools import NO_WEB_ENV, SEARCH_URL_ENV, SEARXNG_ENV, build_tools, web_config, web_enabled
from ..skills import SkillRegistry
from ..web import (
    BING_SEARCH_URL,
    SEARCH_BACKEND_BING,
    SEARCH_BACKEND_SEARXNG,
    WEB_TOOLS,
    WebConfig,
    WebError,
    WebFetcher,
)
from .support import FakeEngine, host_module_dir

PACKAGE_DIR = Path(__file__).resolve().parents[1]  # .../custom_nodes/comfy_studio

#: 两边逐字节相同的四个纯算法模块（改一个就得照着改另一个，见 comfy_studio.web 的模块说明）。
SHARED_MODULES = ("webdom.py", "weberror.py", "websearch.py", "webrobots.py")

#: 两边逐字相同的**函数 / 方法**（``web.py`` 整体是故意有差别的，见下面那条用例）。
#:
#: 名单不是照着"看着像共享"编的，是拿两个文件按 ``ast`` 逐段比出来、当前确实逐字相同的那批：
#: 地址闸门与入口校验（``blocked_reason`` / ``assert_public`` / ``_is_ip_literal`` / ``parse_url`` /
#: ``check_search_url`` / ``check_search_urls``）、
#: 抓取与解包（``_request`` / ``_headers`` / ``_session`` / ``decode_body`` / ``sniff_charset`` /
#: ``_looks_like_html`` / ``html_to_text`` / ``_json_body`` / ``_log``）、robots 与爬行本体
#: （``_robots_rules`` / ``_crawl_page`` / ``_crawl_walk``）、参数夹取那三个小工具、
#: 搜索的两处报错文案（``_empty_results_message`` / ``_all_bases_failed_message`` ——
#: 多实例全挂时"逐个说明原因"的那句就在后者里，两边报的话必须一字不差），
#: 以及搜索主体（``_search_setup`` 校验入参并解析配置 / ``_search_with_failover`` 挨个入口试、
#: 把失败汇总成一句话 —— 这两段原先生长在 ``search`` 肚子里，而 ``search`` 是不受管的）。
#: **刻意不在名单里**的：``__init__`` / ``search`` / ``fetch`` / ``crawl`` / ``close``
#: （宿主那份要接取消令牌与 MCP 外壳、引擎那份不要 —— 所以 ``search`` 现在只剩一层壳，
#: 里面能说错的部分都抽进了上面两个方法）、``_validate``（两边最后一行抛的错类不同：
#: 引擎侧 ``WebError`` 由 ``mcp/tools.py`` 接住，宿主侧 ``McpError`` 由 ``WebClient.call_tool``
#: 接住 —— 各自都有人在等，合并没有意义）。改名单要写清理由，别顺手把报警器调哑。
#: 另注：这个守卫只管"改了一边忘了另一边"。**两份一起改成错的**它当然看不出来（那已经不叫
#: 漂移了）—— 那种错得靠宿主侧的行为用例拦：同一份语义两边都写歪，只有跑起来才现形。
SHARED_METHODS = (
    "_headers",
    "_request",
    "_session",
    "_robots_rules",
    "_crawl_page",
    "_crawl_walk",
    "_searxng_bases",
    "_search_bases",
    "_search_setup",
    "_search_with_failover",
    "_fetch_body",
)
SHARED_FUNCTIONS = (
    "blocked_reason",
    "assert_public",
    "parse_url",
    "_is_ip_literal",
    "check_search_url",
    "check_search_urls",
    "decode_body",
    "sniff_charset",
    "_looks_like_html",
    "html_to_text",
    "_json_body",
    "_log",
    "_bounded_count",
    "_bounded_flag",
    "_empty_results_message",
    "_all_bases_failed_message",
)

#: ``web.py`` 顶层常量里**不逐字比**的那两个：
#:
#: * ``__all__`` —— 公开名清单天然不同（宿主多 ``WebClient``／``WebServerConfig``，引擎多
#:   ``WebToolSpec`` / ``call_web_tool`` / ``qualified_name``），两份安装各自对外的面本来就
#:   该各写各的（对外形状对齐由 MCP 那一层管）。**不代比**。
#: * ``WEB_TOOLS`` —— 两边内容一字不差，差的只是那个 dataclass 的名字（引擎侧
#:   ``WebToolSpec``、宿主侧 ``_Spec``），而名字写在每一条构造里，逐字比必然红。它改成
#:   **按结构比**（:func:`_tool_definitions`）：名字 / 描述 / 参数表照旧逐字对，只是不看构造语法。
#:
#: 其余同名常量都要逐字相同。名单是拿两边现状比出来的，不是照着"看着像共享"编的。
WEB_CONSTANT_EXCEPTIONS = ("__all__", "WEB_TOOLS")


def _pieces_of_source(source: str) -> dict[str, list[str]]:
    """把源码文本里每个顶层函数与类方法的源码切出来，键是 ``"function:名"`` / ``"method:名"``。

    用 ``ast`` 而不是按缩进切：多行签名、嵌套括号、装饰器都得以节点边界为准。键只带方法名不带
    类名 —— 两边类名可能各自改，这不是我们要盯的东西（要盯的是**实现**有没有被改歪）。

    **一个键对着一串实现**：两个类各有一个同名方法时（``agent/types.py`` 的
    ``ToolCall.to_openai`` 与 ``ChatMessage.to_openai`` 就是这样），只留一个会把另一个静默漏掉
    —— 漏掉的正好是"改了一边没改另一边"时最该响的那个；更阴的是**先出现的那一份**被改时会
    被后面那份盖住，"只留最后一份"的写法下这条漂移是隐形的（见
    :class:`SharedPiecesSelfCheckTest`）。比的是排序后的整串，所以同名方法的出现顺序不参与结论。

    收**文本**而不是 ``Path``：切得准不准是这把刀自己的事，合成源码就能验，不必往磁盘上摆
    临时文件（见 :class:`SharedPiecesSelfCheckTest`）。
    """
    lines = source.splitlines()
    pieces: dict[str, list[str]] = {}

    def segment(node: ast.AST) -> str:
        # 从 ``lineno`` 到 ``end_lineno``：装饰器在 ``decorator_list`` 里，天然不在其中。
        return "\n".join(lines[node.lineno - 1 : node.end_lineno])

    def add(key: str, node: ast.AST) -> None:
        pieces.setdefault(key, []).append(segment(node))

    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(f"function:{node.name}", node)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(f"method:{child.name}", child)
    return pieces


def _pieces_of(path: Path) -> dict[str, list[str]]:
    """``path`` 的部件表（怎么切见 :func:`_pieces_of_source`）。

    ``read_text`` 用的是通用换行，所以行尾本来就不参与比对（理由同
    :meth:`SharedModuleDriftTest.test_shared_modules_are_identical`）。
    """
    return _pieces_of_source(path.read_text(encoding="utf-8"))


def _top_level_constants(source: str) -> dict[str, str]:
    """切出顶层 ``NAME = ...`` / ``NAME: T = ...`` 的原样源码，键是名字（怎么用见
    :meth:`SharedModuleDriftTest.test_shared_web_constants_are_identical`）。

    只认**赋值**：``import`` / ``class`` / ``def`` 不是常量（函数与类方法另由
    :func:`_pieces_of_source` 盯着），模块级 docstring 也不是。``a = b = 1`` 这种多重赋值
    跳过 —— 名字不落在单个 ``Name`` 上，硬收进来得先替它决定"算谁的"；本仓 ``web.py``
    里没有这种写法，所以这是"没遇到"，不是"放过了一个已知的洞"。
    """
    lines = source.splitlines()
    out: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if len(targets) == 1 and isinstance(targets[0], ast.Name):
            out[targets[0].id] = "\n".join(lines[node.lineno - 1 : node.end_lineno])
    return out


def _tool_definitions(source: str, constant: str) -> list[str]:
    """把 ``WEB_TOOLS`` 那种"一串工具定义"折成**不含构造类名**的结构化文本表。

    为什么要绕开类名：引擎侧那个 dataclass 叫 ``WebToolSpec``、宿主侧叫 ``_Spec``（宿主没把
    它放进 ``__all__``），名字写在每一条构造里，逐字比这个常量必然红 —— 而两边真正该一致的是
    **给模型看的东西**：每条工具的 ``name`` / ``description`` / ``input_schema``。所以按
    ``ast`` 取每个 ``Call`` 的关键字，各自 ``dump`` 成文本（f-string 里嵌的
    ``{DEFAULT_FETCH_CHARS}`` 这类名字也照原样参与比对，正是想要的效果）。

    只认顶层 ``constant`` 指向的 ``Tuple`` / ``List``，每项必须是 ``Call``；别的形状直接报
    ``AssertionError`` —— 形状改了就该有人来看一眼，而不是悄悄回一张空表让这条守卫变绿。
    """
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        if targets[0].id != constant:
            continue
        value = node.value
        assert isinstance(value, (ast.Tuple, ast.List)), f"{constant} 不再是元组/列表了"
        out: list[str] = []
        for item in value.elts:
            assert isinstance(item, ast.Call), f"{constant} 里出现不是构造调用的项"
            out.append(
                "\n".join(f"{kw.arg}={ast.dump(kw.value, annotate_fields=False)}" for kw in item.keywords)
            )
        return out
    raise AssertionError(f"顶层找不到常量 {constant}")


def _without_module_docstring(source: str) -> str:
    """去掉模块级 docstring 之后剩下的源码（其余一行不动）。

    两份副本允许差的只有模块自己那段说明 —— 各自交代来龙去脉、彼此指路，这本来就该各写各的；
    代码部分不该差。用 ``ast`` 取 docstring 的行范围，而不是去正文里找三引号：docstring 本身
    含引号、含转义、含代码示例时，按文本切会切歪，而切歪的后果是"比到了不该比的地方"。
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    if tree.body:
        first = tree.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            del lines[first.lineno - 1 : first.end_lineno]
    return "\n".join(lines)


class SharedPiecesSelfCheckTest(unittest.TestCase):
    """上面那几把刀自己的用例（合成源码，不需要宿主落点，永远跑）。

    :class:`SharedModuleDriftTest` 比的是仓库里那两份文件，"两边一致"就绿。危险在于**刀钝了
    也绿**：片段少切一段、docstring 多切一行，比的范围就悄悄变小，而报出来的仍然是 OK。这些
    用例拿编出来的源码把每条判断都走一遍 —— 该比出来的差别要比得出来，该放过的地方要放过。
    """

    #: 两个类各有一个同名方法：第一份被改、第二份没改。
    _TWO_COPIES = (
        "class A:\n"
        "    def to_openai(self):\n"
        "        return {RETURN}\n"
        "\n"
        "\n"
        "class B:\n"
        "    def to_openai(self):\n"
        "        return 2\n"
    )

    def test_both_copies_of_a_shared_name_are_kept(self) -> None:
        """同名方法得两份都在 —— 只留一份就等于把另一半交给运气。"""
        pieces = _pieces_of_source(self._TWO_COPIES.replace("{RETURN}", "1"))
        self.assertEqual(len(pieces["method:to_openai"]), 2)

    def test_drift_in_the_first_copy_is_still_visible(self) -> None:
        """**先出现的那一份**被改了也要比得出来。

        这是"一个键对着一串实现"的全部理由：写成 ``pieces[key] = segment(node)``（后者覆盖
        前者）时，两个类的 ``to_openai`` 只剩 B 那份，于是 A 被改歪完全隐形 —— 而 A 正好是
        ``ChatMessage.to_openai``、B 是 ``ToolCall.to_openai`` 时，漏掉的正是"改了一边"的那半。
        """
        mine = _pieces_of_source(self._TWO_COPIES.replace("{RETURN}", "1"))
        theirs = _pieces_of_source(self._TWO_COPIES.replace("{RETURN}", "9"))
        self.assertNotEqual(
            sorted(mine["method:to_openai"]),
            sorted(theirs["method:to_openai"]),
            "第一份被改了却比不出来：切片段那层把同名方法盖成一个了",
        )

    def test_a_module_docstring_may_differ(self) -> None:
        """两份副本允许各写各的说明：说明不同不算漂移。"""
        mine = '"""引擎侧：这份没有取消令牌。"""\n\nimport json\n\n\ndef f():\n    return 1\n'
        theirs = '"""宿主侧：这份接了取消令牌。"""\n\nimport json\n\n\ndef f():\n    return 1\n'
        self.assertEqual(_without_module_docstring(mine), _without_module_docstring(theirs))

    def test_code_right_after_the_docstring_is_still_compared(self) -> None:
        """放过的**只有**那段说明：紧跟其后的正文照比（多切一行就是把第一段代码也放过）。"""
        mine = '"""说明。"""\n\nimport json\n\n\ndef f():\n    return 1\n'
        theirs = '"""说明。"""\n\nimport json\n\n\ndef f():\n    return 2\n'
        self.assertNotEqual(_without_module_docstring(mine), _without_module_docstring(theirs))

    def test_a_file_without_a_docstring_is_left_alone(self) -> None:
        """没有 docstring 就一行都不动（``tree.body[0]`` 是 ``import`` 时别把它当成说明删掉）。"""
        source = "import json\n\n\ndef f():\n    return 1"  # 不留尾换行：splitlines + join 才原样回来
        self.assertEqual(_without_module_docstring(source), source)

    def test_constants_are_cut_by_name_and_annotation(self) -> None:
        """顶层常量只认赋值：带注解的算，函数体里的不算。"""
        source = "A = 1\nB: int = 2\n\n\ndef f():\n    inner = 3\n    return inner\n"
        self.assertEqual(sorted(_top_level_constants(source)), ["A", "B"])

    def test_a_single_sided_constant_change_is_visible(self) -> None:
        """一边把上限调大就要比得出来 —— 调常量正是"两边都能跑、用例还都绿"的那类改动。"""
        mine = _top_level_constants("MAX_FETCH_CHARS = 20000\n")["MAX_FETCH_CHARS"]
        theirs = _top_level_constants("MAX_FETCH_CHARS = 60000\n")["MAX_FETCH_CHARS"]
        self.assertNotEqual(mine, theirs)

    def test_tool_definitions_ignore_the_dataclass_name(self) -> None:
        """工具定义按结构比：dataclass 叫 ``WebToolSpec`` 还是 ``_Spec`` 都不算差异，
        描述差一个字则必须红（那才是模型看到的东西）。"""
        one = 'WEB_TOOLS: tuple[Any, ...] = (WebToolSpec(name="fetch", description="抓一页"),)\n'
        other = 'WEB_TOOLS = (_Spec(name="fetch", description="抓一页"),)\n'
        self.assertEqual(
            _tool_definitions(one, "WEB_TOOLS"), _tool_definitions(other, "WEB_TOOLS")
        )
        drifted = 'WEB_TOOLS = (_Spec(name="fetch", description="抓两页"),)\n'
        self.assertNotEqual(
            _tool_definitions(one, "WEB_TOOLS"), _tool_definitions(drifted, "WEB_TOOLS")
        )

    def test_a_missing_tool_table_is_an_error_not_an_empty_list(self) -> None:
        """找不到那个常量必须报错：回空表会让"两边都没了"看起来像"两边一致"。"""
        with self.assertRaises(AssertionError):
            _tool_definitions("X = ()\n", "WEB_TOOLS")


_HOST_DIR = host_module_dir()


class FakeWebFetcher:
    """只记录"被怎么调的"的假句柄：这里测的是装配与错误形状，不是抓取本身。"""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.error = error

    async def _respond(self, name: str, payload: Any, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, (args, kwargs)))
        if self.error is not None:
            raise self.error
        return payload

    async def search(self, query: Any, **kwargs: Any) -> Any:
        return await self._respond("search", {"query": query, "results": []}, query, **kwargs)

    async def fetch(self, url: Any, **kwargs: Any) -> Any:
        return await self._respond("fetch", {"url": url, "text": "正文"}, url, **kwargs)

    async def crawl(self, url: Any, **kwargs: Any) -> Any:
        return await self._respond("crawl", {"start": url, "pages": []}, url, **kwargs)


def registry() -> SkillRegistry:
    """空 skill 视图：这里的用例不关心 skill 那几把工具。"""
    return SkillRegistry.in_memory(())


def web_tools_of(fetcher: FakeWebFetcher) -> dict[str, Any]:
    """按名字取那三把联网工具（顺带验证它们真的在表里，而且名字对得上）。"""
    tools = build_tools(FakeEngine(), registry(), fetcher)
    return {t.name: t for t in tools if t.name.startswith("web__")}


class WebEnabledTest(unittest.TestCase):
    def test_default_is_on(self) -> None:
        self.assertTrue(web_enabled({}))

    def test_the_name_is_the_one_the_host_copies(self) -> None:
        """开关名是**跨进程契约**：宿主那份照抄了这个字面量
        （``Comfy-Desktop/lib/comfy_studio/mcp/config.py`` 的 ``ENGINE_NO_WEB_ENV`` —— 它没法
        import 引擎的代码，只能抄一份）。只改这里一行，两边用例都还是绿的：引擎不再认那个
        变量，于是把联网工具又挂回来，而面板里就多出第二套同能力工具。钉住字面量，
        谁改名至少这一条先红。
        """
        self.assertEqual(NO_WEB_ENV, "COMFY_NO_WEB")

    def test_only_real_truthy_values_turn_it_off(self) -> None:
        for raw in ("1", "true", "TRUE", " yes ", "on"):
            with self.subTest(raw=raw):
                self.assertFalse(web_enabled({NO_WEB_ENV: raw}))

    def test_unrelated_values_leave_it_on(self) -> None:
        """``COMFY_NO_WEB=0`` 不算关：默认就是开，写反了的人多半想关 —— 但这里不猜他的意思，
        只按写明的规则办（只认 1/true/yes/on），要关就老老实实写 1。"""
        for raw in ("", "0", "false", "no", "off", "nope"):
            with self.subTest(raw=raw):
                self.assertTrue(web_enabled({NO_WEB_ENV: raw}))


class SearchBackendFromEnvTest(unittest.TestCase):
    """``COMFY_SEARXNG_URL`` → 搜索后端。没给变量的机器必须走默认那条不用部署的路。

    这一条的分量在于**不对称**：引擎侧换了后端、面板那行小字却还说"走必应"，用户就会照着
    一个错的结论去排查。所以配置只有一个入口（:func:`web_config`），横幅与面板的机制也各自
    只读它一次。
    """

    def test_without_the_variable_it_is_the_builtin_backend(self) -> None:
        config = web_config({})
        self.assertEqual(config.search_backend, SEARCH_BACKEND_BING)
        self.assertEqual(config.searxng_url, "")

    def test_whitespace_only_does_not_count_as_configured(self) -> None:
        """只敲了空格/换行的那种"填了"：当没填。否则会去连一个空地址，还报"自建实例连不上"，
        把用户引到"我的 SearXNG 坏了"这条错路上去。"""
        for raw in ("", "   ", "\t", "\n"):
            with self.subTest(raw=raw):
                self.assertEqual(web_config({SEARXNG_ENV: raw}).search_backend, SEARCH_BACKEND_BING)
                # 换入口那个变量同一个规矩：空串不算"配了"，否则会去拼一个 "?q=..." 的空地址。
                self.assertEqual(web_config({SEARCH_URL_ENV: raw}).search_url, BING_SEARCH_URL)

    def test_the_address_is_kept_verbatim_after_trimming(self) -> None:
        """多个实例是**在 web.py 里**才拆的：这里原样带着（含逗号），不提前拆一遍 ——
        两份地方各拆一次，早晚会拆得不一样。"""
        config = web_config({SEARXNG_ENV: "  http://127.0.0.1:8888 , https://searx.be  "})
        self.assertEqual(config.search_backend, SEARCH_BACKEND_SEARXNG)
        self.assertEqual(config.searxng_url, "http://127.0.0.1:8888 , https://searx.be")

    def test_the_fetcher_built_from_it_reports_the_same_backend(self) -> None:
        """配置到句柄这一段也要通：横幅与面板报的是 ``fetcher.config``，中间接错线看不出来。"""
        fetcher = WebFetcher(web_config({SEARXNG_ENV: "http://127.0.0.1:8888"}))
        self.assertEqual(fetcher.config.search_backend, SEARCH_BACKEND_SEARXNG)
        self.assertEqual(fetcher.config.searxng_url, "http://127.0.0.1:8888")

    def test_the_entry_point_variable_swaps_the_entry_not_the_backend(self) -> None:
        """``COMFY_WEB_SEARCH_URL`` 换的是"去哪儿问"，读法还是必应 RSS 那套。"""
        config = web_config({SEARCH_URL_ENV: "https://search.example.com/rss"})
        self.assertEqual(config.search_backend, SEARCH_BACKEND_BING)
        self.assertEqual(config.search_url, "https://search.example.com/rss")
        self.assertEqual(config.searxng_url, "")

    def test_the_entry_point_is_trimmed_of_whitespace_and_a_trailing_slash(self) -> None:
        """拼接处是 ``{入口}?q=``：留着尾斜杠就成了 ``.../rss/?q=``（多一层目录）。"""
        config = web_config({SEARCH_URL_ENV: "  https://search.example.com/rss/  "})
        self.assertEqual(config.search_url, "https://search.example.com/rss")

    def test_a_list_of_entry_points_keeps_every_one_of_them(self) -> None:
        """一串入口也是**原样带着**（与自建实例那份同一个规矩）：拆成多个 base 是 ``web.py``
        的活，这里只逐条校验、削掉空白与尾斜杠。"""
        config = web_config(
            {SEARCH_URL_ENV: "  https://a.example.com/rss/ ,  https://b.example.com/rss  "}
        )
        self.assertEqual(config.search_backend, SEARCH_BACKEND_BING)
        self.assertEqual(
            config.search_url, "https://a.example.com/rss, https://b.example.com/rss"
        )

    def test_a_list_without_one_valid_entry_is_refused(self) -> None:
        """只敲了逗号的那串：那不是"配了多个"，是压根没配，照旧拒掉 —— 免得去拼一个以
        逗号开头的 ``?q=`` 地址。"""
        for raw in (",", " , , "):
            with self.subTest(raw=raw):
                with self.assertRaises(WebError) as err:
                    web_config({SEARCH_URL_ENV: raw})
                self.assertIn("http(s)", str(err.exception))

    def test_a_malformed_entry_point_is_refused_at_assembly(self) -> None:
        """不给它猜（与 :func:`parse_url` 对模型给的网址一个口径）：报错里写清要什么形状。"""
        for raw in ("search.example.com", "file:///etc/passwd", "https://"):
            with self.subTest(raw=raw):
                with self.assertRaises(WebError) as err:
                    web_config({SEARCH_URL_ENV: raw})
                self.assertIn("http(s)", str(err.exception))

    def test_both_entry_points_are_refused_not_silently_one_of_them(self) -> None:
        """两个变量都设 = 自相矛盾。挑一个继续跑，另一个就成"设了却不生效"了。"""
        with self.assertRaises(WebError) as err:
            web_config(
                {SEARXNG_ENV: "http://127.0.0.1:8888", SEARCH_URL_ENV: "https://searx.be/"}
            )
        text = str(err.exception)
        self.assertIn(SEARXNG_ENV, text)
        self.assertIn(SEARCH_URL_ENV, text)

    def test_the_fetcher_built_from_the_entry_point_reports_it(self) -> None:
        """配置到句柄这一段也要通：横幅与面板报的是 ``fetcher.config``。"""
        fetcher = WebFetcher(web_config({SEARCH_URL_ENV: "https://search.example.com/rss"}))
        self.assertEqual(fetcher.config.search_backend, SEARCH_BACKEND_BING)
        self.assertEqual(fetcher.config.search_url, "https://search.example.com/rss")


class WebBannerNoteTest(unittest.TestCase):
    """就绪横幅那一截话：四种情况都得说清"能不能上网 / 走哪条路"。"""

    def test_off_says_which_switch_turned_it_off(self) -> None:
        self.assertIn(NO_WEB_ENV, web_banner_note(False, WebConfig()))

    def test_on_by_default_names_the_builtin_backend(self) -> None:
        note = web_banner_note(True, WebConfig())
        self.assertIn("必应", note)
        # 说清是 RSS 那条不用部署的路：用户看日志时不该以为自己缺个实例。
        self.assertIn("RSS", note)

    def test_self_hosted_backend_prints_the_address(self) -> None:
        config = WebConfig(search_backend=SEARCH_BACKEND_SEARXNG, searxng_url="http://127.0.0.1:8888")
        note = web_banner_note(True, config)
        self.assertIn("SearXNG", note)
        self.assertIn("http://127.0.0.1:8888", note, "日志里没地址就没法排障")

    def test_a_custom_entry_point_prints_the_entry(self) -> None:
        """换了入口就得把入口报出来 —— 与自建实例那条同一个理由：日志里没地址没法排障。"""
        note = web_banner_note(True, WebConfig(search_url="https://search.example.com/rss"))
        self.assertIn("https://search.example.com/rss", note)
        # 仍然是必应 RSS 那条路的形状：别让人以为换了后端。
        self.assertIn("RSS", note)

    def test_a_list_of_entry_points_is_printed_whole(self) -> None:
        """配了一串就把整串报出来：只写其中一个，排障的人会以为搜索只去那一个地方
        —— 与 ``host/info`` 报整串是同一条口径。"""
        config = WebConfig(
            search_url="https://a.example.com/rss, https://b.example.com/rss"
        )
        note = web_banner_note(True, config)
        self.assertIn("https://a.example.com/rss", note)
        self.assertIn("https://b.example.com/rss", note)
        self.assertIn("RSS", note)


class ToolSurfaceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()
        self.fetcher = FakeWebFetcher()

    def test_without_a_fetcher_the_table_is_unchanged(self) -> None:
        names = [t.name for t in build_tools(self.engine, registry())]
        self.assertEqual([n for n in names if n.startswith("web__")], [])

    def test_with_a_fetcher_the_three_web_tools_come_last(self) -> None:
        names = [t.name for t in build_tools(self.engine, registry(), self.fetcher)]
        self.assertEqual(names[-3:], ["web__search", "web__fetch", "web__crawl"])

    def test_schemas_and_descriptions_match_the_module_definitions(self) -> None:
        by_name = {t.name: t for t in build_tools(self.engine, registry(), self.fetcher)}
        for spec in WEB_TOOLS:
            with self.subTest(spec=spec.name):
                tool = by_name[f"web__{spec.name}"]
                self.assertEqual(tool.input_schema, spec.input_schema)
                self.assertEqual(tool.description, spec.description)

    async def test_search_returns_the_payload_as_json_text(self) -> None:
        result = await web_tools_of(self.fetcher)["web__search"].handler({"query": "sdxl 显存"})
        self.assertNotIn("isError", result)
        self.assertIn('"sdxl 显存"', result["content"][0]["text"])
        self.assertEqual(self.fetcher.calls[0][0], "search")

    async def test_fetch_passes_the_url_through(self) -> None:
        result = await web_tools_of(self.fetcher)["web__fetch"].handler(
            {"url": "https://example.com/a"}
        )
        self.assertNotIn("isError", result)
        name, (args, _kwargs) = self.fetcher.calls[0]
        self.assertEqual((name, args), ("fetch", ("https://example.com/a",)))

    async def test_web_error_becomes_an_is_error_result(self) -> None:
        """抓不动就是 ``isError`` 文本，交给模型自己换个做法 —— 与其它工具同一个口径。"""
        fetcher = FakeWebFetcher(error=WebError("example.com 是私有网段地址"))
        result = await web_tools_of(fetcher)["web__crawl"].handler({"url": "https://example.com/a"})
        self.assertIs(result.get("isError"), True)
        self.assertIn("是私有网段地址", result["content"][0]["text"])

    async def test_odd_numbers_and_flags_are_rejected_by_validate(self) -> None:
        """``_validate`` 管的是**计数与开关**：写错类型就报错，不许把请求发出去。"""
        tools = web_tools_of(self.fetcher)
        cases = (
            ("web__search", {"query": "a", "limit": 0}),
            ("web__search", {"query": "a", "limit": True}),
            ("web__fetch", {"url": "https://example.com", "max_chars": "一千"}),
            ("web__fetch", {"url": "https://example.com", "max_chars": 0}),
            ("web__crawl", {"url": "https://example.com", "max_pages": 0}),
            ("web__crawl", {"url": "https://example.com", "same_domain": "false"}),
        )
        for name, args in cases:
            with self.subTest(name=name, args=args):
                result = await tools[name].handler(args)
                self.assertIs(result.get("isError"), True, f"{name}{args} 该被判参数不合法")
        self.assertEqual(self.fetcher.calls, [], "参数不合法时不该真去抓")

    async def test_bad_urls_and_blank_query_fail_before_any_request(self) -> None:
        """网址形状与空 query 是**真句柄**在发请求之前挡的（``parse_url`` / ``search``），
        所以这里用真句柄验 —— 它们全都在建会话之前报错，不会出门，也就不会真联网。"""
        fetcher = WebFetcher()
        try:
            tools = {t.name: t for t in build_tools(self.engine, registry(), fetcher)}
            cases = (
                ("web__fetch", {"url": "ftp://example.com"}, "只支持 http"),
                ("web__fetch", {"url": "   "}, "非空字符串"),
                ("web__fetch", {}, "非空字符串"),
                ("web__fetch", {"url": "not a url"}, "只支持 http"),
                ("web__crawl", {"url": "https://:8080/x"}, "没有主机名"),
                ("web__search", {"query": "   "}, "非空字符串"),
            )
            for name, args, expected in cases:
                with self.subTest(name=name, args=args):
                    result = await tools[name].handler(args)
                    self.assertIs(result.get("isError"), True)
                    self.assertIn(expected, result["content"][0]["text"])
        finally:
            await fetcher.close()

    async def test_crawl_defaults_come_from_the_module(self) -> None:
        """只验"传下去了什么"：默认值属于 :mod:`comfy_studio.web` 的常量，不在这里另抄一份。"""
        from ..web import DEFAULT_CRAWL_DEPTH, DEFAULT_CRAWL_PAGES

        await web_tools_of(self.fetcher)["web__crawl"].handler({"url": "https://example.com"})
        name, (args, kwargs) = self.fetcher.calls[0]
        self.assertEqual(name, "crawl")
        self.assertEqual(args, ("https://example.com",))
        self.assertEqual(
            set(kwargs), {"max_pages", "max_depth", "max_chars", "same_domain"}
        )
        self.assertEqual(kwargs["max_pages"], DEFAULT_CRAWL_PAGES)
        self.assertEqual(kwargs["max_depth"], DEFAULT_CRAWL_DEPTH)
        self.assertIs(kwargs["same_domain"], True)

    async def test_crawl_caps_are_clamped_not_rejected(self) -> None:
        """超上限是**夹到上限**（与 limit / max_chars 同一个做法），不是报错。"""
        from ..web import MAX_CRAWL_DEPTH, MAX_CRAWL_PAGES

        await web_tools_of(self.fetcher)["web__crawl"].handler(
            {"url": "https://example.com", "max_pages": 999, "max_depth": 9}
        )
        _name, (_args, kwargs) = self.fetcher.calls[0]
        self.assertEqual(kwargs["max_pages"], MAX_CRAWL_PAGES)
        self.assertEqual(kwargs["max_depth"], MAX_CRAWL_DEPTH)


class TwoSidedLayoutTest(unittest.TestCase):
    """跨侧守卫的"出勤自检"：别让它整批悄悄跳过还显示 OK。

    :class:`SharedModuleDriftTest` 探测不到宿主落点时整组跳过 —— 对"引擎被单独装进另一台机器
    的 ComfyUI"那是正常情况。麻烦在于**同一个跳过也盖住了"本仓布局下探测坏了"**：那时几条守卫
    一条都不跑，输出却还是 ``OK``，正是"存在才跑 → 永远不跑 → 没人发现"的老路。

    这条用例**故意不带 skipUnless**：本仓布局在就要求守卫真的出勤；不在才按合法缺勤记一笔，
    并把探测到什么写进跳过理由。
    """

    def test_drift_guard_has_both_sides_when_the_repo_layout_is_there(self) -> None:
        # 父仓库里两份上游树并排放：<仓库根>/ComfyUI 与 <仓库根>/Comfy-Desktop。
        # PACKAGE_DIR 是 <仓库根>/ComfyUI/custom_nodes/comfy_studio，往上三层就是仓库根。
        host_tree = PACKAGE_DIR.parents[2] / "Comfy-Desktop"
        if not host_tree.is_dir():
            self.skipTest(
                f"没有与 ComfyUI/ 平级的宿主工作树（{host_tree}），"
                "引擎是单独安装的，跨侧守卫这轮不适用"
            )
        self.assertIsNotNone(
            _HOST_DIR,
            f"{host_tree} 在，却没认出宿主落点 —— 跨侧守卫会整批跳过而输出仍是 OK，"
            "先看 host_module_dir() 的探测",
        )


@unittest.skipUnless(
    _HOST_DIR is not None,
    "找不到宿主侧落点 Comfy-Desktop/lib/comfy_studio（引擎被单独安装时属于正常情况）",
)
class SharedModuleDriftTest(unittest.TestCase):
    """守卫"两边该逐字相同"的那部分别被改歪。

    这不是洁癖：引擎侧与宿主侧是**两份互不 import 的安装**（见 :mod:`comfy_studio.web` 的模块
    说明），修一个 bug 只改一边，另一边就会带着老行为继续跑，而且没有任何东西会报错。
    改法是"两边都改"，这几条用例就是那个"改漏了"的报警器。

    覆盖面按"两边该有多像"分三层：整份逐字相同（:data:`SHARED_MODULES`）、只放过模块 docstring
    （``agent/types.py``）、以及整体故意有差别而**部件**该一致（``web.py``）。某份文件归哪一层
    不是凭印象选的，是拿两边比出来的现状 —— 往里加文件之前先比一遍，再写名单与理由。
    """

    def test_shared_modules_are_identical(self) -> None:
        """四个纯算法模块两边逐字相同。

        **比的是文本不是裸字节**：行尾不算漂移。两边落在**不同的换行策略**下 ——
        宿主侧在 ``Comfy-Desktop/.gitattributes`` 的 ``* text=auto eol=lf`` 之下，
        而引擎侧那份住在被上游 gitignore 的 ``custom_nodes/`` 里，只受 ``core.autocrlf`` 摆布。
        同一个文件在两棵树上签出成 CRLF / LF 是**正常的**，拿裸字节比会在换台机器克隆之后
        报一个跟内容无关的假警 —— 而假警会训练人去忽略这条守卫，那才是真损失。
        """
        assert _HOST_DIR is not None
        for name in SHARED_MODULES:
            with self.subTest(module=name):
                # read_text 用通用换行：\r\n 与 \r 都折成 \n（要的就是这个）。
                theirs = (_HOST_DIR / name).read_text(encoding="utf-8")
                self.assertEqual(
                    (PACKAGE_DIR / name).read_text(encoding="utf-8"),
                    theirs,
                    f"{name} 与宿主侧那份不一致了：改副本时两边都要改"
                    f"（引擎侧 {PACKAGE_DIR / name}，宿主侧 {_HOST_DIR / name}）",
                )

    def test_shared_web_pieces_are_identical(self) -> None:
        """``web.py`` 整体是**故意有差别的**（引擎侧没有取消令牌，也没有宿主那套 MCP 外壳），
        但里面这些部件该逐字相同 —— 尤其是 ``_crawl_walk``：抓取的边界全在那儿。
        """
        assert _HOST_DIR is not None
        mine = _pieces_of(PACKAGE_DIR / "web.py")
        theirs = _pieces_of(_HOST_DIR / "web.py")
        for kind, name in [
            *(("method", n) for n in SHARED_METHODS),
            *(("function", n) for n in SHARED_FUNCTIONS),
        ]:
            with self.subTest(kind=kind, name=name):
                key = f"{kind}:{name}"
                self.assertIn(key, mine, f"引擎侧 web.py 里没有 {name}（改名了？改完要同步守卫名单）")
                self.assertIn(key, theirs, f"宿主侧 web.py 里没有 {name}（改名了？改完要同步守卫名单）")
                self.assertEqual(
                    sorted(mine[key]),
                    sorted(theirs[key]),
                    f"{kind} {name} 两边不一致了：改一边就要改另一边"
                    f"（引擎侧 {PACKAGE_DIR / 'web.py'}，宿主侧 {_HOST_DIR / 'web.py'}）",
                )

    def test_shared_web_constants_are_identical(self) -> None:
        """``web.py`` 顶层那些**行为参数**两边必须一致。

        上面那 27 个函数 / 方法守的是"算法有没有被改歪"，守不住常量：把 ``MAX_FETCH_CHARS`` 从
        20000 调成 60000、给 ``USER_AGENT`` 换一个，两边各自都跑得通、用例多半也还是绿的 ——
        于是同一个 ``web__fetch`` 在两处按不同的默认值干活，而工具描述里那个数字还是从常量
        f-string 拼进去的，说的话与实际行为就对不上了。这类常量此前**一条都没人盯**。

        比的只有**两边同名**的常量（``WEB_CONSTANT_EXCEPTIONS`` 里那几个除外）；名单不是凭印象
        编的，是拿两边现状比出来的：除它们之外全都逐字相同。``WEB_TOOLS`` 单独按结构比
        （见 :func:`_tool_definitions`）—— 它两边差的只有那个 dataclass 的名字，而三张工具的
        描述与参数表是模型真正读到的话术，该盯住。
        """
        assert _HOST_DIR is not None
        engine_src = (PACKAGE_DIR / "web.py").read_text(encoding="utf-8")
        host_src = (_HOST_DIR / "web.py").read_text(encoding="utf-8")
        mine = _top_level_constants(engine_src)
        theirs = _top_level_constants(host_src)
        shared = sorted(set(mine) & set(theirs))
        self.assertTrue(shared, "一个两边同名的常量都没比到：切常量那把刀钝了")
        for name in shared:
            if name in WEB_CONSTANT_EXCEPTIONS:
                continue
            with self.subTest(constant=name):
                self.assertEqual(
                    mine[name],
                    theirs[name],
                    f"常量 {name} 两边不一致了：它是行为参数，改一边就要改另一边"
                    f"（引擎侧 {PACKAGE_DIR / 'web.py'}，宿主侧 {_HOST_DIR / 'web.py'}）",
                )
        self.assertIn("WEB_TOOLS", mine, "引擎侧 web.py 里没有 WEB_TOOLS（改名了？）")
        self.assertIn("WEB_TOOLS", theirs, "宿主侧 web.py 里没有 WEB_TOOLS（改名了？）")
        self.assertEqual(
            _tool_definitions(engine_src, "WEB_TOOLS"),
            _tool_definitions(host_src, "WEB_TOOLS"),
            "三张工具的定义（名字 / 描述 / 参数表）两边不一致了：描述是模型看到的话术，"
            f"改一边就要改另一边（引擎侧 {PACKAGE_DIR / 'web.py'}，宿主侧 {_HOST_DIR / 'web.py'}）",
        )

    def test_shared_agent_types_are_identical(self) -> None:
        """``agent/types.py`` 除模块 docstring 外逐字相同。

        宿主侧那份的 docstring 自己写着"与引擎侧 ``agent/types.py`` 是同一套形状的两份实现"
        —— 那句话就是契约，可它此前没有任何东西盯着。两份文件当前只在 docstring 上分叉，
        于是谁顺手改了一边的 ``to_openai``（比如给带 tool_calls 的 assistant 消息加个字段），
        另一边照旧发老形状，要等到"某一边的模型请求被服务端拒了"才看得出来。

        这里比**整份文件**（只放过 docstring），不是列部件名单：要守的就是"整个形状"，字段、
        ``Role`` 别名、``__all__`` 都在里面；而这份文件两边本来就只有 docstring 该各写各的，
        比整份反而更简单、报错也更直。引擎侧这套 agent 是活代码（``routes.py`` 直接 import
        ``AgentSession`` 与 ``OpenAIChatClient``），不是留着的备份。
        """
        assert _HOST_DIR is not None
        engine_side = _without_module_docstring(
            (PACKAGE_DIR / "agent" / "types.py").read_text(encoding="utf-8")
        )
        host_side = _without_module_docstring(
            (_HOST_DIR / "agent" / "types.py").read_text(encoding="utf-8")
        )
        self.assertEqual(
            engine_side,
            host_side,
            "agent/types.py 与宿主侧那份不一致了：改一边就要改另一边"
            f"（引擎侧 {PACKAGE_DIR / 'agent' / 'types.py'}，宿主侧 {_HOST_DIR / 'agent' / 'types.py'}）",
        )


if _HOST_DIR is None:
    print(
        "[test_web_tools] 跳过副本一致性检查：从 "
        f"{PACKAGE_DIR} 往上没找到 Comfy-Desktop/lib/comfy_studio"
    )
