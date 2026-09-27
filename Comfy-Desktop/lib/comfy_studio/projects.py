"""「项目管理」这一页的后端：一剧一目录（manju 那套落点）在面板上的读写。

为什么要有这个模块
------------------
漫剧那条链路的前半段是**资料活**：剧本、角色设定、分镜、对白、素材归档各占一格，
落点是 ``manju/projects/<剧名>/``。规则写在 AI漫剧智能体工作流 的
``08-项目管理/项目目录规范.md``，代码侧的**唯一事实源**是同一工作流里
``07-智能体运行时/src/project.py`` 的 ``PROJECT_DIRS``。

那这里为什么不抄一份落点清单
----------------------------
抄一份的下场不是报错，是**两边悄悄分家**：规范里加了 ``11_AUDIO/``，
面板这份还是老清单，少掉的那一格要么显示成"缺"，要么干脆不出现，
而两处谁都不报错。所以本模块用 :func:`load_spec` 把那份 ``project.py``
**原样载入**来用（它只 import os/re/datetime，能独立载入）：落点、种子空表、
阶段判据、建项目、体检全都是**它的**代码。这里只做三件事：

① 把结果摆成面板要的形状（按"围绕剧本"的顺序分组，见 :data:`PROJECT_SHELVES`）；
② 加一道越界守卫与编码判定 —— 越界复用 :func:`comfy_studio.localfiles.is_within`，
   编码复用 :func:`comfy_studio.novels.decode_text`（同一台机器上剧本与原文往往
   出自同一个编辑器，两处各判一套只会出现"原文读得开、剧本读成乱码"）；
③ 建完项目后把"这一部改的是哪本原著"登记进 ``素材来源登记.md``（:meth:`ProjectLibrary.link_novel`）。

面板的四个动作 → 四个方法
--------------------------
:meth:`ProjectLibrary.list` / :meth:`tree` / :meth:`read` / :meth:`create`；
另加 :meth:`brief`：把一部剧的现状写成一段能塞进对话输入框的话（与对话系统的联动）。
建项目一律**只补不覆盖**（那份 ``create_project`` 的既定行为，这里不另立规矩）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cancel import CancelToken
from .localfiles import is_within
from .mcp import McpError, McpTool
from .novels import MANJU_REL, MAX_TEXT_BYTES, NovelsError, decode_text

#: 项目根落在 manju/ 下的哪一级（与 ``manju/novel/`` 同级）。
PROJECT_SUBDIR = "projects"

#: 工作流目录名。项目根与它**同父**（``manju/{AI漫剧智能体工作流,novel,projects}``）。
WORKFLOW_DIRNAME = "AI漫剧智能体工作流"

#: 事实源：工作流里那份 ``project.py``（``PROJECT_DIRS`` 所在处）。
SPEC_REL = Path(WORKFLOW_DIRNAME) / "07-智能体运行时" / "src" / "project.py"

#: 面板里能点开读的后缀。剧本/设定/台账/分镜表都是这些；音视频与图片不在这条通道上 ——
#: 面板不做播放器，读了也只能给出一堆乱码，"能点但没用"的按钮比没有更糟。
PROJECT_SUFFIXES = (".md", ".txt", ".json", ".csv", ".yaml", ".yml")

#: 一页多少字。与原文那一页**同口径**（``novels.DEFAULT_READ_CHARS``），
#: 免得"读剧本一屏比读原文少一半"这种没人说得清的区别。
DEFAULT_READ_CHARS = 4000
MAX_READ_CHARS = 40000

#: :meth:`ProjectLibrary.list` 一次最多列几部剧。
DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 1000

#: 一集默认几集（建项目那一步要填进模板占位符）。
DEFAULT_EPISODES = 12

#: 面板每一格最多列几个文件（再多就只报个数；面板不是文件管理器）。
MAX_TREE_FILES = 60

#: 登记原著时最多读多少字节的登记表（它是一张表，不是正文）。
REGISTRY_READ_BYTES = 256 * 1024


class ProjectsError(RuntimeError):
    """项目这一页的动作没干成：项目根不在、规范载不上、名字想往外跑、文件读不了。"""


# ─────────────────────────────────────────────────────────────
# 面板的分格：只排顺序与标题，落点本身仍然只来自 ``spec.PROJECT_DIRS``
# ─────────────────────────────────────────────────────────────

#: 「一剧的资料」在面板上按**围绕剧本**的顺序分成几格：剧本在最前，素材归档在后，
#: 演出相关的（世界观 / 角色 / 场景 / 分镜）在中间。
#:
#: ⚠️ 这里的字符串**必须**是 ``spec.PROJECT_DIRS`` 里的落点。规范改了落点而这里没跟上，
#: :func:`shelf_gaps` 会报出来（而不是悄悄少显示一格）；单测对真清单钉住它为空。
PROJECT_SHELVES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("script", "剧本", ("00_PROJECT/01_剧本",)),
    ("dialogue", "对白与配音", ("00_PROJECT/06_对白",)),
    ("index", "资产索引与台账", ("00_PROJECT/02_资产索引", "00_PROJECT/03_台账")),
    ("flow", "流程与进度", ("00_PROJECT/05_流程",)),
    ("delivery", "交付与出图", ("00_PROJECT/04_交付与出图",)),
    ("archive", "素材归档", ("00_PROJECT/07_素材归档",)),
    ("world", "世界观", ("01_WORLD",)),
    ("cast", "角色 · 服装 · 道具", ("02_CHARACTERS", "03_COSTUMES", "04_PROPS")),
    ("scene", "场景 · 表情 · 姿态", ("05_ENVIRONMENTS", "06_EXPRESSIONS", "07_POSES")),
    ("board", "分镜与镜头", ("08_STORYBOARDS", "09_SHOTS")),
    ("check", "一致性与音频", ("10_CONSISTENCY", "11_AUDIO")),
)

#: ``素材来源登记.md`` 里那一行的名字（:meth:`ProjectLibrary.link_novel` 只碰它）。
NOVEL_ROW = "原著名"

#: 种子模板里"还没填"的占位符（与 manju 那份 ``project.py`` 同一个记号）。
PLACEHOLDER = "（待填）"

#: ``素材来源登记.md`` 里记原著那一行的**第二格**（:meth:`ProjectLibrary.link_novel` 只改它）。
#: 只认第二格、行的其余部分原样留着 —— 那张表还有别的列，整行重写等于把别人的记录擦了。
_NOVEL_ROW_RE = re.compile(r"^([ \t]*\|[ \t]*" + NOVEL_ROW + r"[ \t]*\|)([^|]*)(\|.*)$", re.M)


def shelf_gaps(dirs: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """哪些落点**没被面板归到任何一格**。

    规范加了落点、面板忘了加格 —— 这里报出来，而不是让它悄悄不出现在界面上。
    """
    claimed = {rel for _key, _title, rels in PROJECT_SHELVES for rel in rels}
    return tuple(rel for rel in dirs if rel not in claimed)


def shelf_unknown(dirs: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """面板格子里写了、规范里**已经没有**的落点（规范删了，面板还留着）。"""
    known = set(dirs)
    strays = {rel for _key, _title, rels in PROJECT_SHELVES for rel in rels if rel not in known}
    return tuple(sorted(strays))


# ─────────────────────────────────────────────────────────────
# 定位：目录与事实源都不写死机器路径
# ─────────────────────────────────────────────────────────────

def default_project_dir(comfyui_dir: str | os.PathLike[str]) -> Path:
    """默认项目根：``<comfyui-dir>/custom_nodes/comfy_studio/manju/projects``。

    与 :func:`comfy_studio.novels.default_novel_dir` 同一个父目录 —— 原文与项目是
    同一部剧的两头，摆在一起才知道谁是谁的。
    """
    return Path(comfyui_dir).expanduser().resolve() / MANJU_REL / PROJECT_SUBDIR


def default_spec_path(project_dir: str | os.PathLike[str]) -> Path:
    """默认的事实源路径：项目根的**同级**目录里那份 ``project.py``。

    实测布局 ``<ComfyUI>/custom_nodes/comfy_studio/manju/{AI漫剧智能体工作流,novel,projects}``：
    项目根与工作流同父，所以从项目根往上退一级就能找到它 —— 既不必知道 ComfyUI 装在哪，
    也不必写死盘符。找不到时由 :func:`load_spec` 明确报错（不静默降级成"没有落点清单"）。
    """
    return Path(project_dir).expanduser().resolve().parent / SPEC_REL


def load_spec(path: str | os.PathLike[str]) -> Any:
    """把 manju 那份 ``src/project.py`` 当模块载入，回模块对象。

    ``PROJECT_DIRS`` 这类清单一旦在本模块里再抄一份，两边迟早分家，而且**分家不报错**
    （详见模块开头）。那份文件只 import os/re/datetime、没有包内相对导入，
    所以用 ``importlib`` 从一个路径直接执行是安全的。
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise ProjectsError(
            f"找不到项目规范的事实源：{target}\n"
            "它随仓库一起在（AI漫剧智能体工作流/07-智能体运行时/src/project.py）。"
            "开发时用 --comfyui-dir 指到你的 ComfyUI 检出上，或用 --project-dir 直接给项目根。"
        )
    spec = importlib.util.spec_from_file_location("comfy_studio_manju_project_spec", target)
    if spec is None or spec.loader is None:
        raise ProjectsError(f"载入不了 {target}：它不像一个 Python 源文件")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as err:  # 载入期什么都可能抛：原文带出去，别吞成"没有落点"
        raise ProjectsError(f"载入 {target} 失败：{type(err).__name__}: {err}") from err
    missing = [
        attr
        for attr in ("PROJECT_DIRS", "SEED_FILES", "create_project", "scan_project")
        if not hasattr(module, attr)
    ]
    if missing:
        raise ProjectsError(
            f"{target} 里没有 {'、'.join(missing)}：那份规范的接口变了，先同步 projects.py 的用法"
        )
    return module


