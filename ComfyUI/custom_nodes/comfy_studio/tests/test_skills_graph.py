"""UI 图 → API 格式：字段对位、隐式值、动态下拉、缺值与错位处理。

口径全部对着真东西量过（见 ``skills/graph.py`` 顶部出处）：``/object_info`` 的字段顺序
是对位唯一依据，``/history`` 里引擎真收到的报文决定了三件具体写法 —— seed 后的
``control_after_generate`` 不进报文、被转成连线的 widget 仍占位、动态下拉用点号扁平键。
"""

from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ..skills.graph import GraphConvertError, graph_to_api

#: 手写的 ``/object_info`` 片段：形状照抄真接口（``{class_type: {input: {required: ...}}}``）。
#: 离线可跑，不受本机装没装节点影响。
OBJECT_INFO: dict = {
    "CLIPTextEncode": {
        "input": {"required": {"text": ["STRING", {"default": ""}], "clip": ["CLIP"]}},
        "output": ["CONDITIONING"],
    },
    "KSampler": {
        "input": {
            "required": {
                "model": ["MODEL"],
                "seed": ["INT", {"default": 0, "control_after_generate": True}],
                "steps": ["INT", {"default": 20}],
                "sampler_name": [["euler", "ddim"], {"default": "euler"}],
            },
            "optional": {"denoise": ["FLOAT", {"default": 1.0}]},
        },
        "output": ["LATENT"],
    },
    "CreateVideo": {
        "input": {
            "required": {"images": ["IMAGE"], "fps": ["FLOAT", {"default": 30.0}]},
            "optional": {
                "bit_depth": ["COMBO", {"default": "auto", "options": ["auto", 8, 10]}],
                "color_space": ["COMBO", {"default": "sRGB", "options": ["sRGB", "HDR"]}],
            },
        },
        "output": ["VIDEO"],
    },
    "SaveVideo": {
        "input": {
            "required": {
                "video": ["VIDEO"],
                "filename_prefix": ["STRING", {"default": "video/ComfyUI"}],
                "format": ["COMFY_DYNAMICCOMBO_V3", {"options": [
                    {"key": "auto", "inputs": {"required": {"codec": [["auto", "h264"], {"default": "auto"}]}}},
                    {"key": "webm", "inputs": {"required": {"codec": [["libvpx"], {"default": "libvpx"}]}}},
                ]}],
            },
            "optional": {"mute": ["BOOLEAN"]},
        },
        "output": ["STRING"],
    },
    "Note": {"input": {}, "output": []},
}


def _doc(nodes: list[dict], links: list | None = None) -> dict:
    """造一份最小 UI 图。"""
    return {"nodes": nodes, "links": links or []}


def _node(node_id: int, class_type: str, inputs: list | None = None,
          widgets: list | None = None, mode: int = 0) -> dict:
    node: dict = {"id": node_id, "type": class_type, "mode": mode}
    if inputs is not None:
        node["inputs"] = inputs
    if widgets is not None:
        node["widgets_values"] = widgets
    return node


def _widget(name: str, value: object = None, link: int | None = None) -> dict:
    """一个输入项；``link`` 给了就是连了线（新版前端会给它带 ``widget`` 键）。"""
    item: dict = {"name": name, "link": link}
    if link is not None:
        item["widget"] = {"name": name}
    return item


