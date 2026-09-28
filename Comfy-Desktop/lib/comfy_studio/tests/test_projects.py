"""``comfy_studio.projects`` 的单元测试（纯本地：临时目录当项目根）。

跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_projects -v

两组夹具，各钉一件事：

* :data:`FAKE_SPEC` —— 临时目录里放一份**最小** ``project.py``，用来钉本模块**自己**的行为
  （分格、越界、编码、登记原著、建完不覆盖）。规范那边改了内容，这组用例照样该过。
* :class:`RealSpecTest` —— 按 ``__file__`` 往上找到仓库里那份**真** ``project.py``，
  钉"面板的格子没漏掉任何一个落点"（:func:`shelf_gaps` 为空）。这条**只在检出里有它时跑**，
  跳过时会打印原因：那种"存在才跑"却一声不吭的用例，是永远不跑还没人发现的用例。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from comfy_studio.mcp import McpError, McpHub
from comfy_studio.novels import MANJU_REL
from comfy_studio.projects import (
    MAX_TREE_FILES,
    PROJECT_SHELVES,
    PROJECT_SUBDIR,
    SPEC_REL,
    WORKFLOW_DIRNAME,
    ProjectLibrary,
    ProjectsClient,
    ProjectsError,
    default_project_dir,
    default_spec_path,
    load_spec,
    shelf_gaps,
    shelf_unknown,
)
from comfy_studio.rpc import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from comfy_studio.server import StudioHost
from comfy_studio.skills import SkillCatalog

#: 一份最小但**形状完整**的规范（只用到 ``project.py`` 的四个接口）：
#: 落点少几个、故意不含 ``00_PROJECT/02_资产索引``（用来验 ``unknown`` 那条），
#: 种子表里含 ``素材来源登记.md``（登记原著要用它）。
FAKE_SPEC = '''\
"""测试用的最小规范，形状照抄 manju 那份 src/project.py 的对外接口。"""
import os

PROJECT_DIRS = (
    "00_PROJECT/01_剧本",
    "00_PROJECT/01_剧本/00_总纲",
    "00_PROJECT/06_对白",
    "00_PROJECT/07_素材归档",
    "02_CHARACTERS",
    "08_STORYBOARDS",
    "09_SHOTS",
    "11_AUDIO",
)
SCOPE_WHOLE = "全剧级"
SCOPE_EPISODE = "分集级"
SCOPE_MIXED = "混合"
SCOPE_ORDER = (SCOPE_WHOLE, SCOPE_EPISODE, SCOPE_MIXED)
DIR_SCOPES = {
    "00_PROJECT/01_剧本": SCOPE_EPISODE,
    "00_PROJECT/01_剧本/00_总纲": SCOPE_WHOLE,
    "00_PROJECT/06_对白": SCOPE_EPISODE,
    "00_PROJECT/07_素材归档": SCOPE_WHOLE,
    "02_CHARACTERS": SCOPE_WHOLE,
    "08_STORYBOARDS": SCOPE_EPISODE,
    "09_SHOTS": SCOPE_EPISODE,
    "11_AUDIO": SCOPE_EPISODE,
}
SEED_FILES = (
    ("对白表_EPxx.md", "00_PROJECT/06_对白/对白表_EP01.md"),
    ("素材来源登记.md", "00_PROJECT/07_素材归档/素材来源登记.md"),
)
_STAGES = (
    ("S0 建纲", "00_PROJECT/01_剧本", (".md",)),
    ("S5 视频", "09_SHOTS", (".mp4",)),
)
_SEED_BODY = {
    "对白表_EPxx.md": "# 对白表\\n\\n| 角色 | 台词 |\\n| --- | --- |\\n",
    "素材来源登记.md": "# 素材来源登记\\n\\n| 项 | 值 |\\n| --- | --- |\\n| 原著名 | （待填） |\\n| 作者 | |\\n",
}


def create_project(name, *, episodes=12, root=None, upgrade=False, dry=False, log=print):
    path = os.path.join(root, name)
    if os.path.isdir(path) and not upgrade and os.listdir(path):
        raise RuntimeError("项目已存在且非空：%s" % path)
    result = {"path": path, "dirs": [], "files": [], "skipped": [], "pending": []}
    for rel in PROJECT_DIRS:
        full = os.path.join(path, rel.replace("/", os.sep))
        if os.path.isdir(full):
            result["skipped"].append(rel + "/")
            continue
        if not dry:
            os.makedirs(full, exist_ok=True)
        result["dirs"].append(rel + "/")
    for src, dst in SEED_FILES:
        full = os.path.join(path, dst.replace("/", os.sep))
        if os.path.exists(full):
            result["skipped"].append(dst)
            continue
        if not dry:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(_SEED_BODY[src] + "集数：%d\\n" % episodes)
        result["files"].append(dst)
        result["pending"].append(dst)
    return result


def scan_project(name_or_path):
    path = name_or_path
    missing = [rel for rel in PROJECT_DIRS
               if not os.path.isdir(os.path.join(path, rel.replace("/", os.sep)))]
    stages = []
    for label, rel, exts in _STAGES:
        full = os.path.join(path, rel.replace("/", os.sep))
        hits = []
        if os.path.isdir(full):
            for dirpath, _dirs, files in os.walk(full):
                for fn in sorted(files):
                    if exts and not fn.lower().endswith(exts):
                        continue
                    hits.append(os.path.join(dirpath, fn))
        stages.append((label, rel, hits))
    return {"path": path, "missing": missing, "stages": stages}
'''


class ProjectsLibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-projects-")
        self.repo = Path(self._tmp.name)
        self.root = default_project_dir(self.repo)
        self.spec_path = self.root.parent / "fake_spec" / "project.py"
        self.spec_path.parent.mkdir(parents=True, exist_ok=True)
        self.spec_path.write_text(FAKE_SPEC, encoding="utf-8")
        self.library = ProjectLibrary(self.root, spec_path=self.spec_path)
        self._novels = tempfile.TemporaryDirectory(prefix="comfy-studio-projects-novels-")
        self.novel_dir = Path(self._novels.name)
        (self.novel_dir / "某本原著.txt").write_text("第一章", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()
        self._novels.cleanup()

    # ---- 落点与事实源 ---------------------------------------------------

    def test_default_paths_are_repo_relative(self) -> None:
        # 默认落点必须是**检出内相对路径**拼出来的：换机器、换检出照样成立，
        # 不许出现哪台机器的盘符（见仓库根 README「不写死路径」那条）。
        self.assertEqual(default_project_dir(self.repo), self.repo / "custom_nodes/comfy_studio/manju/projects")
        self.assertEqual(PROJECT_SUBDIR, "projects")
        self.assertEqual(WORKFLOW_DIRNAME, "AI漫剧智能体工作流")
        # 事实源在项目根的**同级**：往上退一级就能找到它，不用知道 ComfyUI 装在哪。
        spec = default_spec_path(self.root)
        self.assertEqual(spec.parent.parts[-2:], ("07-智能体运行时", "src"))
        self.assertEqual(spec.name, "project.py")
        self.assertEqual(spec.relative_to(self.repo).parts[0], "custom_nodes")

    def test_missing_spec_is_reported_not_swallowed(self) -> None:
        library = ProjectLibrary(self.root, spec_path=self.root / "没有这份.py")
        status = library.status()  # 不抛：面板与 host/info 都要读它
        self.assertFalse(status["spec_ok"])
        self.assertIn("找不到项目规范的事实源", status["spec_error"])
        # 目录都不在时 list() 只回"这里还没有项目"（那是一种状态）；一旦真要去查项目，
        # 就没有"没有落点清单"这一说了：得把原因顶出来，而不是回一个空列表。
        self.assertFalse(library.list()["exists"])
        self.root.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ProjectsError) as err:
            library.list()
        self.assertIn("找不到项目规范的事实源", str(err.exception))
        with self.assertRaises(ProjectsError):
            library.create("某剧")

    def test_spec_is_loaded_from_the_given_path(self) -> None:
        spec = load_spec(self.spec_path)
        self.assertEqual(tuple(spec.PROJECT_DIRS), tuple(load_spec(self.spec_path).PROJECT_DIRS))
        self.assertIn("00_PROJECT/01_剧本", spec.PROJECT_DIRS)
        status = self.library.status()
        self.assertTrue(status["spec_ok"])
        self.assertEqual(status["dirs"], len(spec.PROJECT_DIRS))

    def test_broken_spec_says_why(self) -> None:
        bad = self.root / "坏的.py"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("PROJECT_DIRS = (", encoding="utf-8")
        with self.assertRaises(ProjectsError) as err:
            load_spec(bad)
        self.assertIn("载入", str(err.exception))

    def test_spec_without_the_needed_interface_says_why(self) -> None:
        thin = self.root / "缺接口.py"
        thin.parent.mkdir(parents=True, exist_ok=True)
        thin.write_text("PROJECT_DIRS = ('x',)\n", encoding="utf-8")
        with self.assertRaises(ProjectsError) as err:
            load_spec(thin)
        self.assertIn("scan_project", str(err.exception))

    # ---- 分格与规范对不对得上 -------------------------------------------

    def test_shelves_cover_the_real_drop_points(self) -> None:
        # 两种分家都要报出来：① 规范多了个落点（面板会少显示一格）；② 规范少了某个落点，
        # 面板的格子还写着它（面板会显示一个永远为空的格）。
        dirs = ("00_PROJECT/01_剧本", "00_PROJECT/03_台账", "新加的落点")
        self.assertEqual(shelf_gaps(dirs), ("新加的落点",))
        self.assertIn("00_PROJECT/02_资产索引", shelf_unknown(dirs))
        self.assertEqual(shelf_gaps([rel for shelf in PROJECT_SHELVES for rel in shelf[2]]), ())
        self.assertTrue(all(len(shelf[2]) > 0 for shelf in PROJECT_SHELVES))

    def test_status_reports_the_gap_between_panel_and_spec(self) -> None:
        status = self.library.status()
        self.assertIn("00_PROJECT/02_资产索引", status["unknown"])

    # ---- 目录不在 = 一种状态，不是错误 ----------------------------------

    def test_missing_project_root_is_a_state(self) -> None:
        result = self.library.list()
        self.assertFalse(result["exists"])
        self.assertEqual(result["projects"], [])
        self.assertEqual(result["dir"], str(self.root))

    # ---- 建项目 ---------------------------------------------------------

    def test_create_makes_the_drop_points_and_registers_the_novel(self) -> None:
        made = self.library.create("流氓天尊", episodes=40, novel="某本原著.txt", novel_dir=self.novel_dir)
        self.assertEqual(made["name"], "流氓天尊")
        self.assertEqual(made["episodes"], 40)
        self.assertIn("00_PROJECT/01_剧本", made["dirs"])
        self.assertIn("00_PROJECT/07_素材归档/素材来源登记.md", made["files"])
        # 登记原著：刚填上，不是"已经填过"。
        self.assertTrue(made["novel"]["linked"])
        self.assertEqual(made["novel"]["reason"], "filled")
        registry = (self.root / "流氓天尊/00_PROJECT/07_素材归档/素材来源登记.md").read_text(encoding="utf-8")
        self.assertIn("| 原著名 | 某本原著.txt |", registry)
        self.assertIn("| 作者 | |", registry)  # 只碰原著那一格，别的列原样留着
        # 建完立刻给一份体检：面板不用为"建好了长什么样"再跑一趟。
        self.assertEqual(made["summary"]["name"], "流氓天尊")

    def test_create_does_not_overwrite_existing_work(self) -> None:
        self.library.create("有的剧")
        script = self.root / "有的剧/00_PROJECT/01_剧本/第01集.md"
        script.write_text("# 第01集\n人写的正文\n", encoding="utf-8")
        with self.assertRaises(ProjectsError):
            self.library.create("有的剧")
        again = self.library.create("有的剧", upgrade=True)
        self.assertTrue(again["skipped"])
        self.assertEqual(script.read_text(encoding="utf-8"), "# 第01集\n人写的正文\n")

    def test_create_validates_the_episode_count(self) -> None:
        for bad in (0, -3, "很多"):
            with self.subTest(episodes=bad):
                with self.assertRaises(ProjectsError):
                    self.library.create("某剧", episodes=bad)
        self.assertFalse(self.root.exists())

    def test_create_rejects_a_name_that_tries_to_leave(self) -> None:
        for name in ("../外面", "..\\外面", str(self.repo / "外面"), ""):
            with self.subTest(name=name):
                with self.assertRaises(ProjectsError):
                    self.library.create(name)
        self.assertFalse((self.repo / "外面").exists())

    # ---- 列表 / 落点 / 简报 ---------------------------------------------

    def test_list_sorts_by_recent_change_and_filters(self) -> None:
        self.library.create("甲剧")
        self.library.create("乙剧")
        stale = 1_600_000_000.0  # 把甲剧按到过去：文件系统的时间戳精度不该决定这条用例过不过
        for path in (self.root / "甲剧").rglob("*"):
            os.utime(path, (stale, stale))
        (self.root / "乙剧/00_PROJECT/01_剧本/第01集.md").write_text("# 新写的\n", encoding="utf-8")
        names = [row["name"] for row in self.library.list()["projects"]]
        self.assertEqual(set(names), {"甲剧", "乙剧"})
        # 最近改过的在前（不是按名字排：用户是来找"昨天那部"的）。
        self.assertEqual(self.library.list()["projects"][0]["name"], "乙剧")
        self.assertEqual(self.library.list(name="甲")["matched"], 1)
        self.assertEqual(self.library.list(name="没有这个")["matched"], 0)

    def test_tree_groups_the_drop_points_and_truncates_long_ones(self) -> None:
        self.library.create("剧甲")
        script_dir = self.root / "剧甲/00_PROJECT/01_剧本"
        for index in range(MAX_TREE_FILES + 5):
            (script_dir / f"稿{index:03d}.md").write_text("字", encoding="utf-8")
        tree = self.library.tree("剧甲")
        shelves = {shelf["key"]: shelf for shelf in tree["shelves"]}
        self.assertTrue(shelves["script"]["exists"])
        self.assertEqual(shelves["script"]["count"], MAX_TREE_FILES + 5)
        bucket = shelves["script"]["dirs"][0]
        self.assertTrue(bucket["truncated"])
        self.assertEqual(bucket["rel"], "00_PROJECT/01_剧本")
        self.assertEqual(len(bucket["files"]), MAX_TREE_FILES)
        self.assertEqual(bucket["files"][0]["rel"], "00_PROJECT/01_剧本/稿000.md")
        self.assertTrue(bucket["files"][0]["readable"])
        # 剧本在最前（面板是按这个顺序画的），项目根那一格在最后。
        self.assertEqual(tree["shelves"][0]["key"], "script")
        self.assertEqual(tree["shelves"][-1]["key"], "root")
        self.assertEqual(tree["gaps"], [])
        # 没有产物的格子照样在（"这一格还空着"本身就是要说的话）。
        self.assertFalse(shelves["index"]["exists"])
        self.assertEqual(shelves["index"]["count"], 0)

    def test_shelf_splits_by_scope_and_does_not_list_nested_twice(self) -> None:
        """⭐ 一格里的落点按**粒度**分组；`01_剧本/` 不把 `00_总纲/` 的文件再列一遍。

        这两种毛病都不报错：粒度混在一列里，人会以为总纲也是"某一集"；
        同一份文件列两遍，看起来只像"这项目文件挺多"。所以只能靠机械守卫钉。
        """
        self.library.create("剧分")
        script = self.root / "剧分/00_PROJECT/01_剧本"
        (script / "EP01-剧本.md").write_text("# EP01", encoding="utf-8")
        (script / "00_总纲/角色小传.md").write_text("小传", encoding="utf-8")
        shelf = {item["key"]: item for item in self.library.tree("剧分")["shelves"]}["script"]
        self.assertEqual([group["title"] for group in shelf["groups"]], ["全剧级", "分集级"])
        whole, episode = shelf["groups"]
        self.assertEqual([bucket["rel"] for bucket in whole["dirs"]],
                         ["00_PROJECT/01_剧本/00_总纲"])
        self.assertEqual([bucket["rel"] for bucket in episode["dirs"]], ["00_PROJECT/01_剧本"])
        # 全剧级那份文件只在它自己那一组里出现，且只出现一次。
        self.assertEqual([f["rel"] for f in whole["dirs"][0]["files"]],
                         ["00_PROJECT/01_剧本/00_总纲/角色小传.md"])
        self.assertEqual([f["rel"] for f in episode["dirs"][0]["files"]],
                         ["00_PROJECT/01_剧本/EP01-剧本.md"])
        self.assertEqual(episode["count"], 1)
        # 简报只在"分得开"的格里写粒度明细。
        self.assertIn("· 全剧级：1 个文件", self.library.brief("剧分")["text"])

    def test_a_landing_without_a_scope_is_reported_not_guessed(self) -> None:
        """事实源漏标一个落点的粒度 → 如实报出来，**不**随手归进某一组。

        归错组的失效模式是静默的：那一格被摆进"全剧级"，人就会以为里面是一份
        跨集共用的设定 —— 它其实只是一处没对齐。
        """
        thin = self.spec_path.parent / "缺粒度.py"
        thin.write_text(FAKE_SPEC.replace('    "11_AUDIO": SCOPE_EPISODE,\n', ""), encoding="utf-8")
        library = ProjectLibrary(self.root, spec_path=thin)
        self.assertEqual(library.status()["scope_gaps"], ["11_AUDIO"])
        library.create("剧漏")
        tree = library.tree("剧漏")
        self.assertEqual(tree["scope_gaps"], ["11_AUDIO"])
        self.assertIn("粒度未知", [g["title"] for s in tree["shelves"] for g in s["groups"]])
        self.assertNotIn("11_AUDIO", [g["title"] for s in tree["shelves"] for g in s["groups"]])
        self.assertIn("11_AUDIO", library.brief("剧漏")["text"])

    def test_tree_reports_the_stage_progress_from_the_spec(self) -> None:
        self.library.create("剧乙")
        summary = self.library.tree("剧乙")["summary"]
        labels = [stage["label"] for stage in summary["stages"]]
        self.assertEqual(labels, ["S0 建纲", "S5 视频"])
        self.assertEqual(summary["stages_done"], 0)
        (self.root / "剧乙/09_SHOTS/第01镜.mp4").write_bytes(b"fake")
        summary = self.library.tree("剧乙")["summary"]
        self.assertEqual(summary["stages_done"], 1)
        self.assertEqual(self.library.tree("剧乙")["summary"]["files"], 3)  # 两份种子 + 这一镜

    def test_brief_is_facts_only(self) -> None:
        self.library.create("剧丙", episodes=24, novel="某本原著.txt", novel_dir=self.novel_dir)
        brief = self.library.brief("剧丙")
        text = brief["text"]
        self.assertIn("【项目】剧丙", text)
        self.assertIn("原著：某本原著.txt", text)
        self.assertIn("S0 建纲", text)
        self.assertIn("剧本与总纲：", text)
        self.assertIn("0/2 段有产物", text)
        # 简报是给模型当素材的：只写查得到的事实，不掺评价。
        for word in ("建议", "优秀", "很好"):
            self.assertNotIn(word, text)

    def test_brief_of_a_missing_project_says_so(self) -> None:
        with self.assertRaises(ProjectsError) as err:
            self.library.brief("查无此剧")
        self.assertIn("没有这个项目", str(err.exception))

    # ---- 读一份资料 -----------------------------------------------------

    def test_read_returns_a_page_with_the_encoding_it_used(self) -> None:
        self.library.create("剧丁")
        script = self.root / "剧丁/00_PROJECT/01_剧本/第01集.md"
        body = "第一场 夜 外\n" + "字" * 100
        script.write_text(body, encoding="utf-8")
        page = self.library.read("剧丁", "00_PROJECT/01_剧本/第01集.md", 0, 5)
        self.assertEqual(page["text"], body[:5])
        self.assertEqual(page["encoding"], "utf-8")
        self.assertEqual(page["total_chars"], len(body))
        self.assertTrue(page["truncated"])
        self.assertEqual(page["rel"], "00_PROJECT/01_剧本/第01集.md")
        tail = self.library.read("剧丁", "00_PROJECT/01_剧本/第01集.md", len(body) - 3)
        self.assertFalse(tail["truncated"])
        self.assertEqual(tail["chars"], 3)

    def test_read_judges_the_encoding_instead_of_guessing(self) -> None:
        # 剧本常常不是 UTF-8（老编辑器、从别处贴来的）：编码是**判**出来的，
        # 判出来是什么就如实说什么，判不出来就报错 —— 不交一屏乱码。
        self.library.create("剧戊")
        script = self.root / "剧戊/00_PROJECT/01_剧本/第01集.md"
        script.write_bytes("张三说：走。".encode("gb18030"))
        page = self.library.read("剧戊", "00_PROJECT/01_剧本/第01集.md")
        self.assertEqual(page["encoding"], "gb18030")
        self.assertEqual(page["text"], "张三说：走。")
        script.write_bytes(b"\x00\x01\x02\xff\xfe\x81\x40\x02")
        with self.assertRaises(ProjectsError) as err:
            self.library.read("剧戊", "00_PROJECT/01_剧本/第01集.md")
        self.assertIn("认不出编码", str(err.exception))

    def test_read_refuses_what_it_cannot_serve(self) -> None:
        self.library.create("剧己")
        (self.root / "剧己/09_SHOTS/第01镜.mp4").write_bytes(b"\x00\x01")
        with self.assertRaises(ProjectsError) as err:
            self.library.read("剧己", "09_SHOTS/第01镜.mp4")
        self.assertIn("不在这里读", str(err.exception))
        with self.assertRaises(ProjectsError) as missing:
            self.library.read("剧己", "00_PROJECT/01_剧本/没有这份.md")
        self.assertIn("没有这个文件", str(missing.exception))
        for chars in (0, -5, "一页"):
            with self.subTest(chars=chars):
                with self.assertRaises(ProjectsError):
                    self.library.read("剧己", "00_PROJECT/06_对白/对白表_EP01.md", 0, chars)

    # ---- 越界 -----------------------------------------------------------

    def test_paths_cannot_leave_the_project(self) -> None:
        self.library.create("剧庚")
        outside = self.root / "外面的.md"
        outside.write_text("外面的字", encoding="utf-8")
        for rel in ("../外面的.md", "..\\外面的.md", str(outside), "/etc/passwd"):
            with self.subTest(rel=rel):
                with self.assertRaises(ProjectsError):
                    self.library.read("剧庚", rel)
        self.assertTrue(outside.is_file())
        for name in ("../剧庚", "..\\剧庚", str(self.root / "剧庚")):
            with self.subTest(name=name):
                with self.assertRaises(ProjectsError):
                    self.library.tree(name)

    # ---- 登记原著 -------------------------------------------------------

    def test_link_novel_keeps_what_is_already_there(self) -> None:
        self.library.create("剧辛")
        registry = self.root / "剧辛/00_PROJECT/07_素材归档/素材来源登记.md"
        registry.write_text(
            "# 素材来源登记\n\n| 项 | 值 |\n| --- | --- |\n| 原著名 | 别人填的那本.txt |\n",
            encoding="utf-8",
        )
        out = self.library.link_novel("剧辛", "某本原著.txt", novel_dir=self.novel_dir)
        self.assertFalse(out["linked"])
        self.assertTrue(out["already"])
        self.assertEqual(out["reason"], "already")
        self.assertEqual(out["current"], "别人填的那本.txt")
        self.assertIn("别人填的那本.txt", registry.read_text(encoding="utf-8"))
        self.assertEqual(self.library.linked_novel(self.root / "剧辛"), "别人填的那本.txt")

    def test_link_novel_checks_the_library_before_writing(self) -> None:
        self.library.create("剧壬")
        out = self.library.link_novel("剧壬", "库里没有这本.txt", novel_dir=self.novel_dir)
        self.assertFalse(out["linked"])
        self.assertEqual(out["reason"], "missing_novel")
        registry = self.root / "剧壬/00_PROJECT/07_素材归档/素材来源登记.md"
        self.assertIn("| 原著名 | （待填） |", registry.read_text(encoding="utf-8"))

    def test_link_novel_rejects_a_path_and_a_missing_registry(self) -> None:
        self.library.create("剧癸")
        with self.assertRaises(ProjectsError):
            self.library.link_novel("剧癸", "../别人的书.txt")
        (self.root / "剧癸/00_PROJECT/07_素材归档/素材来源登记.md").unlink()
        out = self.library.link_novel("剧癸", "某本原著.txt")
        self.assertEqual(out["reason"], "no_registry")
        self.assertFalse(out["linked"])
        self.assertEqual(self.library.linked_novel(self.root / "剧癸"), "")


class ProjectsToolTableTest(unittest.IsolatedAsyncioTestCase):
    """汇进 MCP 工具表那两张：名字、参数、以及"建项目不在这张表里"这条决定。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-projects-tools-")
        self.root = Path(self._tmp.name) / MANJU_REL / PROJECT_SUBDIR
        self.spec_path = Path(self._tmp.name) / "fake_spec.py"
        self.spec_path.write_text(FAKE_SPEC, encoding="utf-8")
        self.library = ProjectLibrary(self.root, spec_path=self.spec_path)
        self.client = ProjectsClient(self.library)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_hub_exposes_the_two_read_tools(self) -> None:
        hub = McpHub([], extra_clients=[ProjectsClient(self.library)])
        await hub.start()
        self.assertEqual(
            [tool.qualified_name for tool in hub.tools], ["projects__list", "projects__brief"]
        )
        brief = next(tool for tool in hub.tools if tool.name == "brief")
        self.assertEqual(brief.input_schema["required"], ["name"])
        listings = next(tool for tool in hub.tools if tool.name == "list")
        self.assertNotIn("required", listings.input_schema)

    async def test_writing_is_not_a_tool(self) -> None:
        # 建项目 / 改名 / 归档是"落盘 + 命名 + 集数"由人拍板的事：模型能读、能据此接话，
        # 但不许替用户按那几个键（它们只在面板上有按钮）。
        tools = await self.client.list_tools()
        self.assertEqual({tool.name for tool in tools}, {"list", "brief"})

    async def test_list_comes_back_as_json_and_missing_project_is_a_result(self) -> None:
        listing = await self.client.call_tool("list", {})
        self.assertFalse(listing["isError"])
        payload = json.loads(listing["content"][0]["text"])
        self.assertFalse(payload["exists"])
        brief = await self.client.call_tool("brief", {"name": "查无此剧"})
        self.assertTrue(brief["isError"])
        self.assertIn("没有这个项目", brief["content"][0]["text"])

    async def test_unknown_tool_name_raises(self) -> None:
        with self.assertRaises(McpError):
            await self.client.call_tool("create", {"name": "某剧"})
        with self.assertRaises(McpError) as typed:
            await self.client.call_tool("list", {"name": 5})
        self.assertIn("必须是字符串", str(typed.exception))