# ─────────────────────────────────────────────────────────────
# 小工具：参数挡一道 + 数文件
# ─────────────────────────────────────────────────────────────

def _as_int(raw: Any, default: int, *, where: str, low: int = 1, high: int) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ProjectsError(f"{where} 必须是整数，实际是 {type(raw).__name__}")
    if raw < low or raw > high:
        raise ProjectsError(f"{where} 要在 {low}~{high} 之间，给的是 {raw}")
    return raw


def _as_bool(raw: Any, default: bool, *, where: str) -> bool:
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise ProjectsError(f"{where} 必须是布尔值")
    return raw


def _as_name(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or raw.strip() == "":
        raise ProjectsError(f"{where} 必须是非空字符串")
    return raw.strip()


def _rel_path(root: Path, path: Path) -> str:
    """项目内相对路径，一律用 ``/``（面板那边不认 Windows 的反斜杠）。"""
    return os.path.relpath(str(path), str(root)).replace(os.sep, "/")


def _count_files(root: Path) -> int:
    """项目里有多少个真文件（``.gitkeep`` 不算 —— 那是空目录的占位，不是资料）。"""
    total = 0
    for _dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        total += sum(1 for name in filenames if name != ".gitkeep")
    return total


def _list_files(root: Path, *, base: Path | None = None, deep: bool = True) -> list[dict[str, Any]]:
    """目录下的文件（按相对路径排），给面板点开用。``deep=False`` 只看这一层。

    ``base`` 是相对路径的起点，默认就是 ``root`` 自己。项目里一律传**项目根**：
    面板是拿着这里给的 ``rel`` 回来 :meth:`ProjectLibrary.read` 的，
    那个路径必须是项目内的完整相对路径，不是"相对这一格"。
    """
    if not root.is_dir():
        return []
    origin = base if base is not None else root
    out: list[dict[str, Any]] = []
    if deep:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(filenames):
                if name == ".gitkeep":
                    continue
                out.append(_file_row(origin, Path(dirpath) / name))
    else:
        for name in sorted(os.listdir(root)):
            if name == ".gitkeep":
                continue
            full = root / name
            if full.is_file():
                out.append(_file_row(origin, full))
    return sorted(out, key=lambda row: row["rel"])


def _file_row(base: Path, path: Path) -> dict[str, Any]:
    """一个文件的几个事实（相对路径 / 字节 / 改动时间）。读不到大小就报 0，不编。"""
    try:
        stat = path.stat()
        size, mtime = stat.st_size, stat.st_mtime
    except OSError:
        size, mtime = 0, 0.0
    rel = _rel_path(base, path)
    return {
        "rel": rel,
        "name": path.name,
        "bytes": size,
        "mtime": mtime,
        "readable": path.suffix.lower() in PROJECT_SUFFIXES,
    }


def _latest_mtime(root: Path) -> float:
    """项目里最近一次改动（0 表示查不到）。"""
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames + ["."]:
            if name == ".gitkeep":
                continue
            try:
                newest = max(newest, os.stat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                continue
    return newest


# ─────────────────────────────────────────────────────────────
# 一、项目根上的五个动作
# ─────────────────────────────────────────────────────────────

class ProjectLibrary:
    """项目根（一剧一目录）上的动作。

    目录与事实源都由调用方给（``--project-dir`` / ``--comfyui-dir``），这里不猜机器布局；
    落点清单、建项目、体检一律走 :func:`load_spec` 载入的那份 ``project.py``。
    """

    def __init__(
        self,
        directory: str | os.PathLike[str],
        spec_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.directory = Path(directory).expanduser().resolve()
        self.spec_path = (
            Path(spec_path).expanduser().resolve() if spec_path else default_spec_path(self.directory)
        )
        #: 事实源模块（懒载入一次，见 :meth:`spec`）；载不上就把原因留在 ``_spec_error``。
        self._spec: Any = None
        self._spec_error = ""

    # ---- 事实源 ---------------------------------------------------------

    def spec(self) -> Any:
        """那份 ``project.py``；载不上抛 :class:`ProjectsError`（带上原文与修法）。"""
        if self._spec is None and not self._spec_error:
            try:
                self._spec = load_spec(self.spec_path)
            except ProjectsError as err:
                self._spec_error = str(err)
        if self._spec is None:
            raise ProjectsError(self._spec_error)
        return self._spec

    def status(self) -> dict[str, Any]:
        """自我说明：项目根在不在、事实源载没载上、面板格与规范对不对得上。

        这个方法的**唯一职责**是让"面板坏了"有据可查：载不上事实源时它**不抛**，
        而是把原文放进 ``spec_error`` —— ``host/info`` 与面板都要读它。
        """
        out: dict[str, Any] = {
            "dir": str(self.directory),
            "exists": self.directory.is_dir(),
            "spec": str(self.spec_path),
            "spec_ok": False,
            "spec_error": "",
            "dirs": 0,
            "seeds": 0,
            "projects": 0,
            "gaps": [],
            "unknown": [],
        }
        if self.directory.is_dir():
            out["projects"] = sum(
                1
                for entry in os.scandir(self.directory)
                if entry.is_dir() and not entry.name.startswith(".")
            )
        try:
            spec = self.spec()
        except ProjectsError as err:
            out["spec_error"] = str(err)
            return out
        dirs = tuple(spec.PROJECT_DIRS)
        out["spec_ok"] = True
        out["dirs"] = len(dirs)
        out["seeds"] = len(spec.SEED_FILES)
        out["gaps"] = list(shelf_gaps(dirs))
        out["unknown"] = list(shelf_unknown(dirs))
        return out

    # ---- 名字 → 目录 -----------------------------------------------------

    def _path(self, name: Any, *, must_exist: bool = True) -> Path:
        """项目名对应的目录。名字不许往外跑（``..`` / 绝对路径 / 带分隔符一律拒）。"""
        raw = _as_name(name, "项目名")
        if raw != os.path.basename(raw) or raw in (".", ".."):
            raise ProjectsError(f"项目名只能是目录名，不带路径：{name!r}")
        target = self.directory / raw
        if not is_within(self.directory, target):
            raise ProjectsError(f"项目名跑到项目根外面去了：{name!r}")
        if must_exist and not target.is_dir():
            raise ProjectsError(f"没有这个项目：{raw}（项目根 {self.directory}）")
        return target

    # ---- 体检 -----------------------------------------------------------

    def _summary(self, path: Path, spec: Any) -> dict[str, Any]:
        """一部剧的现状（列表与详情共用）。阶段判据整个交给 ``spec.scan_project``。"""
        res = spec.scan_project(str(path))
        stages = []
        done = 0
        for label, rel, hits in res["stages"]:
            if hits:
                done += 1
            stages.append(
                {
                    "label": label,
                    "rel": rel,
                    "files": len(hits),
                    "done": bool(hits),
                    "sample": [_rel_path(path, Path(hit)) for hit in hits[:3]],
                }
            )
        return {
            "name": path.name,
            "path": str(path),
            "files": _count_files(path),
            "missing": list(res["missing"]),
            "missing_count": len(res["missing"]),
            "stages": stages,
            "stages_done": done,
            "stages_total": len(stages),
            "mtime": _latest_mtime(path),
        }

    def list(self, name: Any = None, limit: Any = None) -> dict[str, Any]:
        """项目根下有哪些剧、各自到什么程度。

        ``exists: false`` **不是错误**（这份检出还没建过项目）：面板照这个说人话，
        而不是弹一个"读取失败"。``name`` 是子串过滤（找一部剧时不用滚列表）。
        """
        cap = _as_int(limit, DEFAULT_LIST_LIMIT, where="limit", low=1, high=MAX_LIST_LIMIT)
        query = name.strip() if isinstance(name, str) else ""
        out: dict[str, Any] = {
            "dir": str(self.directory),
            "exists": self.directory.is_dir(),
            "query": query,
            "matched": 0,
            "returned": 0,
            "truncated": False,
            "limit": cap,
            "projects": [],
        }
        if not out["exists"]:
            return out
        spec = self.spec()  # 载不上就抛：面板会把 status() 里的原文一并显示出来
        rows = []
        for entry in sorted(os.scandir(self.directory), key=lambda e: e.name):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if query and query.lower() not in entry.name.lower():
                continue
            rows.append(self._summary(Path(entry.path), spec))
        out["matched"] = len(rows)
        rows.sort(key=lambda row: (-row["mtime"], row["name"]))
        out["projects"] = rows[:cap]
        out["returned"] = len(out["projects"])
        out["truncated"] = out["matched"] > out["returned"]
        return out

    # ---- 一部剧的落点 ---------------------------------------------------

    def tree(self, name: Any) -> dict[str, Any]:
        """一部剧的落点，按**围绕剧本**的顺序分组（面板右侧那一屏就照它画）。

        分组只是"摆法"（:data:`PROJECT_SHELVES`），目录本身仍然逐项对着
        ``spec.PROJECT_DIRS`` 查 —— 规范里加了落点而面板没加格，
        ``gaps`` 会如实带出来，不会悄悄少一格。
        """
        spec = self.spec()
        root = self._path(name)
        buckets: dict[str, dict[str, Any]] = {}
        for rel in spec.PROJECT_DIRS:
            full = root / Path(rel)
            listed = _list_files(full, base=root) if full.is_dir() else []
            buckets[rel] = {
                "rel": rel,
                "exists": full.is_dir(),
                "count": len(listed),
                "truncated": len(listed) > MAX_TREE_FILES,
                "files": listed[:MAX_TREE_FILES],
            }
        shelves = []
        for key, title, rels in PROJECT_SHELVES:
            items = [buckets[rel] for rel in rels if rel in buckets]
            shelves.append(
                {
                    "key": key,
                    "title": title,
                    "dirs": items,
                    "exists": any(item["exists"] for item in items),
                    "count": sum(item["count"] for item in items),
                }
            )
        root_files = _list_files(root, deep=False)
        shelves.append(
            {
                "key": "root",
                "title": "项目根",
                "dirs": [],
                "exists": True,
                "count": len(root_files),
                "files": root_files,
            }
        )
        return {
            "name": root.name,
            "path": str(root),
            "dirs": list(spec.PROJECT_DIRS),
            "gaps": list(shelf_gaps(spec.PROJECT_DIRS)),
            "unknown": list(shelf_unknown(spec.PROJECT_DIRS)),
            "shelves": shelves,
            "summary": self._summary(root, spec),
            "novel": self.linked_novel(root),
        }

    # ---- 读一份资料 -----------------------------------------------------

    def read(self, name: Any, rel: Any, offset: Any = None, chars: Any = None) -> dict[str, Any]:
        """读项目里的一份文本（面板点开一格里的文件）。

        编码走原文那套判定（:func:`comfy_studio.novels.decode_text`）：判不出来就明确报错，
        不把一屏乱码当剧本交出去。**只读不写** —— 面板是"看与调用"的入口，
        改剧本请在编辑器里改，避免两处同时改一份文件。

        行尾统一按 ``\\n`` 算（Windows 编辑器写下的 ``\\r\\n`` 归一）。``offset`` / ``chars`` /
        ``total_chars`` 都是**归一之后**的位置：面板照这个翻页，两边口径得一致 ——
        把 ``\\r`` 一起交给面板，页上会多出一堆看不见的字符，翻页也会对不上。
        """
        root = self._path(name)
        rel_text = _as_name(rel, "文件相对路径").replace("\\", "/").lstrip("/")
        target = root / Path(rel_text)
        if not is_within(root, target):
            raise ProjectsError(f"路径跑到项目外面去了：{rel_text!r}")
        if not target.is_file():
            raise ProjectsError(f"项目里没有这个文件：{rel_text}")
        suffix = target.suffix.lower()
        if suffix not in PROJECT_SUFFIXES:
            raise ProjectsError(
                f"这一类文件不在这里读：{rel_text}（只有 {'、'.join(PROJECT_SUFFIXES)} 是文本资料）"
            )
        size = target.stat().st_size
        if size > MAX_TEXT_BYTES:
            raise ProjectsError(f"{rel_text} 有 {size} 字节，超过 {MAX_TEXT_BYTES}：太大，不整读")
        try:
            text, encoding = decode_text(target.read_bytes(), rel_text)
        except NovelsError as err:
            raise ProjectsError(str(err)) from err
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        total = len(text)
        start = _as_int(offset, 0, where="offset", low=0, high=max(0, total))
        want = _as_int(chars, DEFAULT_READ_CHARS, where="chars", low=1, high=MAX_READ_CHARS)
        piece = text[start : start + want]
        return {
            "name": root.name,
            "rel": rel_text,
            "path": str(target),
            "encoding": encoding,
            "bytes": size,
            "total_chars": total,
            "offset": start,
            "requested_chars": want,
            "chars": len(piece),
            "truncated": start + len(piece) < total,
            "text": piece,
        }

    # ---- 与原文（小说库）的联动 -----------------------------------------

    def linked_novel(self, root: Path) -> str:
        """这一部登记的原著（没登记/还空着/没有那张表都回空串 —— 那不是错误）。"""
        registry = root / "00_PROJECT/07_素材归档/素材来源登记.md"
        try:
            with registry.open(encoding="utf-8") as handle:
                body = handle.read(REGISTRY_READ_BYTES)
        except (OSError, UnicodeDecodeError):
            return ""
        found = _NOVEL_ROW_RE.search(body)
        if found is None:
            return ""
        value = found.group(2).strip().strip("`*").strip()
        return "" if PLACEHOLDER in value else value

    def link_novel(
        self,
        name: Any,
        novel_name: Any,
        novel_dir: str | os.PathLike[str] | None = None,
    ) -> dict[str, Any]:
        """把"这一部改的是哪本原著"登记进 ``素材来源登记.md``。

        只做一件事，且**不覆盖已填内容**：那一行还空着（或还是模板占位符）就填上原著文件名；
        已经填过就原样留着，回 ``reason: "already"`` 与现值。理由：这张表是**来源记录**，
        悄悄改掉别人填的来源，比少记一笔糟得多。

        ``novel_dir`` 给了就先确认库里真有这本书 —— 登记一个不存在的来源等于留一条假账。
        """
        root = self._path(name)
        novel = _as_name(novel_name, "原著文件名")
        if novel != os.path.basename(novel) or novel in (".", ".."):
            raise ProjectsError(f"原著只写文件名，不带路径：{novel_name!r}")
        out: dict[str, Any] = {
            "name": root.name,
            "novel": novel,
            "file": "",
            "linked": False,
            "already": False,
            "current": "",
            "reason": "",
        }
        if novel_dir is not None:
            shelf = Path(novel_dir).expanduser().resolve()
            if not (shelf / novel).is_file():
                out["reason"] = "missing_novel"  # 库里没有这本：不登记
                return out
        registry = root / "00_PROJECT/07_素材归档/素材来源登记.md"
        out["file"] = str(registry)
        if not registry.is_file():
            out["reason"] = "no_registry"
            return out
        try:
            body = registry.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as err:
            raise ProjectsError(f"读不了 {registry}：{err}") from err
        found = _NOVEL_ROW_RE.search(body)
        if found is None:
            out["reason"] = "no_row"
            return out
        value = found.group(2).strip().strip("`*").strip()
        if value and PLACEHOLDER not in value:
            out["already"] = True
            out["current"] = value
            out["reason"] = "already"
            return out
        body = body[: found.start(2)] + f" {novel} " + body[found.end(2) :]
        registry.write_text(body, encoding="utf-8")
        out["linked"] = True
        out["reason"] = "filled"
        return out

    # ---- 建项目 / 补落点 -------------------------------------------------

    def create(
        self,
        name: Any,
        episodes: Any = None,
        upgrade: Any = None,
        novel: Any = None,
        novel_dir: str | os.PathLike[str] | None = None,
    ) -> dict[str, Any]:
        """建一个项目（或给已有项目补新增落点），并在最后登记原著。

        落盘的活整个交给 ``spec.create_project``（唯一事实源那份）：目录、``.gitkeep``、
        种子空表、模板占位符替换都是它的事，这里不另立一套。两处细节按面板的需要定：

        * ``log=None``：那份函数默认往 stdout 打日志，而本进程的 stdout 是 **JSON-RPC 通道**，
          打一行日志就把协议搅了；
        * 建完立刻回一份体检（``summary``），面板不用为了"建好了长什么样"再跑一趟。
        """
        spec = self.spec()
        path = self._path(name, must_exist=False)
        count = _as_int(episodes, DEFAULT_EPISODES, where="集数", low=1, high=9999)
        allow = _as_bool(upgrade, False, where="upgrade")
        try:
            made = spec.create_project(
                path.name, episodes=count, root=str(self.directory), upgrade=allow, log=None
            )
        except Exception as err:  # 那份函数用 ProjectError 报"已存在/模板缺失"，原文照传
            raise ProjectsError(str(err)) from err
        out: dict[str, Any] = {
            "name": path.name,
            "path": str(path),
            "episodes": count,
            "upgrade": allow,
            "dirs": [rel.rstrip("/") for rel in made["dirs"]],
            "files": list(made["files"]),
            "skipped": list(made["skipped"]),
            "pending": list(made["pending"]),
            "novel": None,
        }
        if novel is not None:
            out["novel"] = self.link_novel(path.name, novel, novel_dir=novel_dir)
        out["summary"] = self._summary(path, spec)
        return out

    # ---- 给对话用的简报 -------------------------------------------------

    def brief(self, name: Any) -> dict[str, Any]:
        """把一部剧的现状写成人话（面板「发到对话」那一下用）。

        只写**面板查得到的**事实：落点齐不齐、每一格有多少文件、阶段到哪、原著登记了没。
        不写评价、不替用户总结 —— 它是丢进输入框给模型当素材的，掺进判断等于替模型先入为主。
        """
        data = self.tree(name)
        summary = data["summary"]
        total = len(data["dirs"])
        lines = [
            f"【项目】{data['name']}",
            f"路径：{data['path']}",
            f"落点：{total - summary['missing_count']}/{total} 个目录齐"
            + (f"（缺 {'、'.join(summary['missing'])}，补：python main.py project new "
               f"{data['name']} --升级）" if summary["missing"] else ""),
            "",
            "各方资料：",
        ]
        for shelf in data["shelves"]:
            mark = "✅" if shelf["count"] else "☐"
            lines.append(f"  {mark} {shelf['title']}：{shelf['count']} 个文件")
        lines.append("")
        lines.append(
            "阶段："
            + "  ".join(("✅ " if stage["done"] else "☐ ") + stage["label"] for stage in summary["stages"])
        )
        lines.append(f"进度：{summary['stages_done']}/{summary['stages_total']} 段有产物（共 {summary['files']} 个文件）")
        lines.append(
            "原著：" + (data["novel"] or "未登记（见 00_PROJECT/07_素材归档/素材来源登记.md）")
        )
        return {"name": data["name"], "path": data["path"], "text": "\n".join(lines)}


# ─────────────────────────────────────────────────────────────
# 二、给模型看的两张工具（**只读**）
# ─────────────────────────────────────────────────────────────

#: 汇进 MCP 工具表时的 server 名：模型看到的是 ``projects__list`` / ``projects__brief``。
PROJECTS_SERVER = "projects"


@dataclass(frozen=True)
class _Spec:
    """一张项目工具：工具名 + 说明与参数表。"""

    name: str
    description: str
    input_schema: dict[str, Any]


#: 两张工具。为什么只有两张、且都只读：**建项目、改剧本、归档**都是"落盘 + 命名 + 集数"
#: 这类由人拍板的事（建一次就定了这一部剧的名字与集数，改名要动十几个目录）。
#: 模型能读、能据此接话，但不许替用户按下那个键 —— 面板上这几个按钮才是入口。
PROJECTS_TOOLS: tuple[_Spec, ...] = (
    _Spec(
        name="list",
        description=(
            "列出这台机器上已有的漫剧项目（一剧一目录），每部带上：文件数、阶段进度"
            "（S0 建纲 … S7 一致性）、缺哪些落点、最近改动时间。"
            "用户提到某部剧、问“现在做到哪了”“接着往下做”，先查这里再答，别凭印象说。"
            "这也告诉你项目根在哪：路径就在返回值里，读章节文件用文件工具时按它拼。"
            "建项目 / 改名不在工具里：那是人在面板上按的（名字与集数一定下来就要动十几个目录）。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "可选：按名字子串过滤（找某部剧时用，别把整表拉回来）",
                },
            },
        },
    ),
    _Spec(
        name="brief",
        description=(
            "读**一部剧**的现状简报：各方资料各有多少文件（剧本 / 对白与配音 / 资产索引与台账 / "
            "流程与进度 / 交付与出图 / 素材归档 / 世界观 / 角色服装道具 / 场景表情姿态 / 分镜与镜头 / "
            "一致性与音频）、六个阶段到哪一步、缺什么落点、原著登记的是哪本书。"
            "要动一部剧（写剧本、出角色设定、拆分镜）之前先读它，别猜目录里有什么。"
            "名字用 projects__list 给的那个（就是项目目录名）。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "项目名（项目目录名）"},
            },
            "required": ["name"],
        },
    ),
)