class GraphToApiTest(unittest.TestCase):
    def convert(self, doc: dict, info: dict | None = None):
        return graph_to_api(doc, info or OBJECT_INFO, source="test")

    # ---------------------------------------------------------------- 对位

    def test_widget_values_follow_definition_order(self) -> None:
        doc = _doc([
            _node(3, "KSampler", [_widget("model", link=1)], [7, 30, "ddim"]),
        ], [[1, 2, 0, 3, 0, "MODEL"]])
        inputs = self.convert(doc).graph["3"]["inputs"]
        self.assertEqual(inputs["model"], ["2", 0])
        self.assertEqual(inputs["seed"], 7)
        self.assertEqual(inputs["steps"], 30)
        self.assertEqual(inputs["sampler_name"], "ddim")

    def test_optional_widget_without_value_takes_definition_default(self) -> None:
        doc = _doc([_node(3, "KSampler", [], [5, 20, "euler"])])
        result = self.convert(doc)
        self.assertEqual(result.graph["3"]["inputs"]["denoise"], 1.0)
        self.assertEqual(len(result.notes), 1)
        self.assertIn("denoise", result.notes[0])

    def test_control_after_generate_value_is_consumed_and_dropped(self) -> None:
        doc = _doc([_node(3, "KSampler", [], [7, "fixed", 30, "euler"])])
        inputs = self.convert(doc).graph["3"]["inputs"]
        self.assertEqual(inputs["seed"], 7)
        self.assertEqual(inputs["steps"], 30)  # 不是 "fixed"：隐式那一位被吃掉了
        self.assertNotIn("fixed", json.dumps(inputs))

    def test_generate_mode_lookalike_value_is_not_eaten(self) -> None:
        """``steps`` 的值恰好是 "fixed" 时也不能被当成 control_after_generate。"""
        doc = _doc([_node(3, "KSampler", [], [7, 30, "fixed"])])
        inputs = self.convert(doc).graph["3"]["inputs"]
        self.assertEqual(inputs["steps"], 30)
        self.assertEqual(inputs["sampler_name"], "fixed")

    def test_widget_turned_into_input_keeps_its_slot(self) -> None:
        """被转成连线的 widget：报文里是连线引用，但值仍占 widgets_values 一位。"""
        doc = _doc([
            _node(6, "CreateVideo", [_widget("images", link=1), _widget("fps", link=2)], [48, 8]),
        ], [[1, 4, 0, 6, 0, "IMAGE"], [2, 5, 2, 6, 1, "FLOAT"]])
        inputs = self.convert(doc).graph["6"]["inputs"]
        self.assertEqual(inputs["fps"], ["5", 2])
        self.assertEqual(inputs["bit_depth"], 8)  # 没有错位成 fps 的值

    # ------------------------------------------------------------ 动态下拉

    def test_dynamic_combo_uses_flat_dotted_keys(self) -> None:
        doc = _doc([_node(7, "SaveVideo", [], ["out/clip", "auto", "h264"])])
        inputs = self.convert(doc).graph["7"]["inputs"]
        self.assertEqual(inputs["format"], "auto")
        self.assertEqual(inputs["format.codec"], "h264")
        self.assertNotIn("codec", inputs)

    def test_dynamic_combo_sub_value_missing_raises(self) -> None:
        doc = _doc([_node(7, "SaveVideo", [], ["out/clip", "auto"])])
        with self.assertRaises(GraphConvertError) as ctx:
            self.convert(doc)
        self.assertIn("format", str(ctx.exception))

    def test_dynamic_combo_unknown_key_raises(self) -> None:
        doc = _doc([_node(7, "SaveVideo", [], ["out/clip", "mov", "h264"])])
        with self.assertRaises(GraphConvertError) as ctx:
            self.convert(doc)
        self.assertIn("没有这个选项", str(ctx.exception))

    # ------------------------------------------------------------ 错位与缺件

    def test_leftover_widget_values_raise(self) -> None:
        doc = _doc([_node(3, "KSampler", [], [7, 30, "euler", 1.0, "多余"])])
        with self.assertRaises(GraphConvertError) as ctx:
            self.convert(doc)
        self.assertIn("只解释了", str(ctx.exception))
        self.assertIn("多余", str(ctx.exception))

    def test_missing_required_widget_raises(self) -> None:
        doc = _doc([_node(3, "KSampler", [], [7])])
        with self.assertRaises(GraphConvertError) as ctx:
            self.convert(doc)
        self.assertIn("steps", str(ctx.exception))

    def test_unknown_class_type_raises(self) -> None:
        doc = _doc([_node(9, "NoSuchNode", [], [1])])
        with self.assertRaises(GraphConvertError) as ctx:
            self.convert(doc)
        self.assertIn("NoSuchNode", str(ctx.exception))

    def test_dangling_link_raises(self) -> None:
        doc = _doc([_node(3, "KSampler", [_widget("model", link=99)], [7, 30, "euler"])])
        with self.assertRaises(GraphConvertError) as ctx:
            self.convert(doc)
        self.assertIn("#99", str(ctx.exception))

    # ------------------------------------------------------------ 节点取舍

    def test_muted_bypassed_and_outputless_nodes_are_skipped(self) -> None:
        doc = _doc([
            _node(1, "KSampler", [], [1, 20, "euler"], mode=4),
            _node(2, "KSampler", [], [2, 20, "euler"], mode=2),
            _node(3, "Note", [], ["备注"]),
            _node(4, "KSampler", [], [3, 20, "euler"]),
        ])
        graph = self.convert(doc).graph
        self.assertEqual(sorted(graph), ["4"])

    def test_all_nodes_skipped_raises(self) -> None:
        doc = _doc([_node(1, "KSampler", [], [1, 20, "euler"], mode=4)])
        with self.assertRaises(GraphConvertError) as ctx:
            self.convert(doc)
        self.assertIn("没有任何可执行节点", str(ctx.exception))

    def test_not_a_workflow_raises(self) -> None:
        with self.assertRaises(GraphConvertError):
            self.convert({"nodes": "nope"})


class RealWorkflowTest(unittest.TestCase):
    """对着仓里那批真工作流跑一遍（要引擎在跑才能拿到 object_info，拿不到就明确跳过）。"""

    WORKFLOWS = Path(__file__).resolve().parents[3] / "user" / "default" / "workflows" / "AIGC中国风漫剧"
    BASE = "http://127.0.0.1:8188"

    def setUp(self) -> None:
        if not self.WORKFLOWS.is_dir():
            self.skipTest(f"跳过：没找到工作流目录 {self.WORKFLOWS}（不是从 ComfyUI 工作树里跑的？）")
        try:
            with urllib.request.urlopen(f"{self.BASE}/object_info", timeout=10) as resp:
                self.object_info = json.load(resp)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.skipTest(f"跳过：{self.BASE} 上没探到在跑的引擎（{exc}），节点定义拿不到")

    def test_every_shipped_workflow_converts(self) -> None:
        files = sorted(self.WORKFLOWS.glob("*.json"))
        self.assertTrue(files, f"{self.WORKFLOWS} 里一份工作流都没有")
        for path in files:
            with self.subTest(workflow=path.name):
                doc = json.loads(path.read_text(encoding="utf-8"))
                result = graph_to_api(doc, self.object_info, source=path.name)
                self.assertTrue(result.graph, f"{path.name} 转换后没有可执行节点")
                for note in result.notes:
                    self.assertIn(path.name, note, "提示里必须带工作流名，好定位")


if __name__ == "__main__":
    unittest.main()