class RealSpecTest(unittest.TestCase):
    """对仓库里那份**真**规范：面板的格子必须一个落点都不漏。

    这条是"两处清单分家"的唯一机械守卫（分家不报错，只能靠它报）。
    检出里没有那份文件时跳过，并且**打印原因**。
    """

    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[4]
        self.comfyui = self.repo / "ComfyUI"
        self.spec_path = default_spec_path(default_project_dir(self.comfyui))
        if not self.spec_path.is_file():
            self.skipTest(f"检出里没有那份规范，跳过：{self.spec_path}")

    def test_the_default_spec_path_finds_the_real_one(self) -> None:
        # 默认探测法（项目根往上退一级）必须真的指到它：否则面板在真机器上会"没有落点清单"。
        self.assertEqual(self.spec_path, self.comfyui / MANJU_REL / SPEC_REL)

    def test_shelves_cover_every_drop_point_of_the_real_spec(self) -> None:
        spec = load_spec(self.spec_path)
        dirs = tuple(spec.PROJECT_DIRS)
        self.assertEqual(shelf_gaps(dirs), (), "规范里有落点没被面板归到任何一格")
        self.assertEqual(shelf_unknown(dirs), (), "面板的格子里写了规范里没有的落点")
        self.assertGreaterEqual(len(dirs), 11)
        self.assertIn("00_PROJECT/01_剧本", dirs)


