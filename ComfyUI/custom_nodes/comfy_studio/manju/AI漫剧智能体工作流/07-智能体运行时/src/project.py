#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目脚手架与体检 —— 把 `08-项目管理/项目目录规范.md` 变成可执行的东西。

**为什么要有本文件**：目录规范写在文档里就只能靠人记，而人记的失效模式不是
"报错"，是**静默缺项** —— 新项目漏建 `06_对白/`，两个月后配音单无处落；
漏建 `07_素材归档/`，原著授权到发布前才被发现。本文件把规范变成：

    python main.py project new     <项目名>   # 按规范建全套落点 + 预置空表
    python main.py project migrate <项目名>   # v1 老项目升到 v2 结构（只移动，不覆盖）
    python main.py project check   <项目名>   # 缺哪个落点 / 哪一阶段还没产物

**两处一致性**：`PROJECT_DIRS` 必须与规范文档 §一 的目录树逐项一致，
`DIR_SCOPES` 必须与 §三 的「粒度」列逐项一致，都由 `tests/test_project.py`
读那份文档抽出来与本清单比对（`spec_dirs_from_doc` / `spec_scopes_from_doc`）。
这是本仓库「改权威层必须同步实体层」那条纪律的兜底。

**粒度为什么进代码**：规范 §三 给每个数据项标了**粒度**（全剧级 / 分集级）。
它不只是给人看的说明 —— 面板要按粒度分开摆（`00_总纲/` 与分集正文同在一个
`01_剧本/` 下），所以它必须是**机器读得到的数据**（`DIR_SCOPES`），
而不是只有解析 Markdown 才拿得到的一列文字。

**第三份事实源：阶段（S0–S7）**。`STAGE_SPECS` 回答「每一个生产阶段由谁做、
产物落在哪、**怎么跑**、判据在哪」。原先这四件事散在四处 —— `flow_core.STAGES`
（六段）、本文件 `STAGE_OUTPUTS`（六桶）、`生产流程规范（S0-S7）.md` §一（八阶段）、
`流程与落点映射.md` §一（八行）—— **互相不一致也不报错**：用户照着文档敲
`--阶段 表情`，拿到的只有 argparse 的 "invalid choice"，没有任何一处告诉他
「S3 走 `main.py ask`」。故收成一份，并让入口信息（`entries`）能被
`project check` 直接念出来。两份文档由 `tests/test_stages.py` 逐项机械核对。

**为什么有 `migrate`**：v1 把 5 集正文与两份**全剧级**设定（分集大纲与三表、
角色小传）平铺在 `01_剧本/` 一层，归属只能靠看文件名猜。v2 把全剧级的收进
`00_总纲/`。老项目不能靠手拖 —— 手拖的失效模式是**拖错方向还不报错**。

