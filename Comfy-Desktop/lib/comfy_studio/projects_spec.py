#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目脚手架与体检 —— 「一剧一目录」那套落点的**唯一事实源**。

**为什么整份收进宿主包**：这份清单原先住在引擎侧的工作流检出里
（``AI漫剧智能体工作流/07-智能体运行时/src/project.py``），由 ``projects.py``
按路径载入。可宿主包是**随桌面壳分发**的，引擎检出却可能不在 —— 那时
``projects/*`` 连"这一剧该有哪些落点"都答不出来，面板上就是一片"没有落点清单"，
**而且没有任何一处报错**。所以清单与它要用的空表一起收进包内
（``comfy_studio/templates/project/``），宿主侧不再依赖引擎检出。

**⚠️ 现状（2026-09-28）：引擎侧不在检出里。** 本文件 `STAGE_SPECS` 里的 `entries`
（`python main.py flow …`）与 `gate`（`生产流程规范（S0-S7）.md` 章节）指向的东西
**目前都不在仓库里** —— 主运行时 `AI漫剧智能体工作流/07-智能体运行时/` 整目录已不在。
这些字符串留着是为了不丢口径，但**照着敲会失败**。恢复引擎侧时，第一件事是把被
停掉的机械核对接回来（本文件各处标了 ⚠️，宿主侧对应的是
`tests/test_projects.py::RealSpecTest`）。项目**脚手架与体检**不受影响 ——
那部分（`PROJECT_DIRS` / `SEED_FILES` / `scan_project`）在本文件里是自持的。

本文件只 import 标准库（``os`` / ``re`` / ``dataclasses`` / ``datetime``）、
没有包内相对导入，所以两种拿法都成立：``projects.py`` 直接 ``import`` 它
（默认路径，零重复执行），或用 ``--spec <路径>`` 指到一份**替换**实现上
（那时由 ``projects.load_spec`` 按路径执行）。

把规范变成可执行的东西：

    python main.py project new     <项目名>   # 按规范建全套落点 + 预置空表
    python main.py project migrate <项目名>   # v1 老项目升到 v2 结构（只移动，不覆盖）
    python main.py project check   <项目名>   # 缺哪个落点 / 哪一阶段还没产物

**四份事实源全在本文件里，不散在别处**

================================  ==============================================
``PROJECT_DIRS``                  一个项目应有的全部落点（面板格子必须盖住它）
``DIR_SCOPES`` / ``SCOPE_ORDER``  每个落点的粒度、以及粒度的显示顺序
``STAGE_SPECS``                   阶段 S0a–S7a：谁做 · 落哪 · 怎么跑 · 判据在哪
``SEED_FILES``                    建项目预置的空表（模板在 ``templates/project/``）
================================  ==============================================

**为什么粒度进代码**：``00_PROJECT/01_剧本/`` 与它下面的 ``00_总纲/`` 是两种粒度
并存的地方（一集一份的正文 vs 跨集共享的设定），而面板要把它们分开摆。让面板
自己去猜（``00_总纲`` 猜成全剧级、``06_对白`` 猜成…… 猜不出来），猜错的失效模式
是静默的：把一集的对白表摆进"全剧共用"那一栏。所以它必须是机器读得到的数据。

**阶段为什么也进代码**：``STAGE_SPECS`` 回答「每一个生产阶段由谁做、产物落在哪、
**怎么跑**、判据在哪」。原先这四件事散在四处（``flow_core.STAGES`` 六段、本文件
``STAGE_OUTPUTS`` 六桶、两份文档各一张表）—— **互相不一致也不报错**：用户照着
文档敲 ``--阶段 表情``，拿到的只有 argparse 的 "invalid choice"，没有任何一处
告诉他「S3 走 ``main.py ask``」。故收成一份，并让入口信息（``entries``）能被
``project check`` 直接念出来。

**为什么有 ``migrate``**：v1 把 5 集正文与两份**全剧级**设定（分集大纲与三表、
角色小传）平铺在 ``01_剧本/`` 一层，归属只能靠看文件名猜。v2 把全剧级的收进
``00_总纲/``。老项目不能靠手拖 —— 手拖的失效模式是**拖错方向还不报错**。

**不写死机器路径**：项目根由调用方给（宿主侧 ``--project-dir`` / ``--comfyui-dir``），
或按环境变量 ``VOIDE_PROJECTS_ROOT`` 探测。本文件里没有任何盘符。
"""

import os
import re
import shutil
from dataclasses import dataclass
from datetime import date

#: 本文件所在目录 = 宿主包目录（``…/lib/comfy_studio``）。
#: 从 ``__file__`` 推，不认工作目录 —— 宿主进程起在哪，跟包放在哪没关系。
HERE = os.path.dirname(os.path.abspath(__file__))

#: 建项目要用的空表放在哪：与本文件同级的 ``templates/project/``。
#: 与 :data:`SEED_FILES` 配对 —— 种子表写文件名，这里写它所在的目录。
TEMPLATE_DIR = os.path.join(HERE, "templates", "project")

#: 模板里没被替换掉的占位符一律落成它 —— 让「还没填」看得见，而不是留一个 `{{X}}`
PLACEHOLDER = "（待填）"


class ProjectError(Exception):
    """项目脚手架的错误。**显式抛出，不静默兜底。**"""


# ─────────────────────────────────────────────────────────────
# 一、项目目录清单（**唯一事实源**）
# ─────────────────────────────────────────────────────────────

#: 一个项目应有的全部目录 —— 顺序即面板上的显示顺序。
#: 覆盖范围由 `tests/test_projects.py::RealSpecTest` 与宿主侧 `PROJECT_SHELVES`
#: 逐项对拍：漏一个落点，面板上就少一格，而且**不会报错** —— 所以那条对拍不许跳过。
#: 注意 `00_PROJECT/01_剧本` 是**分集级**落点（每集一份正文），
#: 而 `00_PROJECT/01_剧本/00_总纲` 是**全剧级**落点（跨集共享的设定）—— 两者都要建。
PROJECT_DIRS = (
    "00_PROJECT/00_原文解析",
    "00_PROJECT/01_剧本",
    "00_PROJECT/01_剧本/00_总纲",
    "00_PROJECT/02_资产索引",
    "00_PROJECT/03_台账",
    "00_PROJECT/04_交付与出图",
    "00_PROJECT/05_流程",
    "00_PROJECT/06_对白",
    "00_PROJECT/06_对白/对白稿",
    "00_PROJECT/07_素材归档",
    "01_WORLD",
    "02_CHARACTERS",
    "03_COSTUMES",
    "04_PROPS",
    "05_ENVIRONMENTS",
    "06_EXPRESSIONS",
    "07_POSES",
    "08_STORYBOARDS",
    "09_SHOTS",
    "10_CONSISTENCY",
    "11_AUDIO",
    "12_FILMS",
)

#: 粒度的三个取值。**不是审美，是归属判据**（规范 §二 的警示）：
#: 一份管全剧的数据写在分集目录里（或反过来），后果都不是报错 ——
#: 是 S0 出完第 5 集时**没有人知道那份设定该不该跟着改**。
#: 判据只有一句：被不止一集引用的，一律全剧级；一集一份的，一律把集号做前缀。
SCOPE_WHOLE = "全剧级"
SCOPE_EPISODE = "分集级"
SCOPE_MIXED = "混合"

#: 面板摆这几组的顺序（`全剧级` 在前 —— 它是"先定的那份"，分集产物跟着它走）。
#: 顺序也进代码而不是让每个消费者自己排：两边各排一次，就会一边全剧级在前、
#: 一边分集级在前，而**没人会报错**。
SCOPE_ORDER = (SCOPE_WHOLE, SCOPE_EPISODE, SCOPE_MIXED)

#: 每个落点的粒度（与规范 §三 的「粒度」列逐行对应，顺序按 `PROJECT_DIRS`）。
#:
#: **为什么要有这份表**：`PROJECT_DIRS` 只回答"目录在不在这"，回答不了
#: "这里该放全剧级的还是分集级的"。而 `00_PROJECT/01_剧本/` 与它下面的
#: `00_总纲/` 正是两种粒度并存的地方 —— 面板要把它们分开摆，先得有这份数据；
#: 让面板自己去猜（`00_总纲` 猜成全剧级、`06_对白` 猜成…… 猜不出来），
#: 猜错的失效模式又是静默的：把一集的对白表摆进"全剧共用"那一栏。
#:
#: 覆盖性由 `tests/test_projects.py` 守：`DIR_SCOPES` 要给 `PROJECT_DIRS` 每一项都
#: 有口径，`SCOPE_ORDER` 要收齐用到的粒度 —— 少一个就是面板上一格静默消失。
DIR_SCOPES = {
    "00_PROJECT/00_原文解析": SCOPE_WHOLE,
    "00_PROJECT/01_剧本": SCOPE_EPISODE,
    "00_PROJECT/01_剧本/00_总纲": SCOPE_WHOLE,
    "00_PROJECT/02_资产索引": SCOPE_WHOLE,
    "00_PROJECT/03_台账": SCOPE_WHOLE,
    "00_PROJECT/04_交付与出图": SCOPE_MIXED,
    "00_PROJECT/05_流程": SCOPE_MIXED,
    "00_PROJECT/06_对白": SCOPE_EPISODE,
    "00_PROJECT/06_对白/对白稿": SCOPE_EPISODE,
    "00_PROJECT/07_素材归档": SCOPE_WHOLE,
    "01_WORLD": SCOPE_WHOLE,
    "02_CHARACTERS": SCOPE_WHOLE,
    "03_COSTUMES": SCOPE_WHOLE,
    "04_PROPS": SCOPE_WHOLE,
    "05_ENVIRONMENTS": SCOPE_WHOLE,
    "06_EXPRESSIONS": SCOPE_WHOLE,
    "07_POSES": SCOPE_WHOLE,
    "08_STORYBOARDS": SCOPE_EPISODE,
    "09_SHOTS": SCOPE_EPISODE,
    "10_CONSISTENCY": SCOPE_WHOLE,
    "11_AUDIO": SCOPE_EPISODE,
    "12_FILMS": SCOPE_EPISODE,
}


# ─────────────────────────────────────────────────────────────
# 一·二、落点分属哪个**根**（资料根 / 产物根）—— 第二份事实源
# ─────────────────────────────────────────────────────────────

#: 一个落点可以落在两个根上，**只有这两个取值**。
#:
#: **为什么要有这份表**：落点从来不只是"项目下的哪一级"，还含"在哪个根下"。
#: 而 ComfyUI 把这件事钉死了 —— 引擎的加载类节点只认 ``input/``
#: （``folder_paths.annotated_filepath`` 拿 ``is_within_directory`` 校验，
#: 出界直接 ``ValueError``，连"相对路径绕一下"都不行），产物注解只认 ``output/``。
#: 于是：**要按名被工作流读的**（原文、剧本、素材）必须落 input，
#: **工作流产出的**（逐镜片子、成片）必须落 output。这不是审美，是引擎的硬约束。
#:
#: 不写这份表的后果是**静默**的：图出了、也算出了东西，只是不在引擎读得到的地方 ——
#: 面板上"还缺图"永远不消，人以为白跑一趟（与 ``STAGE_RENDER`` 的落点绑错同一种错法）。
ROOT_INPUT = "input"
ROOT_OUTPUT = "output"

#: 落点 → 它的根。**没写的一律 input**（表是"例外清单"，不是全量清单）——
#: 全量清单会随 ``PROJECT_DIRS`` 增删而失配，而失配的失效模式是"新加的格默默落错根"。
DIR_ROOTS = {
    "09_SHOTS": ROOT_OUTPUT,
    "12_FILMS": ROOT_OUTPUT,
}


def root_of(rel: str) -> str:
    """一个落点落在哪个根（``ROOT_INPUT`` / ``ROOT_OUTPUT``）。"""
    return DIR_ROOTS.get(rel, ROOT_INPUT)


def dirs_in_root(kind: str) -> tuple:
    """只落在某个根上的落点，顺序照 ``PROJECT_DIRS``（= 面板显示顺序）。"""
    if kind not in (ROOT_INPUT, ROOT_OUTPUT):
        raise ProjectError("未知的根 %r；只有 %r 与 %r" % (kind, ROOT_INPUT, ROOT_OUTPUT))
    return tuple(rel for rel in PROJECT_DIRS if root_of(rel) == kind)


#: 两个根各自有哪些落点。建项目、体检、迁移都靠它分派 ——
#: 两边各写一遍"哪个落点在哪"，就会一边落 input、一边找 output，而**谁都不报错**。
PROJECT_DIRS_IN = dirs_in_root(ROOT_INPUT)
PROJECT_DIRS_OUT = dirs_in_root(ROOT_OUTPUT)


def root_of_path(rel: str) -> str:
    """一个**文件**路径落在哪个根：按 ``DIR_ROOTS`` 里最长的那个落点前缀判。

    目录用 :func:`root_of`（精确查表）；文件得按前缀问 —— 落点存的是目录，
    文件是它下面的东西（``09_SHOTS/EP01_SH003.mp4``）。
    取最长前缀而不是第一个命中的：落点之间会嵌套（``00_PROJECT/06_对白`` 与
    ``00_PROJECT/06_对白/对白稿``），取短的会把里层那个判到外层的根上去。

    ⚠️ 没命中任何落点 = ``ROOT_INPUT``：项目根下确实有不在任何格子里的文件
    （``README.md``、``_work/``），它们的根是资料根。
    """
    rel = rel.replace(os.sep, "/")
    kind, best = ROOT_INPUT, -1
    for landing in PROJECT_DIRS:
        if (rel == landing or rel.startswith(landing + "/")) and len(landing) > best:
            kind, best = root_of(landing), len(landing)
    return kind

#: 中间产物里**不值得留**的那一类（预览、试跑切片、放大前的源）的目录名。
#: 它落引擎的 ``temp/``（原生语义：随时可清），落项目树里的只有 ``_work/`` 那一层。
TEMP_WORK_DIR = "temp"

#: 中间产物里**要留**的那一类放在项目产物根下的哪一级。
#: 前置下划线 = "不是业务格"：不写进 ``PROJECT_DIRS``（不进面板、不进体检），
#: 与 ``_分集大纲.json`` / ``_SEED_PATTERNS`` 同一个记号。
WORK_SUBDIR = "_work"


# ─────────────────────────────────────────────────────────────
# 一·补、生产阶段（S0a–S7a）—— **阶段 ↔ 工作流配合**的事实源
# ─────────────────────────────────────────────────────────────

#: 图片后缀。引擎侧 `flow_core.PNG_EXTS` 是同一份知识的**第二处** —— 本文件要能被
#: 桌面侧按路径直接执行（`projects.py::load_spec`，那时没有包上下文），不能 import
#: 包内任何东西，所以后缀只能各存一份。
#:
#: ⚠️ 「两边不许分家」那道机械核对原先在引擎侧的 `tests/test_stages.py` 里，
#: 而引擎侧目前不在检出里（见本文件开头「现状」）—— 它现在**没有在跑**。
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


@dataclass(frozen=True)
class StageEntry:
    """一个阶段的**一个入口** —— 也就是"这一段怎么跑"。

    `kind="flow"` → `flow -p <项目> --阶段 <key>`（key 是流水线段名）；
    `kind="cli"`  → `main.py <key> …`（key 是 main.py 的子命令）。

    这里**只存字符串，不解析**：本文件要能被桌面侧按路径直接执行，不能 import
    引擎侧的 `flow_core`（还会成环：flow_core → project）。入口是否真实存在，
    本该由机械核对对着 `flow_core.ORDER` / `main.py` 的子命令表 / agent 注册表
    核 —— 防的正是"文档指向一个根本不存在的入口"。⚠️ 引擎侧不在检出里时，
    这道核对也没在跑（见本文件开头「现状」）。
    """
    kind: str
    key: str
    cmd: str
    agent: str = ""


@dataclass(frozen=True)
class StageSpec:
    """一个生产阶段：**谁做 · 产物落哪 · 怎么跑 · 判据在哪**。

    ⚠️ 别在这里复述判据 —— `gate` 只写判据**在哪**（文档章节 / 门禁命令），
    判据本身由引擎侧 `handover.check_gate` 那套执行。复述一份就会分家。
    """
    code: str
    name: str
    owner: str
    landings: tuple
    check_dirs: tuple
    check_exts: tuple
    entries: tuple
    gate: str


#: S0–S7（另加 S0a / S4a / S7a，见下）。`(code, name, owner)` 三项原先由 `tests/test_stages.py` 从
#: `生产流程规范（S0-S7）.md` §一 与 `流程与落点映射.md` §一 抽表对拍 ——
#: ⚠️ 那两份文档与那个测试目前都不在检出里（见本文件开头「现状」），
#: 所以这份表是**当前唯一**的阶段口径。
#:
#: `landings` 用 `PROJECT_DIRS` 里的相对路径（不另造一套路径写法）；
#: `check_dirs` / `check_exts` 是**体检**口径。
#:
#: 除 S0–S7 外另有三个**补进来的段**（代号带字母后缀，位置就是它在链上的位置）：
#: `S0a`（原文解析）、`S4a`（对白与旁白）、`S7a`（短剧合成）。
#: 它们原先在这条链上**没有落点**：原文只能是"整篇塞进提示词"、对白表有目录有种子却
#: **没有任何一段负责填**、镜头的成片谁也说不清在哪一步合成。补段而不重排 S0–S7 的
#: 编号：老编号是别处（工作流、进度账、面板文案）已经在用的口径，动它换不来任何东西。
#:
#: ⚠️ 新段的 `entries` 指向**宿主侧**的流水线命令（`comfy_studio.pipeline`）——
#: 那是本检出里真实存在、跑得起来的入口；不照抄 S0–S7 那几条 `main.py flow`，
#: 因为那几条指向的是引擎侧，而引擎侧当前不在检出里（见本文件开头「现状」）。
#: 写一个"看起来齐整但根本不存在的入口"，正是 :class:`StageEntry` 要防的那件事。
STAGE_SPECS = (
    StageSpec(
        code="S0a", name="原文解析", owner="01 剧本文本",
        landings=("00_PROJECT/00_原文解析",),
        # 只查这一个目录：它是本段**独占**的落点。不把 00_总纲 或 02_资产索引 拿来共用 ——
        # 那两个目录分别由 S0 / S1 判"完成"，共用之后"原文解析跑过"会被读成"建纲跑过"，
        # 而这两件事差着十万八千里。
        check_dirs=("00_PROJECT/00_原文解析",), check_exts=(".md", ".json"),
        entries=(StageEntry("cli", "pipeline",
                            "python -m comfy_studio.pipeline --project <项目> "
                            "--from S0a --to S0a"),),
        gate="宿主侧流水线的分段报告（comfy_studio.pipeline 的 state）；"
             "这一段只产文本解析，无引擎侧门禁",
    ),
    StageSpec(
        code="S0", name="建纲", owner="01 剧本文本",
        landings=("00_PROJECT/01_剧本", "00_PROJECT/01_剧本/00_总纲",
                  "00_PROJECT/03_台账"),
        # 只查 01_剧本：00_总纲 是它的子目录，_hits 会递归进去；03_台账 会被预置空表，
        # 拿它判"完成"就是自欺 —— 这两者都不该单列进 check_dirs。
        check_dirs=("00_PROJECT/01_剧本",), check_exts=(".md",),
        entries=(StageEntry("flow", "建纲",
                            "python main.py flow -p <项目> --阶段 建纲"),),
        gate="生产流程规范（S0-S7）.md §一；门口那条 = python main.py gate script <交付包>",
    ),
    StageSpec(
        code="S1", name="资产设计", owner="02 服化道",
        landings=("00_PROJECT/02_资产索引", "00_PROJECT/04_交付与出图"),
        check_dirs=("00_PROJECT/02_资产索引",), check_exts=(".md",),
        entries=(StageEntry("flow", "资产",
                            "python main.py flow -p <项目> --阶段 资产"),),
        gate="生产流程规范（S0-S7）.md §一；门口那条 = python main.py gate asset <交付包>",
    ),
    StageSpec(
        code="S2", name="出图", owner="02 服化道",
        landings=("02_CHARACTERS", "03_COSTUMES", "04_PROPS", "05_ENVIRONMENTS"),
        check_dirs=("02_CHARACTERS", "03_COSTUMES", "04_PROPS", "05_ENVIRONMENTS"),
        check_exts=IMAGE_EXTS,
        entries=(
            StageEntry("cli", "angles",
                       "python main.py angles <ENV_ID>   # 场景六角度"),
            StageEntry("cli", "ask",
                       'python main.py ask "赛博朋克女刺客，黑衣"   # 角色/服装/道具定妆板'),
        ),
        gate="生产流程规范（S0-S7）.md §一（三视图是同一人；场景六角度空间一致）",
    ),
    StageSpec(
        code="S3", name="表情 / 动作", owner="02 服化道",
        landings=("06_EXPRESSIONS", "07_POSES"),
        check_dirs=("06_EXPRESSIONS", "07_POSES"), check_exts=IMAGE_EXTS,
        entries=(
            StageEntry("cli", "ask",
                       'python main.py ask "给 CHR_001 出一套表情集"'),
            StageEntry("cli", "run",
                       'python main.py run asset "给 CHR_001 出一套动作集"',
                       agent="asset"),
        ),
        gate="生产流程规范（S0-S7）.md §一（派生 ID 只在主 ID ≥ DRAFT 时才建）",
    ),
    StageSpec(
        code="S4", name="分镜", owner="03 分镜导演",
        landings=("08_STORYBOARDS",),
        check_dirs=("08_STORYBOARDS",), check_exts=(".md", ".json"),
        entries=(
            StageEntry("flow", "分镜", "python main.py flow -p <项目> --阶段 分镜"),
            StageEntry("flow", "首帧", "python main.py flow -p <项目> --阶段 首帧"),
        ),
        gate="生产流程规范（S0-S7）.md §一；门口那条 = python main.py gate storyboard <交付包>",
    ),
    StageSpec(
        code="S4a", name="对白与旁白", owner="01 剧本文本",
        landings=("00_PROJECT/06_对白/对白稿",),
        # 查的是子目录 `对白稿/`，**不是** 06_对白 根：根下放着种子空表
        # （对白表_EP01.md / 配音单_EP01.md），而体检"这份还算空表吗"只读种子文件
        # —— 种子一旦落在某段的 check_dirs 里，那条优化就不等价了
        # （由 tests/test_projects.py 的 test_seed_files_never_land_inside_a_stage_drop_point 钉住）。
        # 与 S6 不冲突：S6 只查 11_AUDIO（声音产物），理由见那一段的注释 ——
        # "稿子写完"不等于"声音做完"。
        check_dirs=("00_PROJECT/06_对白/对白稿",), check_exts=(".md",),
        entries=(StageEntry("cli", "pipeline",
                            "python -m comfy_studio.pipeline --project <项目> "
                            "--from S4a --to S4a"),),
        gate="宿主侧流水线的分段报告；对白/旁白是否与分镜表逐镜对齐，由 S4 的产物对拍",
    ),
    StageSpec(
        code="S5", name="视频", owner="04 视频生成",
        landings=("09_SHOTS",),
        check_dirs=("09_SHOTS",), check_exts=(".mp4", ".mov"),
        entries=(
            StageEntry("flow", "出片", "python main.py flow -p <项目> --阶段 出片"),
            StageEntry("flow", "成片", "python main.py flow -p <项目> --阶段 成片"),
        ),
        gate="生产流程规范（S0-S7）.md §一（镜间连贯：上一镜尾帧接得住下一镜首帧）",
    ),
    StageSpec(
        code="S6", name="音频", owner="05 音乐音频 + 04 视频生成",
        landings=("00_PROJECT/06_对白", "11_AUDIO"),
        # 查 11_AUDIO（音频产物）而不查 00_PROJECT/06_对白：对白表是**人**先填的稿，
        # 会先于配音存在；拿它判"S6 做完"会把"稿子写完"当成"声音做完"。
        check_dirs=("11_AUDIO",), check_exts=(".mp3", ".wav", ".flac", ".m4a"),
        entries=(StageEntry("cli", "run",
                            'python main.py run audio "把 EP01 的对白配出来"',
                            agent="audio"),),
        gate="生产流程规范（S0-S7）.md §一（每条 AUD_ 已登记）",
    ),
    StageSpec(
        code="S7", name="合规", owner="06 合规审核",
        landings=("10_CONSISTENCY",),
        check_dirs=("10_CONSISTENCY",), check_exts=(".md",),
        entries=(StageEntry("cli", "gate", "python main.py gate compliance"),),
        gate="生产流程规范（S0-S7）.md §一（所有 BLOCKING 项 CLOSED 才可发布）",
    ),
    StageSpec(
        code="S7a", name="短剧合成", owner="04 视频生成",
        # 成片落**产物根**（见 ``DIR_ROOTS``）：下游合成要按 ``名[output]`` 注解引用它，
        # 而引擎那条注解读的就是 output 根。留在 ``04_交付与出图``（资料根）里，
        # 要引用就得整份拷过来 —— 而成片动辄几百兆。
        # 那张格子仍然留着，放的是**合成单**：文本稿，落资料根。
        landings=("00_PROJECT/04_交付与出图", "12_FILMS"),
        # 查的是**成片**（视频后缀），不是那张合成单：合成单是"要怎么合"的稿，
        # 它先于成片存在。拿 .md 判"合成完成"就是拿计划当结果。
        check_dirs=("12_FILMS",), check_exts=(".mp4", ".mov", ".mkv"),
        entries=(StageEntry("cli", "pipeline",
                            "python -m comfy_studio.pipeline --project <项目> "
                            "--from S7a --to S7a"),),
        gate="生产流程规范（S0-S7）.md §一（逐镜对齐 · 音画同步 · 总时长）；"
             "宿主侧只出合成单，真正的合成在引擎侧",
    ),
)

#: 阶段的顺序（S0a → S7a，即 `STAGE_SPECS` 的排列）。面板/报告按它摆，别让每个消费者自己排一遍。
STAGE_ORDER = tuple(s.code for s in STAGE_SPECS)
STAGE_BY_CODE = {s.code: s for s in STAGE_SPECS}


# ─────────────────────────────────────────────────────────────
# 工作台的八个步骤：机器侧 11 段 ≠ 用户要走的 8 步
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WorkStep:
    """工作台上的一步：**用户视角**的一段活，可以盖住 0～2 个机器阶段。

    ⚠️ 步骤的先后是**创作顺序**，不等于 :data:`STAGE_ORDER` 那条生产链。两处不一致是
    **故意的**，不是没对齐：用户先想清楚"谁在这、穿什么、这一场怎么拍"再写分镜，
    而机器侧 S1（资产设计）与 S4（分镜）之间还夹着 S2/S3 两段出图。面板照这里的顺序
    摆导航，**跑起来仍然按 ``STAGE_ORDER``** —— 见 :func:`step_stages`。

    ``stages`` 允许为空（见 ``style``）：视觉风格是一段**校订**的活，没有独立的机器阶段，
    它的产物（``01_WORLD``）由智能体写、由这一步的人拍板，不由流水线跑。
    硬给它挂一个阶段，只会让"跑这一步"这个按钮变成一个不知道会跑出什么的东西。
    """

    key: str
    name: str
    goal: str
    #: 这一步负责的阶段（``STAGE_ORDER`` 的子集；可能是空元组）。
    stages: tuple
    #: 这一步看得见、改得动的落点（``PROJECT_DIRS`` 里的相对路径）。
    landings: tuple
    #: 上游步骤的 key：这几步没做完，本步就是缺料。面板照它提示"先跑哪一步"。
    needs: tuple
    #: 一句话的注意（面板当提示用，别在这里复述判据）。
    note: str = ""


#: 工作台的八个步骤，**顺序就是用户要走的顺序**。
#:
#: 与 :data:`STAGE_SPECS` 的分工：阶段表回答"谁做 · 落哪 · 怎么跑 · 判据在哪"，
#: 这张表回答"用户在界面上按什么顺序走、每一步该看见哪些格子"。两者**都要**，
#: 因为它们是两件事：一条生产链分不出"先定风格还是先写分镜"这种**人的**先后。
#:
#: 三条不变量由 :func:`step_gaps` 盯着（单测钉住它为空）：
#: 每个阶段恰好属于一步、每个落点恰好被一步认领、``needs`` 指向的 key 真是一步。
#: 少盯一条的失效模式都是**静默**的：那一段不在导航里、或者同一段出现两次，
#: 而界面上什么都不会报错 —— 只会有人以为"这一步本来就没有"。
WORKBENCH_STEPS = (
    WorkStep(
        key="parse", name="小说文本解析",
        goal="把原著读成机器能用的东西：人物表、场景表、分卷与篇幅，"
             "并标出书里没写清、要人拍板的地方。",
        stages=("S0a",),
        landings=("00_PROJECT/00_原文解析", "00_PROJECT/07_素材归档"),
        needs=(),
        note="原文从「资料库 · 书库」导入。这一段只读原文，不改原文。",
    ),
    WorkStep(
        key="cast", name="角色与场景提取",
        goal="把解析结果定成一份谁能引用的清单：建纲、角色/服装/道具/场景的资产索引，"
             "以及这些资产各自的 ID 与口径。",
        stages=("S0", "S1"),
        landings=("00_PROJECT/01_剧本", "00_PROJECT/01_剧本/00_总纲",
                  "00_PROJECT/02_资产索引", "00_PROJECT/03_台账"),
        needs=("parse",),
        note="资产 ID 一旦定了就是全剧引用它的钥匙；改 ID 等于改所有引用它的地方。",
    ),
    WorkStep(
        key="board", name="分镜脚本",
        goal="把一集拆成一个个镜头：景别、机位、运镜、时长，每一镜一行。",
        stages=("S4",),
        landings=("08_STORYBOARDS",),
        needs=("cast",),
        note="分镜表是下游所有产物的**对齐全凭据**：对白要跟它逐镜对齐，出图要按它取镜。",
    ),
    WorkStep(
        key="dialogue", name="对话与旁白",
        goal="把每一镜的台词、旁白、音效点补齐，并标出谁在说、用什么语气。",
        stages=("S4a",),
        landings=("00_PROJECT/06_对白", "00_PROJECT/06_对白/对白稿"),
        needs=("board",),
        note="目录里那两张表是**建项目时预置的空表**；成稿落在「对白稿」这一格。",
    ),
    WorkStep(
        key="style", name="视觉风格",
        goal="定下这一部戏长什么样：世界观与美术基调、色调与材质、"
             "以及每个人物/场景怎么被画出来。",
        stages=(),
        landings=("01_WORLD", "03_COSTUMES"),
        needs=("cast",),
        note="这一步没有独立的机器阶段：产物由智能体写、由你拍板，不归流水线跑。"
             "口径定在这里，下一步的提示词才有地方抄。",
    ),
    WorkStep(
        key="prompts", name="图像与视频提示词",
        goal="把风格落成一条条能直接喂给模型的提示词，并按提示词把资产图、"
             "表情集、动作集真的出出来。",
        stages=("S2", "S3"),
        landings=("00_PROJECT/04_交付与出图", "02_CHARACTERS", "04_PROPS",
                  "05_ENVIRONMENTS", "06_EXPRESSIONS", "07_POSES"),
        needs=("style",),
        note="提示词里的人物外观**照抄**风格那一步的口径，不要在这里临时发挥。",
    ),
    WorkStep(
        key="video", name="视频生成",
        goal="逐镜出片：首尾帧接得住、镜间连贯，同时把对白与音效配出来。",
        stages=("S5", "S6"),
        landings=("09_SHOTS", "11_AUDIO"),
        needs=("prompts",),
        note="耗时最长、最占显卡的一步；一镜不要了就在这一格删，别去动分镜表。",
    ),
    WorkStep(
        key="cut", name="短剧合成",
        goal="把镜头、声音、字幕合成成片，跑一遍合规项，交出一部能发布的短剧。",
        stages=("S7", "S7a"),
        landings=("10_CONSISTENCY", "00_PROJECT/05_流程", "12_FILMS"),
        needs=("video", "dialogue"),
        note="合成单与成片是两件事：写完成合单不等于合成完了，成片才是结果。",
    ),
)

#: 步骤 key → 那一步。与 ``STAGE_BY_CODE`` 平行。
STEP_BY_KEY = {step.key: step for step in WORKBENCH_STEPS}

#: 步骤的先后（= ``WORKBENCH_STEPS`` 的排列）。导航与"下一步"都按它来，别各自排一遍。
STEP_ORDER = tuple(step.key for step in WORKBENCH_STEPS)

#: 阶段 → 步骤。由 :func:`step_gaps` 保证每个阶段都在里面。
STEP_BY_STAGE = {code: step.key for step in WORKBENCH_STEPS for code in step.stages}


def step_of_stage(code: str) -> str:
    """这个机器阶段归工作台哪一步。

    不在任何一步里是**配置错误**（"这段在界面上没有家"），显式抛错而不是返回空串 ——
    返回空串的失效模式是那一段从导航里**静静地**消失，而报告一切正常。
    """
    key = STEP_BY_STAGE.get(code)
    if key is None:
        raise ProjectError(
            "阶段 %r 不属于工作台任何一步：WORKBENCH_STEPS 里漏了它" % (code,)
        )
    return key


def step_stages(key: str) -> tuple:
    """某一步要跑的阶段，**一律按 ``STAGE_ORDER``**排。

    表里写的先后只当"这一步盖住哪些阶段"用，不当执行顺序 ——
    执行顺序全仓只有 ``STAGE_ORDER`` 一处说了算（流水线也是照它跑的）。
    两处各排一遍的失效模式是：面板上写着"先 S3 再 S2"，跑起来正好颠倒。
    """
    step = STEP_BY_KEY.get(key)
    if step is None:
        raise ProjectError("没有这一步：%r（八步见 WORKBENCH_STEPS）" % (key,))
    return tuple(code for code in STAGE_ORDER if code in step.stages)


def step_gaps() -> tuple:
    """工作台步骤表与三份事实源对不上时的那几条（空元组 = 一切对齐）。

    与 :func:`shelf_gaps` 同一个道理：**报出来**，不让它悄悄少显示一段。
    单测对真表钉住它为空 —— 改了 ``PROJECT_DIRS`` / ``STAGE_SPECS`` 而没跟上这张表时，
    那一条断言会当场炸，而不是等用户在界面上发现"少了一步"。
    """
    problems: list = []
    seen: dict = {}
    for step in WORKBENCH_STEPS:
        for code in step.stages:
            if code not in STAGE_BY_CODE:
                problems.append("步骤 %s 挂着不存在的阶段 %r" % (step.key, code))
            elif code in seen:
                problems.append("阶段 %s 同时挂在 %s 与 %s 两步上" % (code, seen[code], step.key))
            else:
                seen[code] = step.key
        for rel in step.landings:
            if rel not in PROJECT_DIRS:
                problems.append("步骤 %s 认领了不存在的落点 %r" % (step.key, rel))
        for need in step.needs:
            if need not in STEP_BY_KEY:
                problems.append("步骤 %s 的上游 %r 不是一步" % (step.key, need))
    for code in STAGE_ORDER:
        if code not in seen:
            problems.append("阶段 %s 不在工作台任何一步里" % code)
    # 落点也要盖满：没被任何一步认领的格子只在「资料库」里露脸，
    # 用户在步骤流里永远走不到它 —— 那正是"面板很乱但东西找不到"的那种乱。
    claimed = {rel for step in WORKBENCH_STEPS for rel in step.landings}
    for rel in PROJECT_DIRS:
        if rel not in claimed:
            problems.append("落点 %s 不属于任何一步" % rel)
    return tuple(problems)


def stage_how(code: str) -> str:
    """某一段「怎么跑」的第一条入口（给人看的命令）。

    没有入口的阶段是**配置错误**（"这段没人管"），显式抛错而不是返回空串 ——
    返回空串的失效模式是报告里那一行静静地不见了。
    """
    spec = STAGE_BY_CODE.get(code)
    if spec is None:
        raise ProjectError("没有这个阶段：%r（S0a–S7a 见 STAGE_SPECS）" % (code,))
    if not spec.entries:
        raise ProjectError("阶段 %s 在 STAGE_SPECS 里没有入口：它没人管" % code)
    return spec.entries[0].cmd


#: 建项目时预置的空表：(模板文件名, 项目内目标相对路径)。
#: **只补库里没有对应模板的部分** —— 剧本模板、ID 注册表模板等已有权威，
#: 复制一份等于「同一知识两处维护」，故不在此列。
SEED_FILES = (
    ("项目README.md", "README.md"),
    ("00_先读我.md", "00_PROJECT/00_先读我.md"),
    ("单元进度台账.md", "00_PROJECT/05_流程/单元进度台账.md"),
    ("对白表_EPxx.md", "00_PROJECT/06_对白/对白表_EP01.md"),
    ("配音单_EPxx.md", "00_PROJECT/06_对白/配音单_EP01.md"),
    ("素材来源登记.md", "00_PROJECT/07_素材归档/素材来源登记.md"),
    ("归档清单.md", "00_PROJECT/07_素材归档/归档清单.md"),
)


def _seed_episode_pattern(dst: str):
    """把种子表的某个目标路径变成"按集号放宽"的匹配式。

    ``create_project`` 只造 ``EP01`` 那几份，可"第 2 集的空对白表"是同一种东西。
    逐字相等的失效模式是：EP02 的空表被当成**已完成的产物**，进度自己往前跳一格。
    """
    return re.compile("^" + re.escape(dst).replace("EP01", r"EP\d+") + "$")


#: 预置空表的路径匹配式（由 :data:`SEED_FILES` 生成，不另抄一份路径）。
_SEED_PATTERNS = tuple(_seed_episode_pattern(dst) for _src, dst in SEED_FILES)


def _matches_seed(patterns, rel) -> bool:
    """``rel`` 命中 ``patterns`` 里任意一条吗（反斜杠先归正，非字符串一律不算）。"""
    if not isinstance(rel, str):
        return False
    posix = rel.replace("\\", "/")
    return any(pattern.match(posix) for pattern in patterns)


def seed_predicate(seed_files):
    """按一份 ``SEED_FILES`` 造"这一份是不是预置空表"的谓词（``EP01`` 按集号放宽）。

    **按参数生成**，不只认模块自己那份：``projects`` 载入的规范可能是**替换实现**
    （``--spec <路径>`` 或测试里那份最小规范），它未必带 :func:`is_seed_path`，那时
    得退回"照它自己的 ``SEED_FILES`` 判"。放宽规则只写在这一处 —— 两边各抄一份的下场
    不是报错，是同一张 EP02 空对白表在一边算空表、在另一边算产物，面板上的进度自己跳。
    """
    patterns = tuple(_seed_episode_pattern(str(dst)) for _src, dst in seed_files or ())

    def _is_seed(rel) -> bool:
        return _matches_seed(patterns, rel)

    return _is_seed


def is_seed_path(rel: str) -> bool:
    """这一份是不是**建项目预置的空表**（``EP01`` 那一小段按集号放宽）。

    为什么处处要问这一句：预置空表**不是**"这一段做过了"。不区分的话，刚建完项目
    八步工作台就有几步自己"有料"了 —— 用户看见的是空模板，界面说的是有产物。
    这与 ``scan_project`` 里"体检不复读种子文件"是同一个判断（那里用 :func:`_seed_rel_paths`，
    只认逐字相等；这里多认集号，因为面板会把每一集都列出来）。
    """
    return _matches_seed(_SEED_PATTERNS, rel)

#: 阶段产物体检：(阶段名, 落点元组, 匹配后缀)。后缀为空表示"该目录下有任意文件"。
#: **从 `STAGE_SPECS` 派生，不另抄一份** —— 抄一份的失效模式是"体检表里的 S7 还叫
#: 一致性、阶段表里的 S7 叫合规"，两边都不报错，面板上就多了一段谁也对不上的东西。
#: 只探**实质产物目录** —— `03_台账/` `05_流程/` 等会被预置空表，用它们判"已完成"
#: 会得到假阳性（建完项目就显示"S0 已完成"，那是自欺）。
STAGE_OUTPUTS = tuple(
    ("%s %s" % (s.code, s.name), s.check_dirs, s.check_exts)
    for s in STAGE_SPECS
    if s.check_dirs
)

#: v1 → v2 的**结构**迁移：(老相对路径, 新相对路径)。
#: 只搬**全剧级**数据 —— `EP##-剧本.md`（分集级）原地不动。
#: 原先与 `项目目录规范.md` §四 的映射表逐行对应；⚠️ 那份文档目前不在检出里
#: （见本文件开头「现状」），所以这份表是**当前唯一**的迁移口径。
#:
#: `_分集大纲.json` 必须一起搬：它是大纲的机器可读事实源，
#: `pipeline.OUTLINE_JSON` 读的就是它。留在老位置 = 建纲阶段**读不到就重写一份**，
#: 静默地把人改过的大纲覆盖成模型新生成的 —— 正是迁移要防的那种失败。
MIGRATIONS = (
    ("00_PROJECT/01_剧本/分集大纲与三表.md",
     "00_PROJECT/01_剧本/00_总纲/分集大纲与三表.md"),
    ("00_PROJECT/01_剧本/_分集大纲.json",
     "00_PROJECT/01_剧本/00_总纲/_分集大纲.json"),
    ("00_PROJECT/01_剧本/角色小传.md",
     "00_PROJECT/01_剧本/00_总纲/角色小传.md"),
)


# ─────────────────────────────────────────────────────────────
# 二、工作区 / 项目定位（**全部动态探测，不写死机器路径**）
# ─────────────────────────────────────────────────────────────

def find_workspace(start=None) -> str:
    """往上找「工作区根」：含 `projects/` 的那一级。

    实测布局：`<工作区>/projects/<项目名>/`、`<工作区>/novel/*.txt`。

    ⚠️ 这是**兜底**，不是主路径：本文件住在宿主包内，包的工作目录之上
    通常没有 `projects/`，于是它返回空串。宿主侧一律显式给项目根
    （``--project-dir`` / ``--comfyui-dir``），别指望这里猜出来。
    """
    d = os.path.abspath(str(start or HERE))
    for _ in range(6):
        if os.path.isdir(os.path.join(d, "projects")):
            return d
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return ""


def projects_root() -> str:
    """**资料根**：环境变量 `VOIDE_PROJECTS_ROOT` 优先，否则动态探测。

    与 :func:`projects_out_root` 是**两个根**（见 :data:`DIR_ROOTS`）。宿主侧一律显式给
    （``--project-dir`` / ``--comfyui-dir``，统一由 :mod:`.layout` 算出来）——
    这个函数只在"拿路径直接跑本文件"时才是主路径。
    """
    env = os.getenv("VOIDE_PROJECTS_ROOT")
    if env:
        return os.path.abspath(env)
    ws = find_workspace()
    return os.path.join(ws, "projects") if ws else ""


def projects_out_root() -> str:
    """**产物根**：环境变量 `VOIDE_PROJECTS_OUT_ROOT` 优先。

    没配就回**空串**，含义是"单树布局"：产物与资料落同一个根（见 :func:`out_root_for`）。
    这不是兜底，是一种正式配置 —— 只有一部剧、不跑合成的时候，分成两个根只是多一层要维护的东西；
    而且它让"今天只认一个根的调用方"一行都不用改。
    """
    env = os.getenv("VOIDE_PROJECTS_OUT_ROOT")
    return os.path.abspath(env) if env else ""


def out_root_for(path: str, *, root: str = None, out_root: str = None) -> str:
    """给一个**资料根下的项目目录**，推它的产物根；推不出来就回它自己（单树）。

    **两个根**：`root` / `out_root` 给了就用它们，不给就按环境变量（宿主侧惯用的
    `--project-dir` / `--project-out-dir` 走的就是这一条）。显式给不是为了省事：
    宿主自己知道两个根在哪（它算过），而环境变量**可能没设** —— 那时这里会去
    `projects_root()` 往上找 `projects/`，推出的落点跟面板看到的**不是同一个**。

    "推不出来"有两种，都不报错：
    ① 没配产物根（`out_root` 与环境变量都没有）；
    ② 给的路径不在 `root` 底下（调用方自己挑的目录，无从推算同级）——
       这一条尤其重要：单测与 ``--project-dir`` 常常就是这么给的，
       它们要的是"跟以前一模一样"，不是"猜一个新的落点出来"。
    """
    out = os.path.abspath(out_root) if out_root else projects_out_root()
    base = os.path.abspath(root) if root else projects_root()
    if not out or not base:
        return path
    try:
        rel = os.path.relpath(path, base)
    except ValueError:                       # Windows 上跨盘，relpath 直接抛
        return path
    if rel == os.curdir or rel.startswith(os.pardir):
        return path
    return os.path.normpath(os.path.join(out, rel))


def list_projects() -> list:
    d = projects_root()
    if not d or not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d)
                  if os.path.isdir(os.path.join(d, n)) and not n.startswith("."))


def resolve_project(name_or_path: str, *, must_exist: bool = True,
                    kind: str = ROOT_INPUT, root: str = None,
                    out_root: str = None) -> str:
    """把「项目名」或「路径」统一成**某个根下的**项目目录绝对路径。

    ``kind=ROOT_INPUT``（默认）解析**资料根**，``kind=ROOT_OUTPUT`` 解析**产物根**。
    单树布局下两者解析出**同一个目录**，所以今天只认一个根的调用方一行都不用改。

    **两个根**（`root` / `out_root`）：给了就用它们，不给就按环境变量与工作区探测。
    宿主侧一律显式给 —— 它自己算过这两个根，而环境变量可能没设（见 `out_root_for`）。

    ⚠️ 解析产物根时**一律传 `must_exist=False`**：成片还没做出来的项目，
    产物根下那个目录本来就还不存在 —— 那不是"项目不存在"，是"还没出片"。
    拿 `must_exist=True` 去问它，会把一个正常状态报成错误。

    给的是名字时到对应的根下找 —— 找不到就**报错并说清怎么修**，
    不要退回一个相对路径继续跑（那会建到错误的目录里）。
    """
    p = str(name_or_path).strip()
    if not p:
        raise ProjectError("项目名不能为空。")
    if os.path.isabs(p) or os.sep in p or "/" in p:
        cand = os.path.abspath(p)
        if kind == ROOT_OUTPUT:
            cand = out_root_for(cand, root=root, out_root=out_root)
    else:
        if kind == ROOT_OUTPUT:
            base = (os.path.abspath(out_root) if out_root else projects_out_root()) or (
                os.path.abspath(root) if root else projects_root())
        else:
            base = os.path.abspath(root) if root else projects_root()
        if not base:
            raise ProjectError(
                "没探测到项目根。两种修法：① 设环境变量 VOIDE_PROJECTS_ROOT 指向 projects 目录；"
                "② 在工作区里建一个 projects/ 目录（宿主侧会从工作区往上找）。")
        cand = os.path.join(base, p)
    # 这一步要**两条路都走**。"给的是路径"不是"这个项目一定在"：`--project D:/x/没这个项目`
    # 是一条最常敲错的命令，而它曾经在 `--plan` 下静默成功、回一份计划 —— 计划看着完全正常，
    # 只是那份计划属于一个不存在的项目。老实现这里是一道贯穿到底的检查，别再提前 return。
    if must_exist and not os.path.isdir(cand):
        raise ProjectError("项目不存在：%s" % cand)
    return cand


# ─────────────────────────────────────────────────────────────
# 四、建项目
# ─────────────────────────────────────────────────────────────

def _render(text: str, mapping: dict) -> str:
    """替换模板占位符；**没给的一律落成 `（待填）`**，不留 `{{X}}`。"""
    def sub(m):
        return str(mapping.get(m.group(1).strip(), PLACEHOLDER))
    return re.sub(r"\{\{([^{}]+)\}\}", sub, text)


def _is_empty_dir(path: str) -> bool:
    return not any(True for _ in os.scandir(path))


def create_project(name: str, *, episodes: int = 12, root: str = None,
                   out_root: str = None, upgrade: bool = False, dry: bool = False,
                   log=print) -> dict:
    """按规范建一个项目（或给已有项目补落点）。

    **两个根**：资料根（`root`，默认 `projects_root()`）与产物根（`out_root`）。
    哪个落点归哪个根由 :data:`DIR_ROOTS` 说了算，这里只分派、不判断。
    `out_root` 不给时跟着 `projects_out_root()`；那个也没配就是**单树布局**
    （产物与资料同一个根），与两个根之前的行为逐字一致 —— 所以老调用方不用改。

    幂等：**已存在的目录与文件一律不覆盖**。`upgrade=True` 时允许目标已存在；
    否则目标已存在就报错（避免把误输入的项目名建到别人项目头上）。

    返回 `{"path", "path_out", "dirs", "dirs_out", "files", "skipped", "pending"}`。
    """
    if episodes < 1:
        raise ProjectError("集数必须 ≥ 1，收到 %r。" % episodes)

    base = projects_root() if root is None else os.path.abspath(root)
    if not base:
        raise ProjectError(
            "没探测到项目根。两种修法：① 设环境变量 VOIDE_PROJECTS_ROOT；"
            "② 在工作区里建 projects/ 目录（宿主侧会自动往上找）。")
    path = os.path.join(base, name)
    # 产物根：显式给的 > 环境变量配的 > **跟着资料根**（单树布局）。
    path_out = os.path.join(
        os.path.abspath(out_root if out_root is not None else (projects_out_root() or base)),
        name)

    if os.path.isdir(path):
        if not upgrade and not _is_empty_dir(path):
            raise ProjectError(
                "项目已存在且非空：%s\n要给它补新增落点，用：python main.py project new %s --升级"
                % (path, name))
    elif os.path.exists(path):
        raise ProjectError("目标已存在且不是目录：%s" % path)

    if not os.path.isdir(TEMPLATE_DIR):
        raise ProjectError("找不到模板目录：%s" % TEMPLATE_DIR)

    result = {"path": path, "path_out": path_out, "dirs": [], "dirs_out": [],
              "files": [], "skipped": [], "pending": []}

    # ① 目录（含 .gitkeep，空目录才存得进版本库）。
    # 每个落点按**自己的根**拼 —— 这里要是图省事全拼在 `path` 下，
    # `09_SHOTS` / `12_FILMS` 就会在资料根里也长出来一格，而引擎那边读不到它
    # （加载类节点只认 input、产物注解只认 output，见 `DIR_ROOTS`）。
    for rel in PROJECT_DIRS:
        parent = path_out if root_of(rel) == ROOT_OUTPUT else path
        full = os.path.join(parent, rel.replace("/", os.sep))
        if os.path.isdir(full):
            result["skipped"].append(rel + "/")
            continue
        if not dry:
            os.makedirs(full, exist_ok=True)
            keep = os.path.join(full, ".gitkeep")
            if _is_empty_dir(full) and not os.path.exists(keep):
                with open(keep, "w", encoding="utf-8") as fh:
                    fh.write("")
        result["dirs" if root_of(rel) == ROOT_INPUT else "dirs_out"].append(rel + "/")

    # ② 预置空表（模板渲染；已存在不覆盖）
    mapping = {
        "项目名": name,
        "集数": episodes,
        "日期": date.today().isoformat(),
        # 新项目落在链的**最前面**那一段：先把原著导入书库，再跑原文解析。
        # （这两句是写进 `单元进度台账.md` 的初始值，人第一眼就看它。）
        "当前阶段": "S0a 原文解析",
        "下一步动作": "把原著导入书库（面板「管理小说」），跑 S0a 原文解析",
    }
    for src, dst in SEED_FILES:
        src_path = os.path.join(TEMPLATE_DIR, src)
        if not os.path.isfile(src_path):
            raise ProjectError("模板缺失：%s（规范与模板必须同时存在）" % src_path)
        # 空表一律落**资料根**：它们是剧本/台账/对白这类要被人打开读、动手改的文本。
        # 真有人往产物根里加一张空表的时候在这里挡住 —— 那种失配不报错的话，
        # 面板上那一格永远是空的，而人对着"项目已建好"的提示找不到东西。
        owner = root_of_path(dst)
        if owner != ROOT_INPUT:
            raise ProjectError(
                "空表 %s 被摆到了产物根（%s）：预置模板只写资料根里的文本稿，"
                "请把它挪到 %s 下的某个落点里。" % (dst, ROOT_OUTPUT, ROOT_INPUT))
        dst_path = os.path.join(path, dst.replace("/", os.sep))
        if os.path.exists(dst_path):
            result["skipped"].append(dst)
            continue
        if not dry:
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            with open(src_path, encoding="utf-8") as fh:
                body = _render(fh.read(), mapping)
            with open(dst_path, "w", encoding="utf-8") as fh:
                fh.write(body)
        result["files"].append(dst)
        result["pending"].append(dst)

    if log:
        verb = "（预演，未落盘）" if dry else ""
        log("项目：%s%s" % (path, verb))
        if os.path.normcase(path_out) != os.path.normcase(path):
            log("产物：%s" % path_out)
        log("目录：新建 %d 个（资料 %d / 产物 %d），已存在 %d 个"
            % (len(result["dirs"]) + len(result["dirs_out"]),
               len(result["dirs"]), len(result["dirs_out"]), len(result["skipped"])))
        log("空表：写出 %d 份（%s）" % (len(result["files"]), "、".join(result["files"]) or "无"))
        if result["pending"]:
            log("⚠️ 这些文件是**空模板**，里面的 %s 要你填：%s"
                % (PLACEHOLDER, "、".join(result["pending"])))
    return result


# ─────────────────────────────────────────────────────────────
# 五、结构迁移（v1 → v2）
# ─────────────────────────────────────────────────────────────

def _same_file(a: str, b: str) -> bool:
    """两份文件内容是否一模一样（按字节比；读不动就当不同 —— 让冲突浮出来）。"""
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def _prune_empty_dirs(root: str) -> None:
    """把 `root` 底下搬空了的目录自下而上收掉（`root` 自己留着）。

    不收的话，搬完之后资料根里会剩一串空壳目录 + `.gitkeep` ——
    面板上那一格仍然"在"，只是永远是空的，而人以为片子还在那儿。
    """
    for cur, _dirs, _files in os.walk(root, topdown=False):
        if os.path.normcase(cur) == os.path.normcase(root):
            continue
        try:
            if not any(True for _ in os.scandir(cur)):
                os.rmdir(cur)
        except OSError:
            pass


def _move_tree(src: str, dst: str, *, dry: bool) -> list:
    """把 `src` 这棵树搬进 `dst`，**逐文件**按「先查目标再动源」判。

    返回 `[(状态, 相对 src 的路径), …]`，状态与 :func:`migrate_project` 那张表同一套。

    为什么不整个目录 `shutil.move`：目标已经有一份的时候，move 会把两棵树**揉在一起**，
    同名文件直接覆盖 —— 正是迁移最该防的那种失败（把人写的正本换成一份旧副本）。
    逐文件才判得出"这一份到底是不是同一份"。
    """
    actions = []
    for cur, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
        for name in sorted(files):
            if name == ".gitkeep":
                continue
            here = os.path.join(cur, name)
            rel = os.path.relpath(here, src)
            there = os.path.join(dst, rel)
            if os.path.isfile(there):
                actions.append(("duplicate" if _same_file(here, there) else "conflict", rel))
                continue
            if not dry:
                # `shutil.move` 而不是 `os.replace`：两个根可能在**不同盘**上
                # （引擎的 output 目录常被单配到别处），`os.replace` 跨卷会直接失败。
                # 目标不存在这件事上面刚查过，所以 move 不会覆盖任何东西。
                os.makedirs(os.path.dirname(there), exist_ok=True)
                shutil.move(here, there)
            actions.append(("moved", rel))
    if not dry and actions and not any(state == "conflict" for state, _r in actions):
        _prune_empty_dirs(src)
    return actions


def migrate_project(name_or_path: str, *, root: str = None, out_root: str = None,
                    dry: bool = False, log=print) -> dict:
    """把老结构的项目升到当前结构（v1 → v2 → v3）—— **只移动，不覆盖，可反复跑**。

    两件事：

    ① `MIGRATIONS`：v1 → v2，同根内把全剧级设定收回 `00_总纲/`；
    ② `PROJECT_DIRS_OUT`：v2 → v3，把该落**产物根**的那两格（`09_SHOTS` / `12_FILMS`）
       整个从资料根挪过去。第 ② 步只在**配了产物根**（两个根不是同一个目录）时才有事可做，
       单树布局下它逐格报 `skip`。

    **两个根**（`root` / `out_root`）：给了就用它们，不给就按环境变量与工作区探测。
    宿主侧一律显式给（它自己算过 `--project-dir` / `--project-out-dir`）——
    环境变量可能没设，那时这里会去 `projects_root()` 往上找 `projects/`，
    推出的产物根跟面板看到的**不是同一个**。而搬错了**不报错**：
    文件好好地在另一个目录里，面板那一格却是空的 —— 事后没人知道东西去哪了。

    每条 `MIGRATIONS` 的判定顺序（**先查目标再动源，绝不先删后写**）：

    ====================  ==========================================================
    源在 / 目标在          动作
    ====================  ==========================================================
    在 / 不在              移动（`dry=True` 时只报不落盘）
    在 / 在（内容相同）     报 `duplicate`，**不删源** —— 删多出来的那份由人决定
    在 / 在（内容不同）     报 `conflict` 并置 `ok=False`，**一个字节都不动**
    不在 / 在              `skip`（上次已经迁过）
    不在 / 不在            `absent`（这个项目本来就没写过这份）
    ====================  ==========================================================

    迁移脚本最坏的失效模式不是报错，是**把人写的正本换成一份旧副本**。
    所以第 3 行（冲突）宁可不迁也要停下来喊人。

    返回 `{"path", "path_out", "actions": [(状态, 源, 目标)], "ok"}`。
    `ok=False` 是"有冲突要人看"，不是脚本自己失败。
    """
    path = resolve_project(name_or_path, root=root, out_root=out_root)
    actions = []
    for src_rel, dst_rel in MIGRATIONS:
        src = os.path.join(path, src_rel.replace("/", os.sep))
        dst = os.path.join(path, dst_rel.replace("/", os.sep))
        src_here, dst_here = os.path.isfile(src), os.path.isfile(dst)

        if src_here and not dst_here:
            if not dry:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(src, dst)
            actions.append(("moved", src_rel, dst_rel))
        elif src_here and dst_here:
            actions.append(("duplicate" if _same_file(src, dst) else "conflict",
                            src_rel, dst_rel))
        elif dst_here:
            actions.append(("skip", src_rel, dst_rel))
        else:
            actions.append(("absent", src_rel, dst_rel))

    # ② 跨根搬落点（v2 → v3）：判据是 `DIR_ROOTS`，不是又抄一份清单 ——
    #    以后再有落点从资料根挪到产物根，改那张表就够了，这里自动跟上。
    out_path = resolve_project(name_or_path, must_exist=False, kind=ROOT_OUTPUT,
                              root=root, out_root=out_root)
    if os.path.normcase(out_path) != os.path.normcase(path):
        for rel in PROJECT_DIRS_OUT:
            label = rel + "/"
            src = os.path.join(path, rel.replace("/", os.sep))
            dst = os.path.join(out_path, rel.replace("/", os.sep))
            if not os.path.isdir(src):
                actions.append(("skip" if os.path.isdir(dst) else "absent", label, label))
                continue
            moved = _move_tree(src, dst, dry=dry)
            if not moved:                # 只有 .gitkeep 的空壳：视为"本来就没有"
                actions.append(("absent", label, label))
                continue
            for state, inside in moved:
                # `inside` 是 `os.path.relpath` 出来的（Windows 上是反斜杠），
                # 而上面那几行与 `MIGRATIONS` 一律用 `/`：不归一的话，同一份清单里
                # 一半是 `00_PROJECT/01_剧本/…`、一半是 `09_SHOTS/EP01\EP01_SH001.mp4`。
                shown = label + inside.replace(os.sep, "/")
                actions.append((state, shown, shown))

    ok = not any(state == "conflict" for state, _s, _d in actions)
    if log:
        label = {
            "moved": "→ 移动",
            "duplicate": "= 目标已有一份（内容相同）",
            "conflict": "✖ 冲突：两边内容不同，**没动**",
            "skip": "· 已迁过",
            "absent": "· 本来就没有",
        }
        log("迁移：%s%s" % (path, "（预演，未落盘）" if dry else ""))
        for state, src_rel, dst_rel in actions:
            log("  %s  %s" % (label[state], src_rel))
            if state in ("moved", "duplicate", "conflict"):
                log("      → %s" % dst_rel)
        if not ok:
            log("⚠️ 有冲突没处理：请人工比对上面两份，脚本不会替你选一份。")
        elif not any(state == "moved" for state, _s, _d in actions):
            log("无需变更：全剧级数据都已在 00_总纲/，该进产物根的也都已经在了。")
        log("提示：引用旧路径的模块提示词与文档要同步改"
            "（搜「分集大纲与三表」「角色小传」）。")
    return {"path": path, "path_out": out_path, "actions": actions, "ok": ok}


# ─────────────────────────────────────────────────────────────
# 六、体检
# ─────────────────────────────────────────────────────────────

#: 遍历时绕开的目录名 —— 生成物，不是资料。
#: `__pycache__` 是原先就绕的那一个。
#: `_work`（:data:`WORK_SUBDIR`）是加这个根划分时一起加的：中间产物不是"这一格有什么"，
#: 数进"文件数"只会让那个数字随一次失败的重跑而跳动，而面板拿它排序（见 ``projects.list``）。
#: ⚠️ 这份表只管**两个项目根里的遍历**，不管 ``temp/``：可弃中间产物压根不进项目树
#: （落引擎的 ``temp/``），所以不必在这里再绕一个 ``temp``。
#: 项目目录在父仓库里、自身不是独立仓库，所以现实中也见不到 `.git`。
PRUNE_DIRS = frozenset({"__pycache__", WORK_SUBDIR})


def _seed_rel_paths() -> frozenset:
    """`SEED_FILES` 的目标相对路径 —— 也就是"**哪些文件可能是空模板**"。

    有这份集合才敢不去读别的文件。老实现给体检里**每一个命中文件**都开一次，
    只为在正文里搜一个 `（待填）`；可可能的答案只在那几张模板落出来的表上 ——
    余下的读盘全是白花的。一部剧动辄上千个文件（`08_STORYBOARDS/` 每镜一份
    md/json 是最大的一块），而 `projects/list` 每开一次面板就要跑一遍。

    ⚠️ 这不是"把判据放宽了"：内置 `STAGE_OUTPUTS` 的每个 `check_dirs` 与
    `SEED_FILES` 的目标路径**无一重叠**，所以对现行规范这是**等价**变换 ——
    `tests/test_projects.py` 里有一条断言专门钉死这一点（不重叠）。
    """
    return frozenset(dst.replace("/", os.sep) for _src, dst in SEED_FILES)


def _looks_like_blank_template(path: str) -> bool:
    """还是空模板吗（正文里含 `（待填）` 就算还没成稿）。读不动就当已成稿。"""
    try:
        with open(path, encoding="utf-8") as fh:
            return PLACEHOLDER in fh.read()
    except (OSError, UnicodeDecodeError):
        return False


def _claimants(path: str) -> dict:
    """`check_dir 绝对路径 → ((阶段序号, 后缀), …)` —— 一次遍历时用来认领文件。

    键是 `normcase` 过的绝对路径（Windows 大小写不敏感）。值是**元组**而非单个
    阶段：一个落点可以被多个阶段同时盯着（S0 与别的段都看全剧级设定时）。
    做成前缀式认领，是因为一个 `check_dir` 下的**子目录**也算它的产物。
    """
    out: dict = {}
    for idx, (_label, rels, exts) in enumerate(STAGE_OUTPUTS):
        for rel in rels:
            key = os.path.normcase(os.path.join(path, rel.replace("/", os.sep)))
            out.setdefault(key, []).append((idx, exts))
    return {key: tuple(value) for key, value in out.items()}


def scan_project(name_or_path: str, *, out_path: str = None) -> dict:
    """体检：落点齐不齐 + 各阶段有没有实质产物 + 有没有老结构没迁。

    返回 `{"path", "path_out", "missing", "legacy", "stages", "files", "files_in",
    "files_out", "mtime", "stage_specs"}`。

    **两个根**："落点齐不齐"按 :data:`DIR_ROOTS` 分别到资料根 / 产物根里查；
    `files` / `mtime` 是**两个根一起**算的 —— 一部剧的体量本来就横跨两边，
    只数一边会得出"这部戏几乎是空的"这种谁也对不上的结论。
    另有 `files_in` / `files_out` 给出拆分：只有"`09_SHOTS` 里有 300 个文件"这种话
    说得出口，人才知道下一步该往哪边看。

    `files` / `mtime` 都是**同一次遍历顺手算出来的**（数文件 + 最近改动），
    调用方不必再各走一遍全树。
    `legacy` 是**还躺在 v1 位置**的全剧级设定 —— 光看"落点齐不齐"是发现不了它的：
    `01_剧本/` 一直都在，只是里面混着两种粒度的东西。
    """
    path = resolve_project(name_or_path)
    # 产物根：显式给的 > 由资料根推 > 就是资料根自己（**单树布局**）。
    out_root = os.path.abspath(out_path) if out_path else out_root_for(path)
    single = os.path.normcase(out_root) == os.path.normcase(path)

    missing = []
    for rel in PROJECT_DIRS:
        base = path if root_of(rel) == ROOT_INPUT else out_root
        if not os.path.isdir(os.path.join(base, rel.replace("/", os.sep))):
            missing.append(rel)
    legacy = [src_rel for src_rel, _dst_rel in MIGRATIONS
              if os.path.isfile(os.path.join(path, src_rel.replace("/", os.sep)))]

    seeds = _seed_rel_paths()
    buckets: list = [[] for _ in STAGE_OUTPUTS]
    total = 0
    counts = {ROOT_INPUT: 0, ROOT_OUTPUT: 0}
    latest = 0.0

    # **一遍走完**。老实现是「按阶段各自走一遍 check_dirs」（S6/S7 的落点还互相重叠），
    # 调用方再「数一遍文件」+「再取一遍最近改动」—— 同一棵树被完整走 5 遍以上，
    # 而 `08_STORYBOARDS/`（每镜一份）通常正是最大的那一块。
    # 这里用**一次** `os.scandir` 递归同时算出：谁有实质产物、一共几个文件、最近动过没有。
    #
    # 为什么不用 `os.walk`：`os.walk` 只交出名字，要 mtime 就得对每个文件再 `os.stat`
    # 一次 —— 等于把每个目录项读两遍。`os.scandir` 的 `DirEntry` 直接带 `stat()`，
    # Windows 上那份数据来自 `FindFirstFile`/`FindNextFile` 的返回，**不再多一次系统调用**。
    # 三千个文件的合成项目上，光是省掉这一次 stat 就把体检又砍掉近一半。
    #
    # `owners` 随栈带下去而不是每层往上重算：`check_dirs` 的前缀式认领在进目录时
    # 只要加一次，整棵树就都不必回看了。
    #
    # 两个根跑同一段代码，只是 `claimants` 各建一份（键是绝对路径，各查各的）。
    # 单树布局下产物根**就是**资料根 —— 那时只走一遍，否则同一棵树会被数两次。
    roots = [(path, ROOT_INPUT)]
    if not single:
        roots.append((out_root, ROOT_OUTPUT))

    for base, kind in roots:
        claimants = _claimants(base)
        stack: list = [(base, ())]
        while stack:
            dirpath, owners = stack.pop()
            owners = owners + claimants.get(os.path.normcase(dirpath), ())
            try:
                entries = list(os.scandir(dirpath))
            except OSError:
                continue

            try:                        # 目录自身也算一次改动（新建空落点就是一次）
                latest = max(latest, os.stat(dirpath).st_mtime)
            except OSError:
                pass

            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in PRUNE_DIRS:
                            stack.append((entry.path, owners))
                        continue
                    if not entry.is_file():
                        continue
                    if entry.name == ".gitkeep":
                        continue
                    stamp = entry.stat().st_mtime
                except OSError:
                    continue
                latest = max(latest, stamp)
                total += 1
                counts[kind] += 1
                if not owners:
                    continue
                # 相对各自那个根 —— 种子表写的是"项目下的哪一级"，
                # 两个根下项目那一层同名，所以同一套路径在两边都成立。
                if entry.path[len(base) + 1:] in seeds and _looks_like_blank_template(entry.path):
                    continue
                lower = entry.name.lower()
                for idx, exts in owners:
                    if exts and not lower.endswith(exts):
                        continue
                    buckets[idx].append(entry.path)

    # `rel` 仍是**字符串**（桌面/面板只把它当文字念），一格有多个落点时用「、」连
    stages = [(label, "、".join(rels), sorted(buckets[idx]))
              for idx, (label, rels, _exts) in enumerate(STAGE_OUTPUTS)]
    return {"path": path, "path_out": out_root, "missing": missing, "legacy": legacy,
            "stages": stages, "files": total,
            "files_in": counts[ROOT_INPUT], "files_out": counts[ROOT_OUTPUT],
            "mtime": latest, "stage_specs": STAGE_SPECS}


def format_report(res: dict) -> str:
    """把体检结果变成人看的文本（`project check` 的输出）。"""
    lines = ["项目：%s" % res["path"], ""]

    if res["missing"]:
        lines.append("落点：⚠️ 缺 %d 个" % len(res["missing"]))
        for rel in res["missing"]:
            lines.append("  ⚠️ 缺 %s" % rel)
        lines.append("  → 修：python main.py project new %s --升级" % os.path.basename(res["path"]))
    else:
        lines.append("落点：✅ 规范里的 %d 个目录全在" % len(PROJECT_DIRS))
    lines.append("")

    if res.get("legacy"):
        lines.append("结构：⚠️ 还是 v1 —— 这些**全剧级**设定还和分集正文平铺在一层：")
        for rel in res["legacy"]:
            lines.append("  ⚠️ %s" % rel)
        lines.append("  → 修：python main.py project migrate %s" % os.path.basename(res["path"]))
        lines.append("")

    lines.append("阶段产物：")
    done = 0
    for label, rel, hits in res["stages"]:
        if hits:
            done += 1
            lines.append("  ✅ %-12s %s（%d 个文件）" % (label, rel, len(hits)))
            continue
        lines.append("  ☐  %-12s %s（还没有实质产物）" % (label, rel))
        # 没做的这一段**顺手把入口念出来** —— 「阶段 ↔ 工作流配合」不该只写在文档里，
        # 敲完 check 就知道下一步敲什么（入口数据出自 STAGE_SPECS，本报告不另编）。
        code = label.split(" ")[0]
        if code in STAGE_BY_CODE:
            lines.append("        → %s" % stage_how(code))
    lines.append("")
    lines.append("进度：%d/%d 段有产物" % (done, len(res["stages"])))
    return "\n".join(lines)