class ProjectsRpcTest(unittest.TestCase):
    """宿主那一层：方法注册了没、参数越界回什么码、没挂项目根时说不说得清。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-projects-rpc-")
        self.repo = Path(self._tmp.name)
        self.root = default_project_dir(self.repo)
        self.spec_path = self.root.parent / "fake_spec.py"
        self.spec_path.parent.mkdir(parents=True, exist_ok=True)
        self.spec_path.write_text(FAKE_SPEC, encoding="utf-8")
        self.library = ProjectLibrary(self.root, spec_path=self.spec_path)
        self.hub = McpHub([], extra_clients=[ProjectsClient(self.library)])
        self.host = StudioHost(
            self.hub, SkillCatalog(self.hub), comfyui_dir=str(self.repo), projects=self.library
        )
        self.bare = StudioHost(self.hub, SkillCatalog(self.hub))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_methods_are_registered(self) -> None:
        for method in (
            "projects/list",
            "projects/tree",
            "projects/read",
            "projects/create",
            "projects/link_novel",
            "projects/brief",
        ):
            self.assertIn(method, self.host.server.methods)

    def test_info_reports_the_project_dir_and_the_spec_status(self) -> None:
        info = self.host.info({}, None)
        self.assertTrue(info["projects"])
        self.assertEqual(info["project_dir"], str(self.root))
        self.assertTrue(info["project_status"]["spec_ok"])
        self.assertEqual(info["project_status"]["dirs"], 8)
        # 没挂的时候要如实说没有，别报一个假的目录出去。
        self.assertFalse(self.bare.info({}, None)["projects"])
        self.assertIsNone(self.bare.info({}, None)["project_dir"])

    def test_host_without_a_project_dir_says_so(self) -> None:
        with self.assertRaises(RpcError) as err:
            self.bare.projects_list({}, None)
        self.assertEqual(err.exception.code, INTERNAL_ERROR)
        self.assertIn("没挂项目目录", err.exception.message)

    def test_create_then_tree_then_read_over_rpc(self) -> None:
        made = self.host.projects_create({"name": "流氓天尊", "episodes": 40}, None)
        self.assertEqual(made["episodes"], 40)
        tree = self.host.projects_tree({"name": "流氓天尊"}, None)
        self.assertEqual(tree["name"], "流氓天尊")
        page = self.host.projects_read(
            {"name": "流氓天尊", "rel": "00_PROJECT/06_对白/对白表_EP01.md", "chars": 4}, None
        )
        self.assertEqual(page["chars"], 4)
        brief = self.host.projects_brief({"name": "流氓天尊"}, None)
        self.assertIn("【项目】流氓天尊", brief["text"])
        self.assertEqual(self.host.projects_list({}, None)["matched"], 1)

    def test_rpc_validates_parameters(self) -> None:
        for method, params in (
            ("projects_tree", {}),
            ("projects_tree", {"name": "  "}),
            ("projects_read", {"name": "甲", "rel": ""}),
            ("projects_read", {"name": "甲", "rel": "x.md", "offset": -1}),
            ("projects_read", {"name": "甲", "rel": "x.md", "chars": 0}),
            ("projects_create", {"name": "甲", "episodes": 0}),
            ("projects_create", {"name": "甲", "upgrade": "yes"}),
            ("projects_create", {"name": "甲", "novel": 7}),
            ("projects_link_novel", {"name": "甲", "novel": "  "}),
            ("projects_brief", {"name": "  "}),
            ("projects_list", {"name": 5}),
        ):
            with self.subTest(method=method, params=params):
                with self.assertRaises(RpcError) as err:
                    getattr(self.host, method)(params, None)
                self.assertEqual(err.exception.code, INVALID_PARAMS)

    def test_a_missing_project_is_an_internal_error_with_a_readable_message(self) -> None:
        with self.assertRaises(RpcError) as err:
            self.host.projects_tree({"name": "查无此剧"}, None)
        self.assertEqual(err.exception.code, INTERNAL_ERROR)
        self.assertIn("没有这个项目", err.exception.message)
