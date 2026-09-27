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
        self.assertEqual(stages["S0 建纲"], [], "空模板被当成了 S0 产物（体检变安慰剂）")
        self.assertEqual(stages["S1 资产设计"], [])
        self.assertEqual(stages["S6 音频"], [])
        self.assertEqual(stages["S7 一致性"], [])

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