**不写死机器路径**：项目根由 `VOIDE_PROJECTS_ROOT` → 工作区探测得到。
"""

import os
import re
from dataclasses import dataclass
from datetime import date

# 07-智能体运行时/src/ → 07-智能体运行时/ → AI漫剧智能体工作流/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_ROOT = os.path.dirname(ROOT)
SPEC_DIR = os.path.join(WORKFLOW_ROOT, "08-项目管理")
SPEC_FILE = os.path.join(SPEC_DIR, "项目目录规范.md")
TEMPLATE_DIR = os.path.join(SPEC_DIR, "模板")
#: 阶段定义与门禁判据的**权威**总表（"流水线本身"）。
STAGE_SPEC_FILE = os.path.join(WORKFLOW_ROOT, "生产流程规范（S0-S7）.md")
#: 「用户口语 → 阶段 → agent → 命令 → 落点」的映射表。
STAGE_MAP_FILE = os.path.join(SPEC_DIR, "流程与落点映射.md")

#: 模板里没被替换掉的占位符一律落成它 —— 让「还没填」看得见，而不是留一个 `{{X}}`
PLACEHOLDER = "（待填）"


class ProjectError(Exception):
    """项目脚手架的错误。**显式抛出，不静默兜底。**"""


# ─────────────────────────────────────────────────────────────
# 一、项目目录清单（**唯一事实源**，必须与规范文档 §一 一致）
# ─────────────────────────────────────────────────────────────

#: 一个项目应有的全部目录，顺序与 `项目目录规范.md` §一 的树一致。
#: 注意 `00_PROJECT/01_剧本` 是**分集级**落点（每集一份正文），
#: 而 `00_PROJECT/01_剧本/00_总纲` 是**全剧级**落点（跨集共享的设定）—— 两者都要建。
PROJECT_DIRS = (
    "00_PROJECT/01_剧本",
    "00_PROJECT/01_剧本/00_总纲",
    "00_PROJECT/02_资产索引",
    "00_PROJECT/03_台账",
    "00_PROJECT/04_交付与出图",
    "00_PROJECT/05_流程",
    "00_PROJECT/06_对白",
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
#: 由 `tests/test_project.py` 从规范 §三 抽表逐项核对（`spec_scopes_from_doc`）。
DIR_SCOPES = {
    "00_PROJECT/01_剧本": SCOPE_EPISODE,
    "00_PROJECT/01_剧本/00_总纲": SCOPE_WHOLE,
    "00_PROJECT/02_资产索引": SCOPE_WHOLE,
    "00_PROJECT/03_台账": SCOPE_WHOLE,
    "00_PROJECT/04_交付与出图": SCOPE_MIXED,
    "00_PROJECT/05_流程": SCOPE_MIXED,
    "00_PROJECT/06_对白": SCOPE_EPISODE,
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
}


# ─────────────────────────────────────────────────────────────
# 一·补、生产阶段（S0–S7）—— **阶段 ↔ 工作流配合**的事实源
# ─────────────────────────────────────────────────────────────

#: 图片后缀。**必须与 `flow_core.PNG_EXTS` 一样** —— 本文件会被桌面侧按路径直接
#: 执行（`Comfy-Desktop/lib/comfy_studio/projects.py::load_spec`，没有包上下文），
#: 不能 import 包内任何东西，所以后缀只能各存一份；由 `tests/test_stages.py`
#: 机械核对两边不许分家（本仓库对"同一知识两处维护"的一贯处理）。
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


@dataclass(frozen=True)
class StageEntry:
    """一个阶段的**一个入口** —— 也就是"这一段怎么跑"。

    `kind="flow"` → `flow -p <项目> --阶段 <key>`（key 是流水线段名）；
    `kind="cli"`  → `main.py <key> …`（key 是 main.py 的子命令）。

    这里**只存字符串，不解析**：本文件要能被桌面侧按路径直接执行，不能 import
    `flow_core`（还会成环：flow_core → project）。入口是否真实存在，由
    `tests/test_stages.py` 对着 `flow_core.ORDER`、main.py 的子命令表、agent
    注册表核 —— 防的正是"文档指向一个根本不存在的入口"。
    """
    kind: str
    key: str
    cmd: str
    agent: str = ""


@dataclass(frozen=True)
class StageSpec:
    """一个生产阶段：**谁做 · 产物落哪 · 怎么跑 · 判据在哪**。

    ⚠️ 别在这里复述判据 —— `gate` 只写判据**在哪**（文档章节 / 门禁命令），
    判据本身由 `handover.check_gate` 那套执行。复述一份就会分家。
    """
    code: str
    name: str
    owner: str
    landings: tuple
    check_dirs: tuple
    check_exts: tuple
    entries: tuple
    gate: str


#: S0–S7。顺序即 `生产流程规范（S0-S7）.md` §一 与 `流程与落点映射.md` §一 的顺序，
#: 由 `tests/test_stages.py` 从两份文档抽表逐项核对（`(code, name, owner)` 三项）。
#:
#: `landings` 用 `PROJECT_DIRS` 里的相对路径（不另造一套路径写法）；
#: `check_dirs` / `check_exts` 是**体检**口径。
STAGE_SPECS = (
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
)

#: 阶段的顺序（S0 → S7）。面板/报告按它摆，别让每个消费者自己排一遍。
STAGE_ORDER = tuple(s.code for s in STAGE_SPECS)
STAGE_BY_CODE = {s.code: s for s in STAGE_SPECS}


def stage_how(code: str) -> str:
    """某一段「怎么跑」的第一条入口（给人看的命令）。

    没有入口的阶段是**配置错误**（"这段没人管"），显式抛错而不是返回空串 ——
    返回空串的失效模式是报告里那一行静静地不见了。
    """
    spec = STAGE_BY_CODE.get(code)
    if spec is None:
        raise ProjectError("没有这个阶段：%r（S0–S7 见 STAGE_SPECS）" % (code,))
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
#: 与 `项目目录规范.md` §四 的映射表逐行对应。
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

    实测布局：`<工作区>/projects/<项目名>/`、`<工作区>/novel/*.txt`、
    `<工作区>/AI漫剧智能体工作流/07-智能体运行时/`（本文件所在处）。
    """
    d = os.path.abspath(str(start or ROOT))
    for _ in range(6):
        if os.path.isdir(os.path.join(d, "projects")):
            return d
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return ""


