"""``comfy_studio.novels`` 的单元测试（纯本地：临时目录当"引擎检出"，不拉子进程）。

跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_novels -v

后一组 ``NovelsRpcTest`` 顺手把宿主那一层也钉住：直接建 ``StudioHost``（不 serve）调那四个
``novels/*``，看参数越界是不是 ``INVALID_PARAMS``、没挂原文目录时说不说得清 ——
"面板收到的错误"和"库抛的异常"不是一回事，两边都得有人说理。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfy_studio.mcp import McpHub
from comfy_studio.novels import (
    MANJU_REL,
    NOVEL_SUBDIR,
    NovelLibrary,
    NovelsError,
    default_novel_dir,
)
from comfy_studio.rpc import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from comfy_studio.server import StudioHost
from comfy_studio.skills import SkillCatalog

UTF8_BOM = "\ufeff"


class NovelLibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-novels-")
        self.repo = Path(self._tmp.name)
        # 默认落点：<comfyui-dir>/custom_nodes/comfy_studio/manju/novel
        self.novel_dir = self.repo / MANJU_REL / NOVEL_SUBDIR
        self.library = NovelLibrary(self.novel_dir)
        # "用户本机那份原文"另放一处：它当然不在 ComfyUI 检出里。
        self._src_tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-novel-src-")
        self.sources = Path(self._src_tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        self._src_tmp.cleanup()

    def _novel(self, name: str, text: str) -> Path:
        """在原文目录里放一篇（要造隐藏项就在名字前加点，见下面那条用例）。"""
        path = self.novel_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _source(self, name: str, data: bytes) -> Path:
        path = self.sources / name
        path.write_bytes(data)
        return path

    # ---- 落点 -----------------------------------------------------------

    def test_default_dir_is_repo_relative(self) -> None:
        # 默认落点必须是**仓库内相对路径**拼出来的：换机器、换检出照样成立，
        # 不许出现哪台机器的盘符（见仓库根 README 里"不写死路径"那条）。
        self.assertEqual(default_novel_dir(self.repo), self.novel_dir)
        self.assertEqual(default_novel_dir(self.repo).relative_to(self.repo), MANJU_REL / NOVEL_SUBDIR)
        # 用 parts 比对：Windows 上 str() 是反斜杠，钉分隔符没意义，钉层级才有意义。
        self.assertEqual(MANJU_REL.parts, ("custom_nodes", "comfy_studio", "manju"))
        self.assertEqual(NOVEL_SUBDIR, "novel")

    # ---- list -----------------------------------------------------------

    def test_missing_dir_is_a_state_not_an_error(self) -> None:
        result = self.library.list()
        self.assertFalse(result["exists"])
        self.assertEqual(result["novels"], [])
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["dir"], str(self.novel_dir))

    def test_list_sorts_by_name_and_marks_text(self) -> None:
        self._novel("b-第二本.txt", "乙")
        self._novel("A-第一本.txt", "甲")
        self._novel("封面.png", "not-a-text")
        result = self.library.list()
        self.assertTrue(result["exists"])
        self.assertEqual([row["name"] for row in result["novels"]], ["A-第一本.txt", "b-第二本.txt", "封面.png"])
        by_name = {row["name"]: row for row in result["novels"]}
        self.assertTrue(by_name["A-第一本.txt"]["text"])
        self.assertFalse(by_name["封面.png"]["text"])
        self.assertEqual(by_name["A-第一本.txt"]["bytes"], len("甲".encode("utf-8")))

    def test_list_skips_hidden_and_finds_subdirs(self) -> None:
        self._novel(".gitkeep", "")
        self._novel(".DS_Store", "junk")
        self._novel("老书/上卷.txt", "正文")
        result = self.library.list()
        self.assertEqual([row["name"] for row in result["novels"]], ["老书/上卷.txt"])
        self.assertEqual(result["novels"][0]["name"], "老书/上卷.txt")

    def test_hidden_dir_contents_are_not_listed_nor_reachable(self) -> None:
        # 隐藏**目录**里的东西也不算原文：只挡文件名的话，`.私藏/秘本.txt` 会绕过这一条漏进书库。
        self._novel(".私藏/秘本.txt", "藏起来的")
        self.assertEqual(self.library.list()["novels"], [])
        # 列表里不出现的东西，也不该能从名字那条路上读到、更不该删掉 —— 它是**真文件**。
        for name in (".私藏/秘本.txt", ".gitkeep"):
            with self.subTest(name=name):
                with self.assertRaises(NovelsError) as err:
                    self.library.read(name)
                self.assertIn("隐藏项", str(err.exception))
                with self.assertRaises(NovelsError):
                    self.library.delete(name)

    def test_list_filters_and_reports_truncation(self) -> None:
        for index in range(3):
            self._novel(f"废土-{index}.txt", "x")
        self._novel("赛博-1.txt", "y")
        filtered = self.library.list("废土")
        self.assertEqual(filtered["matched"], 3)
        self.assertEqual(filtered["returned"], 3)
        limited = self.library.list(limit=2)
        self.assertEqual(limited["matched"], 4)
        self.assertEqual(limited["returned"], 2)
        self.assertTrue(limited["truncated"])
        self.assertEqual(len(limited["novels"]), 2)

    # ---- read -----------------------------------------------------------

    def test_read_pages_by_characters(self) -> None:
        text = "".join(f"{index:03d}" for index in range(100))
        self._novel("长文.txt", text)
        first = self.library.read("长文.txt", 0, 25)
        self.assertEqual(first["text"], text[:25])
        self.assertEqual(first["offset"], 0)
        self.assertEqual(first["chars"], 25)
        self.assertEqual(first["total_chars"], len(text))
        self.assertEqual(first["next_offset"], 25)
        self.assertFalse(first["at_end"])
        second = self.library.read("长文.txt", first["next_offset"], 25)
        self.assertEqual(second["text"], text[25:50])
        self.assertFalse(second["at_end"])
        tail = self.library.read("长文.txt", len(text) - 10, 25)
        self.assertEqual(tail["text"], text[-10:])
        self.assertTrue(tail["at_end"])
        self.assertEqual(tail["next_offset"], len(text))

    def test_read_strips_bom(self) -> None:
        # 记事本"另存为 UTF-8"会加 BOM：那三个字节不该当成正文的第一个字。
        path = self.novel_dir / "带BOM.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((UTF8_BOM + "第一章").encode("utf-8"))
        result = self.library.read("带BOM.txt")
        self.assertEqual(result["text"], "第一章")
        self.assertEqual(result["total_chars"], 3)

    def test_read_clamps_offset_past_the_end(self) -> None:
        self._novel("短.txt", "就一行")
        result = self.library.read("短.txt", 9999, 10)
        self.assertEqual(result["text"], "")
        self.assertEqual(result["offset"], 3)
        self.assertTrue(result["at_end"])

    def test_read_refuses_what_it_cannot_read(self) -> None:
        self._novel("图.png", "看着像文本但不是原文")
        with self.assertRaises(NovelsError) as non_text:
            self.library.read("图.png")
        self.assertIn("不是原文", str(non_text.exception))
        with self.assertRaises(NovelsError) as missing:
            self.library.read("没这篇.txt")
        self.assertIn("没有这一篇", str(missing.exception))
        with self.assertRaises(NovelsError) as negative:
            self.library.read("图.png", -1)
        self.assertIn("offset", str(negative.exception))

    def test_read_takes_gbk_written_novels(self) -> None:
        # 中文网文十有八九是 GBK/GB18030 而不是 UTF-8（仓库里那本原文就是）：只认 UTF-8 等于
        # 读不了用户自己的书，所以这里认它，并且把用的是哪一种编码报出来（面板会写在状态行上）。
        self._source("gbk.txt", "第一章 你好".encode("gbk"))
        self.library.import_file(str(self.sources / "gbk.txt"))
        result = self.library.read("gbk.txt")
        self.assertEqual(result["encoding"], "gb18030")
        self.assertEqual(result["text"], "第一章 你好")
        self.assertEqual(result["total_chars"], 6)

        # 分页按字符：这两种编码都是变长的，按字节切会把汉字劈成两半。
        self.assertEqual(self.library.read("gbk.txt", 2, 2)["text"], "章 ")
        self.assertEqual(self.library.read("gbk.txt", 2, 2)["total_chars"], 6)

    def test_read_takes_utf16_with_bom(self) -> None:
        # 记事本"另存为 Unicode"：BOM 自己指明字节序，不用猜。
        path = self.novel_dir / "记事本存的.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes("第一章 雪".encode("utf-16"))
        result = self.library.read("记事本存的.txt")
        self.assertEqual(result["encoding"], "utf-16")
        self.assertEqual(result["text"], "第一章 雪")

    def test_read_refuses_what_decodes_but_is_not_text(self) -> None:
        # gb18030 是"几乎什么字节都能解"的超集：解成功不算数，解出来得是人话。
        # 这里拿它的私用区编码造一篇"能解出来、但根本不是字"的东西（PUA 在正常原文里是零），
        # 必须拒 —— 把一屏怪字当正文交出去，看着像面板坏了，用户只会反复点。
        self._source("怪字.txt", "\ue000\ue001\ue002".encode("gb18030") * 200)
        self.library.import_file(str(self.sources / "怪字.txt"))
        with self.assertRaises(NovelsError) as err:
            self.library.read("怪字.txt")
        self.assertIn("不是正文", str(err.exception))

    def test_read_refuses_bytes_no_encoding_takes(self) -> None:
        # 两种编码都解不过去：报错要说清试过哪两种、从第几字节起读不下去，别只说"失败"。
        self._source("二进制.txt", bytes(range(256)) * 40)
        self.library.import_file(str(self.sources / "二进制.txt"))
        with self.assertRaises(NovelsError) as err:
            self.library.read("二进制.txt")
        message = str(err.exception)
        self.assertIn("认不出编码", message)
        self.assertIn("utf-8", message)
        self.assertIn("gb18030", message)
        self.assertIn("Big5", message)  # 不认的那一种也要说出口，免得用户以为面板在偷懒

    def test_read_refuses_oversized_novel(self) -> None:
        self._novel("超大.txt", "abcdefg")
        with mock.patch("comfy_studio.novels.MAX_TEXT_BYTES", 3):
            with self.assertRaises(NovelsError) as err:
                self.library.read("超大.txt")
        self.assertIn("超过面板翻页的上限", str(err.exception))

    # ---- import ---------------------------------------------------------

    def test_import_creates_the_dir_and_copies(self) -> None:
        source = self._source("流氓天尊.txt", "第一章 玄幻".encode("utf-8"))
        result = self.library.import_file(str(source))
        self.assertTrue(result["imported"])
        self.assertTrue(result["created_dir"])
        self.assertEqual(result["name"], "流氓天尊.txt")
        self.assertFalse(result["overwritten"])
        self.assertTrue(self.novel_dir.is_dir())
        self.assertEqual((self.novel_dir / "流氓天尊.txt").read_text(encoding="utf-8"), "第一章 玄幻")
        self.assertEqual(result["bytes"], source.stat().st_size)

    def test_import_existing_asks_first(self) -> None:
        self._novel("流氓天尊.txt", "原来那本")
        source = self._source("流氓天尊.txt", "新来那本".encode("utf-8"))
        result = self.library.import_file(str(source))
        self.assertFalse(result["imported"])
        self.assertEqual(result["reason"], "exists")
        self.assertIn("overwrite", result["message"])
        # 没确认之前，目录里那份一个字都不许动。
        self.assertEqual((self.novel_dir / "流氓天尊.txt").read_text(encoding="utf-8"), "原来那本")

    def test_import_overwrite_replaces(self) -> None:
        self._novel("流氓天尊.txt", "原来那本")
        source = self._source("流氓天尊.txt", "新来那本".encode("utf-8"))
        result = self.library.import_file(str(source), overwrite=True)
        self.assertTrue(result["imported"])
        self.assertTrue(result["overwritten"])
        self.assertFalse(result["created_dir"])
        self.assertEqual((self.novel_dir / "流氓天尊.txt").read_text(encoding="utf-8"), "新来那本")

    def test_import_can_rename(self) -> None:
        source = self._source("sha256-乱七八糟.txt", "正文".encode("utf-8"))
        result = self.library.import_file(str(source), "废土纪元 第一章.txt")
        self.assertEqual(result["name"], "废土纪元 第一章.txt")
        self.assertTrue((self.novel_dir / "废土纪元 第一章.txt").is_file())

    def test_import_refuses_bad_input(self) -> None:
        source = self._source("正经.txt", b"x")
        with self.assertRaises(NovelsError) as missing:
            self.library.import_file(str(self.sources / "没有这个.txt"))
        self.assertIn("不存在", str(missing.exception))
        with self.assertRaises(NovelsError) as is_dir:
            self.library.import_file(str(self.sources))
        self.assertIn("目录", str(is_dir.exception))
        with self.assertRaises(NovelsError) as suffix:
            self.library.import_file(str(self._source("封面.png", b"png")))
        self.assertIn("txt", str(suffix.exception))
        with self.assertRaises(NovelsError) as named:
            self.library.import_file(str(source), "子目录/改名.txt")
        self.assertIn("不能带路径", str(named.exception))
        self.assertFalse((self.novel_dir / "正经.txt").exists())

    def test_import_refuses_to_copy_onto_itself(self) -> None:
        source = self._source("自己.txt", "正文".encode("utf-8"))
        self.library.import_file(str(source))
        inside = self.novel_dir / "自己.txt"
        with self.assertRaises(NovelsError) as err:
            self.library.import_file(str(inside), overwrite=True)
        self.assertIn("不用再导一次", str(err.exception))
        self.assertEqual(inside.read_text(encoding="utf-8"), "正文")

    # ---- delete ---------------------------------------------------------

    def test_delete_removes_one(self) -> None:
        self._novel("删我.txt", "正文")
        self._novel("留我.txt", "正文")
        result = self.library.delete("删我.txt")
        self.assertTrue(result["deleted"])
        self.assertEqual(result["name"], "删我.txt")
        self.assertFalse((self.novel_dir / "删我.txt").exists())
        self.assertTrue((self.novel_dir / "留我.txt").exists())
        with self.assertRaises(NovelsError):
            self.library.delete("删我.txt")

    # ---- 越界 -----------------------------------------------------------

    def test_names_cannot_leave_the_novel_dir(self) -> None:
        outside = self.repo / "别处.txt"
        outside.write_text("外面的文件", encoding="utf-8")
        for name in ("../别处.txt", "..\\别处.txt", str(outside), "/etc/passwd"):
            with self.subTest(name=name):
                with self.assertRaises(NovelsError):
                    self.library.delete(name)
                with self.assertRaises(NovelsError):
                    self.library.read(name)
        self.assertTrue(outside.is_file())


class NovelsRpcTest(unittest.TestCase):
    """宿主那一层：方法注册了没、参数越界回什么码、没挂目录时说不说得清。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-novels-rpc-")
        self.novel_dir = Path(self._tmp.name) / MANJU_REL / NOVEL_SUBDIR
        self.library = NovelLibrary(self.novel_dir)
        self.hub = McpHub([], extra_clients=[])
        self.host = StudioHost(
            self.hub, SkillCatalog(self.hub), comfyui_dir=str(self._tmp.name), novels=self.library
        )
        self.bare = StudioHost(self.hub, SkillCatalog(self.hub))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_methods_are_registered(self) -> None:
        for method in ("novels/list", "novels/read", "novels/import", "novels/delete"):
            self.assertIn(method, self.host.server.methods)

    def test_info_reports_the_novel_dir(self) -> None:
        info = self.host.info({}, None)
        self.assertTrue(info["novels"])
        self.assertEqual(info["novel_dir"], str(self.novel_dir))
        # 没挂的时候要如实说没有，别报一个假的目录出去。
        self.assertFalse(self.bare.info({}, None)["novels"])
        self.assertIsNone(self.bare.info({}, None)["novel_dir"])

    def test_host_without_novel_dir_says_so(self) -> None:
        with self.assertRaises(RpcError) as err:
            self.bare.novels_list({}, None)
        self.assertEqual(err.exception.code, INTERNAL_ERROR)
        self.assertIn("没挂原文目录", err.exception.message)

    def test_read_validates_parameters(self) -> None:
        (self.novel_dir).mkdir(parents=True, exist_ok=True)
        (self.novel_dir / "一本.txt").write_text("正文", encoding="utf-8")
        ok = self.host.novels_read({"name": "一本.txt"}, None)
        self.assertEqual(ok["text"], "正文")
        for params in ({"name": "一本.txt", "offset": -1}, {"name": "一本.txt", "chars": 0}):
            with self.subTest(params=params):
                with self.assertRaises(RpcError) as err:
                    self.host.novels_read(params, None)
                self.assertEqual(err.exception.code, INVALID_PARAMS)
        with self.assertRaises(RpcError) as blank:
            self.host.novels_read({"name": "  "}, None)
        self.assertEqual(blank.exception.code, INVALID_PARAMS)
        with self.assertRaises(RpcError) as typed:
            self.host.novels_read({"name": "一本.txt", "chars": "很多"}, None)
        self.assertEqual(typed.exception.code, INVALID_PARAMS)

    def test_import_existing_comes_back_as_a_result_not_an_error(self) -> None:
        self.novel_dir.mkdir(parents=True, exist_ok=True)
        (self.novel_dir / "一本.txt").write_text("原来那本", encoding="utf-8")
        source = Path(self._tmp.name) / "一本.txt"
        source.write_text("新来那本", encoding="utf-8")
        result = self.host.novels_import({"path": str(source)}, None)
        self.assertFalse(result["imported"])
        self.assertEqual(result["reason"], "exists")
        again = self.host.novels_import({"path": str(source), "overwrite": True}, None)
        self.assertTrue(again["imported"])

    def test_import_bad_path_is_a_parameter_error(self) -> None:
        with self.assertRaises(RpcError) as err:
            self.host.novels_import({"path": str(Path(self._tmp.name) / "没有.txt")}, None)
        self.assertEqual(err.exception.code, INVALID_PARAMS)
        with self.assertRaises(RpcError) as typed:
            self.host.novels_import({"path": "x.txt", "overwrite": "yes"}, None)
        self.assertEqual(typed.exception.code, INVALID_PARAMS)


if __name__ == "__main__":
    unittest.main()
