"""「项目管理」这一页的后端：一剧一目录（manju 那套落点）在面板上的读写。

为什么要有这个模块
------------------
漫剧那条链路的前半段是**资料活**：剧本、角色设定、分镜、对白、素材归档各占一格，
落点是 ``manju/projects/<剧名>/``。落点清单的**唯一事实源**是同一个包里的
:mod:`comfy_studio.projects_spec`（``PROJECT_DIRS`` / ``SEED_FILES`` /
``STAGE_SPECS``）。它原先住在引擎侧工作流的 ``07-智能体运行时/src/project.py``，
随那份工作流检出一起没了 —— 于是面板上"项目管理"这一页在真机器上只会显示
一片空白，而且**没有任何一处报错**。搬进包内之后，宿主包自己就是完整的：
引擎检出不在，也照样建得了项目、做得了体检。

那这里为什么不抄一份落点清单
----------------------------
抄一份的下场不是报错，是**两边悄悄分家**：规范里加了 ``11_AUDIO/``，
面板这份还是老清单，少掉的那一格要么显示成"缺"，要么干脆不出现，
而两处谁都不报错。所以本模块用 :func:`load_spec` 把那份 ``projects_spec.py``
**原样载入**来用（它只 import os/re/datetime，能独立载入）：落点、种子空表、
阶段判据、建项目、体检全都是**它的**代码。这里只做三件事：

① 把结果摆成面板要的形状（按"围绕剧本"的顺序分**格**＝域，格内再按**粒度**
   全剧级 / 分集级分组；格见 :data:`PROJECT_SHELVES`，粒度见 ``spec.DIR_SCOPES``）；
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

import hashlib
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

#: 事实源的文件名：与本模块**同一个包**里的 ``projects_spec.py``（``PROJECT_DIRS`` 所在处）。
#: 从 ``__file__`` 定位，不认工作目录 —— 宿主进程起在哪，跟包放在哪没关系。
SPEC_NAME = "projects_spec.py"

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
#: 一格 = 一个**域**（skelton）；域里再按**粒度**分两组（全剧级 / 分集级），
#: 粒度取自 ``spec.DIR_SCOPES`` —— 这里**不写**哪个落点是哪一级，抄一份就是两处维护。
#:
#: ⚠️ 这里的字符串**必须**是 ``spec.PROJECT_DIRS`` 里的落点。规范改了落点而这里没跟上，
#: :func:`shelf_gaps` 会报出来（而不是悄悄少显示一格）；单测对真清单钉住它为空。
PROJECT_SHELVES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("script", "剧本与总纲", ("00_PROJECT/00_原文解析", "00_PROJECT/01_剧本",
                              "00_PROJECT/01_剧本/00_总纲")),
    ("dialogue", "对白与配音", ("00_PROJECT/06_对白", "00_PROJECT/06_对白/对白稿")),
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


def scope_gaps(spec: Any) -> tuple[str, ...]:
    """哪些落点**没有粒度**（``spec.DIR_SCOPES`` 里查不到）。

    粒度查不到时面板不会崩，只会把那一格摆进"粒度未知"——**而这正是问题**：
    "未知"和"全剧级"在界面上都只是一行字，没人会去追它为什么是未知。
    所以这里报出来（``status`` 与 ``tree`` 都带一份），与 :func:`shelf_gaps` 同一个道理。

    另有一道更早的守卫：``spec`` 里**根本没有** ``DIR_SCOPES`` 时 :func:`load_spec` 直接报错，
    这里只查"有表但漏了项"。
    """
    known_scope: dict[str, str] = dict(getattr(spec, "DIR_SCOPES", {}) or {})
    return tuple(rel for rel in spec.PROJECT_DIRS if rel not in known_scope)


def scope_order(spec: Any) -> tuple[str, ...]:
    """粒度的显示顺序（全剧级在前）。判据在 ``spec.SCOPE_ORDER``，这里不另立一份。

    取的是 spec 里那几个常量**本身**（``SCOPE_WHOLE`` 等），所以哪怕将来改了叫法，
    面板跟着变、不需要改这里。
    """
    order = tuple(getattr(spec, "SCOPE_ORDER", ()) or ())
    if order:
        return order
    # 只有极老的规范才没有 SCOPE_ORDER —— 显式报错，不静默用一份写死的顺序顶上。
    raise ProjectsError(
        "事实源里没有 SCOPE_ORDER：粒度没有显示顺序，面板会把它摆成随机顺序。"
        f"请在事实源（{SPEC_NAME}）里补上（SCOPE_ORDER = (SCOPE_WHOLE, SCOPE_EPISODE, SCOPE_MIXED)）。"
    )


# ─────────────────────────────────────────────────────────────
# 定位：目录与事实源都不写死机器路径
# ─────────────────────────────────────────────────────────────

def default_project_dir(comfyui_dir: str | os.PathLike[str]) -> Path:
    """默认项目根：``<comfyui-dir>/custom_nodes/comfy_studio/manju/projects``。

    与 :func:`comfy_studio.novels.default_novel_dir` 同一个父目录 —— 原文与项目是
    同一部剧的两头，摆在一起才知道谁是谁的。
    """
    return Path(comfyui_dir).expanduser().resolve() / MANJU_REL / PROJECT_SUBDIR


def default_spec_path() -> Path:
    """默认的事实源路径：与本模块**同包**的 ``projects_spec.py``。

    这里刻意**不再从项目根反推**。老做法是"项目根往上退一级，去工作流检出里找
    ``07-智能体运行时/src/project.py``"—— 那条路径的失效模式不是报错，是
    **换了台机器就静默没有落点清单**：工作流检出不在时，面板上就是一片空白，
    而没有任何一处说得出为什么。包内自持之后，事实源与用它的代码同生共死。

    要从外部换一份实现，走 :class:`ProjectLibrary` 的 ``spec_path`` 参数
    （CLI 上是 ``--spec``），不要改这里的默认值。
    """
    return Path(__file__).resolve().parent / SPEC_NAME


#: ``scan_project`` 必须给出的键。缺一个就**当面指名** —— 既不要 KeyError，也不要
#: 静默取个默认值："事实源不合约"和"这个项目坏了"是两句完全不同的话，面板要能分开说。
#: ``files`` / ``mtime`` 在契约里，是因为它们**必须由同一次遍历算出来**：让调用方再各走
#: 一遍全树，就是把"同一棵树走几遍"这件事重新交回给每个调用点。
SCAN_KEYS = ("path", "missing", "legacy", "stages", "files", "mtime")


def _require_scan_keys(res: Any, spec_path: Path) -> None:
    """核对 ``scan_project`` 的返回契约，不合就抛 :class:`ProjectsError`。"""
    if not isinstance(res, dict):
        raise ProjectsError(
            f"事实源 {spec_path} 的 scan_project 要回一个 dict，收到的是 {type(res).__name__}。"
        )
    absent = [key for key in SCAN_KEYS if key not in res]
    if absent:
        raise ProjectsError(
            f"事实源 {spec_path} 的 scan_project 少返回了 {absent}；"
            f"契约是 {list(SCAN_KEYS)} 全给（见 projects_spec.scan_project）。"
        )


def _packaged_spec() -> Any:
    """包内那份事实源（:mod:`comfy_studio.projects_spec`）。

    默认路径下**直接 import**，不再走 :func:`load_spec` 的"按路径执行"：两者是同一份
    代码，但按路径执行要多解析一次源码、多建一个模块对象，而 :meth:`ProjectLibrary.spec`
    在 ``projects/list`` 这条热路径上**每部剧**都要过一遍。

    导不进来时报错而不是降级 —— 降级成"没有落点清单"正是这个模块开头要防的那种失败。
    """
    try:
        from . import projects_spec
    except ImportError as err:
        raise ProjectsError(
            f"载不了包内的事实源 {SPEC_NAME}：{err}。这是安装不完整，不是项目有问题。"
        ) from err
    return projects_spec


def load_spec(path: str | os.PathLike[str]) -> Any:
    """把一份 ``projects_spec.py`` 当模块载入，回模块对象。

    ``PROJECT_DIRS`` 这类清单一旦在本模块里再抄一份，两边迟早分家，而且**分家不报错**
    （详见模块开头）。那份文件只 import os/re/datetime、没有包内相对导入，
    所以用 ``importlib`` 从一个路径直接执行是安全的 —— 这条在它变成包内模块之后
    仍然保留，正是为了 ``--spec <路径>`` 能指向包外的一份**替换**实现（测试就这么做）。

    默认那份**不走这里**：见 :meth:`ProjectLibrary.spec` —— 同包模块直接拿来用，
    省掉一次重复解析与执行。
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise ProjectsError(
            f"找不到项目规范的事实源：{target}\n"
            f"默认那份随宿主包一起在（{SPEC_NAME}，与本模块同目录）；"
            "只有显式给了 --spec / spec_path 才会去别处找。"
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
        for attr in (
            "PROJECT_DIRS",
            "SEED_FILES",
            "create_project",
            "scan_project",
            "DIR_SCOPES",
            "SCOPE_ORDER",
        )
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


def _scope_title(scope: str) -> str:
    """粒度组的标题。空串只有一个来源：那个落点不在 ``spec.DIR_SCOPES`` 里。

    这时叫它"粒度未知"，**不**随手归进某一组 —— 归错了，人就以为那份资料
    真的属于那一层，而它其实只是两边没对齐（:func:`scope_gaps` 会把它报出来）。
    """
    return scope or "粒度未知"


def _list_files(
    root: Path,
    *,
    seeds: Any,
    base: Path | None = None,
    deep: bool = True,
    skip: tuple[Path, ...] = (),
) -> list[dict[str, Any]]:
    """目录下的文件（按相对路径排），给面板点开用。``deep=False`` 只看这一层。

    ``base`` 是相对路径的起点，默认就是 ``root`` 自己。项目里一律传**项目根**：
    面板是拿着这里给的 ``rel`` 回来 :meth:`ProjectLibrary.read` 的，
    那个路径必须是项目内的完整相对路径，不是"相对这一格"。

    ``skip`` 是**不往里走**的子目录（绝对路径）。用法只有一个：``01_剧本/`` 里面套着
    ``00_总纲/``，两个都是落点 —— 不剪掉的话同一份``角色小传.md``会被列两遍，
    而"列了两遍"看起来只是文件多了一个，没人会当成 bug。

    ``seeds`` 是"这一份算不算预置空表"的谓词（由 :func:`_seed_predicate` 按**载入的那份
    规范**造）。**必填**而不是给个默认：漏传的失效模式是面板把空模板全说成产物，
    而界面上一片"已完成"，谁也看不出是漏传了。
    """
    if not root.is_dir():
        return []
    origin = base if base is not None else root
    blocked = {Path(item).resolve() for item in skip}
    out: list[dict[str, Any]] = []
    if deep:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d != "__pycache__" and (Path(dirpath) / d).resolve() not in blocked
            )
            for name in sorted(filenames):
                if name == ".gitkeep":
                    continue
                out.append(_file_row(origin, Path(dirpath) / name, seeds))
    else:
        for name in sorted(os.listdir(root)):
            if name == ".gitkeep":
                continue
            full = root / name
            if full.is_file():
                out.append(_file_row(origin, full, seeds))
    return sorted(out, key=lambda row: row["rel"])


