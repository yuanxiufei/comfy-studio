# -*- coding: utf-8 -*-
"""阶段（S0–S7）与工作流配合的机械守卫 —— 逐文件跑：python tests/test_stages.py

**为什么要这些测试**：阶段定义原先四处在说 —— `flow_core.STAGES`（六段）、
`src/project.py` 的 `STAGE_OUTPUTS`（六桶）、`生产流程规范（S0-S7）.md` §一（八阶段）、
`08-项目管理/流程与落点映射.md` §一（八行）。四处不一致**全都不报错**：

- 文档指着一个不存在的入口（`pipeline.py` 的 docstring 曾写 `main.py run expression`，
  而注册表里只有 `asset`，没有任何一处会红）；
- 体检桶里的阶段名和阶段表里的对不上（"S7 一致性" vs "S7 合规"），面板上就多出
  一格谁也对不上的东西；
- 用户照着映射表敲 `--阶段 表情`，拿到的是 argparse 一句 `invalid choice` ——
  没有任何一处告诉他 S3 走 `main.py ask`。

所以这里把每一处都焊上：

- 阶段表 ↔ 两份文档（`(编号, 名字, 负责模块)` 逐项相等）
- 落点 ↔ `PROJECT_DIRS`（不许另造一套路径写法）
- 入口 ↔ **真入口**（`flow` 段名 ∈ `flow_core.ORDER`；`main.py <子命令>` 真存在；
  `run <agent>` 的 agent 真在注册表里）
- 图片后缀 ↔ `flow_core.PNG_EXTS`（同一份知识存了两处，钉住不许分家）
"""

from __future__ import annotations

import argparse
import contextlib
import io
import unittest

from src import flow_core, project, registry


def _parse_entry(cmd: str) -> tuple:
    """把文档里那条命令解析成 `(kind, key, agent)` —— 只解析**开头那一段**。

    认得两种写法（映射表 §一 的「命令」列只许有这两种）：

        flow -p <项目> --阶段 建纲   →  ("flow", "建纲", "")
        main.py angles <ENV_ID>      →  ("cli", "angles", "")
        main.py run audio "…"        →  ("cli", "run", "audio")

    认不出就**抛断言**：文档里冒出第三种写法时，这里要显式红，而不是静静放过。
    """
    toks = cmd.strip().split()
    if not toks:
        raise AssertionError("映射表里那条命令是空的")
    if toks[0] == "flow":
        if "--阶段" not in toks:
            raise AssertionError("`flow` 命令里没写 `--阶段`：%r" % cmd)
        return "flow", toks[toks.index("--阶段") + 1], ""
    if toks[0].endswith("main.py"):
        sub = toks[1] if len(toks) > 1 else ""
        if sub == "run":
            return "cli", "run", (toks[2] if len(toks) > 2 else "")
        return "cli", sub, ""
    raise AssertionError("认不出的命令写法（只许 `flow …` 与 `main.py …`）：%r" % cmd)


