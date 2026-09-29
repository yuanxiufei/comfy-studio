"""路径落点 —— 输入 / 输出 / 中间产物 / 日志，**唯一的事实源**。

为什么要有这个模块
------------------
在这之前，"项目在哪"这句话有三处各自回答：``projects.default_project_dir``、
``novels.default_novel_dir``、``projects_spec.projects_root``。三处都落在
``<comfyui-dir>/custom_nodes/comfy_studio/manju/`` —— 那是**引擎检出目录内部**。
而引擎的加载类节点只认 ``input/``：``folder_paths.annotated_filepath`` 拿
``is_within_directory`` 校验，出界直接 ``ValueError``，连"用相对路径绕一下"都不行；
产物注解只认 ``output/``。于是：

* 原文、剧本、素材（要按名被 ``LoadImage`` / ``LoadAudio`` 读）落在 ``manju/`` 下
  = **引擎读不到**，每次都要先拷进 ``input/``；
* 成片落在 ``manju/`` 下 = **下游合成引用不到**，只能整份拷过去 —— 成片动辄几百兆。

这个模块把四类路径一次说清，并且**每一处都可覆盖**（命令行 / 环境变量），
默认值仍从 ``--comfyui-dir`` 推 —— 零配置可用，要迁移时不必改代码。

四类路径各落哪
--------------
======================  ================================================  ==================
这一类                  落哪                                              换地方用
======================  ================================================  ==================
输入 · 原文             ``<input>/<ns>/novel/``                           ``--novel-dir``
输入 · 项目资料         ``<input>/<ns>/<剧>/``                            ``--project-dir``
输出 · 视频成品         ``<output>/<ns>/<剧>/``                           ``--project-out-dir``
中间产物（可弃）         ``<引擎的 temp>/``                                 ``--temp-dir``
中间产物（要留）         ``<output>/<ns>/<剧>/_work/``                     跟着产物根
日志 / 流程记录         ``<input>/<ns>/<剧>/00_PROJECT/05_流程/``          跟着资料根
======================  ================================================  ==================

"哪个落点在哪个根"一律问 :mod:`.projects_spec` 的 ``DIR_ROOTS``，这个模块**不抄第二份** ——
抄一份的失效模式是两边各说各的，而谁都不报错。

⚠️ **命名空间（``ns``）不是安全边界**。引擎的 input/output/temp 是**进程级单例**，
没有用户、会话、租户任何维度：能用这个引擎实例的人就读得到 ``input/`` 下**所有**项目。
``--namespace`` 解决的是"多项目 / 多团队**撞名**、归属不清、没法整体搬迁"，
不是"谁能看谁"。真要权限隔离只有两条路：OS 文件权限，或者**一用户一个引擎实例**
（各自 ``--input-directory`` / ``--output-directory`` —— 宿主侧本来就把这两个目录
显式传进来，见 :func:`resolve_layout`）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import projects_spec as spec

# ─────────────────────────────────────────────────────────────
# 一、配置项（命令行 → 环境变量 → 从 comfyui-dir 推）
# ─────────────────────────────────────────────────────────────

#: 引擎检出目录。它下面那三个子目录的**名字**是引擎自己的默认布局。
COMFYUI_DIR_ENV = "COMFYUI_DIR"
INPUT_DIR_ENV = "COMFY_INPUT_DIR"
OUTPUT_DIR_ENV = "COMFY_OUTPUT_DIR"
TEMP_DIR_ENV = "COMFY_STUDIO_TEMP_DIR"
NAMESPACE_ENV = "COMFY_STUDIO_NAMESPACE"
NOVEL_DIR_ENV = "COMFY_STUDIO_NOVEL_DIR"
PROJECT_DIR_ENV = "COMFY_STUDIO_PROJECT_DIR"
PROJECT_OUT_DIR_ENV = "COMFY_STUDIO_PROJECT_OUT_DIR"

#: 引擎检出里三个默认子目录名 —— 与 ComfyUI 自己的默认布局（``folder_paths``）一致。
INPUT_SUBDIR = "input"
OUTPUT_SUBDIR = "output"
TEMP_SUBDIR = "temp"

#: 原文库在**输入根**下的哪一级。与项目同级：原文与项目是同一部剧的两头，
#: 摆在一起才知道谁是谁的（这句话原先写在 ``projects.default_project_dir`` 里）。
NOVEL_SUBDIR = "novel"

#: 引擎 ``input/`` 下的**暂存区**：一份任务要用的参考图/片子先搬到这里，
#: 工作流才认得出它（``LoadImage.image`` 要的是"相对 input 目录"的名字）。
#:
#: ⚠️ 与引擎侧 ``skills/render.py::INPUT_IMAGE_SUBDIR`` 是**同一份知识的两处**：
#: 那边在引擎包里，跨进程、跨包，import 不过来，只能各存一份。
#: 改这里就要同步改那边，否则宿主算出的暂存区与引擎实际落的那一处不是一个地方。
STAGE_SUBDIR = Path("comfy_studio") / "render"


class LayoutError(RuntimeError):
    """路径算不出来：根一个都没给、命名空间想往外跑。"""


def _clean_namespace(raw) -> str:
    """命名空间只允许"若干层普通目录名"—— 不许绝对路径、不许 ``..``、不许盘符。

    它会被拼进真实路径，所以把"想往外跑"的三种写法一次性挡掉：
    绝对路径、``..``、以及 Windows 那种带盘符的形式。空串是合法值（= 单租户）。
    """
    ns = str(raw or "").strip().strip("/\\")
    if not ns:
        return ""
    parts = [p for p in ns.replace("\\", "/").split("/") if p]
    for part in parts:
        if part in (os.curdir, os.pardir):
            raise LayoutError("命名空间里不能有 %r：%r" % (part, raw))
        if os.path.splitdrive(part)[0] or ":" in part:
            raise LayoutError("命名空间不能带盘符：%r" % (raw,))
    return "/".join(parts)


# ─────────────────────────────────────────────────────────────
# 二、布局
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StudioLayout:
    """四类路径的根，一次算清。

    两个**业务根**是 :attr:`input_root` 与 :attr:`output_root`（带命名空间的版本见
    :meth:`root`）；:attr:`temp_root` 是引擎的临时区，它不属于任何项目 ——
    "可弃的中间产物"就该在进程一退就被清掉的地方。
    """

    input_root: Path
    output_root: Path
    temp_root: Path
    #: 多租户 / 多团队的那一层。空串 = 单租户（严格贴规范：``input/novel``、``input/<剧>/``）。
    namespace: str = ""
    #: 三个业务落点的**显式覆盖**；``None`` = 按上面那两个根推。
    #: 它们是"有人手工指了落点"的痕迹，:meth:`describe` 会报出来 ——
    #: 手工指的落点可以离引擎的 ``input/`` 很远，而那种情况下引擎按名读不到它，
    #: 界面上却一切正常，所以"指过没有"本身就得看得见。
    novel_root: Path | None = None
    project_root: Path | None = None
    project_out_root: Path | None = None

    # ---- 根 -------------------------------------------------------------

    def root(self, kind: str) -> Path:
        """``"input"`` / ``"output"`` / ``"temp"`` → 那个根（前两个带上命名空间）。"""
        if kind == spec.ROOT_INPUT:
            return self.input_root / self.namespace if self.namespace else self.input_root
        if kind == spec.ROOT_OUTPUT:
            return self.output_root / self.namespace if self.namespace else self.output_root
        if kind == "temp":
            return self.temp_root
        raise LayoutError(
            "未知的根 %r；可选：%s / %s / temp"
            % (kind, spec.ROOT_INPUT, spec.ROOT_OUTPUT))

    # ---- 项目 -----------------------------------------------------------

    def novel_dir(self) -> Path:
        """原文库：``<input>/<ns>/novel``（被显式指过就是那一个）。"""
        return self.novel_root or self.root(spec.ROOT_INPUT) / NOVEL_SUBDIR

    def projects_root(self) -> Path:
        """**资料根**（一剧一目录的那一层，也是 ``projects/*`` 那几张 RPC 的落点）。"""
        return self.project_root or self.root(spec.ROOT_INPUT)

    def projects_out_root(self) -> Path:
        """**产物根**（成片与逐镜片子的那一层）。"""
        return self.project_out_root or self.root(spec.ROOT_OUTPUT)

    def project_in(self, name: str) -> Path:
        return self.projects_root() / name

    def project_out(self, name: str) -> Path:
        return self.projects_out_root() / name

    def project_roots(self, name: str) -> dict:
        """一部剧的两个根 —— 键就是 ``spec.ROOT_INPUT`` / ``spec.ROOT_OUTPUT``。"""
        return {spec.ROOT_INPUT: self.project_in(name), spec.ROOT_OUTPUT: self.project_out(name)}

    # ---- 落点 -----------------------------------------------------------

    @staticmethod
    def root_of(rel: str) -> str:
        """一个落点（``"09_SHOTS"`` 这种相对路径）落在哪个根。**问事实源**。"""
        return spec.root_of(rel)

    @staticmethod
    def root_of_path(rel: str) -> str:
        """一个**文件**路径落在哪个根（按最长落点前缀判）。也问事实源。"""
        return spec.root_of_path(rel)

    def landing_dir(self, project: str, rel: str) -> Path:
        """一部剧的某个落点**在盘上的绝对路径**。

        这是面板与流水线都该走的那一个入口 —— 谁也别自己 `项目根 + rel`：
        落点挂在哪个根上是 ``DIR_ROOTS`` 说了算，自己拼就会拼到错的那个根上，
        而"落错根"是不报错的（见 ``projects_spec.DIR_ROOTS`` 的注释）。
        """
        base = self.project_in(project) if self.root_of(rel) == spec.ROOT_INPUT \
            else self.project_out(project)
        return base / rel.replace("/", os.sep)

    def work_dir(self, project: str) -> Path:
        """要留的中间产物：``<产物根>/<剧>/_work``（不进 ``PROJECT_DIRS``，不进体检）。"""
        return self.project_out(project) / spec.WORK_SUBDIR

    def stage_dir(self, project: str, task: str = "") -> Path:
        """引擎 ``input/`` 下的暂存区：``<input>/comfy_studio/render/<ns>/<剧>/<任务>``。

        按三层分（命名空间 / 剧 / 任务）不是讲究，是修一个真实缺陷：原先所有项目、
        所有任务的参考图都往**一个扁平目录**里塞，按原文件名落地 ——
        A 项目的 `参考图.png` 会被 B 项目的同名图**直接覆盖**，
        而 A 的工作流如果正在排队，它会静默地读到 B 的图。
        """
        base = self.input_root / STAGE_SUBDIR
        if self.namespace:
            base = base / self.namespace
        base = base / _safe_segment(project, "剧名")
        return base / _safe_segment(task, "任务名") if task else base

    # ---- 说明 -----------------------------------------------------------

    def describe(self) -> dict:
        """给人看/给 ``host/info`` 看的自我说明（路径都在这，别处不必再猜）。"""
        return {
            "namespace": self.namespace,
            "input_root": str(self.input_root),
            "output_root": str(self.output_root),
            "temp_root": str(self.temp_root),
            "novel_dir": str(self.novel_dir()),
            "projects_root": str(self.projects_root()),
            "projects_out_root": str(self.projects_out_root()),
            "stage_subdir": STAGE_SUBDIR.as_posix(),
            "single_root": self.projects_root() == self.projects_out_root(),
            # 哪几项是**手工指的**：指过的落点可以离引擎的 input/ 很远，
            # 那种情况下引擎按名读不到它，而界面上一切正常 —— 所以这一条得看得见。
            "overridden": [
                name
                for name, value in (
                    ("novel_dir", self.novel_root),
                    ("projects_root", self.project_root),
                    ("projects_out_root", self.project_out_root),
                )
                if value is not None
            ],
        }


def _safe_segment(raw: str, what: str) -> str:
    """拼进路径之前把一段名字收干净：不许空、不许带分隔符、不许 ``..``。"""
    name = str(raw or "").strip()
    if not name or name != os.path.basename(name) or name in (os.curdir, os.pardir):
        raise LayoutError("%s 只能是目录名，不带路径：%r" % (what, raw))
    return name


# ─────────────────────────────────────────────────────────────
# 三、解析（命令行 > 环境变量 > 从 comfyui-dir 推）
# ─────────────────────────────────────────────────────────────

def resolve_layout(
    comfyui_dir: str | os.PathLike[str] | None = None,
    *,
    input_dir: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    temp_dir: str | os.PathLike[str] | None = None,
    namespace: str | None = None,
    novel_dir: str | os.PathLike[str] | None = None,
    project_dir: str | os.PathLike[str] | None = None,
    project_out_dir: str | os.PathLike[str] | None = None,
) -> StudioLayout:
    """把命令行参数、环境变量、``--comfyui-dir`` 三方合成一份布局。

    优先级：**显式参数 > 同名环境变量 > 从 ``comfyui_dir`` 推的默认值**。

    ⚠️ 默认值**只在 ``comfyui_dir`` 给了的时候才推得出来**：引擎可以用
    ``--input-directory`` / ``--output-directory`` 把两个根搬到别处，宿主这一侧
    完全看不见那个改动。所以"不知道"时宁可不猜 —— 一个都推不出来就显式报错，
    而不是拿 ``<cwd>/input`` 顶上：那样出来的路径**不报错**，只是每次跑都落错地方。

    最后三个（``novel_dir`` / ``project_dir`` / ``project_out_dir``）是**业务落点**，
    它们与上面那把梯子同一套优先级，但**推不出来不算错**（:func:`StudioLayout.novel_dir`
    那几个会把默认值补上）—— 它们是"就摆在那儿"的目录，不像两个引擎根那样猜错了整条
    流水线都白跑。

    宿主那边（``__main__``）为这几个开关也读了一遍同名环境变量，与本函数结论一致
    （同一把梯子），所以无害；但**新的**取值路径请一律走这里 —— 同一个判断写两处，
    一旦哪天只改了一处，表现是"命令行指了这个目录，跑起来却落在另一个目录"，谁也不报错。
    """
    env = os.environ.get
    comfy = comfyui_dir or env(COMFYUI_DIR_ENV)
    base = Path(comfy).expanduser().resolve() if comfy else None

    def pick(given, env_name: str, sub: str, what: str) -> Path:
        raw = given or env(env_name)
        if raw:
            return Path(raw).expanduser().resolve()
        if base is None:
            raise LayoutError(
                "算不出%s：既没给 --comfyui-dir，也没有 %s。"
                "引擎可以用 --input-directory / --output-directory 把目录搬到别处，"
                "宿主看不见那个改动，所以这里**不猜**。"
                "两种修法：① 给 --comfyui-dir；② 直接给%s对应的那个开关。"
                % (what, env_name, what))
        return base / sub

    def optional(given, env_name: str) -> Path | None:
        """与 ``pick`` 同一把梯子，但**推不出来就算了**。

        推不出来不报错，是因为这三个落点**有默认值**（资料根 / 产物根那一对）：
        它们是"就摆在那儿"的东西，不像两个引擎根那样猜错了整条流水线都白跑。
        """
        raw = given or env(env_name)
        return Path(raw).expanduser().resolve() if raw else None

    return StudioLayout(
        input_root=pick(input_dir, INPUT_DIR_ENV, INPUT_SUBDIR, "输入根"),
        output_root=pick(output_dir, OUTPUT_DIR_ENV, OUTPUT_SUBDIR, "输出根"),
        temp_root=pick(temp_dir, TEMP_DIR_ENV, TEMP_SUBDIR, "临时根"),
        namespace=_clean_namespace(namespace if namespace is not None else env(NAMESPACE_ENV)),
        novel_root=optional(novel_dir, NOVEL_DIR_ENV),
        project_root=optional(project_dir, PROJECT_DIR_ENV),
        project_out_root=optional(project_out_dir, PROJECT_OUT_DIR_ENV),
    )


def layout_of(comfyui_dir: str | os.PathLike[str] | None,
              **kwargs) -> StudioLayout | None:
    """尽量算一份布局；算不出来回 ``None``（"还没挂上"，不是错误）。

    给 ``server.serve_stdio`` 用：那里"没给 ``--comfyui-dir``"是一个**合法状态**
    （面板会照实说这一页没挂上），不该在这里抛出去把整个宿主拦下。
    """
    try:
        return resolve_layout(comfyui_dir, **kwargs)
    except LayoutError:
        return None


# ─────────────────────────────────────────────────────────────
# 四、给老接口用的那几个默认路径
# ─────────────────────────────────────────────────────────────

def default_project_dir(comfyui_dir: str | os.PathLike[str]) -> Path:
    """默认**资料根**：``<comfyui-dir>/input``。

    注意它不再是 `…/manju/projects` —— 理由见模块开头：那里引擎读不到。
    与 :func:`default_novel_dir` 仍是同一个父目录（一剧的原文与资料摆在一起）。
    """
    return Path(comfyui_dir).expanduser().resolve() / INPUT_SUBDIR


def default_project_out_dir(comfyui_dir: str | os.PathLike[str]) -> Path:
    """默认**产物根**：``<comfyui-dir>/output``。

    与 :func:`default_project_dir` 成对：引擎那条 ``名[output]`` 注解读的就是它，
    成片落在这儿，下一步合成才引用得上、不必整个拷一遍。
    """
    return Path(comfyui_dir).expanduser().resolve() / OUTPUT_SUBDIR


def default_novel_dir(comfyui_dir: str | os.PathLike[str]) -> Path:
    """默认原文目录：``<comfyui-dir>/input/novel``。"""
    return default_project_dir(comfyui_dir) / NOVEL_SUBDIR


def default_temp_dir(comfyui_dir: str | os.PathLike[str]) -> Path:
    """默认临时区：``<comfyui-dir>/temp``（引擎自己的可清理目录）。"""
    return Path(comfyui_dir).expanduser().resolve() / TEMP_SUBDIR


__all__ = [
    "LayoutError",
    "StudioLayout",
    "STAGE_SUBDIR",
    "NOVEL_SUBDIR",
    "INPUT_SUBDIR",
    "OUTPUT_SUBDIR",
    "TEMP_SUBDIR",
    "COMFYUI_DIR_ENV",
    "INPUT_DIR_ENV",
    "OUTPUT_DIR_ENV",
    "TEMP_DIR_ENV",
    "NAMESPACE_ENV",
    "NOVEL_DIR_ENV",
    "PROJECT_DIR_ENV",
    "PROJECT_OUT_DIR_ENV",
    "resolve_layout",
    "layout_of",
    "default_project_dir",
    "default_project_out_dir",
    "default_novel_dir",
    "default_temp_dir",
]
