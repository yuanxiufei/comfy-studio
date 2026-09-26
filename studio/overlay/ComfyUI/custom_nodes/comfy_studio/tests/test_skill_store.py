"""skill 的落盘与内存视图：目录拼装、写盘（原子）、查重、存完立刻能用。

这些是"方法复用"的底座：对话里打磨好的工作流要能存成用户自己的 skill，下一次启动还得
读得回来，并且**别的来源**（随包自带那份）不能被顺手覆盖掉。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ..skills import load_skills, validate_skill, WORKFLOWS_DIR
from ..skills.loader import skill_to_json
from ..skills.registry import SkillRegistry
from ..skills.store import (
    DEFAULT_USER_SKILLS_DIR,
    USER_SKILLS_DIR_ENV,
    check_skill_id,
    load_all_skills,
    load_user_skills,
    user_skills_dir,
    write_skill,
)
from .support import make_skill


def sample_document(skill_id: str = "my-flow") -> dict:
    """一份最小但完整的 skill 文档（字段与 skill 文件一一对应）。"""
    return {
        "id": skill_id,
        "title": "我的工作流",
        "description": "对话里打磨出来的那一套",
        "tags": ["自制"],
        "workflow": {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a.safetensors"}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "cfg": 7.0, "model": ["4", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["3", 0]}},
        },
        "params": [
            {"name": "ckpt_name", "type": "string", "node": "4", "field": "ckpt_name", "required": True},
            {"name": "prefix", "type": "string", "node": "9", "field": "filename_prefix", "default": "x"},
        ],
    }


class UserSkillsDirTest(unittest.TestCase):
    def test_env_var_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp, "自定义目录"))
            with mock.patch.dict(os.environ, {USER_SKILLS_DIR_ENV: target}):
                self.assertEqual(user_skills_dir(), Path(target))
                self.assertEqual(load_user_skills(user_skills_dir()), ())

    def test_default_is_a_user_directory_not_the_packaged_one(self) -> None:
        with mock.patch.dict(os.environ):  # 只是在离开时把环境变量还原
            os.environ.pop(USER_SKILLS_DIR_ENV, None)
            resolved = user_skills_dir()
        self.assertEqual(resolved, DEFAULT_USER_SKILLS_DIR)
        # 随包目录是源码的一部分（装配/升级会整份替换），用户的东西绝不能往里写
        self.assertFalse(resolved.is_relative_to(WORKFLOWS_DIR.resolve()))
        self.assertFalse(resolved.is_relative_to(Path(__file__).resolve().parents[1]))


class SkillIdTest(unittest.TestCase):
    def test_accepts_slug_and_rejects_the_rest(self) -> None:
        self.assertEqual(check_skill_id("cat-portrait_2"), "cat-portrait_2")
        for bad in ("Cat", "../跑出去", "有空格 的", "", "-前面是符号", "a/b", "带.点"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as ctx:
                    check_skill_id(bad)
                self.assertIn("不能当文件名", str(ctx.exception))


class SkillJsonTest(unittest.TestCase):
    def test_document_round_trips_without_losing_fields(self) -> None:
        skill = validate_skill(sample_document(), "mem")
        again = validate_skill(skill_to_json(skill), "mem")
        self.assertEqual(skill.id, again.id)
        self.assertEqual(skill.tags, again.tags)
        self.assertEqual(skill.workflow, again.workflow)
        self.assertEqual(
            [(p.name, p.type, p.node, p.field, p.required, p.has_default, p.default) for p in skill.params],
            [(p.name, p.type, p.node, p.field, p.required, p.has_default, p.default) for p in again.params],
        )

    def test_no_default_and_null_default_stay_different(self) -> None:
        document = sample_document()
        document["params"].append({"name": "cfg", "type": "number", "node": "3", "field": "cfg", "required": False})
        document["params"].append({"name": "extra", "type": "integer", "node": "3", "field": "seed", "default": None})
        skill = validate_skill(document, "mem")
        back = validate_skill(skill_to_json(skill), "mem")
        self.assertFalse(back.params[2].has_default, "没声明 default 的不能凭空多出一个默认值")
        self.assertTrue(back.params[3].has_default, "写了 default: null 也算有默认值，值就是 null")
        self.assertIsNone(back.params[3].default)


class LoadPathsTest(unittest.TestCase):
    def test_user_directory_may_be_missing_or_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_user_skills(Path(tmp, "还没建")), ())
            self.assertEqual(load_user_skills(tmp), ())

    def test_builtin_and_user_are_merged_with_builtin_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(validate_skill(sample_document(), "mem"), tmp)
            ids = [s.id for s in load_all_skills(WORKFLOWS_DIR, tmp)]
            self.assertEqual(ids, ["text-to-image", "my-flow"])

    def test_duplicate_ids_are_reported_with_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builtin = Path(tmp, "builtin")
            user = Path(tmp, "user")
            builtin.mkdir()
            user.mkdir()
            packaged = json.loads((WORKFLOWS_DIR / "text-to-image.json").read_text(encoding="utf-8"))
            (builtin / "text-to-image.json").write_text(json.dumps(packaged), encoding="utf-8")
            (user / "text-to-image.json").write_text(json.dumps(packaged), encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                load_all_skills(builtin, user)
            message = str(ctx.exception)
            self.assertIn("id 冲突", message)
            self.assertIn(str(builtin), message)
            self.assertIn(str(user), message)

    def test_a_broken_user_file_is_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "broken.json").write_text("{ 不是 JSON", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_user_skills(tmp)
            self.assertIn("不是合法 JSON", str(ctx.exception))


class WriteSkillTest(unittest.TestCase):
    def test_writes_readable_json_and_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_skill(validate_skill(sample_document(), "mem"), Path(tmp, "深层", "目录"))
            self.assertEqual(target.name, "my-flow.json")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["id"], "my-flow")
            self.assertEqual(list(target.parent.glob("*.tmp")), [], "临时文件必须被换掉，不能留下来")

    def test_writing_the_same_skill_twice_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = validate_skill(sample_document(), "mem")
            first = write_skill(skill, tmp)
            second = write_skill(skill, tmp)
            self.assertEqual(first, second)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["my-flow.json"])


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-registry-")
        self.addCleanup(self._tmp.cleanup)
        self.user_dir = Path(self._tmp.name)
        self.registry = SkillRegistry(builtin_dir=WORKFLOWS_DIR, user_dir=self.user_dir)
        self.registry.reload()

    def test_reload_sees_what_is_on_disk(self) -> None:
        self.assertEqual([s.id for s in self.registry.all()], ["text-to-image"])
        write_skill(validate_skill(sample_document(), "mem"), self.user_dir)
        self.assertIsNone(self.registry.get("my-flow"), "没 reload 之前不该凭空多出来")
        self.registry.reload()
        self.assertEqual([s.id for s in self.registry.all()], ["text-to-image", "my-flow"])

    def test_save_persists_and_returns_the_loaded_skill(self) -> None:
        saved = self.registry.save(sample_document())
        self.assertEqual(saved.id, "my-flow")
        self.assertEqual(Path(saved.source), self.user_dir / "my-flow.json")
        self.assertEqual([p.name for p in saved.params], ["ckpt_name", "prefix"])
        self.assertEqual(self.registry.get("my-flow").title, "我的工作流")

    def test_save_refuses_bad_documents_without_touching_disk(self) -> None:
        for document, expected in (
            ({**sample_document(), "title": ""}, "title"),
            (
                {**sample_document(), "params": [{"name": "x", "type": "integer", "node": "404", "field": "steps"}]},
                "不在 workflow 里",
            ),
            (sample_document("Bad Id"), "不能当文件名"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(ValueError) as ctx:
                    self.registry.save(document)
                self.assertIn(expected, str(ctx.exception))
        self.assertEqual(list(self.user_dir.glob("*.json")), [])

    def test_save_requires_an_explicit_overwrite(self) -> None:
        self.registry.save(sample_document())
        with self.assertRaises(ValueError) as ctx:
            self.registry.save({**sample_document(), "title": "换个标题"})
        self.assertIn("overwrite=true", str(ctx.exception))
        self.assertEqual(self.registry.get("my-flow").title, "我的工作流")

        self.registry.save({**sample_document(), "title": "换个标题"}, overwrite=True)
        self.assertEqual(self.registry.get("my-flow").title, "换个标题")

    def test_builtin_skill_ids_are_taken(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.registry.save({**sample_document("text-to-image"), "id": "text-to-image"}, overwrite=True)
        self.assertIn("随包自带", str(ctx.exception))
        self.assertEqual(len(self.registry.all()), 1)

    def test_in_memory_view_cannot_write(self) -> None:
        registry = SkillRegistry.in_memory([make_skill("demo")])
        self.assertEqual(registry.get("demo").id, "demo")
        with self.assertRaises(ValueError) as ctx:
            registry.save(sample_document())
        self.assertIn("不落盘", str(ctx.exception))

    def test_duplicate_ids_inside_one_source_are_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            SkillRegistry.in_memory([make_skill("demo"), make_skill("demo")])
        self.assertIn("id 冲突", str(ctx.exception))

    def test_paths_are_reported_for_status_output(self) -> None:
        self.assertEqual(
            self.registry.paths(),
            {"builtin": str(WORKFLOWS_DIR), "user": str(self.user_dir)},
        )
        self.assertEqual(SkillRegistry().paths(), {"builtin": None, "user": None})

    def test_packaged_skills_still_load_the_old_way(self) -> None:
        # 老的入口（load_skills）不能被这层重构改掉口味
        self.assertEqual([s.id for s in load_skills(WORKFLOWS_DIR)], ["text-to-image"])


if __name__ == "__main__":
    unittest.main()