def projects_root() -> str:
    """项目根：环境变量 `VOIDE_PROJECTS_ROOT` 优先，否则动态探测。"""
    env = os.getenv("VOIDE_PROJECTS_ROOT")
    if env:
        return os.path.abspath(env)
    ws = find_workspace()
    return os.path.join(ws, "projects") if ws else ""


def list_projects() -> list:
    d = projects_root()
    if not d or not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d)
                  if os.path.isdir(os.path.join(d, n)) and not n.startswith("."))


def resolve_project(name_or_path: str, *, must_exist: bool = True) -> str:
    """把「项目名」或「路径」统一成绝对路径。

    给的是名字时到 `projects_root()` 下找 —— 找不到就**报错并说清怎么修**，
    不要退回一个相对路径继续跑（那会建到错误的目录里）。
    """
    p = str(name_or_path).strip()
    if not p:
        raise ProjectError("项目名不能为空。")
    if os.path.isabs(p) or os.sep in p or "/" in p:
        cand = os.path.abspath(p)
    else:
        root = projects_root()
        if not root:
            raise ProjectError(
                "没探测到项目根。两种修法：① 设环境变量 VOIDE_PROJECTS_ROOT 指向 projects 目录；"
                "② 在工作区里建一个 projects/ 目录（运行时会从 07-智能体运行时/ 往上找）。")
        cand = os.path.join(root, p)
    if must_exist and not os.path.isdir(cand):
        raise ProjectError("项目不存在：%s" % cand)
    return cand


# ─────────────────────────────────────────────────────────────
# 三、从规范文档抽目录树（供测试机械核对，避免"两处清单")
# ─────────────────────────────────────────────────────────────

def spec_dirs_from_doc() -> list:
    """读 `项目目录规范.md` §一 的目录树，抽出其中**要建的目录**（按出现顺序）。

    抽法保守：只认以 `/` 结尾的条目；跳过含 `<` 的（如 `<项目名>/`）
    与含 `…` 的（省略式写法）。文件条目（`README.md`）自然被排除。

    **分组行**（树里标了 `（分组）` 的，如 `00_PROJECT/`）只表达层级、自己不落盘，
    但**仍要进栈** —— 不压栈的话它下级条目的层级会整体串位。v1 用的是
    "只留叶子目录"来蹭掉分组行，那条规则在 `01_剧本/` 下多出 `00_总纲/` 之后
    会把 `01_剧本/` 本身也一起蹭掉（它不再是叶子），所以 v2 改成显式标注。
    代价是：忘标 `（分组）` 的中间层会直接出现在结果里、被
    `tests/test_project.py` 逮住 —— 宁可报错，也不要静默少一个落点。
    """
    if not os.path.isfile(SPEC_FILE):
        raise ProjectError("找不到目录规范：%s" % SPEC_FILE)
    with open(SPEC_FILE, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"```text\n(.*?)```", text, re.S)
    if not m:
        raise ProjectError("规范文档里没找到 §一 的目录树（```text 代码块）：%s" % SPEC_FILE)

    stack = []  # [(深度, 目录名)]
    out = []
    for raw in m.group(1).splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        head = re.match(r"^([│├└─\s]*)(.*)$", line)
        prefix, body = head.group(1), head.group(2)
        parts = body.split()
        if not parts:
            continue
        name = parts[0]
        depth = prefix.count("│") + (1 if ("├" in prefix or "└" in prefix) else 0)
        if not name.endswith("/") or "<" in name or "…" in name:
            continue
        name = name.rstrip("/")
        depth = max(depth, 1)          # depth 是 1-based 层级，栈长度 = depth
        is_group = "（分组）" in body   # 分组行：进栈表达层级，但自己不落盘
        del stack[depth - 1:]
        stack.append(name)
        if not is_group:
            out.append("/".join(stack))
    return out


