# -*- coding: utf-8 -*-
"""全流程的**配置常量 + 公用小工具** —— 2026-09-27 从 `pipeline.py` 切出来。

`pipeline.py` 原本 1547 行塞着三件事：配置常量、公用小工具、流程编排（`Flow` 1000+ 行）。
前两件事跟编排无关，而且别处也用得上（`default_ep` 判最小集、`_md_table` 铺表）。
切出来之后 `pipeline.py` 只剩编排，本文件只管"常量 + 小工具"。

⚠️ 落点清单的唯一事实源仍是 `src/project.py` 的 `PROJECT_DIRS`，
本文件只是 `SKELETON_DIRS = PROJECT_DIRS` 转手（`tests/test_project.py` 盯着这条）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


from . import asset_index
from .project import PROJECT_DIRS, find_workspace, list_projects, projects_root
from .video_provider import find_comfy_root


ROOT = Path(__file__).resolve().parent.parent      # `07-智能体运行时/`
WORKFLOW_ROOT = ROOT.parent                        # `AI漫剧智能体工作流/`

# ── 项目骨架落点（`08-项目管理/项目目录规范.md` §一）──
PROJ = "00_PROJECT"
SCRIPT_DIR = f"{PROJ}/01_剧本"
#: 剧本的**全剧级**设定（分集大纲、角色小传）—— 与上面的分集正文分开住。
#: 判据见规范 §二：**被不止一集引用的，一律全剧级**（v1 时两者平铺在
#: `01_剧本/` 一层，谁属于谁只能靠文件名猜，这就是 v2 要修的东西）。
SCRIPT_META_DIR = f"{SCRIPT_DIR}/00_总纲"
INDEX_DIR = f"{PROJ}/02_资产索引"
LEDGER_DIR = f"{PROJ}/03_台账"
DELIVERY_DIR = f"{PROJ}/04_交付与出图"
#: 建项目时的全套落点。**不要在本文件另抄一份清单** —— 唯一事实源是
#: `src/project.py` 的 `PROJECT_DIRS`，它由 `tests/test_project.py` 与规范文档逐项核对。
#: （历史上这份清单与文档各写一遍，结果 `06_对白/`、`07_素材归档/`、`11_AUDIO/`
#: 挂了很久没人发现 —— 因为缺项不报错。）
SKELETON_DIRS = PROJECT_DIRS
ASSET_DIRS = {"CHR": "02_CHARACTERS", "CST": "03_COSTUMES",
              "PRP": "04_PROPS", "ENV": "05_ENVIRONMENTS"}
PNG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
VER_RE = re.compile(r"_v(\d+(?:\.\d+)?)")

# 四张索引表头 —— 照抄项目里已在用的列（`02_资产索引/*.md`），
# 让模型按表头填，落盘时就不会出现"列对不上"的错位。
IDX_HEADERS = {
    "角色": ["ID", "姓名", "别名", "年龄(EP)", "身份", "社会地位", "外貌要点",
             "关键特征", "出场集", "资产状态"],
    "服装": ["ID", "角色", "服装名", "场合", "时代/阶层", "主色", "材质",
             "状态派生", "出场集", "状态"],
    "道具": ["ID", "名称", "归属", "用途", "尺寸参照", "材料", "状态派生",
             "出场集", "状态"],
    "场景": ["ID", "场景名", "时间", "内/外", "建筑特征", "光源", "主空间关系",
             "出场集", "状态"],
}
IDX_FILE = {"角色": "角色索引（INDEX_CHARACTER）.md",
            "服装": "服装索引（INDEX_COSTUME）.md",
            "道具": "道具索引（INDEX_PROP）.md",
            "场景": "场景索引（INDEX_ENVIRONMENT）.md"}
IDX_TITLE = {"角色": "CHARACTER INDEX", "服装": "COSTUME INDEX",
             "道具": "PROP INDEX", "场景": "ENVIRONMENT INDEX"}

# ⚠️ 台词语速与兜底目标时长**不在这里** —— 唯一来源是 `storyboard.CPS` 与
#    `storyboard.TARGET_SEC`（节奏常数与分镜算法同处一文件，改了要一起重跑分镜）。
#    这里曾各存一份同值副本（`LINE_CPS = 4.5` / `TARGET_SEC = 105.0`），2026-09-27 删掉：
#    同值副本的失效模式是"改一处、另几处静默失效"，本文件不再持有任何时长常数。
LINE_SHARE = 0.55         # 一集里台词占多少时间（其余是动作段与留白）


class StageError(RuntimeError):
    """阶段失败 —— 一律显式抛出，由 CLI 打成人话。"""


@dataclass(frozen=True)
class Stage:
    key: str
    code: str
    what: str
    llm: bool = False


STAGES: tuple = (
    Stage("建纲", "S0", "小说 → 分集大纲 / 每集剧本 / 角色小传 / ID 注册表 / 未决项表",
          llm=True),
    Stage("资产", "S1", "剧本 → 视觉圣经 + 四张索引 + 生图提示词", llm=True),
    Stage("分镜", "S4", "剧本 → 九列分镜表 + shots_<EP>.json（帧数/首帧/提示词）"),
    Stage("首帧", "S4", "每镜首帧 PNG（ComfyUI 文生图；有资产图时挂参考图）"),
    Stage("出片", "S5", "每镜 mp4（ComfyUI fl2v 时间线，逐镜一跑）"),
    Stage("成片", "S5", "按镜序拼接成片 mp4"),
)
ORDER = [s.key for s in STAGES]
BY_KEY = {s.key: s for s in STAGES}


@dataclass
class StageResult:
    key: str
    ok: bool = True
    detail: str = ""
    files: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    skipped: bool = False


# ─────────────────────────────────────────────────────────────
# 工作区 / 项目定位（**全部动态探测，不写死机器路径**）
# ─────────────────────────────────────────────────────────────
# `find_workspace` / `projects_root` / `list_projects` 的实现已移到 `src/project.py`：
# 项目脚手架需要它们，而脚手架**不能反过来依赖本模块**（会形成循环导入）。
# 上面已从那边导入，`__all__` 继续导出，历史调用方无感。


def default_ep(project: str) -> str:
    """项目里最小的一集（没有剧本时给 EP01）。"""
    d = os.path.join(project, SCRIPT_DIR)
    names = os.listdir(d) if os.path.isdir(d) else []
    eps = sorted(set(re.findall(r"EP\d+", " ".join(names))))
    return eps[0] if eps else "EP01"


# ─────────────────────────────────────────────────────────────
# 小工具
# ─────────────────────────────────────────────────────────────

def _read(path: str) -> str:
    """读文本（utf-8 / `strict`）。

    ⚠️ 与 `asset_index._read()` 是**唯一一处刻意保留的差异**（2026-09-27 核对）：
    那边是 `errors="replace"` —— 读的是**人写的**资产索引/台账表，个别坏字节
    不该让整张表读不出来；这边 `strict` —— 读的是 `config.json`/剧本这类
    **机器产物**，坏编码要当场报，静默替换会把"文件坏了"变成"内容少了几个字"。
    口径仅此一处不同；别处再需要读文本，请复用这两个之一，不要另写第三份。
    """
    with open(path, encoding="utf-8") as f:
        return f.read()


# 名字归一（去空白/全角括号/大小写）—— 与 asset_index 同一套口径，
# 免得"注册表认得出、这里认不出"。
norm_key = asset_index.norm


def auto_frame_workflow() -> str:
    """找本机 ComfyUI 里的「分镜首帧」工作流（找不到返回空串，让 provider 自己报错）。

    为什么按名字找而不是写死路径：工作流 JSON 是**用户资产**，会改名、会加批次，
    写死等于把用户的目录结构钉进代码（也违反"扫描/探测类路径一律不许写死"）。
    """
    root = find_comfy_root()
    if not root:
        return ""
    wf_dir = Path(root) / "user" / "default" / "workflows"
    base = Path(root) / "user" / "default"
    for pat in ("**/*分镜首帧*.json", "**/*首帧*.json", "**/*storyboard*frame*.json"):
        for base_dir in (wf_dir, base):
            hits = sorted(base_dir.glob(pat))
            if hits:
                return str(hits[0])
    return ""


def _load_cfg(root: Path) -> dict:
    p = root / "config.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise StageError(f"config.json 解析失败（{p}）：{e}") from e


def _write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return path


def _md_table(headers: list, rows: list) -> str:
    """按给定表头把 dict 行铺成 markdown 表（缺列补 `—`，多余的列丢掉）。"""
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        cells = []
        for h in headers:
            v = r.get(h, "")
            if isinstance(v, (list, tuple)):
                v = "、".join(str(x) for x in v)
            cells.append(str(v).replace("|", "／").replace("\n", " ").strip() or "—")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def _append_registry_rows(text: str, prefix: str, rows: list) -> tuple:
    """把新行追加到注册表里 `` `PREFIX` `` 那一节的表格尾部，返回 `(新文本, 行数)`。

    为什么按**表头名**映射而不是按列号拼：模板
    （`01-剧本文本/模板/ID-REGISTRY.md` §四）与实际项目文件
    （`## 一、角色段 \\`CHR_\\``）的**列数与顺序都不一样**，按列号拼会错位。
    定位不到那节就抛错 —— 不猜结构。
    """
    m = re.search(rf"^#{{2,4}}.*`{re.escape(prefix)}_`.*$", text, re.M)
    if not m:
        raise StageError(
            f"注册表里找不到 `` `{prefix}_` `` 那一节的标题 —— 请确认它写成"
            f"「## 一、角色段 `CHR_`」这样，或手工补登记")
    lines = text[m.end():].split("\n")
    hi = next((i for i, ln in enumerate(lines) if ln.strip().startswith("|")), -1)
    if hi < 0:
        raise StageError(f"注册表 `{prefix}_` 那节下面没有表格 —— 拒绝往未知结构里追加")
    headers = [c.strip() for c in lines[hi].strip().strip("|").split("|")]
    j = hi + 1
    while j < len(lines) and lines[j].strip().startswith("|"):
        j += 1
    add = 0
    for r in rows:
        cells = [str(r.get(h, "—")).replace("|", "／").strip() or "—" for h in headers]
        lines.insert(j, "| " + " | ".join(cells) + " |")
        j += 1
        add += 1
    return text[:m.end()] + "\n".join(lines), add
