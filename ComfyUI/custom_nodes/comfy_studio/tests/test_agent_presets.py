# -*- coding: utf-8 -*-
"""``.codebuddy/agents/`` 那些子智能体，与宿主包 ``agent/presets/`` 是不是一条线上。

这批 agent 的链路是**一条单向派生**：

    agent/presets/*.md  ──(`_build.py` 加 frontmatter)──▶  .codebuddy/agents/studio-*.md

链路上任何一处"改了上游、忘了重生成"都**不报错**，症状只是"规则改了，实际部署的 agent
还是旧的"。本套件把那条链机械钉住：拿 `_build.py` **自己的**渲染函数重算一遍，与磁盘逐字
比对 —— 因此能同时抓两类问题：

* 改了 presets 却没跑 `_build.py`；
* 有人手改了生成出来的 agent（下次重生成会被静默覆盖，白改）。

⚠️ 与宿主侧那套的分工：`Comfy-Desktop/lib/comfy_studio/tests/test_agents_tools.py` 的
`PresetTests` 管"**面板下拉里的清单**与文件对不对得上"（它随宿主包单独分发，不能依赖仓库
根）；本套件管"**派生 agent**与源规格对不对得上"（只有完整仓库里才跑得起来）。

跑法（引擎 venv 的 python，cwd 在 ``ComfyUI/custom_nodes``）::

    python -m unittest comfy_studio.tests.test_agent_presets -t .
"""

from __future__ import annotations

import importlib.util
import re
import unittest
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()          # .../comfy_studio/tests/test_agent_presets.py
#: 往上四级就是仓库根：tests → comfy_studio → custom_nodes → ComfyUI → <仓库根>
REPO_ROOT = HERE.parents[4]
BUILD_PY = REPO_ROOT / ".codebuddy" / "agents" / "_build.py"
AGENTS_DIR = BUILD_PY.parent
#: 安装器 —— `OWNED_GLOB`（"哪一批 agent 属于本批"）的**唯一**出处。它是另一个脚本，
#: 不在 `_build.py` 里，所以核对要去它那儿读（见 :func:`installed_owned_glob`）。
INSTALL_PY = AGENTS_DIR / "_install_user.py"

MISSING = f"没找到 {BUILD_PY} —— 本套件只在**完整仓库**里跑（`comfy_studio/` 被单独拿走时不适用）"

#: `_build.py` 模块本身（`setUpModule` 里加载；见下面为什么要动态加载）。
BUILD: Any = None

#: `_install_user.py` 模块本身（同上：它也是"另一条链的唯一实现"，要复用而非重写）。
INSTALL: Any = None

#: 正文里**不该出现**的写法：指向本仓库的落点。这些必须自包含（规则全文内联），
#: 出现仓库路径就说明它指的是本仓库的某个文件 —— 搬到别的项目 / 装到用户级就会指空。
#: ⚠️ 出处注记（`> 生成自 …`）例外：它**必须**写仓库落点，核对前先剥掉。
REPO_PATH = re.compile(
    r"ComfyUI/|Comfy-Desktop/|\.codebuddy/|AI漫剧智能体工作流|智能体搭建参考md"
)

#: `_build.py` 注入的出处注记的首行前缀（剥注记时按它认）。
PROV_PREFIX = "> 生成自 "


def _load_py(path: Path, alias: str) -> Any:
    """按文件路径加载仓库里的一个脚本。

    为什么要**动态**加载：它们在仓库根的 `.codebuddy/agents/` 下（不是 `comfy_studio` 包的
    一部分，`import comfy_studio...` 够不着），而它们各自是那条链的**唯一权威实现** ——
    测试必须复用它们的函数，否则"测试用的算法"与"干活的算法"各写一份、各自漂移，
    守卫就成了摆设。
    """
    if not path.is_file():
        raise unittest.SkipTest(MISSING)
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:      # pragma: no cover - 路径不是 .py 才会
        raise unittest.SkipTest(MISSING)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setUpModule() -> None:      # noqa: N802 - unittest 规定的名字
    """加载 `_build.py`（生成器）与 `_install_user.py`（安装器）。"""
    global BUILD, INSTALL
    BUILD = _load_py(BUILD_PY, "comfy_studio_agent_build")
    INSTALL = _load_py(INSTALL_PY, "comfy_studio_agent_install")


