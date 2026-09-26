"""skills 层：模板加载/校验、参数合并与类型检查、参数注入、输出收集。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ..skills import WORKFLOWS_DIR, build_prompt, collect_images, load_skills, merge_params
from ..skills.loader import load_skill_file, validate_skill
from ..skills.params import SEED_RANDOM
from ..skills.types import SkillOutputImage, SkillParam
from .support import make_skill

#: 一份合法的最小 skill 文档，各用例在它上面改坏一处。
GOOD: dict = {
    "id": "demo",
    "title": "示例",
    "description": "示例 skill",
    "tags": ["test"],
    "workflow": {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ""}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 20}},
    },
    "params": [
        {"name": "ckpt_name", "type": "string", "required": True, "node": "4", "field": "ckpt_name"},
        {"name": "steps", "type": "integer", "default": 20, "node": "3", "field": "steps"},
    ],
}


def _broken(**changes: object) -> dict:
    """在 GOOD 的基础上改坏（顶层键直接替换）。"""
    doc = json.loads(json.dumps(GOOD))
    doc.update(changes)
    return doc


class ValidateSkillTest(unittest.TestCase):
    def test_accepts_a_minimal_document(self) -> None:
        skill = validate_skill(GOOD, "mem")
        self.assertEqual(skill.id, "demo")
        self.assertEqual([p.name for p in skill.params], ["ckpt_name", "steps"])
        self.assertEqual(skill.tags, ("test",))
        self.assertTrue(skill.param("ckpt_name").required)
        self.assertFalse(skill.param("ckpt_name").has_default)
        self.assertEqual(skill.param("steps").default, 20)

    def test_explicit_null_default_is_not_missing_default(self) -> None:
        doc = _broken(
            params=[{"name": "p", "type": "string", "node": "4", "field": "ckpt_name", "default": None}]
        )
        param = validate_skill(doc, "mem").params[0]
        self.assertTrue(param.has_default)
        self.assertIsNone(param.default)

    def test_hint_falls_back_to_injection_target(self) -> None:
        doc = _broken(params=[{"name": "p", "type": "string", "node": "4", "field": "ckpt_name"}])
        param = validate_skill(doc, "mem").params[0]
        self.assertIn("4", param.hint())
        self.assertIn("ckpt_name", param.hint())

    def test_rejects_broken_documents(self) -> None:
        cases: list[tuple[str, object, str]] = [
            ("顶层不是对象", [], "必须是 JSON 对象"),
            ("id 为空", _broken(id=""), "id 必须是非空字符串"),
            ("title 缺失", {k: v for k, v in GOOD.items() if k != "title"}, "title 必须是非空字符串"),
            ("description 不是字符串", _broken(description=3), "description 必须是非空字符串"),
            ("workflow 不是对象", _broken(workflow=[]), "workflow 必须是节点映射"),
            ("workflow 为空", _broken(workflow={}), "workflow 不能为空"),
            (
                "节点不是对象",
                _broken(workflow={"4": "CheckpointLoaderSimple"}),
                "workflow 节点 4 必须是对象",
            ),
            ("节点缺 class_type", _broken(workflow={"4": {"inputs": {}}}), "缺少 class_type"),
            ("节点缺 inputs", _broken(workflow={"4": {"class_type": "X"}}), "缺少 inputs"),
            ("params 不是数组", _broken(params={}), "params 必须是数组"),
            ("params 项不是对象", _broken(params=["x"]), "每一项都必须是对象"),
            ("参数缺 name", _broken(params=[{"type": "string"}]), "必须有非空 name"),
            ("参数 type 非法", _broken(params=[{"name": "p", "type": "image"}]), "type 必须是"),
            ("参数引用不存在的节点", _broken(params=[{"name": "p", "type": "string", "node": "99"}]), "不在 workflow 里"),
            (
                "参数引用不存在的字段",
                _broken(params=[{"name": "p", "type": "string", "node": "4", "field": "nope"}]),
                "不是节点 4 的输入",
            ),
            ("tags 不是字符串数组", _broken(tags="image"), "tags 必须是字符串数组"),
            ("tags 里有非字符串", _broken(tags=[1]), "tags 必须是字符串数组"),
        ]
        for label, doc, fragment in cases:
            with self.subTest(label):
                with self.assertRaises(ValueError) as ctx:
                    validate_skill(doc, "mem")
                self.assertIn(fragment, str(ctx.exception))

    def test_rejects_duplicate_param_names(self) -> None:
        doc = _broken(
            params=[
                {"name": "p", "type": "string", "node": "4", "field": "ckpt_name"},
                {"name": "p", "type": "string", "node": "4", "field": "ckpt_name"},
            ]
        )
        with self.assertRaises(ValueError) as ctx:
            validate_skill(doc, "mem")
        self.assertIn("重复定义", str(ctx.exception))


class LoadSkillsTest(unittest.TestCase):
    def test_packaged_workflow_directory_is_valid(self) -> None:
        skills = load_skills(WORKFLOWS_DIR)
        ids = [s.id for s in skills]
        self.assertEqual(ids, ["text-to-image"], "随包自带的 skill 目录内容变了")
        skill = skills[0]
        self.assertTrue(skill.title and skill.description)
        self.assertEqual(
            [p.name for p in skill.params],
            ["ckpt_name", "positive", "negative", "width", "height", "steps", "cfg", "seed"],
        )
        self.assertEqual(skill.param("seed").default, SEED_RANDOM)
        self.assertEqual(skill.param("cfg").type, "number")
        self.assertTrue(skill.param("positive").required)
        self.assertFalse(skill.param("negative").required)

    def test_loads_files_in_name_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in ("b.json", "a.json"):
                doc = _broken(id=name[:-5])
                (directory / name).write_text(json.dumps(doc), encoding="utf-8")
            self.assertEqual([s.id for s in load_skills(directory)], ["a", "b"])

    def test_reports_bad_inputs_instead_of_skipping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "broken.json").write_text("{ not json", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_skills(directory)
            self.assertIn("不是合法 JSON", str(ctx.exception))

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                load_skills(tmp)
            self.assertIn("没有任何 .json 文件", str(ctx.exception))

        with self.assertRaises(NotADirectoryError):
            load_skills(Path(tempfile.gettempdir()) / "comfy-studio-不存在的目录")

    def test_load_skill_file_points_at_the_offending_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"id": "x"}), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_skill_file(path)
            self.assertIn("bad.json", str(ctx.exception))


class MergeParamsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = validate_skill(GOOD, "mem")

    def test_fills_defaults_and_keeps_only_declared_names(self) -> None:
        merged = merge_params(self.skill, {"ckpt_name": "a.safetensors"})
        self.assertEqual(merged, {"ckpt_name": "a.safetensors", "steps": 20})

    def test_rejects_unknown_param_with_the_available_list(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            merge_params(self.skill, {"ckpt": "a.safetensors"})
        message = str(ctx.exception)
        self.assertIn("不认识这些参数: ckpt", message)
        self.assertIn("ckpt_name", message)

    def test_reports_all_missing_required_params_at_once(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            merge_params(self.skill, {})
        self.assertIn("缺少必填参数: ckpt_name", str(ctx.exception))

    def test_type_checks(self) -> None:
        given = {"ckpt_name": "a.safetensors", "steps": 7}
        self.assertIs(merge_params(self.skill, given)["steps"], 7)
        # bool 是 int 的子类，不能被当成 integer/number 混进来
        for bad in (True, "20", 20.5, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as ctx:
                    merge_params(self.skill, {**given, "steps": bad})
                self.assertIn("需要 integer", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            merge_params(self.skill, {"ckpt_name": 1})
        self.assertIn("需要 string", str(ctx.exception))

    def test_number_accepts_int_and_returns_float(self) -> None:
        skill = validate_skill(
            _broken(params=[{"name": "cfg", "type": "number", "default": 7, "node": "3", "field": "seed"}]),
            "mem",
        )
        self.assertEqual(merge_params(skill, {})["cfg"], 7.0)
        self.assertEqual(merge_params(skill, {"cfg": 8})["cfg"], 8.0)
        with self.assertRaises(ValueError):
            merge_params(skill, {"cfg": False})

    def test_boolean_only_accepts_bool(self) -> None:
        skill = validate_skill(
            _broken(params=[{"name": "flag", "type": "boolean", "default": True, "node": "3", "field": "seed"}]),
            "mem",
        )
        self.assertIs(merge_params(skill, {})["flag"], True)
        self.assertIs(merge_params(skill, {"flag": False})["flag"], False)
        with self.assertRaises(ValueError):
            merge_params(skill, {"flag": 1})

    def test_optional_param_without_default_is_omitted(self) -> None:
        skill = validate_skill(
            _broken(params=[{"name": "opt", "type": "string", "node": "4", "field": "ckpt_name"}]),
            "mem",
        )
        self.assertEqual(merge_params(skill, {}), {})


class BuildPromptTest(unittest.TestCase):
    def test_injects_into_the_declared_node_field(self) -> None:
        skill = validate_skill(GOOD, "mem")
        prompt = build_prompt(skill, {"ckpt_name": "a.safetensors", "steps": 8})
        self.assertEqual(prompt["4"]["inputs"]["ckpt_name"], "a.safetensors")
        self.assertEqual(prompt["3"]["inputs"]["steps"], 8)

    def test_does_not_touch_the_skill_template(self) -> None:
        skill = validate_skill(GOOD, "mem")
        build_prompt(skill, {"ckpt_name": "a.safetensors", "steps": 8})
        self.assertEqual(skill.workflow["4"]["inputs"]["ckpt_name"], "")
        self.assertEqual(skill.workflow["3"]["inputs"]["steps"], 20)

    def test_seed_random_is_replaced_but_explicit_seed_survives(self) -> None:
        skill = make_skill(
            params=(SkillParam(name="seed", type="integer", node="3", field="seed", default=SEED_RANDOM),)
        )
        seen = {build_prompt(skill, {})["3"]["inputs"]["seed"] for _ in range(20)}
        self.assertTrue(all(0 <= value < 0x1_0000_0000_0000 for value in seen), seen)
        self.assertGreater(len(seen), 1, "seed=-1 应该每次换一个随机值")
        self.assertEqual(build_prompt(skill, {"seed": 42})["3"]["inputs"]["seed"], 42)

    def test_bad_params_surface_before_submitting(self) -> None:
        skill = validate_skill(GOOD, "mem")
        with self.assertRaises(ValueError):
            build_prompt(skill, {"ckpt_name": "a.safetensors", "steps": "8"})


class CollectImagesTest(unittest.TestCase):
    def test_normalizes_and_skips_garbage(self) -> None:
        entry = {
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "a.png"},
                        {"filename": "b.png", "subfolder": "sub", "type": "temp"},
                        {"no_filename": True},
                        "不是对象",
                    ]
                },
                "10": "不是对象",
                "11": {"images": "不是数组"},
                "12": {},
            }
        }
        images = collect_images(entry)
        self.assertEqual(
            [(i.node, i.filename, i.subfolder, i.type) for i in images],
            [("9", "a.png", "", "output"), ("9", "b.png", "sub", "temp")],
        )

    def test_missing_outputs_is_empty(self) -> None:
        self.assertEqual(collect_images({}), ())
        self.assertEqual(collect_images({"outputs": None}), ())

    def test_url_matches_the_view_route(self) -> None:
        image = SkillOutputImage(node="9", filename="a b.png", subfolder="子 目录", type="output")
        url = image.url("http://127.0.0.1:8188/")
        self.assertTrue(url.startswith("http://127.0.0.1:8188/view?"))
        self.assertIn("filename=a+b.png", url)
        self.assertIn("subfolder=", url)
        self.assertIn("type=output", url)


if __name__ == "__main__":
    unittest.main()
