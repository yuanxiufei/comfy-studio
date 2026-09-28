# -*- coding: utf-8 -*-
"""项目脚手架与体检（`08-项目管理/项目目录规范.md`）的测试。

═══════════════════════════════════════════════════════════════════
重点（沿用本项目铁律：证明它**真的会报**，而不是"正常情况能过"）
═══════════════════════════════════════════════════════════════════
钉住五条不变量：

  ① **两处清单必须一致** —— `src/project.py` 的 `PROJECT_DIRS`
     与规范文档 §一 的目录树逐项相同。
     之所以要钉：目录清单天然是两处（文档给人看、代码给机器跑），
     而两者不一致的失效模式**不报错** —— 文档加了 `06_对白/`、代码没加，
     结果新项目永远缺那个落点，直到有人要交配音单才发现。
  ② **建项目不许覆盖** —— 二次跑 / `--升级` 跑，已有人工内容的文件保持原样。
  ③ **体检不许自欺** —— 刚建完的项目**不得**显示"S0 已完成"。
     预置空表若被当成产物，体检就从"体检"退化成"安慰剂"。
  ④ **不写死机器路径** —— 源码里不得出现盘符绝对路径（换台机器就静默跳过）。
  ⑤ **同一知识一处维护** —— 节奏常数（台词语速/目标时长/时长容差）只有
     `storyboard.py` 一份，别处不得再存同值副本（改一处、另几处静默失效）。
  ⑥ **迁移不许覆盖** —— v1 → v2 只把平铺在 `01_剧本/` 的**全剧级**设定收进
     `00_总纲/`；目标已存在且内容不同时**两边都不动**并报冲突。
     迁移脚本最坏的失效模式不是报错，是把人写的正本换成一份旧副本。
  ⑦ **粒度是数据，不是注脚** —— `DIR_SCOPES` 必须与规范 §三 的「粒度」列逐项一致。
     粒度判错的失效模式是静默的：面板把一集的对白表摆进"全剧共用"那一栏，
     或者反过来 —— 没人会收到报错。

运行：`python tests/test_project.py`
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import pipeline, project        # noqa: E402


def _stages(res: dict) -> dict:
    return {label: hits for label, _rel, hits in res["stages"]}


class ProjectScaffoldTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="manju_proj_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.name = "测试剧"

    def _new(self, **kw):
        return project.create_project(self.name, root=self.tmp, log=None, **kw)

    def _p(self, *parts) -> str:
        return os.path.join(self.tmp, self.name, *parts)

    # ── ① 两处清单一致 ────────────────────────────────────────

    def test_dirs_match_spec_doc(self):
        """`PROJECT_DIRS` 必须与规范文档 §一 的树逐项一致（顺序也算）。"""
        spec = project.spec_dirs_from_doc()
        self.assertTrue(spec, "规范文档里没抽出任何目录 —— 树的写法变了？")
        self.assertEqual(list(project.PROJECT_DIRS), spec,
                         "目录清单与 `08-项目管理/项目目录规范.md` §一 不一致："
                         "改了文档就要改 src/project.py，反之亦然")

    def test_pipeline_reuses_the_same_list(self):
        """pipeline 不得另抄一份骨架清单（曾经的失效点就在这）。"""
        self.assertIs(pipeline.SKELETON_DIRS, project.PROJECT_DIRS)

    def test_new_dirs_are_covered(self):
        """那次漏掉的三个落点必须都在清单里。"""
        for rel in ("00_PROJECT/06_对白", "00_PROJECT/07_素材归档", "11_AUDIO"):
            self.assertIn(rel, project.PROJECT_DIRS)

    # ── 建项目 ───────────────────────────────────────────────

    def test_create_builds_every_dir(self):
        res = self._new()
        for rel in project.PROJECT_DIRS:
            self.assertTrue(os.path.isdir(os.path.join(self.tmp, self.name,
                                                       *rel.split("/"))), rel)
        self.assertEqual(len(res["dirs"]), len(project.PROJECT_DIRS))

    def test_seed_files_written_with_project_name(self):
        res = self._new()
        self.assertTrue(res["files"], "一份空表都没写出来")
        readme = self._p("README.md")
        body = Path(readme).read_text(encoding="utf-8")
        self.assertIn(self.name, body, "项目名没写进入口文件")
        self.assertNotIn("{{", body, "模板占位符没被替换干净")

    def test_episodes_recorded(self):
        self._new(episodes=40)
        body = Path(self._p("README.md")).read_text(encoding="utf-8")
        self.assertIn("40", body)

    def test_templates_all_exist(self):
        for src, dst in project.SEED_FILES:
            self.assertTrue(os.path.isfile(os.path.join(project.TEMPLATE_DIR, src)),
                            "模板缺失：%s（它要落成 %s）" % (src, dst))

    def test_dry_run_touches_nothing(self):
        res = self._new(dry=True)
        self.assertFalse(os.path.exists(res["path"]), "--预演 不该落盘")
        self.assertTrue(res["dirs"])

    # ── ② 不许覆盖 ───────────────────────────────────────────

    def test_existing_project_refuses_without_upgrade(self):
        self._new()
        with self.assertRaises(project.ProjectError) as cm:
            self._new()
        self.assertIn("--升级", str(cm.exception),
                      "报错信息要告诉人怎么修，不能只说一句失败")

    def test_second_run_keeps_human_edits(self):
        self._new()
        target = self._p("00_PROJECT", "06_对白", "对白表_EP01.md")
        Path(target).write_text("人手写的内容", encoding="utf-8")
        res = project.create_project(self.name, root=self.tmp,
                                     upgrade=True, log=None)
        self.assertIn("00_PROJECT/06_对白/对白表_EP01.md", res["skipped"])
        self.assertEqual(Path(target).read_text(encoding="utf-8"), "人手写的内容")

    def test_upgrade_fills_only_missing(self):
        self._new()
        gone = self._p("11_AUDIO")
        shutil.rmtree(gone)
        res = project.create_project(self.name, root=self.tmp,
                                     upgrade=True, log=None)
        self.assertTrue(os.path.isdir(gone), "升级没补回缺的落点")
        self.assertIn("11_AUDIO/", res["dirs"])
        self.assertEqual(res["files"], [], "升级不该再写空表（那些文件已在）")

    def test_bad_episodes_rejected(self):
        with self.assertRaises(project.ProjectError):
            self._new(episodes=0)

    # ── ③ 体检不许自欺 ───────────────────────────────────────

    def test_check_not_fooled_by_seed_files(self):
        """⭐ 刚建完的项目：落点齐，但**任何阶段都不该显示"有产物"**。"""
        res = self._new()
        got = project.scan_project(res["path"])
        self.assertEqual(got["missing"], [], "刚建完就报缺落点")
        stages = _stages(got)
        # 逐个阶段都过一遍，而不是挑两个名字断言 —— 挑名字的写法在阶段表增删时
        # **静默漏管**（2026-09-28 加 S2 出图 / S3 表情 / 动作 时正是这样）。
        self.assertEqual(
            sorted(stages),
            ["S0 建纲", "S1 资产设计", "S2 出图", "S3 表情 / 动作",
             "S4 分镜", "S5 视频", "S6 音频", "S7 合规"],
            "阶段表变了：对照 src/project.py 的 STAGE_SPECS 与两份流程文档",
        )
        for label, hits in stages.items():
            self.assertEqual(hits, [], "%s 把空模板占了位当成了产物（体检变安慰剂）" % label)

    def test_check_sees_real_output(self):
        self._new()
        script = self._p("00_PROJECT", "01_剧本", "EP01-剧本.md")
        Path(script).write_text("# EP01 真剧本", encoding="utf-8")
        stages = _stages(project.scan_project(self._p()))
        self.assertEqual(len(stages["S0 建纲"]), 1)

    def test_check_ignores_gitkeep(self):
        """`.gitkeep` 是占位，不是产物。"""
        self._new()
        self.assertEqual(_stages(project.scan_project(self._p()))["S4 分镜"], [])

    def test_check_reports_missing_dir(self):
        res = self._new()
        shutil.rmtree(self._p("11_AUDIO"))
        got = project.scan_project(res["path"])
        self.assertIn("11_AUDIO", got["missing"])
        self.assertIn("11_AUDIO", project.format_report(got))

    def test_report_tells_how_to_fix(self):
        res = self._new()
        shutil.rmtree(self._p("11_AUDIO"))
        text = project.format_report(project.scan_project(res["path"]))
        self.assertIn("--升级", text)

    def test_unknown_project_raises(self):
        with self.assertRaises(project.ProjectError):
            project.scan_project("这个项目名一定不存在_" + os.urandom(4).hex())

    def test_resolve_by_path(self):
        res = self._new()
        self.assertEqual(project.resolve_project(res["path"]), res["path"])

    # ── ④ 不写死机器路径 ─────────────────────────────────────

    def test_no_hardcoded_drive_path_in_source(self):
        """源码里出现 `X:\\` 这类盘符路径 → 换台机器就静默跳过，属低级错误。

        扫**整个 `src/`**而不是一份文件名清单：清单式守卫在文件被切开/新增时
        会静默漏管（`pipeline.py` 2026-09-27 拆成 `flow_core.py` + `flow_prompts.py`
        就是例子 —— 新文件不扫就等于没守卫）。
        正则排除 `https://` 这类协议头（`s:/` 也长得像盘符）。
        """
        pat = re.compile(r"(?<!\w)[A-Za-z]:[\\/](?!/)")
        srcs = sorted((Path(project.ROOT) / "src").glob("*.py"))
        self.assertTrue(srcs, "src/ 下一份 .py 都没扫到 —— 根目录推错了？")
        for p in srcs:
            hit = pat.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(hit, "%s 里出现盘符路径：%r" % (p.name, hit.group(0) if hit else ""))

    # ── ⑤ 同一知识一处维护 ───────────────────────────────────

    def test_rhythm_constants_have_one_home(self):
        """节奏常数（台词语速/目标时长/时长容差）**只有 `storyboard.py` 一份**。

        2026-09-27 收口前是三份同值副本：`flow_core.LINE_CPS = 4.5`、
        `flow_core.TARGET_SEC = 105.0`、`storyboard.shots_markdown(target_sec=105.0)`，
        外加 `pipeline` 里两处硬写 `* 1.3`（= `1 + storyboard.TOL`）。
        同值副本的失效模式是**改一处、另几处静默失效**（改台词预算却不改时长估计，
        或是反过来）—— 它**不会报错**，所以只能用机械守卫钉。

        判据取**定义形态**而不是裸值：`4.5` / `105.0` 在 docstring 与规则章节号
        （`§四·4.5`）里合法出现，拿值去扫会误报。
        """
        from src import flow_core, storyboard
        # 唯一来源本身要还在（守卫不能因为名字被改就静默失效）
        self.assertEqual((storyboard.CPS, storyboard.TARGET_SEC, storyboard.TOL),
                         (4.5, 105.0, 0.30))
        for mod in (flow_core, pipeline):
            for name in ("LINE_CPS", "TARGET_SEC"):
                self.assertFalse(hasattr(mod, name),
                                 f"{mod.__name__} 又出现了 `{name}` 副本 —— "
                                 f"唯一来源是 storyboard.py")

        pat = re.compile(r"^\s*(LINE_CPS|TARGET_SEC)\s*=", re.M)
        srcs = sorted((Path(project.ROOT) / "src").glob("*.py"))
        self.assertTrue(srcs, "src/ 下一份 .py 都没扫到 —— 根目录推错了？")
        for p in srcs:
            if p.name == "storyboard.py":
                continue
            body = p.read_text(encoding="utf-8")
            hit = pat.search(body)
            self.assertIsNone(hit, "%s 里又定义了 %s —— 唯一来源是 storyboard.py"
                              % (p.name, hit.group(1) if hit else ""))
            self.assertNotIn("* 1.3", body,
                             "%s 里硬写了 `* 1.3` —— 那是 `1 + storyboard.TOL`，"
                             "会跟着 TOL 漂移" % p.name)

    def test_dir_constants_are_in_the_skeleton(self):
        """各处写死的**目录名**必须是 `project.PROJECT_DIRS` 里的项（或它的路径前缀）。

        这类重复最隐蔽：它们不是清单（没法整体比对），只是散落的字符串。
        规范改了目录名（如 `02_CHARACTERS` 改名），`PROJECT_DIRS` 与规范文档会一起改，
        而 `flow_core.SCRIPT_DIR` / `storyboard.STORYBOARD_DIR` 这类常量**不报错** ——
        表现是"图明明出了却归档不进去"，属静默失效。
        """
        from src import flow_core, storyboard
        dirs = tuple(project.PROJECT_DIRS)
        self.assertTrue(dirs, "PROJECT_DIRS 是空的 —— 这条守卫会静默通过")
        targets = [(flow_core, "PROJ"), (flow_core, "SCRIPT_DIR"),
                   (flow_core, "SCRIPT_META_DIR"),
                   (flow_core, "INDEX_DIR"), (flow_core, "LEDGER_DIR"),
                   (flow_core, "DELIVERY_DIR"), (flow_core, "ASSET_DIRS"),
                   (storyboard, "STORYBOARD_DIR"), (storyboard, "SHOTS_DIR")]
        for mod, name in targets:
            val = getattr(mod, name)
            for v in (val.values() if isinstance(val, dict) else [val]):
                ok = v in dirs or any(d.startswith(v + "/") for d in dirs)
                self.assertTrue(ok, "%s.%s = %r 不在 `project.PROJECT_DIRS` 里 —— "
                                "规范改了目录名，这里会静默找不到目录"
                                % (mod.__name__, name, v))

    def test_roots_are_derived_from_file(self):
        """根目录必须由 `__file__` 推出来，而不是写死。"""
        self.assertEqual(Path(project.ROOT).name, "07-智能体运行时")
        self.assertEqual(Path(project.WORKFLOW_ROOT).name, "AI漫剧智能体工作流")
        self.assertTrue(os.path.isfile(project.SPEC_FILE))

    # ── ⑥ v1 → v2 结构迁移 ───────────────────────────────────

    def _v1_layout(self) -> str:
        """手工摆一个 v1 老项目：**全剧级**数据和分集正文平铺在 `01_剧本/`。

        这是 v1 的真实形态 —— 落点一个不缺，所以"缺落点"那套体检对它毫无反应。
        """
        self._new()
        mk = self._p("00_PROJECT", "01_剧本")
        Path(mk, "分集大纲与三表.md").write_text("三表正文", encoding="utf-8")
        Path(mk, "_分集大纲.json").write_text('{"剧名": "测试剧"}', encoding="utf-8")
        Path(mk, "角色小传.md").write_text("小传正文", encoding="utf-8")
        Path(mk, "EP01-剧本.md").write_text("# EP01", encoding="utf-8")
        return mk

    def test_migrate_moves_whole_drama_settings(self):
        mk = self._v1_layout()
        res = project.migrate_project(self._p(), log=None)
        self.assertTrue(res["ok"])
        self.assertEqual([a[0] for a in res["actions"]], ["moved"] * 3)
        self.assertFalse(os.path.exists(os.path.join(mk, "分集大纲与三表.md")),
                         "老位置还留着一份 —— 那是被复制而不是被移动")
        got = Path(mk, "00_总纲", "分集大纲与三表.md").read_text(encoding="utf-8")
        self.assertEqual(got, "三表正文", "搬过去之后内容变了")
        self.assertTrue(os.path.isfile(os.path.join(mk, "00_总纲", "_分集大纲.json")),
                        "大纲 JSON 没搬 —— 建纲会读不到它，然后重写一份覆盖掉人的改动")
        self.assertTrue(os.path.isfile(os.path.join(mk, "EP01-剧本.md")),
                        "分集正文是分集级的，不该被搬走")

    def test_migrate_is_idempotent(self):
        self._v1_layout()
        project.migrate_project(self._p(), log=None)
        res = project.migrate_project(self._p(), log=None)
        self.assertTrue(res["ok"], "二次跑报失败 —— 幂等没做到")
        self.assertEqual([a[0] for a in res["actions"]], ["skip"] * 3)

    def test_migrate_never_overwrites(self):
        """⭐ 目标已存在且**内容不同** → 报冲突，两边一个字节都不动。

        这条守的是迁移最坏的失效模式：脚本替人选一份，把人手写的正本换成旧副本，
        而且**不报错**。宁可停下来喊人。
        """
        mk = self._v1_layout()
        dst = Path(mk, "00_总纲", "分集大纲与三表.md")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("人手写的正本", encoding="utf-8")
        res = project.migrate_project(self._p(), log=None)
        self.assertFalse(res["ok"], "有冲突却报成功 —— 人会以为已经迁完了")
        self.assertEqual(res["actions"][0][0], "conflict")
        self.assertEqual(dst.read_text(encoding="utf-8"), "人手写的正本", "目标被覆盖了")
        self.assertEqual(Path(mk, "分集大纲与三表.md").read_text(encoding="utf-8"),
                         "三表正文", "源被删了")

    def test_migrate_duplicate_keeps_the_source(self):
        """两边内容一样 → 只报 duplicate，**不替人删源**（删哪份是人决定的）。"""
        mk = self._v1_layout()
        dst = Path(mk, "00_总纲", "分集大纲与三表.md")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("三表正文", encoding="utf-8")
        res = project.migrate_project(self._p(), log=None)
        self.assertTrue(res["ok"])
        self.assertEqual(res["actions"][0][0], "duplicate")
        self.assertTrue(os.path.isfile(os.path.join(mk, "分集大纲与三表.md")))

    def test_migrate_dry_run_touches_nothing(self):
        mk = self._v1_layout()
        res = project.migrate_project(self._p(), dry=True, log=None)
        self.assertEqual([a[0] for a in res["actions"]], ["moved"] * 3)
        self.assertTrue(os.path.isfile(os.path.join(mk, "分集大纲与三表.md")),
                        "--预演 不该落盘")
        self.assertFalse(os.path.exists(os.path.join(mk, "00_总纲",
                                                    "分集大纲与三表.md")))

    def test_check_reports_v1_layout(self):
        """v1 是新旧交替期的**静默**问题：落点一个不缺，只有体检点得出来。"""
        self._v1_layout()
        got = project.scan_project(self._p())
        self.assertEqual(got["missing"], [], "v1 布局并不缺落点 —— 靠缺落点发现不了它")
        self.assertIn("00_PROJECT/01_剧本/分集大纲与三表.md", got["legacy"])
        self.assertIn("project migrate", project.format_report(got),
                      "体检报了问题却没给修法")

    def test_check_is_quiet_on_v2_layout(self):
        """新项目（v2）不该被误报成待迁移。"""
        self._new()
        got = project.scan_project(self._p())
        self.assertEqual(got["legacy"], [])
        self.assertNotIn("project migrate", project.format_report(got))

    def test_migration_targets_live_in_the_new_landing(self):
        """迁移目标必须落在新落点里，来源就是 v1 那两份 —— 别处不许偷偷加。"""
        landing = "00_PROJECT/01_剧本/00_总纲"
        self.assertIn(landing, project.PROJECT_DIRS, "新落点没进清单，迁移目标无处可落")
        self.assertTrue(project.MIGRATIONS, "迁移表空了 —— 这条守卫会静默通过")
        for src_rel, dst_rel in project.MIGRATIONS:
            self.assertEqual(os.path.dirname(dst_rel), landing, dst_rel)
            self.assertEqual(os.path.dirname(src_rel), "00_PROJECT/01_剧本", src_rel)
            self.assertNotEqual(src_rel, dst_rel)

    def test_migration_map_matches_spec_doc(self):
        """§四 的迁移表必须与 `MIGRATIONS` 对得上 —— 否则文档说的和跑的不是一回事。"""
        body = Path(project.SPEC_FILE).read_text(encoding="utf-8")
        for src_rel, dst_rel in project.MIGRATIONS:
            self.assertIn(src_rel, body, "§四 没写源路径：%s" % src_rel)
            self.assertIn(dst_rel, body, "§四 没写目标路径：%s" % dst_rel)

    # ── ⑦ 粒度（全剧级 / 分集级）───────────────────────────────

    def test_scopes_match_spec_doc(self):
        """`DIR_SCOPES` 必须与规范 §三 的「粒度」列逐项一致（键集与取值都算）。

        粒度判错的失效模式**不报错**：把一集的对白表摆进"全剧共用"那一栏，
        或把全剧设定摆进分集栏 —— 两边都还长得像模像样。
        """
        doc = project.spec_scopes_from_doc()
        self.assertTrue(doc, "§三 里一个粒度都没抽到 —— 表的写法变了？")
        self.assertEqual(project.DIR_SCOPES, doc,
                         "粒度表与 `08-项目管理/项目目录规范.md` §三 不一致："
                         "改了文档就要改 src/project.py 的 DIR_SCOPES，反之亦然")

    def test_scopes_cover_every_landing(self):
        """每个落点都要有粒度 —— 少一个，面板那一格就只能猜。"""
        missing = [rel for rel in project.PROJECT_DIRS if rel not in project.DIR_SCOPES]
        self.assertEqual(missing, [], "这些落点没标粒度")
        strays = [rel for rel in project.DIR_SCOPES if rel not in project.PROJECT_DIRS]
        self.assertEqual(strays, [], "粒度表里写了清单里没有的落点")

    def test_scope_values_are_known_ones(self):
        """取值只许是这三种 —— 否则面板那边的分组逻辑会把它漏掉。"""
        known = {project.SCOPE_WHOLE, project.SCOPE_EPISODE, project.SCOPE_MIXED}
        self.assertEqual(known, {"全剧级", "分集级", "混合"})
        for rel, scope in project.DIR_SCOPES.items():
            self.assertIn(scope, known, "%s 的粒度是 %r" % (rel, scope))

    def test_the_one_place_two_scopes_live_together(self):
        """⭐ `01_剧本/`（分集级）与它下面的 `00_总纲/`（全剧级）正是 v2 的理由。

        这条盯住"两种粒度并存"这件事本身：它俩要是变成一个粒度，v2 就白分了，
        而面板那边按粒度分组也会退化成只有一组（看不出坏）。
        """
        self.assertEqual(project.DIR_SCOPES["00_PROJECT/01_剧本"], project.SCOPE_EPISODE)
        self.assertEqual(project.DIR_SCOPES["00_PROJECT/01_剧本/00_总纲"],
                         project.SCOPE_WHOLE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