class StagesDocTest(unittest.TestCase):
    """阶段表 ↔ 两份流程文档。"""

    def test_specs_match_authority_doc(self):
        """⭐ `STAGE_SPECS` 的 (编号, 名字, 负责模块) 必须与权威总表逐项一致。"""
        doc = project.spec_stages_from_doc()
        self.assertTrue(doc, "§一 一个阶段都没抽到 —— 表的写法变了？")
        mine = [(s.code, s.name, s.owner) for s in project.STAGE_SPECS]
        self.assertEqual(
            mine, doc,
            "阶段表与 `生产流程规范（S0-S7）.md` §一 不一致："
            "改了文档就要改 src/project.py 的 STAGE_SPECS，反之亦然")

    def test_specs_match_map_doc(self):
        """⭐ 映射表 §一 的阶段列与 agent 列也要一致（它是给人照着敲的那张表）。"""
        doc = project.spec_stage_map_from_doc()
        self.assertTrue(doc, "§一 主表一个阶段都没抽到 —— 写法变了？")
        self.assertEqual([(c, n) for c, n, _a, _cmd in doc],
                         [(s.code, s.name) for s in project.STAGE_SPECS],
                         "`08-项目管理/流程与落点映射.md` §一 的阶段与 STAGE_SPECS 不一致")
        self.assertEqual([a for _c, _n, a, _cmd in doc],
                         [s.owner for s in project.STAGE_SPECS],
                         "映射表的 agent 列与 STAGE_SPECS 的 owner 不一致")

    def test_stage_order_has_no_gaps(self):
        """编号就是顺序（S0 → S7），中间不许缺号 —— 缺号会让面板的进度条错位。"""
        self.assertEqual(list(project.STAGE_ORDER),
                         ["S%d" % i for i in range(len(project.STAGE_ORDER))],
                         "阶段编号不连续：%r" % (project.STAGE_ORDER,))
        self.assertEqual(len(project.STAGE_BY_CODE), len(project.STAGE_SPECS))

    def test_landings_are_real_project_dirs(self):
        """落点只许写 `PROJECT_DIRS` 里的相对路径 —— 不另造一套写法。"""
        for s in project.STAGE_SPECS:
            for rel in tuple(s.landings) + tuple(s.check_dirs):
                self.assertIn(rel, project.PROJECT_DIRS,
                              "%s %s 的落点不在项目目录清单里：%s" % (s.code, s.name, rel))

    def test_image_exts_are_the_same_as_flow(self):
        """图片后缀这份知识存了两处（`project.py` 不能 import `flow_core`），钉住不许分家。"""
        self.assertEqual(project.IMAGE_EXTS, flow_core.PNG_EXTS,
                         "project.IMAGE_EXTS 与 flow_core.PNG_EXTS 分家了")


