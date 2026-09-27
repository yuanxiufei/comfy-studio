"""本机文件的衔接：把本地素材接进 ComfyUI，把产出找回来，读本地的文本文件。

**为什么放在宿主进程**：这三个动作都要知道「这台机器上的 ComfyUI 装在哪」——
引擎的 `input/`、`output/` 目录是它下面的子目录（事实取自 ``ComfyUI/folder_paths.py:69-71``：
``output/temp/input`` 都拼在 ``base_path`` 上，``base_path`` 就是 ComfyUI 检出目录）。
桌面壳拉起宿主时就给了 ``--comfyui-dir``，所以只有宿主这边算得出真实路径；
引擎侧那个 MCP server 走的是 HTTP，看不见引擎的磁盘布局。

三个工具（汇进工具表后叫 ``localfiles__<tool>``）：

* ``import_file`` —— 用户的本地图片/音频/视频接进引擎的 ``input/``，返回一个可以直接
  填进 ``LoadImage.image`` / ``LoadAudio.audio`` 这类字段的名字。这是"本地素材"唯一的
  入口：ComfyUI 的加载类节点只认 ``input/`` 下的相对路径，工作流里没法直接写
  ``D:\\图片\\cat.png``。
* ``list_files`` —— 列 ``output/``（或 ``input/`` / ``temp/``）里的文件，**带本机绝对路径**。
  引擎返回的 history 只有 ``filename`` + ``subfolder``，用户问"刚生成的图存哪了"、
  或者要把这次的产出接着当下一轮的素材，都得靠它换算成盘上的真实位置。
* ``read_text`` —— 读本机文本文件（提示词、工作流 JSON、说明），有大小上限。

形状与画布 / 审核那两条通道的 client 一致（``config`` / ``start`` / ``list_tools`` /
``call_tool``），好直接汇进 :class:`~comfy_studio.mcp.McpHub`，agent 循环那边不用改。
但**它不是回程通道**：不推 ``agent/event``、不等桌面壳回话，因此和它们不同 ——
只要 ``--comfyui-dir`` 已知就挂上，不需要额外的启动开关。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cancel import CancelToken
from .mcp import McpError, McpTool

#: 汇进工具表时用的 server 名。
LOCAL_FILES_SERVER = "localfiles"

#: 三类目录名。事实来源：``ComfyUI/folder_paths.py:69-71``（base_path 下的 output/temp/input）。
DIR_KINDS: tuple[str, ...] = ("output", "input", "temp")

#: ``read_text`` 不传 max_bytes 时读多少。
DEFAULT_TEXT_BYTES = 64 * 1024
#: ``read_text`` 允许的上限：再大就不该往对话里灌了。
MAX_TEXT_BYTES = 1024 * 1024

#: ``list_files`` 默认/最多返回几条。
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 200

#: 比这个大的文件不值得为了"是不是同一份"再整读一遍，直接按不同处理（换名另存）。
MAX_HASH_BYTES = 256 * 1024 * 1024
_HASH_CHUNK = 1024 * 1024


class LocalFilesError(RuntimeError):
    """本地文件操作没干成：源文件不在、目录不在、不是文本、名字想往外跑等。"""


@dataclass(frozen=True)
class LocalFilesServerConfig:
    """与 :class:`~comfy_studio.mcp.McpServerConfig` 同形的极小配置：这里只需要名字。"""

    name: str = LOCAL_FILES_SERVER


@dataclass(frozen=True)
class _Spec:
    """一个本地文件工具：MCP 工具名 + 说明与参数表。"""

    name: str
    description: str
    input_schema: dict[str, Any]


LOCAL_FILES_TOOLS: tuple[_Spec, ...] = (
    _Spec(
        name="import_file",
        description=(
            "把用户本机的一个文件接进 ComfyUI 的 input 目录，让工作流能用它（当参考图、"
            "ControlNet 输入、音视频素材等）。ComfyUI 的加载类节点只认 input 目录下的相对"
            "路径，所以用户说“用 D:\\图片\\cat.png 当参考图”时，先调它拿到 value，"
            "再把 value 填进对应节点的输入字段（例如 LoadImage 的 image）。"
            "返回 reused=true 表示 input 里已有一份内容相同的文件，没有重复拷贝。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "本机文件的绝对路径（用户给你的那个）",
                },
                "name": {
                    "type": "string",
                    "description": "可选：接进来之后叫什么名字；默认用源文件的文件名",
                },
                "subfolder": {
                    "type": "string",
                    "description": "可选：放进 input 下的子目录（相对路径，如 refs/2026）",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "同名时是否覆盖，默认 false（false 时会自动改名避开）",
                },
            },
            "required": ["path"],
        },
    ),
    _Spec(
        name="list_files",
        description=(
            "列 ComfyUI 本机目录里的文件，返回**绝对路径**、大小与修改时间（最近的在前）。"
            "用途：① 回答“刚才生成的图存哪了”；② 把这次的产出接着当下一轮素材"
            "（type=input 时可 import 的源就在 output 里）；③ 核对某个文件名是否真的存在，"
            "别凭引擎返回的 filename 猜路径。name 给文件名或路径片段就只回匹配的。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": list(DIR_KINDS),
                    "description": "看哪个目录：output（产出，默认）/ input（素材）/ temp（临时）",
                },
                "name": {
                    "type": "string",
                    "description": "可选：只列匹配这个名字的（完整相对路径、文件名或片段，忽略大小写）",
                },
                "limit": {
                    "type": "integer",
                    "description": f"最多返回几条，默认 {DEFAULT_LIST_LIMIT}（上限 {MAX_LIST_LIMIT}）",
                },
            },
        },
    ),
    _Spec(
        name="read_text",
        description=(
            "读用户本机的一个文本文件（提示词、工作流 JSON、参数说明），有大小上限，"
            "超出上限的内容会被截断并标出 truncated=true。二进制素材（图片/音视频）不要用它，"
            "那是 import_file 的事——读出来是一堆乱码。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "本机文本文件的绝对路径"},
                "max_bytes": {
                    "type": "integer",
                    "description": f"最多读多少字节，默认 {DEFAULT_TEXT_BYTES}（上限 {MAX_TEXT_BYTES}）",
                },
            },
            "required": ["path"],
        },
    ),
)


def is_within(root: Path, candidate: Path) -> bool:
    """``candidate`` 落在 ``root`` 之内吗？

    对外的名字：本模块和 :mod:`comfy_studio.novels` 都要用同一套越界检查，
    这种守卫各写一份迟早会有一份被改松。

    抄 ``ComfyUI/folder_paths.py:326-340`` 的 ``is_within_directory``：两边都过 realpath，
    这样 root 里放一个指向别处的符号链接也逃不出去；不同盘符（Windows）会抛
    ValueError，那种情况一律算"不在里面"。
    """
    try:
        real_root = os.path.realpath(root)
        real_target = os.path.realpath(candidate)
        return os.path.commonpath((real_root, real_target)) == real_root
    except ValueError:
        return False


def _digest(path: Path) -> str | None:
    """分块算 sha256；文件大到不值得再读一遍时返回 None。"""
    try:
        if path.stat().st_size > MAX_HASH_BYTES:
            return None
    except OSError:
        return None
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _as_int(raw: Any, default: int, *, where: str, low: int = 1, high: int) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise LocalFilesError(f"{where} 必须是整数，实际是 {type(raw).__name__}")
    if raw < low or raw > high:
        raise LocalFilesError(f"{where} 要在 {low}~{high} 之间，给的是 {raw}")
    return raw


def _as_str(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or raw.strip() == "":
        raise LocalFilesError(f"{where} 必须是非空字符串")
    return raw.strip()


def _as_bool(raw: Any, default: bool, *, where: str) -> bool:
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise LocalFilesError(f"{where} 必须是布尔值")
    return raw


class LocalFiles:
    """本机文件操作。目录一律由调用方（桌面壳 / ``--input-dir``）给出，代码里不写死盘符。"""

    def __init__(
        self,
        comfyui_dir: str | os.PathLike[str],
        input_dir: str | os.PathLike[str] | None = None,
        output_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.comfyui_dir = Path(comfyui_dir).resolve()
        # 默认布局就是 ComfyUI 检出目录下的 input/output；引擎用 --input-directory /
        # --output-directory 改过的话，调用方得把对应的目录显式传进来。
        self.input_dir = Path(input_dir).resolve() if input_dir else self.comfyui_dir / "input"
        self.output_dir = Path(output_dir).resolve() if output_dir else self.comfyui_dir / "output"
        self.temp_dir = self.comfyui_dir / "temp"

    # ---- 目录 -----------------------------------------------------------

    def directory(self, kind: str) -> Path:
        if kind not in DIR_KINDS:
            raise LocalFilesError(f"未知目录类型 {kind}；可选: {', '.join(DIR_KINDS)}")
        return {"output": self.output_dir, "input": self.input_dir, "temp": self.temp_dir}[kind]

    # ---- import_file ----------------------------------------------------

    def import_file(
        self,
        path: str,
        name: str | None = None,
        subfolder: str = "",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """把一个本地文件拷进 ``input/``，返回能填进工作流的名字。"""
        source = Path(path).expanduser()
        if not source.exists():
            raise LocalFilesError(f"本地文件不存在: {source}")
        if not source.is_file():
            raise LocalFilesError(f"这是个目录，不是文件: {source}")
        real = Path(os.path.realpath(source))
        if not real.is_file():
            raise LocalFilesError(f"跟随链接之后仍然不是文件: {source} -> {real}")

        target_name = name if name else real.name
        if Path(target_name).name != target_name:
            raise LocalFilesError(f"name 只能是文件名，不能带路径: {target_name}")

        dest_dir = self._subdir(subfolder)
        # 上游上传图片时也是先建目录再写（``ComfyUI/server.py:417-418``）。
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / target_name
        if not is_within(self.input_dir, dest):
            raise LocalFilesError(f"目标路径跑到 input 目录外面了: {dest}")

        reused = False
        if dest.exists():
            if overwrite:
                pass
            else:
                source_hash = _digest(real)
                if source_hash is not None and source_hash == _digest(dest):
                    # 同一份素材重复接入：别再堆一份，直接把已有的那份告诉他。
                    reused = True
                else:
                    stem, suffix = os.path.splitext(target_name)
                    index = 1
                    while dest.exists():
                        # 命名规则与上游一致：``name (1).ext``（``ComfyUI/server.py:420-432``）。
                        target_name = f"{stem} ({index}){suffix}"
                        dest = dest_dir / target_name
                        index += 1

        if not reused:
            shutil.copy2(real, dest)

        value = f"{subfolder.strip('/')}/{target_name}" if subfolder.strip("/") else target_name
        return {
            "value": value,
            "name": target_name,
            "subfolder": subfolder.strip("/"),
            "type": "input",
            "path": str(dest),
            "bytes": dest.stat().st_size,
            "source": str(real),
            "reused": reused,
        }

    def _subdir(self, subfolder: str) -> Path:
        rel = subfolder.strip().replace("\\", "/").strip("/")
        target = self.input_dir if rel == "" else self.input_dir / rel
        if not is_within(self.input_dir, target):
            raise LocalFilesError(f"subfolder 跑到 input 目录外面了: {subfolder}")
        return target

    # ---- list_files -----------------------------------------------------

    def list_files(self, kind: str = "output", name: str | None = None, limit: int | None = None) -> dict[str, Any]:
        """列某个目录下的文件（最近的在前），带本机绝对路径。"""
        directory = self.directory(kind)
        if not directory.is_dir():
            # 不返回空列表：目录还没建出来和"目录里没有文件"是两件事，
            # 混在一起会让"产出在哪"的答案看起来像"什么都没生成"。
            raise LocalFilesError(
                f"{kind} 目录还不存在: {directory}（引擎还没跑过？或用 --{kind}-directory 换过位置）"
            )
        cap = _as_int(limit, DEFAULT_LIST_LIMIT, where="limit", high=MAX_LIST_LIMIT)
        needle = name.strip().lower() if isinstance(name, str) and name.strip() else None

        found: list[dict[str, Any]] = []
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(directory).as_posix()
            if needle is not None and needle not in rel.lower():
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            found.append(
                {
                    "name": path.name,
                    "subfolder": path.parent.relative_to(directory).as_posix()
                    if path.parent != directory
                    else "",
                    "path": str(path),
                    "bytes": info.st_size,
                    "mtime": info.st_mtime,
                }
            )
        found.sort(key=lambda item: item["mtime"], reverse=True)
        return {
            "type": kind,
            "dir": str(directory),
            "matched": len(found),
            "returned": min(len(found), cap),
            "files": found[:cap],
        }

    # ---- read_text ------------------------------------------------------

    def read_text(self, path: str, max_bytes: int | None = None) -> dict[str, Any]:
        """读一个文本文件（UTF-8，允许带 BOM），超出上限的部分截断并如实标出。"""
        limit = _as_int(max_bytes, DEFAULT_TEXT_BYTES, where="max_bytes", high=MAX_TEXT_BYTES)
        target = Path(path).expanduser()
        if not target.exists():
            raise LocalFilesError(f"本地文件不存在: {target}")
        if not target.is_file():
            raise LocalFilesError(f"这是个目录，不是文件: {target}")
        with target.open("rb") as handle:
            raw = handle.read(limit + 1)
        truncated = len(raw) > limit
        raw = raw[:limit]
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as err:
            raise LocalFilesError(
                f"不是 UTF-8 文本文件（{target}，位置 {err.start}）："
                "二进制素材请用 import_file 接进引擎，别用 read_text"
            ) from err
        return {
            "path": str(target),
            "bytes": target.stat().st_size,
            "read_bytes": len(raw),
            "truncated": truncated,
            "text": text,
        }


def _validate(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """参数在本地先挡一道：模型给的形状不对就别去动文件。"""
    if name == "import_file":
        out = {
            "path": _as_str(args.get("path"), "path"),
            "name": args.get("name"),
            "subfolder": args.get("subfolder") or "",
            "overwrite": _as_bool(args.get("overwrite"), False, where="overwrite"),
        }
        if out["name"] is not None:
            out["name"] = _as_str(out["name"], "name")
        if not isinstance(out["subfolder"], str):
            raise LocalFilesError("subfolder 必须是字符串")
        return out
    if name == "list_files":
        kind = args.get("type") or "output"
        if not isinstance(kind, str) or kind not in DIR_KINDS:
            raise LocalFilesError(f"type 必须是 {' / '.join(DIR_KINDS)} 之一")
        name_arg = args.get("name")
        if name_arg is not None and not isinstance(name_arg, str):
            raise LocalFilesError("name 必须是字符串")
        return {"kind": kind, "name": name_arg, "limit": args.get("limit")}
    if name == "read_text":
        return {"path": _as_str(args.get("path"), "path"), "max_bytes": args.get("max_bytes")}
    raise McpError(f"本地文件工具里没有 {name}")


class LocalFilesClient:
    """鸭子型 MCP client：形状与 :class:`~comfy_studio.mcp.client.McpStdioClient` 一致，
    好直接汇进 :class:`~comfy_studio.mcp.McpHub` 的工具表。
    """

    def __init__(
        self,
        files: LocalFiles,
        config: LocalFilesServerConfig | None = None,
    ) -> None:
        self.files = files
        self.config = config if config is not None else LocalFilesServerConfig()

    @property
    def alive(self) -> bool:
        return True

    def stderr_tail(self) -> str:
        return ""

    async def start(self) -> None:
        """没有子进程要拉：这张工具表一直都在。"""

    async def close(self) -> None:
        """没有连接要关。"""

    async def list_tools(self) -> list[McpTool]:
        return [
            McpTool(
                server=self.config.name,
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
            )
            for spec in LOCAL_FILES_TOOLS
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel: CancelToken | None = None
    ) -> dict[str, Any]:
        """跑一个本地文件动作。

        ``cancel`` 收下但不用：这几个动作都是**一次本地读写**，没有可中断的长等待
        （拷贝大文件也就几秒），不像引擎那边跑一张图要几分钟。
        """
        if name == "import_file":
            call = self.files.import_file
        elif name == "list_files":
            call = self.files.list_files
        elif name == "read_text":
            call = self.files.read_text
        else:
            known = ", ".join(spec.name for spec in LOCAL_FILES_TOOLS)
            raise McpError(f"本地文件工具表里没有 {name}；可用: {known}")
        try:
            result = call(**_validate(name, dict(arguments or {})))
        except LocalFilesError as err:
            # 工具没干成不算协议错误：回 isError 让模型看到原因并自己改（与画布/审核一致）。
            return {"content": [{"type": "text", "text": str(err)}], "isError": True}
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
            "isError": False,
        }


__all__ = [
    "DEFAULT_LIST_LIMIT",
    "DEFAULT_TEXT_BYTES",
    "DIR_KINDS",
    "LOCAL_FILES_SERVER",
    "LOCAL_FILES_TOOLS",
    "LocalFiles",
    "LocalFilesClient",
    "LocalFilesError",
    "LocalFilesServerConfig",
    "MAX_LIST_LIMIT",
    "MAX_TEXT_BYTES",
    "is_within",
]
