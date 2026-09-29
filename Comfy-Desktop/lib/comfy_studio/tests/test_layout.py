"""layout：四类路径怎么算出来 —— 全库路径的**唯一真源**。

这一组不碰引擎、不碰网络、不建真项目，问的只有一件事：**给一组开关，算出来是哪几个目录**。
所以它跑得飞快，也正因为快，将来"某个开关不生效"这种改动会被它当场抓住。

环境变量在这一组里必须清干净（``clear=True``）：跑测试的这台机器上设过什么，
就会改掉结论 —— 而本机设过什么，正是这套解析最先要对付的东西。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfy_studio import projects_spec as spec
from comfy_studio.layout import (
    INPUT_DIR_ENV,
    INPUT_SUBDIR,
    NOVEL_DIR_ENV,
    NOVEL_SUBDIR,
    OUTPUT_DIR_ENV,
    OUTPUT_SUBDIR,
    PROJECT_DIR_ENV,
    PROJECT_OUT_DIR_ENV,
    TEMP_SUBDIR,
    LayoutError,
    default_novel_dir,
    default_project_dir,
    default_project_out_dir,
    default_temp_dir,
    layout_of,
    resolve_layout,
)


class ResolveLayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-layout-")
        self.root = Path(self._tmp.name).resolve()
        self.comfy = self.root / "ComfyUI"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _resolve(self, **kwargs):
        with mock.patch.dict(os.environ, {}, clear=True):
            return resolve_layout(**kwargs)

    # ---- 三个引擎根 -----------------------------------------------------

    def test_engine_roots_default_under_comfyui_dir(self) -> None:
        layout = self._resolve(comfyui_dir=str(self.comfy))
        self.assertEqual(layout.input_root, self.comfy / INPUT_SUBDIR)
        self.assertEqual(layout.output_root, self.comfy / OUTPUT_SUBDIR)
        self.assertEqual(layout.temp_root, self.comfy / TEMP_SUBDIR)

    def test_explicit_beats_environment(self) -> None:
        """同一把梯子的头两级：显式参数 > 环境变量。

        反过来就会"命令行指了 A、跑起来落在 B"，而且两边都不报错。
        """
        given = self.root / "given"
        with mock.patch.dict(
            os.environ, {INPUT_DIR_ENV: str(self.root / "from-env")}, clear=True
        ):
            layout = resolve_layout(comfyui_dir=str(self.comfy), input_dir=str(given))
        self.assertEqual(layout.input_root, given)

    def test_environment_beats_derived(self) -> None:
        """第二级 vs 第三级：设过环境变量就别再拿 comfyui-dir 去推。

        这条正是共享存储那个场景：引擎的 `--output-directory` 被搬到了别处，
        宿主看不见，只能靠人显式告诉它。
        """
        shared = self.root / "shared-output"
        with mock.patch.dict(os.environ, {OUTPUT_DIR_ENV: str(shared)}, clear=True):
            layout = resolve_layout(comfyui_dir=str(self.comfy))
        self.assertEqual(layout.output_root, shared)

    def test_nothing_given_is_an_error_not_a_guess(self) -> None:
        """一个根都推不出来就报错，**不拿** ``<cwd>/input`` 顶上。

        顶上那种做法不报错：每次跑都落错地方，而人只会觉得"这功能时灵时不灵"。
        """
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LayoutError):
                resolve_layout()
        # 宿主那一侧要的是"没挂上"而不是异常：没给 --comfyui-dir 是合法状态。
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(layout_of(None))
        self.assertIsNotNone(layout_of(str(self.comfy)))

    # ---- 三个业务落点 ---------------------------------------------------

    def test_business_landings_default_to_the_engine_roots(self) -> None:
        """三个业务落点的默认值 = 两个引擎根下的一级 —— 与引擎的读取范围对齐。"""
        layout = self._resolve(comfyui_dir=str(self.comfy))
        self.assertEqual(layout.novel_dir(), self.comfy / INPUT_SUBDIR / NOVEL_SUBDIR)
        self.assertEqual(layout.projects_root(), self.comfy / INPUT_SUBDIR)
        self.assertEqual(layout.projects_out_root(), self.comfy / OUTPUT_SUBDIR)
        self.assertFalse(layout.describe()["single_root"])
        self.assertEqual(layout.describe()["overridden"], [])

    def test_business_landings_read_their_own_environment_variables(self) -> None:
        """这三个开关的环境变量那一级也得真的生效，别只是声明在那儿。"""
        data = self.root / "data"
        films = self.root / "films"
        novels = self.root / "novels"
        with mock.patch.dict(
            os.environ,
            {
                PROJECT_DIR_ENV: str(data),
                PROJECT_OUT_DIR_ENV: str(films),
                NOVEL_DIR_ENV: str(novels),
            },
            clear=True,
        ):
            layout = resolve_layout(comfyui_dir=str(self.comfy))
        self.assertEqual(layout.projects_root(), data)
        self.assertEqual(layout.projects_out_root(), films)
        self.assertEqual(layout.novel_dir(), novels)

    def test_overridden_landings_are_reported(self) -> None:
        """手工指的落点要**报出来**。

        指过的落点可以离引擎的 ``input/`` 很远，那种情况下引擎按名读不到它 ——
        而界面上一切正常，所以"指过没有"本身就得看得见。
        """
        data = self.root / "data"
        layout = self._resolve(
            comfyui_dir=str(self.comfy),
            project_dir=str(data),
            project_out_dir=str(data),
        )
        self.assertEqual(layout.projects_root(), data)
        self.assertTrue(layout.describe()["single_root"])
        self.assertEqual(
            layout.describe()["overridden"], ["projects_root", "projects_out_root"]
        )

    # ---- 落点落在哪个根 -------------------------------------------------

    def test_landing_dir_follows_dir_roots(self) -> None:
        """一个落点在盘上的位置**只**由事实源的 ``DIR_ROOTS`` 说了算。

        这里没有第二份判断 —— 抄一份的失效模式是两边各说各的，谁也不报错。
        """
        layout = self._resolve(comfyui_dir=str(self.comfy))
        self.assertEqual(
            layout.landing_dir("剧甲", "08_STORYBOARDS").parent, layout.project_in("剧甲")
        )
        self.assertEqual(
            layout.landing_dir("剧甲", "09_SHOTS").parent, layout.project_out("剧甲")
        )
        # 与事实源对一遍：那张表将来加一格，这里就不许自己漂。
        self.assertEqual(spec.root_of("08_STORYBOARDS"), spec.ROOT_INPUT)
        self.assertEqual(spec.root_of("09_SHOTS"), spec.ROOT_OUTPUT)
        self.assertEqual(spec.root_of("12_FILMS"), spec.ROOT_OUTPUT)

    # ---- 暂存区 ---------------------------------------------------------

    def test_stage_dir_separates_projects_and_tasks(self) -> None:
        """暂存区按 命名空间 / 剧 / 任务 三层分，不是讲究。

        原先所有项目、所有任务的参考图都往**一个扁平目录**里塞、按原文件名落地：
        A 项目的 `参考图.png` 会被 B 项目的同名图**直接覆盖**，而 A 的工作流如果正在排队，
        它会静默地读到 B 的图 —— 出片结果对不上，却不报任何错。
        """
        layout = self._resolve(comfyui_dir=str(self.comfy))
        same = layout.stage_dir("剧甲", "出图")
        self.assertNotEqual(same, layout.stage_dir("剧乙", "出图"))
        self.assertNotEqual(same, layout.stage_dir("剧甲", "合成"))
        self.assertEqual(same.name, "出图")
        self.assertEqual(same.parent.name, "剧甲")
        # 落在引擎 input/ 下：工作流要的是"相对 input 的名字"，出界的它读不到。
        self.assertTrue(str(same).startswith(str(layout.input_root)))

    def test_stage_dir_refuses_to_escape(self) -> None:
        """剧名 / 任务名是要拼进真实路径的，所以不许带分隔符、不许 ``..``、不许留空。

        剧名那一侧**空也要拒**：``stage_dir("")`` 会拼出暂存区的**公共父目录**，
        那是所有项目混在一起的那一层 —— 谁往那儿写，谁就在跟别人抢文件名。
        """
        layout = self._resolve(comfyui_dir=str(self.comfy))
        for bad in ("..", "../逃", "a/b", "a\\b", ""):
            with self.assertRaises(LayoutError, msg=bad):
                layout.stage_dir(bad, "出图")
        # 任务名空是**另一种意思**（"项目级那一层"），见下一个用例 —— 所以这里从 ".." 起。
        for bad in ("..", "../逃", "a/b", "a\\b"):
            with self.assertRaises(LayoutError, msg=bad):
                layout.stage_dir("剧甲", bad)

    def test_stage_dir_without_a_task_is_the_project_level_dir(self) -> None:
        """不给任务名 = 整个项目共用的那一层，不是错误。"""
        layout = self._resolve(comfyui_dir=str(self.comfy))
        self.assertEqual(layout.stage_dir("剧甲"), layout.stage_dir("剧甲", "出图").parent)

    # ---- 命名空间 -------------------------------------------------------

    def test_namespace_lands_between_root_and_project(self) -> None:
        layout = self._resolve(comfyui_dir=str(self.comfy), namespace="teamA")
        self.assertEqual(layout.projects_root(), self.comfy / INPUT_SUBDIR / "teamA")
        self.assertEqual(
            layout.novel_dir(), self.comfy / INPUT_SUBDIR / "teamA" / NOVEL_SUBDIR
        )
        # 临时区不属于任何项目，也就不该跟着命名空间走。
        self.assertEqual(layout.temp_root, self.comfy / TEMP_SUBDIR)

    def test_namespace_cannot_escape(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LayoutError):
                resolve_layout(comfyui_dir=str(self.comfy), namespace="../逃")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LayoutError):
                resolve_layout(comfyui_dir=str(self.comfy), namespace="C:/逃")


class DefaultDirTest(unittest.TestCase):
    """给老接口用的那几个默认值 —— 它们和 :func:`resolve_layout` 必须说的是同一件事。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-defaults-")
        self.comfy = Path(self._tmp.name).resolve() / "ComfyUI"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_defaults_pair_up_with_the_resolved_layout(self) -> None:
        """默认落点与 ``resolve_layout`` 算出来的**逐字相同**。

        两处各算一份是完全可以的，只要结论一致；不一致时人会去改其中一个，
        而真正生效的是另一个。
        """
        layout = layout_of(str(self.comfy))
        assert layout is not None
        self.assertEqual(default_project_dir(self.comfy), layout.projects_root())
        self.assertEqual(default_project_out_dir(self.comfy), layout.projects_out_root())
        self.assertEqual(default_novel_dir(self.comfy), layout.novel_dir())
        self.assertEqual(default_temp_dir(self.comfy), layout.temp_root)

    def test_the_two_roots_are_not_the_same_directory(self) -> None:
        """资料根与产物根**默认分开**，而且落在引擎真正读写的两个目录里。

        成片落在 ``input/`` 下的话，引擎那条 `名[output]` 注解读不到它，
        下游合成只能整份拷过去（成片动辄几百兆）。
        """
        self.assertEqual(default_project_dir(self.comfy), self.comfy / INPUT_SUBDIR)
        self.assertEqual(default_project_out_dir(self.comfy), self.comfy / OUTPUT_SUBDIR)
        self.assertNotEqual(
            default_project_dir(self.comfy), default_project_out_dir(self.comfy)
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
