"""``comfy_studio.localfiles`` 的单元测试（纯本地，不拉任何子进程）。

用临时目录当 ComfyUI 检出：``<tmp>/input`` 与 ``<tmp>/output`` 就是那两类目录。
跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_local_files -v
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from comfy_studio.localfiles import (
    DEFAULT_TEXT_BYTES,
    LOCAL_FILES_TOOLS,
    MAX_TEXT_BYTES,
    LocalFiles,
    LocalFilesClient,
    LocalFilesError,
)
from comfy_studio.mcp import McpError


def _call(client: LocalFilesClient, tool: str, **args):
    return asyncio.run(client.call_tool(tool, args))


def _payload(result: dict) -> dict:
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


class LocalFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-localfiles-")
        self.root = Path(self._tmp.name)
        self.files = LocalFiles(self.root)
        self.client = LocalFilesClient(self.files)
        # 用户的"本机素材"另放一处，模拟它不在 ComfyUI 目录里。
        self._src_tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-sources-")
        self.sources = Path(self._src_tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        self._src_tmp.cleanup()

    def _source(self, name: str, data: bytes = b"png-bytes") -> Path:
        path = self.sources / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    # ---- 工具表 ---------------------------------------------------------

    def test_tools_are_named_and_described(self) -> None:
        tools = asyncio.run(self.client.list_tools())
        names = [t.name for t in tools]
        self.assertEqual(names, [spec.name for spec in LOCAL_FILES_TOOLS])
        self.assertEqual(names, ["import_file", "list_files", "read_text"])
        for tool in tools:
            self.assertEqual(tool.server, "localfiles")
            self.assertTrue(tool.description.strip())
            self.assertIn("properties", tool.input_schema)

    def test_unknown_tool_is_a_protocol_error(self) -> None:
        with self.assertRaises(McpError):
            asyncio.run(self.client.call_tool("nope", {}))

    # ---- import_file ----------------------------------------------------

    def test_import_copies_into_input_and_returns_the_workflow_value(self) -> None:
        source = self._source("cat.png")
        payload = _payload(_call(self.client, "import_file", path=str(source)))

        self.assertEqual(payload["value"], "cat.png")
        self.assertEqual(payload["type"], "input")
        self.assertIs(payload["reused"], False)
        copied = self.root / "input" / "cat.png"
        self.assertEqual(Path(payload["path"]), copied)
        self.assertEqual(copied.read_bytes(), b"png-bytes")
        self.assertEqual(payload["bytes"], len(b"png-bytes"))
        self.assertEqual(Path(payload["source"]), source)

    def test_import_into_a_subfolder_prefixes_the_value(self) -> None:
        source = self._source("cat.png")
        payload = _payload(
            _call(self.client, "import_file", path=str(source), subfolder="refs/2026")
        )
        self.assertEqual(payload["value"], "refs/2026/cat.png")
        self.assertEqual(payload["subfolder"], "refs/2026")
        self.assertTrue((self.root / "input" / "refs" / "2026" / "cat.png").is_file())

    def test_import_renames_instead_of_overwriting_a_different_file(self) -> None:
        source = self._source("cat.png", b"first")
        first = _payload(_call(self.client, "import_file", path=str(source)))
        source.write_bytes(b"second")
        second = _payload(_call(self.client, "import_file", path=str(source)))

        self.assertEqual(first["name"], "cat.png")
        # 命名规则照抄上游上传接口：``name (1).ext``。
        self.assertEqual(second["name"], "cat (1).png")
        self.assertEqual(second["value"], "cat (1).png")
        self.assertEqual((self.root / "input" / "cat.png").read_bytes(), b"first")
        self.assertEqual((self.root / "input" / "cat (1).png").read_bytes(), b"second")

    def test_import_reuses_an_identical_file_instead_of_stacking_copies(self) -> None:
        source = self._source("cat.png", b"same")
        _payload(_call(self.client, "import_file", path=str(source)))
        again = _payload(_call(self.client, "import_file", path=str(source)))

        self.assertIs(again["reused"], True)
        self.assertEqual(again["name"], "cat.png")
        self.assertEqual(sorted(p.name for p in (self.root / "input").iterdir()), ["cat.png"])

    def test_import_can_overwrite_when_asked(self) -> None:
        source = self._source("cat.png", b"first")
        _payload(_call(self.client, "import_file", path=str(source)))
        source.write_bytes(b"second")
        payload = _payload(_call(self.client, "import_file", path=str(source), overwrite=True))

        self.assertEqual(payload["name"], "cat.png")
        self.assertIs(payload["reused"], False)
        self.assertEqual((self.root / "input" / "cat.png").read_bytes(), b"second")

    def test_import_refuses_a_missing_source(self) -> None:
        result = _call(self.client, "import_file", path=str(self.sources / "nope.png"))
        self.assertIs(result["isError"], True)
        self.assertIn("不存在", result["content"][0]["text"])

    def test_import_refuses_a_directory_as_source(self) -> None:
        result = _call(self.client, "import_file", path=str(self.sources))
        self.assertIs(result["isError"], True)
        self.assertIn("目录", result["content"][0]["text"])

    def test_import_refuses_a_subfolder_that_escapes_input(self) -> None:
        source = self._source("cat.png")
        result = _call(self.client, "import_file", path=str(source), subfolder="../escape")
        self.assertIs(result["isError"], True)
        self.assertIn("input", result["content"][0]["text"])
        self.assertFalse((self.root / "escape").exists())

    def test_import_refuses_a_name_that_carries_a_path(self) -> None:
        source = self._source("cat.png")
        result = _call(self.client, "import_file", path=str(source), name="sub/cat.png")
        self.assertIs(result["isError"], True)
        self.assertIn("只能是文件名", result["content"][0]["text"])

    def test_import_rejects_a_non_boolean_overwrite(self) -> None:
        source = self._source("cat.png")
        result = _call(self.client, "import_file", path=str(source), overwrite="yes")
        self.assertIs(result["isError"], True)
        self.assertIn("布尔值", result["content"][0]["text"])

    # ---- list_files -----------------------------------------------------

    def test_list_outputs_reports_absolute_paths_newest_first(self) -> None:
        out = self.root / "output"
        (out / "2026-09").mkdir(parents=True)
        older = out / "a.png"
        older.write_bytes(b"a")
        newer = out / "2026-09" / "b.png"
        newer.write_bytes(b"bb")
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_800_000_000, 1_800_000_000))

        payload = _payload(_call(self.client, "list_files"))

        self.assertEqual(payload["type"], "output")
        self.assertEqual(Path(payload["dir"]), out)
        self.assertEqual([f["name"] for f in payload["files"]], ["b.png", "a.png"])
        self.assertEqual(payload["files"][0]["subfolder"], "2026-09")
        self.assertEqual(Path(payload["files"][0]["path"]), newer)
        self.assertEqual(payload["files"][0]["bytes"], 2)

    def test_list_files_filters_by_name_and_honours_limit(self) -> None:
        out = self.root / "output"
        out.mkdir()
        for name in ("cat.png", "dog.png", "cat-2.png"):
            (out / name).write_bytes(b"x")

        by_name = _payload(_call(self.client, "list_files", name="cat"))
        self.assertEqual(sorted(f["name"] for f in by_name["files"]), ["cat-2.png", "cat.png"])
        self.assertEqual(by_name["matched"], 2)

        limited = _payload(_call(self.client, "list_files", limit=1))
        self.assertEqual(limited["matched"], 3)
        self.assertEqual(limited["returned"], 1)
        self.assertEqual(len(limited["files"]), 1)

    def test_list_files_can_look_at_input(self) -> None:
        source = self._source("cat.png")
        _call(self.client, "import_file", path=str(source))
        payload = _payload(_call(self.client, "list_files", type="input"))
        self.assertEqual([f["name"] for f in payload["files"]], ["cat.png"])

    def test_list_files_reports_a_missing_directory_instead_of_an_empty_list(self) -> None:
        result = _call(self.client, "list_files")
        self.assertIs(result["isError"], True)
        self.assertIn("还不存在", result["content"][0]["text"])

    def test_list_files_rejects_an_unknown_type_and_a_silly_limit(self) -> None:
        (self.root / "output").mkdir()
        bad_type = _call(self.client, "list_files", type="models")
        self.assertIs(bad_type["isError"], True)
        self.assertIn("output", bad_type["content"][0]["text"])

        bad_limit = _call(self.client, "list_files", limit=0)
        self.assertIs(bad_limit["isError"], True)
        self.assertIn("limit", bad_limit["content"][0]["text"])

    # ---- read_text ------------------------------------------------------

    def test_read_text_returns_content_and_size(self) -> None:
        source = self._source("prompt.txt", "一只猫，胶片感".encode("utf-8"))
        payload = _payload(_call(self.client, "read_text", path=str(source)))
        self.assertEqual(payload["text"], "一只猫，胶片感")
        self.assertIs(payload["truncated"], False)
        self.assertEqual(payload["read_bytes"], len("一只猫，胶片感".encode("utf-8")))

    def test_read_text_truncates_and_says_so(self) -> None:
        source = self._source("big.txt", b"a" * 5000)
        payload = _payload(_call(self.client, "read_text", path=str(source), max_bytes=1000))
        self.assertEqual(len(payload["text"]), 1000)
        self.assertIs(payload["truncated"], True)
        self.assertEqual(payload["bytes"], 5000)

    def test_read_text_strips_a_bom(self) -> None:
        source = self._source("bom.txt", b"\xef\xbb\xbfhello")
        payload = _payload(_call(self.client, "read_text", path=str(source)))
        self.assertEqual(payload["text"], "hello")

    def test_read_text_refuses_binary_with_a_way_out(self) -> None:
        source = self._source("cat.png", b"\x89PNG\r\n\x1a\n\xff\xfe")
        result = _call(self.client, "read_text", path=str(source))
        self.assertIs(result["isError"], True)
        self.assertIn("import_file", result["content"][0]["text"])

    def test_read_text_refuses_a_limit_above_the_cap(self) -> None:
        source = self._source("big.txt", b"a")
        result = _call(self.client, "read_text", path=str(source), max_bytes=MAX_TEXT_BYTES + 1)
        self.assertIs(result["isError"], True)
        self.assertIn(str(MAX_TEXT_BYTES), result["content"][0]["text"])

    def test_read_text_default_limit_is_the_documented_one(self) -> None:
        source = self._source("mid.txt", b"a" * (DEFAULT_TEXT_BYTES + 5))
        payload = _payload(_call(self.client, "read_text", path=str(source)))
        self.assertEqual(len(payload["text"]), DEFAULT_TEXT_BYTES)
        self.assertIs(payload["truncated"], True)

    # ---- 目录解析 -------------------------------------------------------

    def test_directories_can_be_pointed_elsewhere(self) -> None:
        other_in = self.sources / "my-input"
        other_out = self.sources / "my-output"
        files = LocalFiles(self.root, input_dir=other_in, output_dir=other_out)
        self.assertEqual(files.directory("input"), other_in)
        self.assertEqual(files.directory("output"), other_out)
        # temp 没有对应的启动参数，永远按默认布局算。
        self.assertEqual(files.directory("temp"), self.root / "temp")
        with self.assertRaises(LocalFilesError):
            files.directory("models")


if __name__ == "__main__":
    unittest.main()