class StagesEntryTest(unittest.TestCase):
    """「每一阶段怎么跑」必须指向**真实存在**的入口。"""

    @classmethod
    def setUpClass(cls):
        import main as main_mod          # 真入口：argparse 表，不抄一份子命令清单
        parser = main_mod.build_parser()
        subs = [a for a in parser._actions
                if isinstance(a, argparse._SubParsersAction)]
        if not subs:
            raise AssertionError("main.py 的 parser 里没有子命令表 —— 结构变了？")
        cls.parser = parser
        cls.subcommands = set(subs[0].choices)

    def test_every_stage_has_at_least_one_entry(self):
        """每一段都要有入口 —— "没人管"的阶段是配置错误，不是可接受的留白。"""
        for s in project.STAGE_SPECS:
            self.assertTrue(s.entries, "%s %s 没有入口：这一段没人管" % (s.code, s.name))

    def test_entries_point_at_real_places(self):
        """flow 段名 / `main.py` 子命令 / agent —— 三样都得真存在。"""
        for s in project.STAGE_SPECS:
            for e in s.entries:
                if e.kind == "flow":
                    self.assertIn(e.key, flow_core.ORDER,
                                  "%s 的入口说 `--阶段 %s`，但流水线里没这一段"
                                  % (s.code, e.key))
                elif e.kind == "cli":
                    self.assertIn(e.key, self.subcommands,
                                  "%s 的入口说 `main.py %s`，但没有这个子命令"
                                  % (s.code, e.key))
                    if e.agent:
                        self.assertIn(e.agent, registry.AGENTS,
                                      "%s 的入口说 `run %s`，但注册表里没有这个 agent"
                                      % (s.code, e.agent))
                else:
                    self.fail("%s 的入口 kind 不认识：%r（只许 flow / cli）" % (s.code, e.kind))

    def test_map_doc_commands_point_at_real_places(self):
        """⭐ 文档里写的那条命令，代码里必须有对应入口。

        `pipeline.py` 的 docstring 曾写 `python main.py run expression` —— 注册表里
        根本没有 `expression`（只有 `asset`），而这句话在文档里躺了很久没人发现。
        这条测试就是防这个：**文档指向的入口必须真的存在**。
        """
        for code, name, _agent, cmd in project.spec_stage_map_from_doc():
            kind, key, agent = _parse_entry(cmd)
            spec = project.STAGE_BY_CODE[code]
            hits = [e for e in spec.entries
                    if e.kind == kind and e.key == key and (not agent or e.agent == agent)]
            self.assertTrue(
                hits,
                "%s %s 在映射表里写的是 `%s`，但 STAGE_SPECS 里没有这条入口"
                % (code, name, cmd))
            if kind == "flow":
                self.assertIn(key, flow_core.ORDER,
                              "%s：流水线里没有 `%s` 这一段" % (code, key))
            else:
                self.assertIn(key, self.subcommands,
                              "%s：没有 `main.py %s` 这个子命令" % (code, key))
                if agent:
                    self.assertIn(agent, registry.AGENTS,
                                  "%s：注册表里没有 agent `%s`" % (code, agent))

    def test_flow_stages_belong_to_known_stage_codes(self):
        """流水线每一段的 `code` 必须是 S0–S7 里的一段，且双向对得上。"""
        for st in flow_core.STAGES:
            self.assertIn(st.code, project.STAGE_BY_CODE,
                          "流水线段 %r 标了不存在的阶段 %r" % (st.key, st.code))
            spec = project.STAGE_BY_CODE[st.code]
            self.assertTrue(
                [e for e in spec.entries if e.kind == "flow" and e.key == st.key],
                "流水线段 %r 属于 %s，但 %s 的入口里没写它"
                % (st.key, st.code, st.code))

    def test_stage_outputs_cover_every_stage(self):
        """体检桶要覆盖全部阶段 —— 少一段，面板上就少一格，且不报错。"""
        labels = [lb.split(" ")[0] for lb, _rels, _exts in project.STAGE_OUTPUTS]
        self.assertEqual(labels, list(project.STAGE_ORDER),
                         "体检桶（STAGE_OUTPUTS）与阶段表（STAGE_SPECS）不同步")
        for lb, rels, exts in project.STAGE_OUTPUTS:
            self.assertTrue(rels, "%s 的体检没写落点" % lb)
            self.assertTrue(exts, "%s 的体检没写后缀（空 = 该目录下任意文件，易假阳性）" % lb)

    def test_cli_hint_for_a_stage_outside_the_pipeline(self):
        """⭐ 敲一个流水线不覆盖的阶段，报错里必须**给出它的入口**。

        原先这里是 `choices=ORDER`，只会给一句 `invalid choice` —— 用户手里拿的
        偏偏是一张写着「S3 表情 / 动作」的映射表。报得太少，等于没报。
        """
        cases = (
            (["flow", "-p", "x", "--阶段", "表情"], "main.py ask"),          # S3：不在流水线里
            (["flow", "-p", "x", "--阶段", "S7"], "main.py gate compliance"),  # 按编号敲
            (["flow", "-p", "x", "--阶段", "资产设计"], "--阶段 资产"),       # 名字与段名不同名
        )
        for argv, want in cases:
            # buf 要在 `with` 外面建：parse_args 抛 SystemExit 会跳出 assertRaises 块，
            # 块内异常之后的语句根本不会执行（取 getvalue 得放在块外）。
            buf = io.StringIO()
            with self.assertRaises(SystemExit) as cm:
                with contextlib.redirect_stderr(buf):
                    self.parser.parse_args(argv)
            self.assertEqual(cm.exception.code, 2, "用法错误应当 exit 2")
            err = buf.getvalue()
            self.assertIn(want, err,
                          "敲 `--阶段 %s` 时没告诉用户该敲什么，只说了：%s"
                          % (argv[-1], err))


if __name__ == "__main__":
    unittest.main(verbosity=2)
