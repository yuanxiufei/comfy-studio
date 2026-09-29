"""``comfy_studio.projects`` 的单元测试（纯本地：临时目录当项目根）。

跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_projects -v

两组夹具，各钉一件事：

* :data:`FAKE_SPEC` —— 临时目录里放一份**最小** ``projects_spec.py``，用来钉本模块**自己**的
  行为（分格、越界、编码、登记原著、建完不覆盖）。规范那边改了内容，这组用例照样该过。
* :class:`RealSpecTest` —— 直接拿**包内那份真规范**（``default_spec_path()``），钉"面板的
  格子没漏掉任何一个落点"（:func:`shelf_gaps` 为空）。这条**不许跳过**。

  它过去写成"按 ``__file__`` 往上找到检出里那份 ``project.py``，没有就 skipTest" ——
  而那份文件后来**真的**不在检出里了，于是这道唯一的守卫生效方式变成了留一个绿色的
  "skipped"。这正是本文件开头警告的那种用例：**存在才跑，于是永远不跑**。事实源搬进
  包内之后，它没有任何跳过的理由了。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfy_studio import projects as projects_module
from comfy_studio import projects_spec as spec_module
from comfy_studio.layout import INPUT_SUBDIR, OUTPUT_SUBDIR
from comfy_studio.mcp import McpError, McpHub
from comfy_studio.projects import (
    DEFAULT_READ_CHARS,
    MAX_READ_CHARS,
    MAX_TREE_FILES,
    PROJECT_SHELVES,
    SPEC_NAME,
    ProjectLibrary,
    ProjectsClient,
    ProjectsError,
    default_project_dir,
    default_project_out_dir,
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
    total = 0
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn == ".gitkeep":
                continue
            total += 1
            newest = max(newest, os.stat(os.path.join(dirpath, fn)).st_mtime)
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
    return {"path": path, "missing": missing, "legacy": [], "stages": stages,
            "files": total, "mtime": newest}
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
        # 两个默认落点各归各的根，而且**都在引擎真正读写的目录**里：资料根 =
        # <检出>/input（加载类节点只认 input）、产物根 = <检出>/output（产物注解只认
        # output）。落反了不报错 —— 产物在盘上，就是不在引擎读得到的地方。
        self.assertEqual(default_project_dir(self.repo), self.repo / INPUT_SUBDIR)
        self.assertEqual(default_project_out_dir(self.repo), self.repo / OUTPUT_SUBDIR)
        self.assertEqual((INPUT_SUBDIR, OUTPUT_SUBDIR), ("input", "output"))
        # 事实源与 projects 模块**同包**：从 __file__ 定位 —— 不用知道 ComfyUI 装在哪，
        # 也不许受当前工作目录影响（换台机器、换检出照样成立）。
        spec = default_spec_path()
        self.assertEqual(spec.name, SPEC_NAME)
        self.assertEqual(spec.parent, Path(projects_module.__file__).resolve().parent)
        self.assertTrue(spec.is_file(), f"默认那份事实源必须随包一起在：{spec}")

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

    # ---- 体检快照（列表的合并） -----------------------------------------
    #
    # 这一组钉的是"快照管什么、不管什么"。它**不**承诺"现在"：管的是"窗口之内连着问就并成
    # 一次扫描"（窗口见 SNAPSHOT_MAX_AGE_SECONDS），要"现在"的调用走 refresh=True。
    # 用例把窗口放大 / 压成 0 来钉行为，不去 sleep 等钟走 —— 测试不等钟。
    #
    # 另外钉住一件事：**它不靠 mtime 判断"盘上动过没有"**。设计稿那条建议是以"项目路径 +
    # 顶层 mtime"为键，实测在本平台上撑不住（Windows 的目录时间戳延迟更新：往
    # 08_STORYBOARDS/ 里新写一份分镜，那一格自己的 mtime 过一会儿才变），于是改成时间窗口。

    def _pin_window(self, seconds: float):
        return mock.patch.object(projects_module, "SNAPSHOT_MAX_AGE_SECONDS", seconds)

    def _count_scans(self) -> list[str]:
        """把事实源那份 ``scan_project`` 包一层计数：真走了一遍全树才 +1。"""
        spec = self.library.spec()
        real = spec.scan_project
        calls: list[str] = []

        def counting(name_or_path, **_kwargs):
            calls.append(name_or_path)
            return real(name_or_path)

        spec.scan_project = counting
        return calls

    def test_list_coalesces_repeat_asks_inside_the_window(self) -> None:
        """窗口之内：连着问几遍，不会把每一部剧重扫一遍。"""
        self.library.create("甲剧")
        self.library.create("乙剧")
        calls = self._count_scans()
        with self._pin_window(60.0):
            self.library.list()
            self.assertEqual(len(calls), 1, "甲剧这一部还没存过快照")
            self.library.list()
            self.assertEqual(len(calls), 1, "窗口之内：这一遍并进上一次")
            self.library.list(refresh=True)
            self.assertEqual(len(calls), 3, "refresh 是不吃快照的那一下：两部都重扫")
            self.library.list()
            self.assertEqual(len(calls), 3, "刚重扫过的又成了最新的一份")

    def test_a_snapshot_past_the_window_is_not_reused(self) -> None:
        """窗口之外一律重扫：快照不是"一直有效"，是"窗口之内算数"。"""
        self.library.create("剧甲")
        calls = self._count_scans()
        with self._pin_window(0.0):
            self.library.list()
            self.library.list()
        self.assertEqual(len(calls), 2)

    def test_a_change_is_invisible_inside_the_window_and_visible_after_refresh(self) -> None:
        """窗口之内的写入看不见 —— 这是这条优化划出来的界，界外那条路是 ``refresh=True``。"""
        self.library.create("剧甲")
        shot = self.root / "剧甲/09_SHOTS/EP01/SH001.mp4"
        shot.parent.mkdir(parents=True)
        with self._pin_window(60.0):
            self.library.list()
            stale = self.library.list()["projects"][0]
            shot.write_bytes(b"ftyp")
            self.assertEqual(self.library.list()["projects"][0]["files"], stale["files"])
            self.assertEqual(self.library.list()["projects"][0]["stages"][1]["files"], 0)
            # 面板那个「刷新」键走的就是这条：看得见盘上此刻的样子。
            fresh = self.library.list(refresh=True)["projects"][0]
            self.assertEqual(fresh["files"], stale["files"] + 1)
            self.assertEqual(fresh["stages"][1]["files"], 1)
        self.assertEqual(len(self.library._snapshots), 1, "一部剧只留一条，重扫是原地替换")

    def test_our_own_writes_invalidate_the_snapshot(self) -> None:
        """本库自己写的那一下（面板上改剧本）不会留下一份"还算数"的旧快照。"""
        self.library.create("剧乙")
        self.library.list()  # 盘上先摆着一份有效快照（create 自己也顺手存过一份）
        calls = self._count_scans()
        with self._pin_window(60.0):
            self.library.list()
            self.assertEqual(len(calls), 0, "没动过盘：回的该是上一份")
            # 面板新写一份剧本：`base_digest=""` 的读法是"我读到的是这份还不存在"。
            self.library.write("剧乙", "00_PROJECT/01_剧本/第01集.md", "# 第01集\n人写的\n", "")
            rows = self.library.list()["projects"]
            self.assertEqual(len(calls), 1, "自己写过就得重扫（不等窗口过）")
            self.assertEqual(rows[0]["files"], 3, "两张种子空表 + 刚写的这一份")

    def test_the_snapshot_store_is_bounded(self) -> None:
        """留着的快照有上限：几十部剧来回翻，内存不能跟着项目数一直长。"""
        for index in range(4):
            self.library.create(f"剧{index}")
        with self._pin_window(60.0), mock.patch.object(projects_module, "SNAPSHOT_MAX_ENTRIES", 2):
            self.library.list()
        self.assertEqual(len(self.library._snapshots), 2)

    def test_tree_always_rescans(self) -> None:
        """详情页当场逐格列文件，体检要是吃快照，同一页就会出现"列了 12 个、却说这格没料"。"""
        self.library.create("剧丙")
        calls = self._count_scans()
        with self._pin_window(60.0):
            self.library.list()
            before = len(calls)
            self.library.tree("剧丙")
            self.assertEqual(len(calls), before + 1)
            self.library.tree("剧丙")
            self.assertEqual(len(calls), before + 2)

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

    def test_read_whole_hands_back_the_whole_file(self) -> None:
        # 工作台那一栏要"整份读来改"：面板只说 whole，不抄这里的上限（40 万字也是这里给的）。
        self.library.create("剧丁二")
        script = self.root / "剧丁二/00_PROJECT/01_剧本/第01集.md"
        body = "场" * (DEFAULT_READ_CHARS + 500)
        script.write_bytes(body.encode("utf-8"))
        # 不带 whole：照默认一页，后面的字没上来。
        page = self.library.read("剧丁二", "00_PROJECT/01_剧本/第01集.md")
        self.assertEqual(page["chars"], DEFAULT_READ_CHARS)
        self.assertTrue(page["truncated"])
        # 带 whole：整份都在手上，可以原样写回去。
        whole = self.library.read("剧丁二", "00_PROJECT/01_剧本/第01集.md", whole=True)
        self.assertEqual(whole["text"], body)
        self.assertFalse(whole["truncated"])
        self.assertEqual(whole["offset"], 0)
        # offset / chars 是翻页用的，whole 那一趟不该被它们带偏。
        again = self.library.read(
            "剧丁二", "00_PROJECT/01_剧本/第01集.md", 10, 5, whole=True
        )
        self.assertEqual(again["text"], body)
        # 比上限还长的：whole 也读不完，truncated 仍然是真 —— 这一份就只能看不能改。
        (self.root / "剧丁二/00_PROJECT/01_剧本/第02集.md").write_bytes(
            ("长" * (MAX_READ_CHARS + 10)).encode("utf-8")
        )
        long_page = self.library.read("剧丁二", "00_PROJECT/01_剧本/第02集.md", whole=True)
        self.assertEqual(long_page["chars"], MAX_READ_CHARS)
        self.assertTrue(long_page["truncated"])
        with self.assertRaises(ProjectsError) as err:
            self.library.read("剧丁二", "00_PROJECT/01_剧本/第01集.md", whole="是")
        self.assertIn("whole", str(err.exception))

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

    # ---- 改一份资料 -----------------------------------------------------

    def test_write_needs_the_digest_instead_of_guessing(self) -> None:
        """没读过就写 = **拒写**，不是"照写不误"。

        "我没读过"与"我读过、它没变"是两件事。把前者当后者，一次盲写就盖掉了别人
        （智能体、生成脚本）刚写进去的东西，而面板上什么都不会报 —— 所以就当场拒。
        """
        self.library.create("剧甲二")
        rel = "00_PROJECT/06_对白/对白表_EP01.md"
        before = (self.root / "剧甲二" / rel).read_text(encoding="utf-8")
        with self.assertRaises(ProjectsError) as err:
            self.library.write("剧甲二", rel, "抢写")
        self.assertIn("得先读一遍", str(err.exception))
        with self.assertRaises(ProjectsError) as loose:
            self.library.write("剧甲二", rel, "抢写", 5)
        self.assertIn("base_digest 必须是字符串", str(loose.exception))
        self.assertEqual((self.root / "剧甲二" / rel).read_text(encoding="utf-8"), before)

    def test_write_creates_a_new_artifact_only_when_it_is_really_absent(self) -> None:
        """``base_digest == ""`` 的意思是"我读到的是它还不存在"：真不在才让写。

        这期间有人建了一份同名文件就**拒写**（绝不覆盖）—— 建产物与改产物是两件事，
        把前者当成后者的后果是把别人的东西删成一句话。
        """
        self.library.create("剧乙二")
        rel = "08_STORYBOARDS/分镜表.md"
        made = self.library.write("剧乙二", rel, "第一镜：全景。\n", "")
        self.assertTrue(made["created"])
        self.assertEqual(
            (self.root / "剧乙二" / rel).read_text(encoding="utf-8"), "第一镜：全景。\n"
        )
        with self.assertRaises(ProjectsError) as err:
            self.library.write("剧乙二", rel, "又写", "")
        self.assertIn("已经存在", str(err.exception))
        self.assertEqual(
            (self.root / "剧乙二" / rel).read_text(encoding="utf-8"), "第一镜：全景。\n"
        )

    def test_write_refuses_a_digest_that_moved_under_it(self) -> None:
        """摘要对不上 = 编辑期间别人改过了。**不合并、不覆盖**，把两边摆出来。

        自动合并冲突在 markdown 上做不对，而"做不对还默默做"正是把一份手改过的分镜表
        毁掉的方式；所以这里只报错，让人自己决定。
        """
        self.library.create("剧丙二")
        rel = "00_PROJECT/01_剧本/第01集.md"
        target = self.root / "剧丙二" / rel
        # 用 write_bytes 而不是 write_text：后者在 Windows 上会把 \n 翻成 \r\n，
        # 而 digest 是**盘上那些字节**的摘要，翻过之后这条断言就只在 Linux 上成立。
        target.write_bytes("甲\n乙\n".encode("utf-8"))
        page = self.library.read("剧丙二", rel)
        self.assertEqual(
            page["digest"], hashlib.sha256("甲\n乙\n".encode("utf-8")).hexdigest()
        )
        target.write_bytes("甲\n乙\n丙\n".encode("utf-8"))
        with self.assertRaises(ProjectsError) as err:
            self.library.write("剧丙二", rel, "甲\n改\n", page["digest"])
        self.assertIn("被改过了", str(err.exception))
        self.assertIn(page["digest"][:12], str(err.exception))
        self.assertEqual(target.read_text(encoding="utf-8"), "甲\n乙\n丙\n")
        # 重读一遍就能改：守卫拦的是"拿着旧版本硬写"，不是"不许改"。
        again = self.library.read("剧丙二", rel)
        out = self.library.write("剧丙二", rel, "甲\n乙\n丙丁\n", again["digest"])
        self.assertFalse(out["created"])
        self.assertEqual(target.read_text(encoding="utf-8"), "甲\n乙\n丙丁\n")

    def test_write_keeps_the_line_endings_and_the_encoding_it_found(self) -> None:
        """行尾与编码**沿用原文件**。

        :meth:`read` 把 ``\\r\\n`` 归一成 ``\\n``；写回不还原的话，在 Windows 上改一个字
        会让整份文件在 git 里"全变了" —— 下一次 diff review 就没法看了。
        """
        self.library.create("剧丁三")
        rel = "00_PROJECT/01_剧本/第01集.md"
        target = self.root / "剧丁三" / rel
        target.write_bytes("甲\r\n乙\r\n".encode("gb18030"))
        page = self.library.read("剧丁三", rel)
        self.assertEqual(page["encoding"], "gb18030")
        out = self.library.write("剧丁三", rel, "甲\n丙\n", page["digest"])
        self.assertEqual(out["newline"], "crlf")
        self.assertEqual(out["encoding"], "gb18030")
        self.assertEqual(target.read_bytes(), "甲\r\n丙\r\n".encode("gb18030"))

    def test_write_refuses_what_it_cannot_serve(self) -> None:
        """与 :meth:`read` 同一套守卫：越界、二进制、正文不是字符串，一个都不放过去。"""
        self.library.create("剧戊三")
        (self.root / "剧戊三/09_SHOTS/第01镜.mp4").write_bytes(b"\x00\x01")
        with self.assertRaises(ProjectsError) as err:
            self.library.write("剧戊三", "09_SHOTS/第01镜.mp4", "字", "")
        self.assertIn("不在这里改", str(err.exception))
        with self.assertRaises(ProjectsError) as notext:
            self.library.write("剧戊三", "00_PROJECT/01_剧本/第01集.md", None, "")
        self.assertIn("必须是字符串", str(notext.exception))
        for rel in ("../跑出去.md", "..\\跑出去.md", "00_PROJECT/../../跑出去.md"):
            with self.subTest(rel=rel):
                with self.assertRaises(ProjectsError) as out:
                    self.library.write("剧戊三", rel, "字", "")
                self.assertIn("跑到项目外面", str(out.exception))
        # 别人刚删了我要改的那一份：报"已经不在了"，不是当成新建悄悄写下去。
        with self.assertRaises(ProjectsError) as gone:
            self.library.write("剧戊三", "00_PROJECT/01_剧本/第01集.md", "字", "a" * 64)
        self.assertIn("已经不在了", str(gone.exception))

    def test_tree_marks_the_premade_blank_tables(self) -> None:
        """预置空表要被标出来 —— 它是**空模板**，不是"这一步做过了"。

        不标记的失效模式在面板上很难看：刚建完项目，空对白表与真产物长得一模一样，
        而"阶段工作台"与"资料库"都照着文件数说"这里有料了"。
        """
        self.library.create("剧己三")
        rows = self._dirs("剧己三")
        dialogue = rows["00_PROJECT/06_对白"]
        self.assertEqual(dialogue["count"], 1)
        self.assertEqual(dialogue["seed_count"], 1)
        self.assertTrue(all(row["seed"] for row in dialogue["files"]))
        # 第 2 集的空表与第 1 集是同一种东西：按集号放宽，不是逐字相等。
        (self.root / "剧己三/00_PROJECT/06_对白/对白表_EP02.md").write_text("", encoding="utf-8")
        again = self._dirs("剧己三")["00_PROJECT/06_对白"]
        self.assertEqual(again["seed_count"], 2)
        self.assertEqual(again["count"], 2)
        # 真产物不会被误标，也不进 seed_count
        self.library.write("剧己三", "00_PROJECT/06_对白/对白稿_第01集.md", "台词。\n", "")
        written = self._dirs("剧己三")["00_PROJECT/06_对白"]
        by_name = {row["name"]: row["seed"] for row in written["files"]}
        self.assertFalse(by_name["对白稿_第01集.md"])
        self.assertEqual(written["seed_count"], 2)
        self.assertEqual(written["count"], 3)

    def _dirs(self, name: str) -> dict:
        """``tree`` 里所有落点，按相对路径索引。"""
        tree = self.library.tree(name)
        return {item["rel"]: item for shelf in tree["shelves"] for item in shelf["dirs"]}

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


class TwoRootLayoutTest(unittest.TestCase):
    """资料根与产物根分开时：每个落点归哪个根**只有** ``DIR_ROOTS`` 一处说了算。

    这一组用**包内那份真规范**（不套 ``FAKE_SPEC``）：两个根是规范里 ``DIR_ROOTS`` 定义的，
    换一份老规范就没有这件事了 —— "老规范照样能用"由 :class:`ProjectsLibraryTest` 那组守着。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-two-roots-")
        self.repo = Path(self._tmp.name)
        # 与宿主侧同一个算法：两个根从 comfyui-dir 那一对目录推出来（见 layout 模块）。
        self.in_root = self.repo / "input"
        self.out_root = self.repo / "output"
        self.library = ProjectLibrary(self.in_root, out_directory=self.out_root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---- 根怎么分 -------------------------------------------------------

    def test_not_giving_an_out_root_means_one_tree(self) -> None:
        """不给产物根 = 单树布局。老调用方一行不改还能跑，全靠这一条。"""
        one = ProjectLibrary(self.in_root)
        self.assertTrue(one.single_root)
        self.assertEqual(one.out_directory, one.directory)
        self.assertFalse(self.library.single_root)
        self.assertTrue(self.library.status()["single_root"] is False)
        self.assertEqual(self.library.status()["dir_out"], str(self.out_root))

    def test_every_landing_has_exactly_one_root(self) -> None:
        """每个落点都得有归属，而且**只能有一个**。

        漏一个 = 那一格不知道往哪儿落；两半重叠 = 同一个落点会在两个根下各建一个目录，
        而面板只会去其中一个里找。
        """
        kinds_in = spec_module.dirs_in_root(spec_module.ROOT_INPUT)
        kinds_out = spec_module.dirs_in_root(spec_module.ROOT_OUTPUT)
        self.assertEqual(sorted(kinds_in + kinds_out), sorted(spec_module.PROJECT_DIRS))
        self.assertEqual(set(kinds_in) & set(kinds_out), set())
        # 逐镜片子与成片在产物根（引擎的产物注解读得到），剧本/素材/音频在资料根
        # （加载类节点按名读得到）。
        for rel in ("09_SHOTS", "12_FILMS"):
            self.assertEqual(spec_module.root_of(rel), spec_module.ROOT_OUTPUT, rel)
        for rel in ("11_AUDIO", "08_STORYBOARDS"):
            self.assertEqual(spec_module.root_of(rel), spec_module.ROOT_INPUT, rel)

    def test_a_bare_name_still_means_the_data_root(self) -> None:
        """没列进 ``DIR_ROOTS`` 的落点一律落**资料根** —— 那张表是**例外表**，不是白名单。

        反过来的话，规范里新加一格而这里忘了登记，那一格会**静默**落到产物根：目录建出来了、
        面板上也看得见，就是引擎按名读不到它。
        """
        self.assertEqual(spec_module.root_of("98_没人登记过的格子"), spec_module.ROOT_INPUT)

    # ---- 建项目 ---------------------------------------------------------

    def test_create_puts_each_dir_in_its_own_root(self) -> None:
        self.library.create("剧甲")
        for rel in spec_module.dirs_in_root(spec_module.ROOT_INPUT):
            self.assertTrue((self.in_root / "剧甲" / rel).is_dir(), rel)
            self.assertFalse((self.out_root / "剧甲" / rel).exists(), rel)
        for rel in spec_module.dirs_in_root(spec_module.ROOT_OUTPUT):
            self.assertTrue((self.out_root / "剧甲" / rel).is_dir(), rel)
            self.assertFalse((self.in_root / "剧甲" / rel).exists(), rel)

    def test_create_reports_the_two_roots_separately(self) -> None:
        """两个根**分开报**：合成一份的话，人看见 ``12_FILMS`` 在列表里，就会去资料根下找它。"""
        made = self.library.create("剧甲")
        self.assertEqual(made["path"], str(self.in_root / "剧甲"))
        self.assertEqual(made["path_out"], str(self.out_root / "剧甲"))
        self.assertEqual(set(made["dirs"]), set(spec_module.PROJECT_DIRS_IN))
        self.assertEqual(set(made["dirs_out"]), set(spec_module.PROJECT_DIRS_OUT))

    # ---- 读写要落到对的那个根 -------------------------------------------

    def test_reading_and_writing_a_product_cell_crosses_roots(self) -> None:
        """产物那一格的读写落在**产物根**，而面板拿回来的 ``rel`` 相对**它自己那个根**。

        拿资料根去 relpath，面板会收到 `../../output/剧/09_SHOTS/…` 这种既长又指不到
        地方的字符串 —— 它按这个字符串回来读写，就再也找不到那份文件了。
        """
        self.library.create("剧甲")
        wrote = self.library.write(
            "剧甲", "09_SHOTS/视频提示词.md", "S5 视频提示词：特写，推镜。", base_digest=""
        )
        self.assertEqual(wrote["rel"], "09_SHOTS/视频提示词.md")
        self.assertTrue((self.out_root / "剧甲/09_SHOTS/视频提示词.md").is_file())
        self.assertFalse((self.in_root / "剧甲/09_SHOTS").exists())

        got = self.library.read("剧甲", "09_SHOTS/视频提示词.md")
        self.assertEqual(got["rel"], "09_SHOTS/视频提示词.md")
        self.assertIn("推镜", got["text"])

    def test_roots_hands_the_host_two_absolute_paths(self) -> None:
        """宿主侧就靠这一条：两个根都算成绝对路径，再**显式**交给流水线。

        不显式给的话，流水线只能拿项目**名字**去问事实源，而那条路走环境变量与工作区探测 ——
        和宿主算出来的可以不是同一个根，并且两边都不报错。
        """
        self.library.create("剧甲")
        project, project_out = self.library.roots("剧甲")
        self.assertEqual(project, (self.in_root / "剧甲").resolve())
        self.assertEqual(project_out, (self.out_root / "剧甲").resolve())
        with self.assertRaises(ProjectsError):
            self.library.roots("没有这部剧")


class SpecMigrationTest(unittest.TestCase):
    """`migrate_project` 的 v2 → v3 那一步：把该进产物根的两格**跨根搬**过去。

    这一步动的是真文件（`shutil.move`，不是 copy），而它最坏的失效模式不是报错 ——
    是**把人写好的正本换成一份旧副本**，或者搬丢一份而面板上只是"那一格空了"。
    所以逐条钉住三件事：该搬的搬对、两边都有且内容不同时**一个字节都不动**、预演不落盘。

    两个根由环境变量给（`VOIDE_PROJECTS_ROOT` / `VOIDE_PROJECTS_OUT_ROOT`）——
    那是 :func:`spec.resolve_project` 找根的路，也就是跑 `main.py project migrate` 时走的那条。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-migrate-")
        self.repo = Path(self._tmp.name)
        self.in_root = self.repo / "input"
        self.out_root = self.repo / "output"
        self.project = self.in_root / "剧甲"
        self.project.mkdir(parents=True)
        self.env = mock.patch.dict(
            os.environ,
            {
                "VOIDE_PROJECTS_ROOT": str(self.in_root),
                "VOIDE_PROJECTS_OUT_ROOT": str(self.out_root),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, root: Path, rel: str, text: str) -> Path:
        path = root / "剧甲" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _states(self, res: dict) -> dict:
        """``源相对路径 → 状态``。迁移表的行与跨根那两格都在这一个字典里。"""
        return {src: state for state, src, _dst in res["actions"]}

    def test_the_cross_root_step_moves_what_dir_roots_says(self) -> None:
        """该进产物根的两格搬过去，不该动的一格**原地不动**。

        判据只有事实源的 ``DIR_ROOTS`` 一处：这里另抄一份"哪两格要搬"的话，
        规范将来再把一格挪到产物根，迁移脚本就不会跟着动 —— 而它不报错，只是不搬。
        """
        shot = self._write(self.in_root, "09_SHOTS/EP01/EP01_SH001.mp4", "逐镜片子")
        film = self._write(self.in_root, "12_FILMS/成片.mp4", "成片")
        audio = self._write(self.in_root, "11_AUDIO/EP01.wav", "音频")

        res = spec_module.migrate_project("剧甲", log=None)

        self.assertTrue(res["ok"])
        self.assertEqual(res["path"], str(self.project.resolve()))
        expected = {
            "09_SHOTS/EP01/EP01_SH001.mp4": "逐镜片子",
            "12_FILMS/成片.mp4": "成片",
        }
        for rel, text in expected.items():
            there = self.out_root / "剧甲" / rel
            self.assertTrue(there.is_file(), "%s 该搬到产物根" % rel)
            self.assertEqual(there.read_text(encoding="utf-8"), text)
            self.assertEqual(self._states(res)[rel], "moved", rel)
        for gone in (shot, film):
            self.assertFalse(gone.exists(), "%s 该搬走（源不能留着）" % gone)
        # 旧位置底下搬空了的**子目录**自下而上收掉 —— 留着的话资料根里会挂着一层
        # 谁也对不上的空壳。（落点那一级自己留着，见 `_prune_empty_dirs` 的说明。）
        self.assertFalse((self.project / "09_SHOTS/EP01").exists())
        self.assertEqual(list((self.project / "09_SHOTS").rglob("*")), [])
        self.assertEqual(list((self.project / "12_FILMS").rglob("*")), [])
        # 资料根那一格（音频）一个字节都不该动。
        self.assertTrue(audio.is_file())
        self.assertEqual(audio.read_text(encoding="utf-8"), "音频")
        self.assertFalse((self.out_root / "剧甲/11_AUDIO").exists())

    def test_a_conflict_is_reported_and_nothing_is_touched(self) -> None:
        """两边都有、内容不同 → 报 ``conflict``、``ok=False``，并且**两边都不动**。

        脚本替人挑一份正是它最该拒的事：挑错了就是把人的正本换成旧副本，
        而盘上两份都还在，看起来"迁完了"。
        """
        mine = self._write(self.in_root, "09_SHOTS/EP01_SH001.mp4", "我改过的")
        theirs = self._write(self.out_root, "09_SHOTS/EP01_SH001.mp4", "产物根里那份")

        res = spec_module.migrate_project("剧甲", log=None)

        self.assertFalse(res["ok"])
        self.assertEqual(self._states(res)["09_SHOTS/EP01_SH001.mp4"], "conflict")
        self.assertEqual(mine.read_text(encoding="utf-8"), "我改过的")
        self.assertEqual(theirs.read_text(encoding="utf-8"), "产物根里那份")

    def test_a_duplicate_is_reported_without_deleting_anything(self) -> None:
        """两份一样时报 ``duplicate``（内容相同 = 多半是上一次搬到一半又跑了一遍）。

        报 ``duplicate`` 而不是"删掉多的那一份"：删不删是人定的事，
        而脚本多删一份的代价，跟它多覆盖一份是一样的。
        """
        self._write(self.in_root, "09_SHOTS/EP01_SH001.mp4", "同一份")
        keep = self._write(self.out_root, "09_SHOTS/EP01_SH001.mp4", "同一份")

        res = spec_module.migrate_project("剧甲", log=None)

        self.assertTrue(res["ok"])
        self.assertEqual(self._states(res)["09_SHOTS/EP01_SH001.mp4"], "duplicate")
        self.assertTrue(keep.is_file())
        self.assertTrue((self.project / "09_SHOTS/EP01_SH001.mp4").is_file())

    def test_a_dry_run_reports_but_does_not_touch_the_disk(self) -> None:
        """预演只报不落盘 —— 人要先看见"会搬什么"才敢让它真搬。"""
        shot = self._write(self.in_root, "09_SHOTS/EP01_SH001.mp4", "逐镜片子")

        res = spec_module.migrate_project("剧甲", dry=True, log=None)

        self.assertEqual(self._states(res)["09_SHOTS/EP01_SH001.mp4"], "moved")
        self.assertTrue(shot.is_file())
        self.assertFalse((self.out_root / "剧甲/09_SHOTS/EP01_SH001.mp4").exists())

    def test_one_tree_has_nothing_to_move(self) -> None:
        """单树布局（没配产物根）下这一步**无事可做**，而且不该报错。

        两个根是同一个目录时还去"跨根搬"，目标就是源自己 —— 那样搬一步就把文件弄丢了。
        """
        self._write(self.in_root, "09_SHOTS/EP01_SH001.mp4", "逐镜片子")
        with mock.patch.dict(os.environ, {"VOIDE_PROJECTS_OUT_ROOT": ""}):
            res = spec_module.migrate_project("剧甲", log=None)

        self.assertTrue(res["ok"])
        self.assertNotIn("09_SHOTS/EP01_SH001.mp4", self._states(res))
        self.assertTrue((self.project / "09_SHOTS/EP01_SH001.mp4").is_file())


class ProjectsToolTableTest(unittest.IsolatedAsyncioTestCase):
    """汇进 MCP 工具表那两张：名字、参数、以及"建项目不在这张表里"这条决定。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-projects-tools-")
        self.root = Path(self._tmp.name) / INPUT_SUBDIR
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

    async def test_the_model_can_ask_for_a_fresh_list(self) -> None:
        """模型刚用别的工具往项目里写过东西时，它得能要到"盘上此刻"那一份。

        宿主只知道自己写的那几笔（``_forget_snapshots``）；别的进程写的它不知道，
        所以这个口子必须留在工具表上，而不是只留在面板里。
        """
        tools = await self.client.list_tools()
        listings = next(tool for tool in tools if tool.name == "list")
        self.assertIn("refresh", listings.input_schema["properties"])
        self.library.create("剧甲")
        shot = self.root / "剧甲/09_SHOTS/EP01/SH001.mp4"
        shot.parent.mkdir(parents=True)
        first = json.loads((await self.client.call_tool("list", {}))["content"][0]["text"])
        shot.write_bytes(b"ftyp")
        cached = json.loads((await self.client.call_tool("list", {}))["content"][0]["text"])
        self.assertEqual(cached["projects"][0]["files"], first["projects"][0]["files"])
        fresh = json.loads(
            (await self.client.call_tool("list", {"refresh": True}))["content"][0]["text"]
        )
        self.assertEqual(fresh["projects"][0]["files"], first["projects"][0]["files"] + 1)
        with self.assertRaises(McpError) as wrong:
            await self.client.call_tool("list", {"refresh": "yes"})
        self.assertIn("true / false", str(wrong.exception))


class RealSpecTest(unittest.TestCase):
    """对**真**那份规范：面板的格子必须一个落点都不漏，种子空表必须都在。

    这是"两处清单分家"的唯一机械守卫（分家不报错，只能靠它报），所以它**不许跳过**。
    """

    def setUp(self) -> None:
        self.spec_path = default_spec_path()
        self.assertTrue(
            self.spec_path.is_file(),
            f"包内事实源必须随包一起在，否则面板在真机器上会'没有落点清单'：{self.spec_path}",
        )

    def test_the_default_spec_path_is_the_packaged_one(self) -> None:
        # 默认事实源必须与 projects 模块同一个包：不能靠往上退目录猜（那条路径一旦
        # 猜空就是"没有落点清单"），也不能因为当前工作目录不同而指到别处。
        self.assertEqual(self.spec_path.parent, Path(projects_module.__file__).resolve().parent)
        self.assertEqual(self.spec_path.name, SPEC_NAME)
        self.assertEqual(ProjectLibrary(Path(tempfile.gettempdir())).spec_path, self.spec_path)

    def test_shelves_cover_every_drop_point_of_the_real_spec(self) -> None:
        spec = load_spec(self.spec_path)
        dirs = tuple(spec.PROJECT_DIRS)
        self.assertEqual(shelf_gaps(dirs), (), "规范里有落点没被面板归到任何一格")
        self.assertEqual(shelf_unknown(dirs), (), "面板的格子里写了规范里没有的落点")
        self.assertGreaterEqual(len(dirs), 11)
        self.assertIn("00_PROJECT/01_剧本", dirs)

    def test_every_seed_file_has_a_template_on_disk(self) -> None:
        # 自持之后，"模板在不在"也是这条守卫的一部分：`SEED_FILES` 指的空表必须真能在
        # 包内找到，否则**建项目**会在第一步就抛 —— 而那是只有用户才会撞见的那一步。
        spec = load_spec(self.spec_path)
        template_dir = Path(spec.TEMPLATE_DIR)
        self.assertTrue(template_dir.is_dir(), f"模板目录不在：{template_dir}")
        absent = tuple(src for src, _dst in spec.SEED_FILES
                       if not (template_dir / src).is_file())
        self.assertEqual(absent, (), "种子空表的模板缺了，建项目会当场失败")

    def test_seed_files_never_land_inside_a_stage_drop_point(self) -> None:
        # 体检里"这份文件还算空表吗"只检查种子文件（省掉读每一个产物）。这条断言钉死
        # 那个优化的**前提**：种子路径与任何阶段的 check_dirs 都不重叠。哪天有人把种子
        # 放进 check_dirs，那条优化就不再等价 —— 这里会先炸。
        spec = load_spec(self.spec_path)
        seeds = [dst for _src, dst in spec.SEED_FILES]
        claimed = [rel for _label, rels, _exts in spec.STAGE_OUTPUTS for rel in rels]
        for seed in seeds:
            for rel in claimed:
                self.assertFalse(
                    seed == rel or seed.startswith(rel + "/"),
                    f"种子 {seed} 落进了阶段落点 {rel} —— 体检里'跳过空表'那条优化不再等价",
                )


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
            "projects/migrate",
            "projects/link_novel",
            "projects/brief",
            "projects/write",
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

    def test_write_over_rpc_round_trips_and_refuses_a_stale_digest(self) -> None:
        self.host.projects_create({"name": "流氓天尊"}, None)
        rel = "00_PROJECT/06_对白/对白表_EP01.md"
        page = self.host.projects_read({"name": "流氓天尊", "rel": rel, "chars": 1}, None)
        written = self.host.projects_write(
            {"name": "流氓天尊", "rel": rel, "text": "改了\n", "base_digest": page["digest"]}, None
        )
        self.assertFalse(written["created"])
        self.assertNotEqual(written["digest"], page["digest"])
        # 拿着读过的旧 digest 再写一次 —— 中间那份文件已经变了，必须拒写。
        with self.assertRaises(RpcError) as stale:
            self.host.projects_write(
                {"name": "流氓天尊", "rel": rel, "text": "又改\n", "base_digest": page["digest"]}, None
            )
        self.assertEqual(stale.exception.code, INTERNAL_ERROR)
        self.assertIn("被改过", stale.exception.message)
        # 压根没读过就写 —— 等于盲写，拒。
        with self.assertRaises(RpcError) as blind:
            self.host.projects_write({"name": "流氓天尊", "rel": rel, "text": "盲写\n"}, None)
        self.assertEqual(blind.exception.code, INTERNAL_ERROR)
        self.assertIn("先读一遍", blind.exception.message)

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
            ("projects_migrate", {}),
            ("projects_migrate", {"name": "甲", "dry": "yes"}),
            ("projects_link_novel", {"name": "甲", "novel": "  "}),
            ("projects_brief", {"name": "  "}),
            ("projects_write", {"name": "甲", "rel": "x.md"}),
            ("projects_write", {"name": "甲", "rel": "x.md", "text": 5}),
            ("projects_write", {"name": "甲", "rel": "x.md", "text": "x", "base_digest": 5}),
            ("projects_write", {"name": "甲", "rel": "  ", "text": "x"}),
            ("projects_read", {"name": "甲", "rel": "x.md", "whole": 5}),
            ("projects_list", {"name": 5}),
            ("projects_list", {"refresh": "yes"}),
        ):
            with self.subTest(method=method, params=params):
                with self.assertRaises(RpcError) as err:
                    getattr(self.host, method)(params, None)
                self.assertEqual(err.exception.code, INVALID_PARAMS)

    def test_refresh_over_rpc_asks_for_the_disk_as_it_is(self) -> None:
        """面板那个「刷新」键走的就是这条：不是"再问一遍同样的东西"。

        默认那一下（不带 ``refresh``）是列表自己的优化；带上的那一下是用户自己要看的。
        """
        self.host.projects_create({"name": "剧丁"}, None)
        shot = self.root / "剧丁/09_SHOTS/EP01/SH001.mp4"
        shot.parent.mkdir(parents=True)
        self.host.projects_list({}, None)
        stale = self.host.projects_list({}, None)["projects"][0]
        shot.write_bytes(b"ftyp")
        again = self.host.projects_list({}, None)["projects"][0]
        self.assertEqual(again["files"], stale["files"])
        fresh = self.host.projects_list({"refresh": True}, None)["projects"][0]
        self.assertEqual(fresh["files"], stale["files"] + 1)

    def test_a_missing_project_is_an_internal_error_with_a_readable_message(self) -> None:
        with self.assertRaises(RpcError) as err:
            self.host.projects_tree({"name": "查无此剧"}, None)
        self.assertEqual(err.exception.code, INTERNAL_ERROR)
        self.assertIn("没有这个项目", err.exception.message)

    def test_migrate_over_rpc_says_which_spec_cannot_do_it(self) -> None:
        # FAKE_SPEC 是一份**老**规范（没有 migrate_project）：不知道"两个根"这件事的实现
        # 硬跑只会把产物格留在资料根下，而它会**报成功**。所以这里宁可不做，把原因说清。
        self.host.projects_create({"name": "流氓天尊"}, None)
        with self.assertRaises(RpcError) as err:
            self.host.projects_migrate({"name": "流氓天尊", "dry": True}, None)
        self.assertEqual(err.exception.code, INTERNAL_ERROR)
        self.assertIn("migrate_project", err.exception.message)


