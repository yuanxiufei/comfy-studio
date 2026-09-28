"""产物回收（``skills/outputs.py``）：分类判据、从 history 认产物、取回与落盘。

这里所有断言的口径都来自真源码，不是想当然：
* ``SaveVideo`` 走 ``PreviewVideo``，history 里的键**同样是 ``images``** —— 图与视频只能靠
  扩展名分（出处 ``comfy_api/latest/_ui.py``）；
* ``webp`` 是引擎给 ``mimetypes`` 打的小灶（``folder_paths.extension_mimetypes_cache``），
  漏了它就会把 webp 产物误判成 other。
"""

from __future__ import annotations

import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from ..skills.outputs import (
    OutputFetchError,
    collect_media,
    guess_kind,
    local_path,
    save_media,
    save_media_batch,
)
from ..skills.types import SkillOutputMedia, SkillRunResult


def _media(**kwargs: object) -> SkillOutputMedia:
    base: dict = {"node": "9", "filename": "a.png", "subfolder": "", "type": "output", "kind": "image"}
    base.update(kwargs)
    return SkillOutputMedia(**base)  # type: ignore[arg-type]


class GuessKindTest(unittest.TestCase):
    def test_mirrors_the_engine_extension_table(self) -> None:
        # webp：mimetypes 在 Windows 上猜不出来，只有引擎那张补丁表认得它
        self.assertEqual(guess_kind("a.webp"), "image")

    def test_common_production_extensions(self) -> None:
        cases = {
            "a.png": "image",
            "a.jpg": "image",
            "a.mp4": "video",
            "a.webm": "video",
            "a.mkv": "video",
            "a.mp3": "audio",
            "a.wav": "audio",
            "a.flac": "audio",  # SaveAudio 的默认容器
        }
        for filename, kind in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(guess_kind(filename), kind)

    def test_unknown_kinds_are_kept_as_other_not_dropped(self) -> None:
        self.assertEqual(guess_kind("a.txt"), "other")
        self.assertEqual(guess_kind("没有扩展名"), "other")
        # 引擎表里 fbx 是 3D 模型，不属于我们的媒体类别
        self.assertEqual(guess_kind("a.fbx"), "other")


class CollectMediaTest(unittest.TestCase):
    def test_video_hangs_under_the_images_key(self) -> None:
        entry = {"outputs": {"6": {"images": [{"filename": "clip.mp4"}, {"filename": "shot.png"}], "animated": (True,)}}}
        media = collect_media(entry)
        self.assertEqual(
            [(item.node, item.filename, item.kind) for item in media],
            [("6", "clip.mp4", "video"), ("6", "shot.png", "image")],
        )

    def test_audio_key(self) -> None:
        entry = {"outputs": {"12": {"audio": [{"filename": "voice.flac", "subfolder": "audio"}]}}}
        media = collect_media(entry)
        self.assertEqual([(item.kind, item.subfolder, item.type) for item in media], [("audio", "audio", "output")])

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
        media = collect_media(entry)
        self.assertEqual(
            [(i.node, i.filename, i.subfolder, i.type, i.kind) for i in media],
            [("9", "a.png", "", "output", "image"), ("9", "b.png", "sub", "temp", "image")],
        )

    def test_missing_outputs_is_empty(self) -> None:
        self.assertEqual(collect_media({}), ())
        self.assertEqual(collect_media({"outputs": None}), ())


class LocalPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def test_finds_the_file_under_the_type_root(self) -> None:
        (self.root / "sub").mkdir()
        (self.root / "sub" / "a.png").write_bytes(b"x")
        found = local_path(_media(subfolder="sub"), resolve_dir=lambda _type: str(self.root))
        self.assertEqual(found, (self.root / "sub" / "a.png"))

    def test_missing_file_is_none(self) -> None:
        self.assertIsNone(local_path(_media(), resolve_dir=lambda _type: str(self.root)))

    def test_path_escape_is_refused(self) -> None:
        """``subfolder`` 来自 history，带上 ``..`` 就能指到根外面（上游有同样的用例）。"""
        (self.root / "output").mkdir()
        (self.root / "outside.png").write_bytes(b"x")
        found = local_path(
            _media(subfolder="..", filename="outside.png"),
            resolve_dir=lambda _type: str(self.root / "output"),
        )
        self.assertIsNone(found)

    def test_unknown_folder_type_is_none(self) -> None:
        self.assertIsNone(local_path(_media(type="远端"), resolve_dir=lambda _type: None))