def read_agent(name: str) -> str:
    return (AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def split_agent(text: str) -> tuple[str, str]:
    """拆成 `(frontmatter, 正文)` —— 正文含 `_build.py` 注入的出处注记。"""
    _, front, body = text.split("---\n", 2)
    return front, body


def spec_body(text: str) -> str:
    """剥掉出处注记，只留**规格正文**（那份要能整份带走的）。

    ⚠️ `split("---\\n", 2)` 切出的第三段以 frontmatter 收尾那个换行开头（`---\\n\\n` 的第二
    个 `\\n`），得先 `lstrip` 掉才能认出注记首行。少这一步注记就剥不掉，正文里那行
    `> 生成自 <仓库落点>` 会把"自包含"检查判红 —— 而它本该只检查规格正文。
    """
    body = split_agent(text)[1].lstrip("\n")
    if body.startswith(PROV_PREFIX):
        cut = body.find("\n\n")
        return body[cut + 2:] if cut != -1 else body
    return body


def installed_owned_glob() -> str:
    """从 `_install_user.py` 读它认领「本批」的 glob。

    那是**它的**常量（`_build.py` 里没有）：生成器管"规格 → agent"，安装器管"agent → 用户级"，
    "哪一批算本批"由安装器说了算。这里核对两边认定的前缀一致 —— 前缀一旦分叉，安装器就认不出
    新生成的 agent（`--校验` 会报"没有本批文件"），而那不会让任何东西报错。
    """
    text = INSTALL_PY.read_text(encoding="utf-8")
    match = re.search(r'^OWNED_GLOB\s*=\s*"([^"]+)"', text, re.M)
    if match is None:                                   # pragma: no cover - 常量被改名才会走到
        raise AssertionError(f"{INSTALL_PY} 里找不到 OWNED_GLOB")
    return match.group(1)


class DerivedAgentTests(unittest.TestCase):
    """生成物 == 按源规格重算。"""

    def test_every_source_has_a_generated_agent(self) -> None:
        for item in BUILD.SOURCES:
            path = AGENTS_DIR / f"{item['name']}.md"
            self.assertTrue(
                path.is_file(),
                f"{path.name} 不存在 —— 跑 `python .codebuddy/agents/_build.py` 生成它")

    def test_generated_agents_match_a_fresh_render(self) -> None:
        for item in BUILD.SOURCES:
            want = BUILD.render(item)[0]
            got = read_agent(item["name"])
            self.assertEqual(
                got, want,
                f"{item['name']}.md 与「按源规格重算」不一致 ——"
                " 要么改了 presets 没重生成，要么有人手改了生成物；"
                "跑 `python .codebuddy/agents/_build.py` 对齐")

    def test_no_orphan_agents(self) -> None:
        # 源规格改名 / 删除之后，旧名字的生成物还躺在 agent 目录里被主 Agent 看见 ——
        # 它会照着**已经不存在的规则**干活，而且不报错。
        self.assertEqual(
            BUILD.orphan_agents(), [],
            "有不在生成清单里的 studio-*.md：源规格改名或删除后留下的孤儿，删掉它")


class SourceLayoutTests(unittest.TestCase):
    """源规格与 `SOURCES` 清单：一处源、一一对应。"""

    def test_source_directory_is_the_host_package_presets(self) -> None:
        # 源就住在宿主包里（宿主面板下拉直接读它）。若这条断言红了，说明源又跑到别处去了，
        # 那"同一知识两处维护"的问题会跟着回来。
        self.assertEqual(BUILD.SRC_DIR, BUILD.REPO_ROOT / BUILD.HOST_AGENT_REL / "presets")
        self.assertTrue(BUILD.SRC_DIR.is_dir(), BUILD.SRC_DIR)
        self.assertEqual(BUILD.SRC_DIR.name, "presets")

    def test_sources_and_presets_are_one_to_one(self) -> None:
        # README.md 是目录说明，不是某份人设。
        on_disk = {p.name for p in BUILD.SRC_DIR.glob("*.md")} - {"README.md"}
        self.assertEqual(
            on_disk, {item["src"] for item in BUILD.SOURCES},
            "presets/ 里有的规格没进 SOURCES，或 SOURCES 指向了不存在的规格")

    def test_agent_names_are_unique_and_prefixed(self) -> None:
        # 前缀是 `_install_user.py` 认领"属于本批"的依据（OWNED_GLOB = studio-*.md）。
        names = [item["name"] for item in BUILD.SOURCES]
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertTrue(name.startswith("studio-"), name)
        # 生成器与安装器必须认同一套前缀：分叉的后果不是报错，而是安装器认不出新 agent。
        owned = installed_owned_glob()
        self.assertEqual(owned, "studio-*.md")
        self.assertTrue(all(fnmatch(f"{name}.md", owned) for name in names), names)


class FrontmatterTests(unittest.TestCase):
    """字段名与取值：写错**不报错**，只是主 Agent 永远不选它。"""

    def test_description_uses_the_official_field_name(self) -> None:
        # 官方文档给的是 `description`；写成 `desc` 会被静默忽略 —— 主 Agent 拿不到
        # 调用依据，这个智能体就再也不会被自动选中。
        for item in BUILD.SOURCES:
            front, _ = split_agent(read_agent(item["name"]))
            self.assertIn("description:", front, item["name"])
            self.assertNotIn("\ndesc:", front, f"{item['name']}：字段名是 description，不是 desc")

    def test_agent_mode_matches_the_declaration(self) -> None:
        # `agentMode` 是**唯一**的"自动入口"判据（官方：agentic = 主 Agent 自动判断调用时机，
        # manual = 用户手动选）。取值只有这两个枚举，写别的等于两边都不认。
        for item in BUILD.SOURCES:
            front, _ = split_agent(read_agent(item["name"]))
            m = re.search(r"^agentMode:\s*(\S+)\s*$", front, re.M)
            self.assertIsNotNone(m, f"{item['name']}：frontmatter 里没有 agentMode")
            mode = m.group(1) if m else None
            self.assertIn(mode, ("agentic", "manual"), item["name"])
            self.assertEqual(mode, item["mode"], item["name"])

    def test_the_frontmatter_switches_follow_the_official_schema(self) -> None:
        """核对两个开关字段的取值 —— 依据是官方 Subagents 文档，不是偏好。

        官方字段表（https://www.codebuddy.ai/docs/zh/ide/Features/Subagents）里
        ``enabledAutoRun`` 对应 **Auto Run**：「Subagents 调用工具时是否需要用户的同意」。
        ``true`` = 调工具不必逐次点头；文档给出的 agentic 与 manual 两个示例**都是 true**。

        ⚠️ 它**不是**"能不能被自动选中"的开关 —— 那件事由 ``agentMode`` 一处决定
        （见 :meth:`test_agent_mode_matches_the_declaration`，官方定义 agentic = 主 Agent
        自动判断调用时机）。这里防的是有人把 ``enabledAutoRun`` 误当"自动入口开关"关掉：
        关掉不会让 agent 更保守，只会让它在 agentic 模式下每调一次工具都要用户点同意 ——
        那恰是 agentic 模式要避免的事。
        """
        for item in BUILD.SOURCES:
            front, _ = split_agent(read_agent(item["name"]))
            self.assertIn("enabled: true", front, item["name"])
            self.assertIn("enabledAutoRun: true", front, item["name"])

    def test_one_direction_has_exactly_one_automatic_entry(self) -> None:
        # 服化道方向有**两个** agent（costume-prop-engine / asset-library）—— 两者都能响应
        # "出一套视觉设定"，只允许一个自动入口：同时自动 = 同一句话走两条路、行为不确定。
        manual = [item["name"] for item in BUILD.SOURCES if item["mode"] == "manual"]
        self.assertEqual(manual, ["studio-asset-library"])

    def test_the_spec_body_carries_no_repo_path(self) -> None:
        for item in BUILD.SOURCES:
            body = spec_body(read_agent(item["name"]))
            bad = REPO_PATH.search(body)
            found = bad.group(0) if bad else ""
            self.assertIsNone(
                bad,
                f"{item['name']}：规格正文里出现了本仓库路径 {found!r}"
                " —— 这份 agent 不再自包含，搬到别的项目就会指空")


class TopicNeutralityTests(unittest.TestCase):
    """口径（见 `_build.py` 顶部）：这批智能体是**通用内容生产**的，与题材无关。

    题材住在**具体项目的规则**里，不住在 agent 里 —— 换个项目 = 换一份规则，agent
    本身不改一个字。写窄了的后果是**静默的**：主 Agent 在别的题材上不选它，没有报错。

    2026-09-28 之前这条口径**只写在 `_build.py` 的注释里、一个守卫都没有**，于是 4 份
    规格把 agent 焊死在「2分钟AI漫剧短剧」上：剧本 27 处、服化道 9 处、资产库 7 处、
    面板下拉说明 1 处。修完就补了这条守卫，免得再漂回去。

    ⚠️ 判据必须是「左不接『动』」的正则：素材来源枚举里的 `动漫剧情` 里嵌着一个「漫剧」，
       用 `in` 判定会把它报成泄漏（生成器首跑就假警报了一次）。
    """

    def test_the_wordlist_and_the_regex_agree(self) -> None:
        # 词表是给人看的、正则是干活的那个：两处一旦分叉，守卫就只拦得住词表里的词。
        for word in BUILD.FORBIDDEN_TOPIC:
            self.assertEqual(BUILD.topic_hits(word), [word], word)

    def test_the_trap_word_is_not_a_leak(self) -> None:
        self.assertEqual(BUILD.topic_hits("- 动漫剧情"), [])

    def test_the_source_specs_do_not_bind_the_agent_to_one_topic(self) -> None:
        for item in BUILD.SOURCES:
            hits = BUILD.topic_hits(item["desc"])
            self.assertEqual(hits, [], f"{item['name']} 的 description 里有 {hits}")
            src = BUILD.SRC_DIR / item["src"]
            hits = BUILD.topic_hits(src.read_text(encoding="utf-8"))
            self.assertEqual(hits, [], f"{item['name']} 的角色段（{item['src']}）里有 {hits}")

    def test_the_derived_agents_do_not_bind_the_agent_to_one_topic(self) -> None:
        # 派生是逐字搬运，源干净则产物必然干净 —— 但那句"必然"要靠这条兜着：
        # 万一哪天有人改成"顺手改两个字"，泄漏就会从这里漏出去。
        for item in BUILD.SOURCES:
            hits = BUILD.topic_hits(split_agent(read_agent(item["name"]))[1])
            self.assertEqual(hits, [], f"{item['name']} 的派生正文里有 {hits}")


class InstallerTests(unittest.TestCase):
    """安装器（`.codebuddy/agents/` → 用户级）的渲染：只加注记，**不动正文一个字**。

    为什么这条链也要核对：安装器的 :func:`render` 在"用户级一个都没装"时**从没被执行过**
    （`--校验` 对缺失文件直接 `continue`），于是它的 bug 能一直躺着 —— 直到某天真去安装，
    才在**看起来该由被装内容负责**的地方炸掉，让人去改 agent 正文而不是改脚本。

    2026-09-28 就是这样栽的：`render` 把 frontmatter 后面那个空行算漏了，注记剥不掉，
    7 个文件被各自那行出处**全部**判红，报的还是"这份 agent 不再自包含"。
    """

    def test_installer_renders_without_touching_the_body(self) -> None:
        for item in BUILD.SOURCES:
            name = item["name"]
            out, body_chars = INSTALL.render(AGENTS_DIR / f"{name}.md")
            # 原文里唯一被允许的改动是安装器的**换行规范化**（CRLF → LF、去尾空白、补一个换行）。
            want = read_agent(name).rstrip() + "\n"
            note_block = "\n" + INSTALL.note(name) + "\n"
            self.assertIn(note_block, out, f"{name}：注记没插进产物")
            self.assertEqual(
                out.replace(note_block, "", 1), want,
                f"{name}：安装器动了正文 —— 它只该往 frontmatter 后插注记，"
                "正文必须逐字带走（两条链都不改正文，才谈得上「各算各的不会漂」）")
            self.assertEqual(body_chars, len(split_agent(want)[1]), name)

    def test_the_two_links_share_one_repo_path_rule(self) -> None:
        # "正文里不许出现本仓库落点"是**两条链共用**的一条纪律（生成时查一次、安装时再查
        # 一次）。判据各写一份就会漂，而漂的方向恰好是最坏的那边：安装器放过生成器拦下的
        # 写法，后果是这份 agent 在别人的项目里指着不存在的文件干活、而且不报错。
        self.assertEqual(INSTALL.REPO_PATH.pattern, REPO_PATH.pattern)


if __name__ == "__main__":
    unittest.main()