#: §三 表头里的三个必需列（少一列就说明表被改过，抽出来的东西不能信）。
_SCOPE_TABLE_COLS = ("域", "落点", "粒度")


def spec_scopes_from_doc() -> dict:
    """读 `项目目录规范.md` §三 的数据项表，抽出 `{落点: 粒度}`。

    抽法保守，**只认 §三 那一张表**（`§三` 到下一个 `---`）：§二 里也有一列「粒度」，
    那是给人看的散文式小结；两处都抽就会变成"两份权威"，这里只认 §三。

    一行的「落点」格可以写好几个落点（`\\`A/\\` · \\`B/\\``）—— 它们共享这一行的粒度。
    **不许用 `…` 省略**：省略式写法抽不出来，漏掉的落点会被
    `tests/test_project.py` 的"与 `DIR_SCOPES` 逐项一致"逮住，而不是静默丢失。

    表头少列、格子取不到粒度时**显式报错** —— 抽不出来就返回空表的话，
    守卫会变成"两个空表相等"的假通过。
    """
    if not os.path.isfile(SPEC_FILE):
        raise ProjectError("找不到目录规范：%s" % SPEC_FILE)
    with open(SPEC_FILE, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^## 三、.*?(?=^---$)", text, re.S | re.M)
    if not m:
        raise ProjectError("规范文档里没找到 §三 的数据项表：%s" % SPEC_FILE)
    section = m.group(0)
    rows = [ln for ln in section.splitlines() if ln.strip().startswith("|")]
    if not rows:
        raise ProjectError("§三 里没有任何表格行 —— 表被改成别的写法了？")

    header = [c.strip().strip("*").strip() for c in rows[0].strip().strip("|").split("|")]
    for col in _SCOPE_TABLE_COLS:
        if col not in header:
            raise ProjectError("§三 的表头里没有「%s」列：%r" % (col, header))
    i_land, i_scope = header.index("落点"), header.index("粒度")

    out = {}
    for line in rows[1:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) <= max(i_land, i_scope) or set(cells[0]) <= set("-: "):
            continue  # 分隔行 / 表头行
        scope = cells[i_scope].strip("*").strip()
        if scope not in (SCOPE_WHOLE, SCOPE_EPISODE, SCOPE_MIXED):
            raise ProjectError("§三 里有个不认识的粒度：%r（行：%s）" % (scope, line.strip()))
        for rel in re.findall(r"`([^`]+?)/`", cells[i_land]):
            out[rel] = scope
    if not out:
        raise ProjectError("§三 的「落点」列一个带 `/` 的落点都没抽到 —— 写法变了？")
    return out


# ─────────────────────────────────────────────────────────────
# 三·补、从两份流程文档抽阶段表（供 tests/test_stages.py 机械核对）
# ─────────────────────────────────────────────────────────────

def _table_rows(path: str, section_re: str, where: str) -> list:
    """取一份 Markdown 里某一节的**所有表格行**（原样，含 `|`）。

    节号找不着、或那一节里一行表格都没有 —— 一律**报错**：抽不出来就返回空表的话，
    下游的守卫会退化成"两个空表相等"的假通过。
    """
    if not os.path.isfile(path):
        raise ProjectError("找不到 %s：%s" % (where, path))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(section_re, text, re.S | re.M)
    if not m:
        raise ProjectError("%s 里没找到「%s」那一节（正则：%s）" % (path, where, section_re))
    rows = [ln for ln in m.group(0).splitlines() if ln.strip().startswith("|")]
    if not rows:
        raise ProjectError("%s 的「%s」里没有任何表格行 —— 表被改成别的写法了？" % (path, where))
    return rows


def _cells(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _split_stage(label: str) -> tuple:
    """把 `**S0 建纲**` 拆成 `("S0", "建纲")`。拆不出就报错（**不猜**）。"""
    s = label.strip().strip("*").strip()
    m = re.match(r"^(S\d+)\s*(.*)$", s)
    if not m:
        raise ProjectError("这格不像一个阶段：%r（要写成 `**S0 建纲**`）" % label)
    return m.group(1), m.group(2).strip()


#: §一 那种"一张表管一整个阶段序列"的节，到下一个小节标题为止。
_SECTION_ONE_RE = r"^## 一、.*?(?=^## |^### )"


def spec_stages_from_doc() -> list:
    """读 `生产流程规范（S0-S7）.md` §一 的总表，抽出 `[(编号, 名字, 负责模块), …]`。

    这是**权威表**：阶段编号、名字、负责模块三项以它为准。
    **不许用 `…` 省略阶段** —— 省略式写法抽不出来，会被 `tests/test_stages.py`
    逮成"少了一段"，而不是静默丢失。
    """
    rows = _table_rows(STAGE_SPEC_FILE, _SECTION_ONE_RE, "§一 总表")
    header = [c.strip().strip("*").strip() for c in _cells(rows[0])]
    for col in ("阶段", "负责模块"):
        if col not in header:
            raise ProjectError("§一 的表头里没有「%s」列：%r" % (col, header))
    i_code, i_owner = header.index("阶段"), header.index("负责模块")
    out = []
    for line in rows[1:]:
        cells = _cells(line)
        if len(cells) <= max(i_code, i_owner) or set(cells[0]) <= set("-: "):
            continue                      # 分隔行
        code, name = _split_stage(cells[i_code])
        out.append((code, name, cells[i_owner].strip().strip("*").strip()))
    if not out:
        raise ProjectError("§一 一个阶段都没抽到 —— 写法变了？")
    return out


def spec_stage_map_from_doc() -> list:
    """读 `流程与落点映射.md` §一 主表，抽出 `[(编号, 名字, agent, 第一条命令), …]`。

    「第一条命令」是从「命令」列里第一个反引号取出的**原文**（如
    `flow -p <项目> --阶段 建纲`、`main.py angles <ENV_ID>`）——
    本函数**不解析**它：解析与"这条命令指向的入口是否真的存在"的核对在
    `tests/test_stages.py`（那里才能 import `flow_core` / `main`）。
    """
    rows = _table_rows(STAGE_MAP_FILE, _SECTION_ONE_RE, "§一 主表")
    header = [c.strip().strip("*").strip() for c in _cells(rows[0])]
    for col in ("阶段", "agent", "命令"):
        if col not in header:
            raise ProjectError("§一 的表头里没有「%s」列：%r" % (col, header))
    i_code = header.index("阶段")
    i_agent = header.index("agent")
    i_cmd = header.index("命令")
    out = []
    for line in rows[1:]:
        cells = _cells(line)
        if len(cells) <= max(i_code, i_agent, i_cmd) or set(cells[0]) <= set("-: "):
            continue                      # 分隔行
        code, name = _split_stage(cells[i_code])
        cmds = re.findall(r"`([^`]+?)`", cells[i_cmd])
        if not cmds:
            raise ProjectError("%s %s 那行的「命令」列里没有反引号命令：%r"
                               % (code, name, cells[i_cmd]))
        out.append((code, name, cells[i_agent].strip().strip("*").strip(), cmds[0]))
    if not out:
        raise ProjectError("§一 主表一个阶段都没抽到 —— 写法变了？")
    return out


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
                   upgrade: bool = False, dry: bool = False, log=print) -> dict:
    """按规范建一个项目（或给已有项目补落点）。

    幂等：**已存在的目录与文件一律不覆盖**。`upgrade=True` 时允许目标已存在；
    否则目标已存在就报错（避免把误输入的项目名建到别人项目头上）。

    返回 `{"path", "dirs", "files", "skipped", "pending"}`。
    """
    if episodes < 1:
        raise ProjectError("集数必须 ≥ 1，收到 %r。" % episodes)

    base = projects_root() if root is None else os.path.abspath(root)
    if not base:
        raise ProjectError(
            "没探测到项目根。两种修法：① 设环境变量 VOIDE_PROJECTS_ROOT；"
            "② 在工作区里建 projects/ 目录（运行时会自动往上找）。")
    path = os.path.join(base, name)

    if os.path.isdir(path):
        if not upgrade and not _is_empty_dir(path):
            raise ProjectError(
                "项目已存在且非空：%s\n要给它补新增落点，用：python main.py project new %s --升级"
                % (path, name))
    elif os.path.exists(path):
        raise ProjectError("目标已存在且不是目录：%s" % path)

    if not os.path.isdir(TEMPLATE_DIR):
        raise ProjectError("找不到模板目录：%s" % TEMPLATE_DIR)

    result = {"path": path, "dirs": [], "files": [], "skipped": [], "pending": []}

    # ① 目录（含 .gitkeep，空目录才存得进版本库）
    for rel in PROJECT_DIRS:
        full = os.path.join(path, rel.replace("/", os.sep))
        if os.path.isdir(full):
            result["skipped"].append(rel + "/")
            continue
        if not dry:
            os.makedirs(full, exist_ok=True)
            keep = os.path.join(full, ".gitkeep")
            if _is_empty_dir(full) and not os.path.exists(keep):
                with open(keep, "w", encoding="utf-8") as fh:
                    fh.write("")
        result["dirs"].append(rel + "/")

    # ② 预置空表（模板渲染；已存在不覆盖）
    mapping = {
        "项目名": name,
        "集数": episodes,
        "日期": date.today().isoformat(),
        "当前阶段": "S0 建纲",
        "下一步动作": "把原著放进工作区 novel/，跑 S0 建纲出分集大纲",
    }
    for src, dst in SEED_FILES:
        src_path = os.path.join(TEMPLATE_DIR, src)
        if not os.path.isfile(src_path):
            raise ProjectError("模板缺失：%s（规范与模板必须同时存在）" % src_path)
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
        log("目录：新建 %d 个，已存在 %d 个" % (len(result["dirs"]), len(result["skipped"])))
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


def migrate_project(name_or_path: str, *, dry: bool = False, log=print) -> dict:
    """把 v1 结构的项目升到 v2 —— **只移动，不覆盖，可反复跑**。

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

    返回 `{"path", "actions": [(状态, 源, 目标)], "ok"}`。
    `ok=False` 是"有冲突要人看"，不是脚本自己失败。
    """
    path = resolve_project(name_or_path)
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
            log("无需变更：全剧级数据都已在 00_总纲/。")
        log("提示：引用旧路径的模块提示词与文档要同步改"
            "（搜「分集大纲与三表」「角色小传」）。")
    return {"path": path, "actions": actions, "ok": ok}


# ─────────────────────────────────────────────────────────────
# 六、体检
# ─────────────────────────────────────────────────────────────

def _hits(full: str, exts: tuple) -> list:
    """目录下有实质文件吗（排除 .gitkeep 与 `（待填）` 未成稿的种子文件）。"""
    if not os.path.isdir(full):
        return []
    out = []
    for dirpath, _dirs, files in os.walk(full):
        for fn in sorted(files):
            if fn == ".gitkeep":
                continue
            if exts and not fn.lower().endswith(exts):
                continue
            fp = os.path.join(dirpath, fn)
            if _looks_like_blank_template(fp):
                continue
            out.append(fp)
    return sorted(out)


def _looks_like_blank_template(path: str) -> bool:
    """还是空模板吗（正文里含 `（待填）` 就算还没成稿）。读不动就当已成稿。"""
    try:
        with open(path, encoding="utf-8") as fh:
            return PLACEHOLDER in fh.read()
    except (OSError, UnicodeDecodeError):
        return False


def scan_project(name_or_path: str) -> dict:
    """体检：落点齐不齐 + 各阶段有没有实质产物 + 有没有 v1 老结构没迁。

    返回 `{"path", "missing", "legacy", "stages"}`。
    `legacy` 是**还躺在 v1 位置**的全剧级设定 —— 光看"落点齐不齐"是发现不了它的：
    `01_剧本/` 一直都在，只是里面混着两种粒度的东西。
    """
    path = resolve_project(name_or_path)
    missing = [rel for rel in PROJECT_DIRS
               if not os.path.isdir(os.path.join(path, rel.replace("/", os.sep)))]
    legacy = [src_rel for src_rel, _dst_rel in MIGRATIONS
              if os.path.isfile(os.path.join(path, src_rel.replace("/", os.sep)))]
    stages = []
    for label, rels, exts in STAGE_OUTPUTS:
        hits = []
        for rel in rels:
            hits.extend(_hits(os.path.join(path, rel.replace("/", os.sep)), exts))
        # `rel` 仍是**字符串**（桌面/面板只把它当文字念），一格有多个落点时用「、」连
        stages.append((label, "、".join(rels), sorted(hits)))
    return {"path": path, "missing": missing, "legacy": legacy,
            "stages": stages, "stage_specs": STAGE_SPECS}


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