def _seed_predicate(spec: Any) -> Any:
    """按**载入的那份规范**造一个"这一份是不是预置空表"的谓词。

    规范自带 ``is_seed_path`` 就用它；没有就退回"照它自己的 ``SEED_FILES`` 判"，
    而那条规则（``EP01`` 按集号放宽）**借包内那份的** :func:`projects_spec.seed_predicate`，
    不在这里重写：退回逐字比对的下场是 EP02 的空对白表被算成**产物**，
    面板上八步工作台里那一步自己"有料"了 —— 用户看见的是空模板，界面说的是有产物。
    """
    fn = getattr(spec, "is_seed_path", None)
    if callable(fn):
        return lambda rel: bool(fn(rel))
    pattern_builder = getattr(spec, "seed_predicate", None)
    if callable(pattern_builder):
        return pattern_builder(getattr(spec, "SEED_FILES", ()))
    try:
        return _packaged_spec().seed_predicate(getattr(spec, "SEED_FILES", ()))
    except ProjectsError:
        # 包内那份都载不上（安装不完整）时不该让"列个文件"也炸掉：退到逐字相等，
        # 至少还认得出建项目时预置的那几份。
        rels = {str(dst).replace("\\", "/") for _src, dst in getattr(spec, "SEED_FILES", ())}
        return lambda rel: rel.replace("\\", "/") in rels


