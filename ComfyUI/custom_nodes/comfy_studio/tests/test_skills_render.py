"""渲染入口（``skills/render.py``）：目标表、注入点、外部组接线。

分两截：不需要引擎的（目标表自检、放输入文件）与需要引擎的（真转换 + 逐条核对注入点）。
后者是这里最要紧的一条 —— 参数表里写的 ``node``/``field`` 必须**真在图里存在**，
否则运行期才发现就晚了；拿不到 ``/object_info`` 就明确跳过并说明原因。

参考图那条特别记录一下：一度以为能直接往导演节点接 ``reference_image_N``，实测真
``/object_info`` 里导演节点根本没有这些键 —— 正解是外部组
（``MiniMaxH3DirectorGroupImageToVideo`` / ``...ReferenceToVideo`` → ``GroupsCombine`` →
导演台 ``i2v_groups`` / ``r2v_groups``），形状取自节点自带的可跑示例图。
"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..skills.render import (
    COMBINE_AUTOGROW,
    COMBINE_CLASS,
    COMBINE_SLOT,
    DIRECTOR_PORT,
    GROUP_CLASS,
    GROUP_NODE_ID,
    MAX_REFERENCE_IMAGES,
    RENDER_TARGETS,
    RenderError,
    RenderTarget,
    _check_injection_points,
    _group_slots,
    _input_keys,
    build_render_skill,
    find_target,
    stage_input_file,
    target_path,
    workflows_dir,
)
from ..skills.types import SkillParam

#: 引擎要真在跑才拿得到节点定义（与 test_skills_graph.py 同一套口径）。
BASE = "http://127.0.0.1:8188"


class InjectionPointTest(unittest.TestCase):
    """注入点校验本身，**不需要引擎**：喂一张假定义表就够。

    对真图逐条核的那条在下面需要引擎的类里；这里管的是"判据与报错" ——
    表指向节点定义里没有的键时，必须当场报错，而不是注进去被引擎静默丢掉
    （``execution.validate_inputs`` 只按节点定义遍历，报文里多出来的键既不校验也不执行）。
    """

    #: ``CLIPTextEncode`` 只认 ``text`` 一个键。
    OBJECT_INFO: dict[str, Any] = {"CLIPTextEncode": {"input": {"required": {"text": ["STRING", {}]}}}}
    WORKFLOW: dict[str, Any] = {"5": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}}

    def _target(self, *params: SkillParam) -> RenderTarget:
        return replace(find_target("scene-card"), params=params)

    def test_a_matching_param_passes(self) -> None:
        target = self._target(SkillParam(name="prompt", type="string", node="5", field="text"))
        _check_injection_points(target, self.WORKFLOW, self.OBJECT_INFO, target.params)

    def test_a_field_the_node_does_not_have_is_refused(self) -> None:
        target = self._target(SkillParam(name="prompt", type="string", node="5", field="positiv"))
        with self.assertRaises(RenderError) as caught:
            _check_injection_points(target, self.WORKFLOW, self.OBJECT_INFO, target.params)
        message = str(caught.exception)
        self.assertIn("positiv", message)
        self.assertIn("text", message, "要说清这个节点真有哪些键，好直接去改表或改图")

    def test_a_node_that_is_not_in_the_graph_is_refused(self) -> None:
        target = self._target(SkillParam(name="prompt", type="string", node="99", field="text"))
        with self.assertRaises(RenderError) as caught:
            _check_injection_points(target, self.WORKFLOW, self.OBJECT_INFO, target.params)
        self.assertIn("#99", str(caught.exception))


class TargetTableTest(unittest.TestCase):
    def test_ids_are_unique(self) -> None:
        ids = [target.id for target in RENDER_TARGETS]
        self.assertEqual(len(ids), len(set(ids)), f"渲染目标 id 撞车：{ids}")

    def test_every_target_has_a_real_file(self) -> None:
        if not workflows_dir().is_dir():
            self.skipTest(f"跳过：没找到工作流目录 {workflows_dir()}（可用 COMFY_STUDIO_WORKFLOWS_DIR 指定）")
        for target in RENDER_TARGETS:
            with self.subTest(target=target.id):
                self.assertTrue(target_path(target).is_file(), f"{target.id} 的 {target.file} 不在")

    def test_only_the_video_targets_take_reference_images(self) -> None:
        """首尾帧/参考素材只有 04/05/06：图类与后处理类都不收。"""
        kinds = {target.id: target.group_kind for target in RENDER_TARGETS if target.group_kind}
        self.assertEqual(kinds, {"video-draft": "i2v", "video-final": "i2v", "video-multishot": "r2v"})

    def test_find_target_lists_alternatives(self) -> None:
        with self.assertRaises(RenderError) as ctx:
            find_target("不存在的目标")
        self.assertIn("character-sheet", str(ctx.exception))

    def test_storyboard_params_do_not_call_the_layout_constraint_negative(self) -> None:
        """01 的 #6 是布局约束，02/03 才是负向 —— 名字不能一刀切。"""
        names = {param.name for param in find_target("character-sheet").params}
        self.assertIn("layout", names)
        self.assertNotIn("negative", names)
        self.assertIn("negative", {param.name for param in find_target("scene-card").params})


