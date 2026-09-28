"""产物的回收：从 history 条目里认出图/视频/音频，并取回来落到本地目录。

**为什么不能按键名判类型**（事实出处：``comfy_api/latest/_ui.py`` 的 ``as_dict``）：

* ``SavedImages.as_dict()`` → ``{"images": [...]}``（``SaveImage`` / ``PreviewImage``）；
* ``PreviewVideo.as_dict()`` → ``{"images": [...], "animated": (True,)}`` ——
  **``SaveVideo`` 走的就是这个，视频文件也挂在 ``images`` 键下**；
* ``SavedAudios.as_dict()`` / ``PreviewAudio.as_dict()`` → ``{"audio": [...]}``。

所以 history 里只有 ``images`` 与 ``audio`` 两个键装文件，图与视频混在 ``images`` 里。
分类只能看扩展名，判据与引擎自己的 ``folder_paths.filter_files_content_types`` 同源
（``mimetypes.guess_type`` + 扩展名缓存），不另造一张扩展名表。

取回文件有两条路，按代价排序：
1. **本机直接复制** —— 引擎与本进程同机时产物已经在磁盘上（
   ``folder_paths.get_directory_by_type(type)/subfolder/filename``），省一次 HTTP 往返；
2. ``GET {base_url}/view?...`` —— 引擎在别的机器上（HTTP 那套客户端）时只能这样拿。
第 1 条走不通才退第 2 条；两条都不通就显式报错，绝不返回空文件。
"""

from __future__ import annotations

import asyncio
import mimetypes
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

from .types import SkillOutputMedia

__all__ = [
    "DEFAULT_DOWNLOAD_TIMEOUT",
    "OutputFetchError",
    "collect_media",
    "fetch_bytes",
    "guess_kind",
    "local_path",
    "save_media",
    "save_media_async",
    "save_media_batch",
]

#: 一次 /view 下载的上限（秒）。视频动辄几百 MB，别用默认的无限等。
DEFAULT_DOWNLOAD_TIMEOUT = 120.0

#: history 条目 ``outputs[node]`` 里可能装文件的键（见模块头）。
_MEDIA_KEYS = ("images", "audio")

#: 认得的产物类别；认不出的归 ``other``（保留，不丢）。
KINDS = ("image", "video", "audio", "other")

#: 引擎自己给"mimetypes 猜不出来"的扩展名开的小灶，逐字照抄
#: ``folder_paths.py`` 的 ``extension_mimetypes_cache``（``webp`` 尤其要：
#: ``mimetypes.guess_type("a.webp")`` 在 Windows 上回空，不补这张表就会把 webp 图
#: 误判成 other。``fbx`` 是 3D 模型，走的是 ``PreviewUI3D`` 的 ``result`` 键，不会到这儿）。
_SEEDED_KINDS = {"webp": "image", "fbx": "model"}

# 扩展名 → 类别。判据同 folder_paths.filter_files_content_types：先查补丁表，
# 再用 mimetypes，都认不出就 other。缓存起来，避免逐个文件重复猜。
_mime_cache: dict[str, str] = dict(_SEEDED_KINDS)

# 目录解析器：给 type（output/temp/input）回该类型的根目录；回 None 表示定位不了。
DirResolver = Callable[[str], "str | None"]


class OutputFetchError(RuntimeError):
    """产物取不回来（本地找不到，且 /view 也拿不到）。"""


def guess_kind(filename: str) -> str:
    """按扩展名判产物类别：``image`` / ``video`` / ``audio`` / ``other``。"""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = _mime_cache.get(extension)
    if kind is None:
        mime, _encoding = mimetypes.guess_type(filename, strict=False)
        kind = mime.split("/")[0] if mime else ""
        _mime_cache[extension] = kind
    return kind if kind in KINDS else "other"