class ProjectMigrateTest(unittest.TestCase):
    """``ProjectLibrary.migrate``：面板上那一下「搬家」的落盘与回执（**真规范** + 两个根）。

    为什么这条通道值得单独一组用例：它是唯一一个**移动人已经做好的东西**的动作。
    预演报错只是白点一下；真搬搬错则是"文件到了另一个目录里，而面板那一格空着" ——
    两边都不报错，事后没人知道东西去哪了。所以这里钉的四件事是：预演不落盘、
    真搬搬对且源不留、冲突两边都不动还要报上来、单树布局下原地不动。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-migrate-lib-")
        self.repo = Path(self._tmp.name)
        self.in_root = self.repo / "input"
        self.out_root = self.repo / "output"
        self.library = ProjectLibrary(self.in_root, out_directory=self.out_root)
        self.addCleanup(self._tmp.cleanup)

    def _v2_project(self) -> Path:
        """搭一部**v2 结构**的老项目：产物格还在资料根里，全剧级设定还在 v1 位置。"""
        path = self.in_root / "剧甲"
        (path / "09_SHOTS/EP01").mkdir(parents=True)
        (path / "09_SHOTS/EP01/EP01_SH001.mp4").write_text("逐镜片子", encoding="utf-8")
        (path / "00_PROJECT/01_剧本").mkdir(parents=True)
        (path / "00_PROJECT/01_剧本/分集大纲与三表.md").write_text("大纲", encoding="utf-8")
        return path

    def _by_rel(self, res: dict) -> dict:
        return {item["rel"]: item for item in res["actions"]}

    def test_a_dry_run_shows_where_each_thing_would_go(self) -> None:
        path = self._v2_project()

        res = self.library.migrate("剧甲", dry=True)

        self.assertTrue(res["dry"])
        self.assertTrue(res["ok"])
        self.assertFalse(res["single_root"])
        seen = self._by_rel(res)
        # 同根内收拢（v1 → v2）：源与目标都在资料根
        v1 = seen["00_PROJECT/01_剧本/分集大纲与三表.md"]
        self.assertEqual(v1["state"], "moved")
        self.assertEqual(v1["root"], "input")
        self.assertEqual(v1["dst"], str(path / "00_PROJECT/01_剧本/00_总纲/分集大纲与三表.md"))
        # 跨根（v2 → v3）：**相对路径两边一模一样**，所以回执必须给出绝对路径 + 哪个根 ——
        # 只给相对路径的话，面板画出来的"从哪搬到哪"是同一句话，等于没说。
        shot = seen["09_SHOTS/EP01/EP01_SH001.mp4"]
        self.assertEqual(shot["state"], "moved")
        self.assertEqual(shot["root"], "output")
        self.assertEqual(shot["src"], str(path / "09_SHOTS/EP01/EP01_SH001.mp4"))
        self.assertEqual(shot["dst"], str(self.out_root / "剧甲/09_SHOTS/EP01/EP01_SH001.mp4"))
        # 预演：盘上一个字节都没动（只报了"会搬两份"）
        self.assertEqual(res["counts"].get("moved"), 2)
        self.assertTrue((path / "09_SHOTS/EP01/EP01_SH001.mp4").is_file())
        self.assertTrue((path / "00_PROJECT/01_剧本/分集大纲与三表.md").is_file())
        self.assertFalse((self.out_root / "剧甲").exists())

    def test_it_moves_for_real_and_leaves_nothing_behind(self) -> None:
        path = self._v2_project()

        res = self.library.migrate("剧甲")

        self.assertFalse(res["dry"])
        self.assertTrue(res["ok"])
        there = self.out_root / "剧甲/09_SHOTS/EP01/EP01_SH001.mp4"
        self.assertEqual(there.read_text(encoding="utf-8"), "逐镜片子")
        # 源**不能留**：留着的话资料根里还是那一格"有东西"，而面板看的是产物根。
        self.assertFalse((path / "09_SHOTS/EP01/EP01_SH001.mp4").exists())
        self.assertTrue((path / "00_PROJECT/01_剧本/00_总纲/分集大纲与三表.md").is_file())
        self.assertFalse((path / "00_PROJECT/01_剧本/分集大纲与三表.md").exists())
        # 顺手回的体检是**搬之后**的，且两个根一起数（这件东西现在横跨两边）
        self.assertEqual(res["summary"]["files"], 2)

    def test_a_conflict_is_reported_and_neither_copy_is_touched(self) -> None:
        path = self._v2_project()
        mine = path / "09_SHOTS/EP01/EP01_SH001.mp4"
        theirs = self.out_root / "剧甲/09_SHOTS/EP01/EP01_SH001.mp4"
        theirs.parent.mkdir(parents=True)
        theirs.write_text("产物根那份", encoding="utf-8")

        res = self.library.migrate("剧甲")

        self.assertFalse(res["ok"])
        self.assertEqual(res["conflicts"], ["09_SHOTS/EP01/EP01_SH001.mp4"])
        self.assertEqual(mine.read_text(encoding="utf-8"), "逐镜片子")
        self.assertEqual(theirs.read_text(encoding="utf-8"), "产物根那份")
        # 逐行独立：**没有冲突的那一行照常搬**（冲突只拦住它自己那一份），报告里逐条列着。
        self.assertEqual(self._by_rel(res)["00_PROJECT/01_剧本/分集大纲与三表.md"]["state"], "moved")
        self.assertTrue((path / "00_PROJECT/01_剧本/00_总纲/分集大纲与三表.md").is_file())

    def test_a_single_root_library_moves_nothing_between_roots(self) -> None:
        library = ProjectLibrary(self.in_root)          # 单树：两个根是同一个目录
        (self.in_root / "剧甲/09_SHOTS").mkdir(parents=True)
        (self.in_root / "剧甲/09_SHOTS/EP01_SH001.mp4").write_text("逐镜片子", encoding="utf-8")

        res = library.migrate("剧甲")

        self.assertTrue(res["single_root"])
        self.assertEqual([item for item in res["actions"] if item["root"] == "output"], [])
        # 产物格**原地不动**：它本来就该在唯一的那个根里 —— 这时候还去"跨根搬"，
        # 目标就是源自己。
        self.assertTrue((self.in_root / "剧甲/09_SHOTS/EP01_SH001.mp4").is_file())
        self.assertEqual(res["moved"], 0)

    def test_a_missing_project_is_a_readable_error(self) -> None:
        with self.assertRaises(ProjectsError) as err:
            self.library.migrate("查无此剧")
        self.assertIn("没有这个项目", str(err.exception))