class _ViewHandler(http.server.BaseHTTPRequestHandler):
    """冒充引擎的 /view：返回固定字节，并把收到的查询串记下来。"""

    payload = b""
    seen: list = []

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的接口名
        type(self).seen.append(self.path)
        body = type(self).payload
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # 测试里不需要访问日志
        pass


class SaveMediaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.target = self.root / "落点"
        self.source_root = self.root / "output"
        self.source_root.mkdir()
        _ViewHandler.seen = []
        _ViewHandler.payload = b""
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ViewHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def test_prefers_copying_the_file_already_on_this_machine(self) -> None:
        (self.source_root / "a.png").write_bytes(b"local-artifact")
        saved = save_media(_media(), self.target, resolve_dir=lambda _type: str(self.source_root))
        self.assertEqual(saved.read_bytes(), b"local-artifact")
        self.assertEqual(_ViewHandler.seen, [], "本机能直接复制，不该再去走 HTTP")

    def test_falls_back_to_the_view_route(self) -> None:
        _ViewHandler.payload = b"remote-artifact"
        saved = save_media(_media(subfolder="sub", filename="b.mp4", kind="video"),
                           self.target, base_url=self.base_url, resolve_dir=lambda _type: None)
        self.assertEqual(saved.read_bytes(), b"remote-artifact")
        self.assertTrue(_ViewHandler.seen[-1].startswith("/view?"), _ViewHandler.seen)
        self.assertIn("filename=b.mp4", _ViewHandler.seen[-1])

    def test_named_target_is_used_and_existing_files_are_not_overwritten(self) -> None:
        (self.source_root / "a.png").write_bytes(b"one")
        first = save_media(_media(), self.target, name="ID-001.png", resolve_dir=lambda _type: str(self.source_root))
        second = save_media(_media(), self.target, name="ID-001.png", resolve_dir=lambda _type: str(self.source_root))
        self.assertEqual(first.name, "ID-001.png")
        self.assertEqual(second.name, "ID-001_1.png")
        self.assertEqual(first.read_bytes(), b"one")

    def test_neither_local_nor_base_url_raises(self) -> None:
        with self.assertRaises(OutputFetchError):
            save_media(_media(), self.target, resolve_dir=lambda _type: None)


class SaveMediaBatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_saves_every_media_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "a.png").write_bytes(b"1")
            (root / "b.mp4").write_bytes(b"2")
            target = root / "落点"
            saved = await save_media_batch(
                [_media(), _media(filename="b.mp4", kind="video")],
                target,
                resolve_dir=lambda _type: str(root),
            )
            self.assertEqual([path.name for path in saved], ["a.png", "b.mp4"])
            self.assertEqual([path.read_bytes() for path in saved], [b"1", b"2"])


class RunResultJsonTest(unittest.TestCase):
    def _result(self) -> SkillRunResult:
        return SkillRunResult(
            prompt_id="p-1",
            media=(
                _media(),
                _media(node="6", filename="clip.mp4", subfolder="video", kind="video"),
                _media(node="12", filename="v.flac", subfolder="audio", kind="audio"),
            ),
            outputs={},
        )

    def test_splits_by_kind_and_keeps_the_images_shape(self) -> None:
        result = self._result()
        self.assertEqual([item.filename for item in result.images], ["a.png"])
        self.assertEqual([item.filename for item in result.videos], ["clip.mp4"])
        self.assertEqual([item.filename for item in result.audios], ["v.flac"])

    def test_json_carries_urls_for_every_kind(self) -> None:
        data = self._result().to_json("http://127.0.0.1:8188/")
        self.assertEqual([item["filename"] for item in data["images"]], ["a.png"])
        self.assertEqual([item["filename"] for item in data["videos"]], ["clip.mp4"])
        self.assertEqual([item["filename"] for item in data["audios"]], ["v.flac"])
        for key in ("images", "videos", "audios"):
            self.assertTrue(data[key][0]["url"].startswith("http://127.0.0.1:8188/view?"), key)

    def test_url_matches_the_view_route(self) -> None:
        url = _media(filename="a b.png", subfolder="子 目录").url("http://127.0.0.1:8188/")
        self.assertTrue(url.startswith("http://127.0.0.1:8188/view?"))
        self.assertIn("filename=a+b.png", url)
        self.assertIn("subfolder=", url)
        self.assertIn("type=output", url)


if __name__ == "__main__":
    unittest.main()