def collect_media(entry: dict[str, Any]) -> tuple[SkillOutputMedia, ...]:
    """从 history 条目的 ``outputs`` 里取出全部产物（图/视频/音频），按出现顺序。

    结构来源是上面那几个 ``as_dict``；这里只做形状校验，遇到不成形的条目跳过，
    不抛异常 —— 一个节点吐了脏数据不该让整次运行的结果收不回来。
    """
    media: list[SkillOutputMedia] = []
    for node_id, output in (entry.get("outputs") or {}).items():
        if not isinstance(output, dict):
            continue
        for key in _MEDIA_KEYS:
            for file in output.get(key) or []:
                if not isinstance(file, dict) or not file.get("filename"):
                    continue
                filename = str(file["filename"])
                media.append(
                    SkillOutputMedia(
                        node=str(node_id),
                        filename=filename,
                        subfolder=str(file.get("subfolder") or ""),
                        type=str(file.get("type") or "output"),
                        kind=guess_kind(filename),
                    )
                )
    return tuple(media)


def _engine_dir(folder_type: str) -> str | None:
    """问引擎要某类产物的根目录；不在引擎进程里就回 None（走 /view 那条路）。"""
    try:
        import folder_paths  # type: ignore[import-not-found]
    except ImportError:
        return None
    directory = folder_paths.get_directory_by_type(folder_type)  # type: ignore[no-any-return]
    return str(directory) if directory else None


def local_path(media: SkillOutputMedia, *, resolve_dir: DirResolver | None = None) -> Path | None:
    """产物在本机磁盘上的位置；定位不到（远端引擎、文件已被清）回 None。

    路径要落在该类型的根目录内：``subfolder`` 来自 history，带上 ``..`` 就能指到根外面
    （上游有同样的用例：``tests-unit/execution_test/test_enrich_output.py`` 的
    ``test_executed_path_escape_is_skipped``）。
    """
    resolver = resolve_dir or _engine_dir
    root = resolver(media.type)
    if not root:
        return None
    root_path = Path(root).resolve()
    candidate = (root_path / media.subfolder / media.filename).resolve()
    if root_path not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def fetch_bytes(
    media: SkillOutputMedia,
    base_url: str,
    *,
    timeout: float = DEFAULT_DOWNLOAD_TIMEOUT,
) -> bytes:
    """从 ``/view`` 拉一个产物的字节（同步；在事件循环里请用 :func:`save_media_async`）。"""
    request = urllib.request.Request(media.url(base_url))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - 地址由本模块拼
            return response.read()
    except (urllib.error.URLError, OSError) as err:
        raise OutputFetchError(f"下载产物失败 {media.filename}: {err}") from err


def _unique_path(target: Path) -> Path:
    """目标已存在就加 ``_1`` / ``_2`` 后缀：产物之间不该互相覆盖。"""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for index in range(1, 10_000):
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise OutputFetchError(f"落盘失败：{target} 旁边已经有 {10_000} 个同名文件")


def save_media(
    media: SkillOutputMedia,
    target_dir: str | Path,
    *,
    base_url: str | None = None,
    name: str | None = None,
    resolve_dir: DirResolver | None = None,
    timeout: float = DEFAULT_DOWNLOAD_TIMEOUT,
) -> Path:
    """把一个产物落到 ``target_dir``，返回落到的完整路径。

    ``name`` 可以指定落盘用的文件名（调用方按资产 ID 命名时用），不给就用引擎产出的原名。
    本机找得到就复制，找不到且给了 ``base_url`` 就走 ``/view`` 下载，两样都不行就报错。
    """
    directory = Path(target_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = _unique_path(directory / (name or media.filename))

    source = local_path(media, resolve_dir=resolve_dir)
    if source is not None:
        shutil.copy2(source, target)
        return target
    if not base_url:
        raise OutputFetchError(
            f"取不回产物 {media.filename}：本机没有这个文件（type={media.type}），也没给 base_url"
        )
    target.write_bytes(fetch_bytes(media, base_url, timeout=timeout))
    return target


async def save_media_async(
    media: SkillOutputMedia,
    target_dir: str | Path,
    **kwargs: Any,
) -> Path:
    """:func:`save_media` 的异步壳：复制/下载都是阻塞 IO，扔到线程里做，别卡住事件循环。"""
    return await asyncio.to_thread(save_media, media, target_dir, **kwargs)


async def save_media_batch(
    media: Iterable[SkillOutputMedia],
    target_dir: str | Path,
    **kwargs: Any,
) -> tuple[Path, ...]:
    """一批产物顺序落盘（顺序而非并发：同一次运行的产物不该争抢磁盘/带宽）。"""
    saved: list[Path] = []
    for item in media:
        saved.append(await save_media_async(item, target_dir, **kwargs))
    return tuple(saved)