class StageInputFileTest(unittest.TestCase):
    def test_copies_under_the_render_subdir_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "首帧.png"
            source.write_bytes(b"image-bytes")
            input_dir = root / "input"

            name = stage_input_file(source, input_dir=input_dir)
            self.assertEqual(name, "comfy_studio/render/首帧.png")
            staged = input_dir / "comfy_studio" / "render" / "首帧.png"
            self.assertEqual(staged.read_bytes(), b"image-bytes")

            self.assertEqual(stage_input_file(source, input_dir=input_dir), name)
            self.assertEqual(staged.read_bytes(), b"image-bytes")

    def test_missing_source_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RenderError):
                stage_input_file(Path(tmp) / "没有这个.png", input_dir=Path(tmp) / "input")


class RealRenderTest(unittest.TestCase):
    """对着真工作流 + 真节点定义跑（要引擎在跑，拿不到就明确跳过）。"""

    def setUp(self) -> None:
        if not workflows_dir().is_dir():
            self.skipTest(f"跳过：没找到工作流目录 {workflows_dir()}")
        try:
            with urllib.request.urlopen(f"{BASE}/object_info", timeout=15) as resp:
                self.object_info = json.load(resp)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.skipTest(f"跳过：{BASE} 上没探到在跑的引擎（{exc}），节点定义拿不到")

    def test_every_param_points_at_a_real_field(self) -> None:
        """参数表的 ``node``/``field`` 逐个对真图核：对不上说明表在撒谎。"""
        for target in RENDER_TARGETS:
            with self.subTest(target=target.id):
                plan = build_render_skill(target, self.object_info)
                workflow = plan.skill.workflow
                self.assertTrue(workflow, f"{target.id} 转换后没有可执行节点")
                for param in target.params:
                    self.assertIn(param.node, workflow, f"{target.id} 的参数 {param.name} 指向不存在的节点 {param.node}")
                    inputs = workflow[param.node]["inputs"]
                    self.assertIn(
                        param.field,
                        inputs,
                        f"{target.id} 的参数 {param.name} 指向 {param.node}.{param.field}，"
                        f"该节点真有的键是 {sorted(inputs)}",
                    )

    def test_group_slots_come_from_the_node_definitions(self) -> None:
        self.assertEqual(_group_slots("i2v", self.object_info), ("first_frame", "last_frame"))
        slots = _group_slots("r2v", self.object_info)
        self.assertEqual(len(slots), MAX_REFERENCE_IMAGES)
        self.assertTrue(all(slot.startswith("ref_images.ref_image_") for slot in slots), slots)

    def test_fl2v_images_become_an_external_group(self) -> None:
        plan = build_render_skill(
            find_target("video-draft"),
            self.object_info,
            image_names=("comfy_studio/render/首帧.png", "comfy_studio/render/尾帧.png"),
            duration_sec=5.0,
        )
        workflow = plan.skill.workflow
        group = workflow[GROUP_NODE_ID]
        self.assertEqual(group["class_type"], GROUP_CLASS["i2v"])
        # 首帧进 first_frame、尾帧进 last_frame，都走 LoadImage 的真连线
        for index, (slot, name) in enumerate(
            zip(("first_frame", "last_frame"), ("comfy_studio/render/首帧.png", "comfy_studio/render/尾帧.png"))
        ):
            node_id = f"cs-ref-{index}"
            self.assertEqual(workflow[node_id]["class_type"], "LoadImage")
            self.assertEqual(workflow[node_id]["inputs"]["image"], name)
            self.assertEqual(group["inputs"][slot], [node_id, 0])
        self.assertEqual(group["inputs"]["duration_sec"], 5.0)
        # 组 → Combine → 导演台的口（不是直接接导演节点）
        self.assertEqual(workflow["cs-combine"]["inputs"][COMBINE_SLOT], [GROUP_NODE_ID, 0])
        self.assertEqual(workflow["5"]["inputs"][DIRECTOR_PORT["i2v"]], ["cs-combine", 0])

    def test_prompt_moves_onto_the_group_when_images_are_wired(self) -> None:
        """外部组这条路提示词要落在组上：作者示例图里导演台的 global_prompt 就是空的。"""
        target = find_target("video-draft")
        plain = build_render_skill(target, self.object_info)
        prompt_param = next(param for param in plain.skill.params if param.name == "prompt")
        self.assertEqual((prompt_param.node, prompt_param.field), ("5", "global_prompt"))
        self.assertNotIn(DIRECTOR_PORT["i2v"], plain.skill.workflow["5"]["inputs"], "没给图时不该冒出外部组口")

        grouped = build_render_skill(target, self.object_info, image_names=("a.png",), duration_sec=4.0)
        moved = next(param for param in grouped.skill.params if param.name == "prompt")
        self.assertEqual((moved.node, moved.field), (GROUP_NODE_ID, "prompt"))
        self.assertEqual(grouped.skill.workflow[GROUP_NODE_ID]["inputs"]["prompt"], "")

    def test_duration_is_folded_from_the_graph_and_recorded(self) -> None:
        plan = build_render_skill(find_target("video-draft"), self.object_info, image_names=("a.png",))
        group = plan.skill.workflow[GROUP_NODE_ID]
        metadata = plan.skill.workflow["5"]["inputs"]
        expected = round(float(metadata["total_frames"]) / float(metadata["frame_rate"]), 2)
        self.assertEqual(group["inputs"]["duration_sec"], expected)
        self.assertTrue(any("duration_sec" in note for note in plan.notes), plan.notes)

    def test_r2v_images_fill_the_reference_slots(self) -> None:
        names = tuple(f"ref-{index}.png" for index in range(MAX_REFERENCE_IMAGES))
        plan = build_render_skill(find_target("video-multishot"), self.object_info, image_names=names, duration_sec=6.0)
        group = plan.skill.workflow[GROUP_NODE_ID]
        self.assertEqual(group["class_type"], GROUP_CLASS["r2v"])
        for index in range(MAX_REFERENCE_IMAGES):
            self.assertEqual(group["inputs"][f"ref_images.ref_image_{index}"], [f"cs-ref-{index}", 0])
        self.assertEqual(plan.skill.workflow["5"]["inputs"][DIRECTOR_PORT["r2v"]], ["cs-combine", 0])

    def test_too_many_images_raises(self) -> None:
        with self.assertRaises(RenderError) as ctx:
            build_render_skill(
                find_target("video-draft"),
                self.object_info,
                image_names=("a.png", "b.png", "c.png"),
                duration_sec=5.0,
            )
        self.assertIn("最多收 2 张图", str(ctx.exception))

        over = tuple(f"f{index}.png" for index in range(MAX_REFERENCE_IMAGES + 1))
        with self.assertRaises(RenderError):
            build_render_skill(find_target("video-multishot"), self.object_info, image_names=over, duration_sec=6.0)

    def test_image_targets_refuse_reference_images(self) -> None:
        with self.assertRaises(RenderError) as ctx:
            build_render_skill(find_target("storyboard-frame"), self.object_info, image_names=("a.png",))
        self.assertIn("不接受参考图", str(ctx.exception))

    def test_everything_the_group_path_needs_is_in_the_node_definitions(self) -> None:
        """接线用的类名/口名必须真存在 —— 版本变了要在这里炸，而不是运行期。"""
        for kind, class_type in GROUP_CLASS.items():
            with self.subTest(kind=kind):
                self.assertIn(class_type, self.object_info)
        combine_keys = _input_keys(self.object_info, COMBINE_CLASS)
        # 真定义里只有 Autogrow 口 groups；groups.group_0 是提交期展开的实例名，定义里当然没有
        self.assertIn(COMBINE_AUTOGROW, combine_keys, sorted(combine_keys))
        self.assertNotIn(COMBINE_SLOT, combine_keys)
        director = self.object_info["MiniMaxH3Director"]
        for port in DIRECTOR_PORT.values():
            self.assertIn(port, (director.get("input") or {}).get("optional") or {}, f"导演节点没有 {port} 口")
        # 这条是试错留下的证据：导演节点定义里没有 reference_image_N，直连那条路是错的
        for section in ("required", "optional"):
            keys = (director.get("input") or {}).get(section) or {}
            self.assertFalse(
                [key for key in keys if key.startswith("reference_image_")], "导演节点竟然有 reference_image_N？"
            )


if __name__ == "__main__":
    unittest.main()