def _file_row(base: Path, path: Path, seeds: Any) -> dict[str, Any]:
    """一个文件的几个事实（相对路径 / 字节 / 改动时间 / 是不是预置空表）。读不到大小就报 0，不编。

    面板靠 ``seed`` 把"建项目时预置的空模板"与"真跑出来的产物"分开 ——
    不分开的话"管理小说"与"阶段工作台"都会把空表说成成果。
    """
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
        "seed": bool(seeds(rel)),
    }


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
        #: ``None`` = 用包内那份（直接 import）；给了就在 :meth:`spec` 里按路径载入。
        self._spec_override = Path(spec_path).expanduser().resolve() if spec_path else None
        #: 给人看/给 ``host/info`` 看的事实源路径（默认那份也在包内）。
        self.spec_path = self._spec_override or default_spec_path()
        #: 事实源模块（懒载入一次，见 :meth:`spec`）；载不上就把原因留在 ``_spec_error``。
        self._spec: Any = None
        self._spec_error = ""

    # ---- 事实源 ---------------------------------------------------------

    def spec(self) -> Any:
        """那份 ``projects_spec``；载不上抛 :class:`ProjectsError`（带上原文与修法）。"""
        if self._spec is None and not self._spec_error:
            try:
                self._spec = (
                    load_spec(self._spec_override)
                    if self._spec_override is not None
                    else _packaged_spec()
                )
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
            "scope_gaps": [],
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
        out["scope_gaps"] = list(scope_gaps(spec))
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
        """一部剧的现状（列表与详情共用）。阶段判据整个交给 ``spec.scan_project``。

        ``files`` / ``mtime`` **直接取它那一遍遍历的结果**，不再自己各走一遍全树。
        口径由事实源保证（``projects_spec.PRUNE_DIRS`` / ``_seed_rel_paths``）——
        这里要是再算一遍，两边一旦有出入又是"两处维护"。
        """
        res = spec.scan_project(str(path))
        _require_scan_keys(res, self.spec_path)
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
            "files": res["files"],
            "missing": list(res["missing"]),
            "missing_count": len(res["missing"]),
            "stages": stages,
            "stages_done": done,
            "stages_total": len(stages),
            "mtime": res["mtime"],
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
        """一部剧的落点，按**围绕剧本**的顺序分格、格内再按**粒度**分两组。

        两层摆放，两个来源，这里只做摆法、不复制知识：

        * **格**（域）来自 :data:`PROJECT_SHELVES`（剧本 → … → 素材归档 → 项目根）；
        * **粒度**来自 ``spec.DIR_SCOPES``（全剧级 / 分集级 / 混合），顺序取 ``spec.SCOPE_ORDER``。

        一格里的落点按粒度归成 ``groups``，面板就照它画小标题 —— 于是
        ``01_剧本/`` 下的``00_总纲/``（全剧级）与分集正文（分集级）不再是混在一列里的
        一堆文件名，而是"先定的总纲"与"一集一份的正文"两组。

        目录本身仍然逐项对着 ``spec.PROJECT_DIRS`` 查 —— 规范里加了落点而面板没加格，
        ``gaps`` 会如实带出来，不会悄悄少一格。
        """
        spec = self.spec()
        root = self._path(name)
        scopes: dict[str, str] = dict(getattr(spec, "DIR_SCOPES", {}) or {})
        order = scope_order(spec)
        # 嵌套落点：`01_剧本/` 里面套着 `00_总纲/`。父格列文件时要把它剪掉，
        # 否则同一份文件在父格与子格里各出现一次（多列一遍，不像 bug，像"文件真多"）。
        nested = {
            rel: tuple(root / Path(other) for other in spec.PROJECT_DIRS if other.startswith(rel + "/"))
            for rel in spec.PROJECT_DIRS
        }
        seeds = _seed_predicate(spec)
        buckets: dict[str, dict[str, Any]] = {}
        for rel in spec.PROJECT_DIRS:
            full = root / Path(rel)
            listed = (
                _list_files(full, base=root, skip=nested[rel], seeds=seeds)
                if full.is_dir()
                else []
            )
            buckets[rel] = {
                "rel": rel,
                "scope": scopes.get(rel, ""),
                "exists": full.is_dir(),
                "count": len(listed),
                "seed_count": sum(1 for row in listed if row["seed"]),
                "truncated": len(listed) > MAX_TREE_FILES,
                "files": listed[:MAX_TREE_FILES],
            }
        shelves = []
        for key, title, rels in PROJECT_SHELVES:
            items = [buckets[rel] for rel in rels if rel in buckets]
            groups = []
            for scope in tuple(order) + ("",):
                members = [item for item in items if item["scope"] == scope]
                if not members:
                    continue
                groups.append(
                    {
                        "scope": scope,
                        "title": _scope_title(scope),
                        "dirs": members,
                        "exists": any(item["exists"] for item in members),
                        "count": sum(item["count"] for item in members),
                    }
                )
            shelves.append(
                {
                    "key": key,
                    "title": title,
                    "dirs": items,
                    "groups": groups,
                    "exists": any(item["exists"] for item in items),
                    "count": sum(item["count"] for item in items),
                }
            )
        root_files = _list_files(root, deep=False, seeds=seeds)
        shelves.append(
            {
                "key": "root",
                "title": "项目根",
                "dirs": [],
                "groups": [],
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
            "scope_gaps": list(scope_gaps(spec)),
            "scopes": list(order),
            "shelves": shelves,
            "summary": self._summary(root, spec),
            "novel": self.linked_novel(root),
        }

    # ---- 读一份资料 -----------------------------------------------------

    def read(
        self,
        name: Any,
        rel: Any,
        offset: Any = None,
        chars: Any = None,
        whole: Any = None,
    ) -> dict[str, Any]:
        """读项目里的一份文本（面板点开一格里的文件）。

        编码走原文那套判定（:func:`comfy_studio.novels.decode_text`）：判不出来就明确报错，
        不把一屏乱码当剧本交出去。

        行尾统一按 ``\\n`` 算（Windows 编辑器写下的 ``\\r\\n`` 归一）。``offset`` / ``chars`` /
        ``total_chars`` 都是**归一之后**的位置：面板照这个翻页，两边口径得一致 ——
        把 ``\\r`` 一起交给面板，页上会多出一堆看不见的字符，翻页也会对不上。

        ``digest`` 是**这一份文件整份**的 sha256（不是这一页的）。面板改完要写回时带着它回来，
        见 :meth:`write`：那个参数是"我改的是我读到的这一版"这句话的唯一凭据。

        ``whole=True`` 是给**要改完写回**的面板那一趟的（工作台右边那一栏）：整份读来，一次
        翻页都不分。为什么不让面板自己传 ``chars=40000``：那个上限是**这里**的常量
        （:data:`MAX_READ_CHARS`），面板抄一份就会两边分家（``novels.py`` 那边为同一个毛病
        挨过一次，见 ``DEFAULT_READ_CHARS`` 的注释）。所以面板只说"我要整份"，上限由这里给。

        ⚠️ 整份也**可能不够**：比 :data:`MAX_READ_CHARS` 还长的文件，``whole=True`` 回来时
        ``truncated`` 仍然是真。**别拿这一份写回去** —— :meth:`write` 写的是调用方给的那段
        全文，把半份当全文交上去，等于把余下的内容删掉，而 :meth:`write` 自己看不出这件事
        （它拿到的是"一段更短的完整文本"，合法得很）。
        """
        if _as_bool(whole, False, where="whole"):
            offset, chars = 0, MAX_READ_CHARS
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
        raw = target.read_bytes()
        try:
            text, encoding = decode_text(raw, rel_text)
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
            "digest": hashlib.sha256(raw).hexdigest(),
            "total_chars": total,
            "offset": start,
            "requested_chars": want,
            "chars": len(piece),
            "truncated": start + len(piece) < total,
            "text": piece,
        }

    # ---- 改一份资料 -----------------------------------------------------

    def write(
        self,
        name: Any,
        rel: Any,
        text: Any,
        base_digest: Any = None,
    ) -> dict[str, Any]:
        """把面板上改过的正文写回原位。**本模块唯一一处改项目资料的地方。**

        为什么开这个口子：面板上"看得见却改不了"的正是最需要当场改一个错别字的东西
        （分镜表、对白稿、提示词）—— 改一处的代价是切回编辑器里找那份文件，而找不到时
        人会去改**另一个**同名文件，那才是真的乱。``read`` 从前那句"只读不写"靠的是
        "改剧本请在编辑器里改"，而在面板里逐格看产物、发现一处不对，就是没法改。

        ``base_digest`` 是**必填**的乐观锁，三个取值各对应一件事实：

        * ``None``（没给）→ **拒写**。"我没读过"与"我读过、它没变"是两件事，
          把前者当后者，等于用一次盲写盖掉别人（智能体、生成脚本）刚写进去的东西。
        * ``""``（空串）→ 调用方读到的是"这份文件还不存在"。真不存在才让写（新建产物）；
          这期间有人建了一份同名文件就**拒写**，绝不覆盖。
        * 别的字符串 → 必须与当前文件的 sha256（``read`` 回的 ``digest``）逐字相同。

        **不吞、不合并、不备份**：对不上就报错并把两边都摆出来，由人决定。自动合并冲突
        在 markdown 上做不对，而"做不对还默默做"正是把一份手改过的分镜表毁掉的方式。

        有一件事**这里看不出来**，得由调用方守：交上来的 ``text`` 必须是**整份**。半份也
        "合法"—— 那只是一段更短的完整文本，摘要对得上、大小也不超，于是这份文件余下的内容
        被静静删掉。所以拿 :meth:`read` 的 ``whole=True`` 读、并在 ``truncated`` 为真时
        **不要**写回（那说明这一份比 :data:`MAX_READ_CHARS` 还长，只读不写）。

        写盘走"同目录临时文件 + 原子换名"，行尾与编码**沿用原文件**（读的时候把 ``\\r\\n``
        归一了，写回去不还原的话，一次改一个字会让整份文件在 git 里变成全改）。
        """
        root = self._path(name)
        if not isinstance(text, str):
            raise ProjectsError("正文必须是字符串")
        rel_text = _as_name(rel, "文件相对路径").replace("\\", "/").lstrip("/")
        target = root / Path(rel_text)
        if not is_within(root, target):
            raise ProjectsError(f"路径跑到项目外面去了：{rel_text!r}")
        suffix = target.suffix.lower()
        if suffix not in PROJECT_SUFFIXES:
            raise ProjectsError(
                f"这一类文件不在这里改：{rel_text}（只有 {'、'.join(PROJECT_SUFFIXES)} 是文本资料）"
            )
        if base_digest is not None and not isinstance(base_digest, str):
            raise ProjectsError("base_digest 必须是字符串（没读过就不传）")

        existed = target.is_file()
        current = ""
        encoding = "utf-8"
        newline = "\n"
        if existed:
            try:
                raw = target.read_bytes()
            except OSError as err:
                raise ProjectsError(f"读不了 {rel_text}：{err}") from err
            if len(raw) > MAX_TEXT_BYTES:
                raise ProjectsError(
                    f"{rel_text} 有 {len(raw)} 字节，超过 {MAX_TEXT_BYTES}：太大，不整写"
                )
            try:
                _before, encoding = decode_text(raw, rel_text)
            except NovelsError as err:
                raise ProjectsError(str(err)) from err
            current = hashlib.sha256(raw).hexdigest()
            # 行尾沿用原文件：`read` 把 \r\n 归一成了 \n，写回不还原的话，
            # 在 Windows 上改一个字会让整份文件在 git 里"全变了"。
            newline = "\r\n" if b"\r\n" in raw else "\n"

        if base_digest is None:
            raise ProjectsError(
                f"要改 {rel_text} 得先读一遍再改（带着 read 回的 digest 当 base_digest）："
                "没读过就写，等于把别人刚写进去的东西盖掉 —— 这个目录里同时还有智能体与生成脚本在写。"
            )
        if base_digest == "":
            if existed:
                raise ProjectsError(
                    f"{rel_text} 已经存在了（读到的那一版是空的）："
                    "这边记的是'它还不存在'，先重读一遍再决定怎么改。"
                )
        elif not existed:
            raise ProjectsError(
                f"{rel_text} 已经不在了（读到的那一版是 {base_digest[:12]}…）："
                "多半是被删了或挪了位置，先重读一遍。"
            )
        elif current != base_digest:
            raise ProjectsError(
                f"{rel_text} 在编辑期间被改过了（读到的是 {base_digest[:12]}…，现在是 {current[:12]}…）："
                "这个目录里同时还有智能体与生成脚本在写。请重读一遍，把改动合进去再存。"
            )
        payload = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
        try:
            data = payload.encode(encoding, errors="strict")
        except UnicodeEncodeError as err:
            raise ProjectsError(
                f"{rel_text} 原来不是 UTF-8（{encoding}），改完的正文里有它写不出的字符：{err}"
            ) from err
        if len(data) > MAX_TEXT_BYTES:
            raise ProjectsError(f"要写进去的有 {len(data)} 字节，超过 {MAX_TEXT_BYTES}：太大，不整写")
        tmp = target.with_name(target.name + ".cs-tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            os.replace(tmp, target)
        except OSError as err:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise ProjectsError(f"写不进 {rel_text}：{err}") from err
        return {
            "name": root.name,
            "rel": rel_text,
            "path": str(target),
            "encoding": encoding,
            "newline": "crlf" if newline == "\r\n" else "lf",
            "bytes": len(data),
            "chars": len(payload),
            "created": not existed,
            "digest": hashlib.sha256(data).hexdigest(),
            "base_digest": base_digest,
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

        只写**面板查得到的**事实：落点齐不齐、每一格有多少文件、**每一格里全剧级 /
        分集级各多少**、阶段到哪、原著登记了没。
        不写评价、不替用户总结 —— 它是丢进输入框给模型当素材的，掺进判断等于替模型先入为主。

        粒度那一层**只在分得开的时候写**（一格里有两种粒度）：一格本来就全是分集级时，
        再写一行"全剧级 0 个"是噪声，模型读噪声会当成"这里缺东西"。
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
            groups = list(shelf.get("groups", []))
            if len(groups) > 1:
                for group in groups:
                    lines.append(f"      · {group['title']}：{group['count']} 个文件")
        if data["scope_gaps"]:
            lines.append(f"  ⚠️ 这些落点在事实源里没有粒度标记：{'、'.join(data['scope_gaps'])}")
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
            "（S0a 原文解析 … S7a 短剧合成）、缺哪些落点、最近改动时间。"
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
            "读**一部剧**的现状简报：各方资料各有多少文件（剧本与总纲 / 对白与配音 / 资产索引与台账 / "
            "流程与进度 / 交付与出图 / 素材归档 / 世界观 / 角色服装道具 / 场景表情姿态 / 分镜与镜头 / "
            "一致性与音频）、一格里有两种粒度时**全剧级 / 分集级各多少**、"
            "十一个生产阶段（S0a–S7a）到哪一步、缺什么落点、原著登记的是哪本书。"
            "要动一部剧（写剧本、出角色设定、拆分镜）之前先读它，别猜目录里有什么。"
            "**先把全剧级（总纲 / 资产索引 / 台账）读出来再碰分集产物** —— "
            "纲领性设定的权威在 `00_PROJECT/01_剧本/00_总纲/`，不在某一集正文里。"
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
    "SPEC_NAME",
    "ProjectLibrary",
    "ProjectsClient",
    "ProjectsError",
    "ProjectsServerConfig",
    "SCAN_KEYS",
    "default_project_dir",
    "default_spec_path",
    "load_spec",
    "scope_gaps",
    "scope_order",
    "shelf_gaps",
    "shelf_unknown",
]
