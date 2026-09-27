#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目脚手架与体检 —— 把 `08-项目管理/项目目录规范.md` 变成可执行的东西。

**为什么要有本文件**：目录规范写在文档里就只能靠人记，而人记的失效模式不是
"报错"，是**静默缺项** —— 新项目漏建 `06_对白/`，两个月后配音单无处落；
漏建 `07_素材归档/`，原著授权到发布前才被发现。本文件把规范变成：

    python main.py project new   <项目名>     # 按规范建全套落点 + 预置空表
    python main.py project check <项目名>     # 缺哪个落点 / 哪一阶段还没产物

**两处一致性**：`PROJECT_DIRS` 必须与规范文档 §一 的目录树逐项一致，
由 `tests/test_project.py` 读那份文档抽树、与本清单比对。
这是本仓库「改权威层必须同步实体层」那条纪律的兜底。

**不写死机器路径**：项目根由 `VOIDE_PROJECTS_ROOT` → 工作区探测得到。
"""

import os
import re
from datetime import date

# 07-智能体运行时/src/ → 07-智能体运行时/ → AI漫剧智能体工作流/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_ROOT = os.path.dirname(ROOT)
SPEC_DIR = os.path.join(WORKFLOW_ROOT, "08-项目管理")
SPEC_FILE = os.path.join(SPEC_DIR, "项目目录规范.md")
TEMPLATE_DIR = os.path.join(SPEC_DIR, "模板")

#: 模板里没被替换掉的占位符一律落成它 —— 让「还没填」看得见，而不是留一个 `{{X}}`
PLACEHOLDER = "（待填）"


class ProjectError(Exception):
    """项目脚手架的错误。**显式抛出，不静默兜底。**"""


# ─────────────────────────────────────────────────────────────
# 一、项目目录清单（**唯一事实源**，必须与规范文档 §一 一致）
# ─────────────────────────────────────────────────────────────

#: 一个项目应有的全部目录，顺序与 `项目目录规范.md` §一 的树一致。
PROJECT_DIRS = (
    "00_PROJECT/01_剧本",
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

#: 阶段产物体检：(阶段名, 相对路径, 匹配后缀)。后缀为空表示"该目录下有任意文件"。
#: 只探**实质产物目录** —— `03_台账/` `05_流程/` 等会被预置空表，用它们判"已完成"
#: 会得到假阳性（建完项目就显示"S0 已完成"，那是自欺）。
STAGE_OUTPUTS = (
    ("S0 建纲", "00_PROJECT/01_剧本", (".md",)),
    ("S1 资产设计", "00_PROJECT/02_资产索引", (".md",)),
    ("S4 分镜", "08_STORYBOARDS", (".md", ".json")),
    ("S5 视频", "09_SHOTS", (".mp4", ".mov")),
    ("S6 音频", "11_AUDIO", (".mp3", ".wav", ".flac", ".m4a")),
    ("S7 一致性", "10_CONSISTENCY", (".md",)),
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
    最后**只留叶子目录** —— 树里的 `00_PROJECT/` 是分组行（它的子目录才是落点），
    与 `PROJECT_DIRS` 的口径一致。
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
        del stack[depth - 1:]
        stack.append(name)
        out.append("/".join(stack))
    # 只留叶子目录：`00_PROJECT/` 这类是**分组行**，它的子目录才是真正的落点。
    return [d for d in out if not any(o.startswith(d + "/") for o in out)]


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
# 五、体检
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
    """体检：落点齐不齐 + 各阶段有没有实质产物。返回结构化结果。"""
    path = resolve_project(name_or_path)
    missing = [rel for rel in PROJECT_DIRS
               if not os.path.isdir(os.path.join(path, rel.replace("/", os.sep)))]
    stages = []
    for label, rel, exts in STAGE_OUTPUTS:
        full = os.path.join(path, rel.replace("/", os.sep))
        hits = _hits(full, exts)
        stages.append((label, rel, hits))
    return {"path": path, "missing": missing, "stages": stages}


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

    lines.append("阶段产物：")
    done = 0
    for label, rel, hits in res["stages"]:
        if hits:
            done += 1
            lines.append("  ✅ %-12s %s（%d 个文件）" % (label, rel, len(hits)))
        else:
            lines.append("  ☐  %-12s %s（还没有实质产物）" % (label, rel))
    lines.append("")
    lines.append("进度：%d/%d 段有产物" % (done, len(res["stages"])))
    return "\n".join(lines)