def _validate(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """参数在本地先挡一道：形状不对就别去翻目录。"""
    if name == "list":
        query = args.get("name")
        if query is not None and not isinstance(query, str):
            raise McpError("name 必须是字符串（子串过滤）")
        return {"name": query}
    if name == "brief":
        return {"name": args.get("name")}
    raise McpError(f"项目工具表里没有 {name}")


@dataclass(frozen=True)
class ProjectsServerConfig:
    """与 :class:`~comfy_studio.mcp.McpServerConfig` 同形的极小配置：这里只需要名字。"""

    name: str = PROJECTS_SERVER


class ProjectsClient:
    """鸭子型 MCP client：形状与 :class:`~comfy_studio.mcp.client.McpStdioClient` 一致，
    好直接汇进 :class:`~comfy_studio.mcp.McpHub` 的工具表（与画布 / 本地文件 / 记忆同一个做法）。
    """

    def __init__(self, library: ProjectLibrary, config: ProjectsServerConfig | None = None) -> None:
        self.library = library
        self.config = config if config is not None else ProjectsServerConfig()

    @property
    def alive(self) -> bool:
        return True

    def stderr_tail(self) -> str:
        return ""

    async def start(self) -> None:
        """没有子进程要拉：这张工具表一直都在。"""

    async def close(self) -> None:
        """没有连接要关；项目就是磁盘上的目录，随时可以再读。"""

    async def list_tools(self) -> list[McpTool]:
        return [
            McpTool(
                server=self.config.name,
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
            )
            for spec in PROJECTS_TOOLS
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel: CancelToken | None = None
    ) -> dict[str, Any]:
        """跑一个只读动作。

        ``cancel`` 收下但不用：两个动作都是**一次本地目录扫描**，没有可中断的长等待
        （真遇到超大目录也是秒级，不值得为它加一套取消）。
        失败（名字不对、项目不存在、规范载不上、文件读不了）一律回 ``isError`` 文本交给模型 ——
        它常能自己改对（换个名字、先 list 一下）再试。
        """
        spec = next((item for item in PROJECTS_TOOLS if item.name == name), None)
        if spec is None:
            known = ", ".join(item.name for item in PROJECTS_TOOLS)
            raise McpError(f"项目工具表里没有 {name}；可用: {known}")
        try:
            kwargs = _validate(name, dict(arguments or {}))
            if name == "list":
                result: Any = self.library.list(**kwargs)
            else:
                result = self.library.brief(**kwargs)
        except ProjectsError as err:
            return {"content": [{"type": "text", "text": str(err)}], "isError": True}
        return {
            "content": [
                {"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}
            ],
            "isError": False,
        }


__all__ = [
    "DEFAULT_EPISODES",
    "DEFAULT_LIST_LIMIT",
    "DEFAULT_READ_CHARS",
    "MAX_LIST_LIMIT",
    "MAX_READ_CHARS",
    "MAX_TREE_FILES",
    "NOVEL_ROW",
    "PLACEHOLDER",
    "PROJECTS_SERVER",
    "PROJECTS_TOOLS",
    "PROJECT_SHELVES",
    "PROJECT_SUBDIR",
    "PROJECT_SUFFIXES",
    "ProjectLibrary",
    "ProjectsClient",
    "ProjectsError",
    "ProjectsServerConfig",
    "WORKFLOW_DIRNAME",
    "default_project_dir",
    "default_spec_path",
    "load_spec",
    "shelf_gaps",
    "shelf_unknown",
]
