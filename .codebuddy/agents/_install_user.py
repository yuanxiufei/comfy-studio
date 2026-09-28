# -*- coding: utf-8 -*-
r"""把本目录（`.codebuddy/agents/`）的子智能体**安装到 CodeBuddy 用户级**。

═══════════════════════════════════════════════════════════════════════
为什么需要「安装」而不是「复制」
═══════════════════════════════════════════════════════════════════════
本目录的 agent 是**项目级**的：它们在 comfy-studio 仓库里被调用，
所以正文里的路径写成**相对漫剧数据根**（`AI漫剧智能体工作流/07-智能体运行时`）。

⚠️ **2026-09-27 起有两个根**（搬迁的后果，见 :data:`MANJU_REL` 的注释）：
本目录住仓库根（= CodeBuddy 的 workspace 根），而正文路径的基准是
`ComfyUI/custom_nodes/comfy_studio/manju/` —— 安装时**分别**绝对化，别混。

用户级（`~/.codebuddy/agents/`）的 agent 会**在本机所有项目里生效** ——
那时 cwd 是别人的项目，相对路径必然失效。所以安装 = 三件事：

  ① **路径绝对化**：把 `AI漫剧智能体工作流/`、`07-智能体运行时/` 这类
     **只可能有一个解释**的写法换成绝对路径，让命令能直接粘去执行；
  ② **声明路径基准**：剩下的**不带盘符**的写法（`02-服化道/…`、`模板/…`）
     本来就无法全局替换（`01-声音设计引擎.md` 是相对**模块目录**、`02-服化道/…`
     是相对**工作流根**），故在正文最前把两种基准**说明白**，而不是硬猜；
  ③ **标注派生关系**：写明权威源与重装命令，防止有人直接改用户级那份
     （改了会在下次安装时**静默丢失**）。

⚠️ **源仍在本目录**（单一权威来源）。用户级那份是**派生物**，不要手改。

═══════════════════════════════════════════════════════════════════════
⚠️ 路径替换**必须单遍**完成（踩过的坑）
═══════════════════════════════════════════════════════════════════════
若分多遍做（先 `AI漫剧智能体工作流` 再 `07-智能体运行时`），第二遍会命中
**第一遍刚生成的那一段**，得到：

    D:/…/agent-voide/AI漫剧智能体工作流/D:/…/agent-voide/AI漫剧智能体工作流/07-智能体运行时

它**不报错**、长得还挺像路径 —— 是最难发现的一类静默错误。
故：① 单遍正则替换；② `convert()` 内置**签名自检**（`路径紧跟另一个盘符路径` 即抛错）。

═══════════════════════════════════════════════════════════════════════
用法
═══════════════════════════════════════════════════════════════════════
    python .codebuddy/agents/_install_user.py             # 安装（覆盖同名）
    python .codebuddy/agents/_install_user.py --校验       # 只比对不写盘（非 0 = 不一致）
    python .codebuddy/agents/_install_user.py --预览       # 只看清单，不写
    python .codebuddy/agents/_install_user.py --卸载       # 删除已装的本批文件
    python .codebuddy/agents/_install_user.py --目标 <目录>  # 换目标（默认 ~/.codebuddy/agents）
    python .codebuddy/agents/_install_user.py --仅移植型   # 只装**移植型**（参考 md 那 6 个，自包含）

⚠️ `--仅移植型` 是**口径**，不是一个可选的小开关：移植型正文**不含本仓库专属路径**
（`test_agents.py` 有断言），所以它们在别的项目里也能独立干活，是最适合用户级的 6 个；
而 7 个 `manju-0N-*` 是**联动型**（规则给路径 + 调本仓库 `07` 的代码），离开本仓库无意义。
无论装、校验、卸载，**三个动作必须带同一个口径**，否则 `--校验` 会把没装的那批报成「缺失」。

⚠️ 仓库自带的校验只覆盖**项目级**（`.codebuddy/agents/`），不含用户级：
    python AI漫剧智能体工作流/07-智能体运行时/tests/test_agents.py
用户级那侧要跑本文件的 `--校验` —— 它按**同一套渲染逻辑**重算后逐字比对，
于是能抓到两类静默问题：**改了源却没重装** ｜ **手改了用户级副本**。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent             # `<仓库根>/.codebuddy/agents/`
REPO_ROOT = HERE.parent.parent                     # comfy-studio 仓库根（workspace 根）

# ⚠️ 本仓**唯一**一处写死的「仓库内相对落点」—— 注意这不是机器绝对路径（不违反
#    「路径不许写死」那条口径：那条禁的是 `D:\…`，换了机器就静默失效）。
#    写在这里是因为项目级 agent **必须**住 workspace 根才被 CodeBuddy 认（只认那里），
#    而漫剧业务数据在引擎侧扩展位下，两者隔着四级目录，无法用「向上找」连起来。
#    改布局时只改这一行；`_build.py` 与 `tests/test_agents.py` 各有一份同源声明。
MANJU_REL = "ComfyUI/custom_nodes/comfy_studio/manju"
ROOT = REPO_ROOT / MANJU_REL                       # 漫剧数据根（`AI漫剧智能体工作流/` 的父级）

DEFAULT_DEST = Path.home() / ".codebuddy" / "agents"

WF_REL = "AI漫剧智能体工作流"
RUN_REL = "07-智能体运行时"
SPEC_REL = "智能体搭建参考md"
BUILD_REL = ".codebuddy/agents/_build.py"

# ⚠️ 左边界：前面若是**路径字符**（`/` `\` `.` `:` 或 ASCII 词字符），说明这段已经处在
#    某条路径里（例如 `AI漫剧智能体工作流/07-智能体运行时` 的后半段）→ 不再套一次前缀。
#    ⚠️ 左边界**只列 ASCII**、不交给 Unicode `\w`：否则中文被当词字符，
#       「见07-智能体运行时/README.md」这类**紧贴中文**的正确写法会被漏替换。
BOUNDARY = r"(?<![0-9A-Za-z_/\\.:])"

# ⚠️ 双重替换的**签名**：路径紧跟另一个盘符路径（`…/D:/…`）。正常文本不该出现。
DOUBLE_SUB = re.compile(r"[/\\][A-Za-z]:[/\\]")

# 用户级副本必须由本文件生成；用它认领"属于本批"的文件（`--校验` 找多余件用）。
OWNED_GLOB = "manju-*.md"


def _rules(abs_root: str) -> list[tuple[str, str]]:
    """相对写法 → 绝对写法（**长串在前**，避免短串抢先匹配）。

    ⚠️ 这里**只放全局唯一解释**的写法。像 `02-服化道/…` 这种
       （既是 `AI漫剧智能体工作流/02-服化道/…`，又出现在模块内相对语境）**不在此列** ——
       它是靠正文最前的「路径基准」声明消歧的，硬替换会改写错语义。
    """
    wf = f"{abs_root}/{WF_REL}"
    pairs = [
        (WF_REL, wf),                                   # `AI漫剧智能体工作流/…`
        (SPEC_REL, f"{abs_root}/{SPEC_REL}"),           # `智能体搭建参考md/…`
        # ⚠️ 生成脚本在 **agents 根**（= 仓库根）下，不在数据根下 —— 它是本目录的邻居。
        (BUILD_REL, f"{REPO_ROOT.as_posix()}/{BUILD_REL}"),
        (RUN_REL, f"{wf}/{RUN_REL}"),                   # 裸写法 `07-智能体运行时/main.py`
    ]
    return sorted(pairs, key=lambda kv: len(kv[0]), reverse=True)


def convert(text: str, abs_root: str) -> tuple[str, int]:
    """纯函数：相对路径 → 绝对路径，并返回 `(新文本, 替换次数)`。

    单遍完成（见文件头「为什么必须单遍」），尾声做一次双重替换自检。
    """
    rules = _rules(abs_root)
    pat = re.compile(BOUNDARY + "(" + "|".join(re.escape(k) for k, _ in rules) + ")")
    table = dict(rules)
    out, n = pat.subn(lambda m: table[m.group(1)], text)

    # `cd <工作流根>/07-智能体运行时` → `cd /d "…"`：cmd 下可跨盘，且路径含中文也安全
    target = f"{abs_root}/{WF_REL}/{RUN_REL}"
    c = out.count(f"cd {target}")
    if c:
        out = out.replace(f"cd {target}", f'cd /d "{target}"')
        n += c

    bad = DOUBLE_SUB.search(out)
    if bad:
        raise AssertionError(
            "路径绝对化发生**双重替换**（"
            f"位置 {bad.start()}：…{out[max(0, bad.start() - 44):bad.end() + 24]}…）"
            " —— 分遍替换的产物又被下一遍匹配了；本函数必须单遍完成。")
    return out, n


def note(name: str, abs_root: str) -> str:
    """安装副本注记：派生关系 + **路径基准**（相对写法靠它消歧）。

    ⚠️ 这里刻意出现**两个根**：权威源与生成器住 **agents 根**（仓库根 = workspace 根），
    而正文里的路径基准是 **漫剧数据根**（`abs_root`）。搬迁前它们是同一级，现在不是了。
    """
    wf = f"{abs_root}/{WF_REL}"
    src_dir = f"{REPO_ROOT.as_posix()}/.codebuddy/agents"
    return (
        "> ⚠️ 本文件是**用户级安装副本**（`~/.codebuddy/agents/`，对本机**所有项目**生效）。\n"
        f"> 权威源：`{src_dir}/{name}.md` —— **不要直接改这里**；\n"
        f"> 改源后重装：`python \"{src_dir}/_install_user.py\"`"
        "（`--校验` 只比对、不写盘）。\n"
        ">\n"
        f"> 📍 **路径基准（本机实测）**：漫剧数据根 = `{abs_root}`；工作流根 = `{wf}`。\n"
        "> 正文里**不带盘符**的写法**两种基准**，按上下文判：\n"
        "> 　① 多数（`02-服化道/…`、`01-剧本文本/…`、`模板/…`）→ 以**工作流根**为基准；\n"
        "> 　② 少数（如 `01-声音设计引擎.md`）→ 以**所在模块目录**为基准，上文已给出该模块的绝对路径。\n"
        "> ⚠️ **若上述目录不存在**（换了机器 / 仓库被挪走 / 在别的项目里干活）：\n"
        "> 先探测真实位置，**探测不到就向用户索要** —— 不要照抄这里的路径去读文件，更不要猜。\n"
        "> ⚠️ 命令按 cmd 体例写（`cd /d \"…\"`）；PowerShell 下换成 `Set-Location \"…\"`。\n"
    )


def render(src: Path, abs_root: str) -> tuple[str, int]:
    """纯函数：按声明**算出**用户级该有的完整内容 → `(内容, 绝对化处数)`。

    ⭐ 安装与 `--校验` **共用这一份** —— 否则"校验用的算法"与"安装用的算法"
    会各自漂移，校验就成了摆设。
    """
    text = src.read_text(encoding="utf-8").replace("\r\n", "\n")
    text, n_sub = convert(text, abs_root)
    text = text.rstrip() + "\n"

    m = re.match(r"\A---\r?\n.*?\r?\n---\r?\n", text, re.S)
    if not m:
        raise ValueError(f"{src.name}：没有 frontmatter（用户级 agent 必须有）")
    out = text[: m.end()] + "\n" + note(src.stem, abs_root) + "\n" + text[m.end():]
    return out, n_sub


def expected(src: Path, abs_root: str) -> str:
    """只要内容（校验用）。"""
    return render(src, abs_root)[0]


def sources() -> list[Path]:
    return sorted(p for p in HERE.glob("*.md") if not p.name.startswith("_"))


def kind(p: Path) -> str:
    """联动型（`manju-0N-*`，规则只给路径 + 调 07 的代码）｜ 移植型（参考 md 逐字移植）。"""
    return "联动" if re.match(r"^manju-0\d-", p.name) else "移植"


def first_diff(want: str, got: str) -> str:
    """给"陈旧/手改"一条**可定位**的线索，而不是只说"不一致"。"""
    w, g = want.split("\n"), got.split("\n")
    for i, (a, b) in enumerate(zip(w, g), 1):
        if a != b:
            return f"首处不同在第 {i} 行：期望 {a[:56]!r} / 实得 {b[:56]!r}"
    return f"行数不同（期望 {len(w)}，实得 {len(g)}）"


def install(files: list[Path], dest_dir: Path, abs_root: str, preview: bool) -> int:
    total = 0
    for p in files:
        out, n_sub = render(p, abs_root)
        if not preview:
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / p.name).write_text(out, encoding="utf-8", newline="\n")
        total += len(out)
        flag = "（预览）" if preview else ""
        print(f"  ✅ {p.name:34s} {kind(p)}型 {len(out):6d} 字符 ｜ 绝对化 {n_sub:2d} 处 {flag}")
    print()
    print(f"  合计 {total} 字符（≈ {total / 1024:.0f} KB）")
    return 0


def verify(files: list[Path], dest_dir: Path, abs_root: str) -> int:
    ok: list[str] = []
    missing: list[str] = []
    stale: list[tuple[str, str]] = []          # (文件名, 首处不同)
    for p in files:
        d = dest_dir / p.name
        if not d.is_file():
            missing.append(p.name)
            continue
        want = expected(p, abs_root)
        got = d.read_text(encoding="utf-8").replace("\r\n", "\n")
        if got == want:
            ok.append(p.name)
        else:
            stale.append((p.name, first_diff(want, got)))

    names = {p.name for p in files}
    extra = sorted(d.name for d in dest_dir.glob(OWNED_GLOB) if d.name not in names)

    print(f"  权威源：{HERE}")
    print(f"  目标  ：{dest_dir}")
    print(f"  比对本批 {len(files)} 个 agent")
    print()
    for n in ok:
        print(f"  OK   {n:34s} 与源一致")
    for n in missing:
        print(f"  ❌   {n:34s} 未安装 —— 跑 `_install_user.py` 装它")
    for n, why in stale:
        print(f"  ❌   {n:34s} 与源不一致（源改了没重装 / 有人手改了副本）→ {why}")
    for n in extra:
        print(f"  ⚠️   {n:34s} 目标目录里有、源里没有 → 源改名/删除后留下的陈旧副本，建议删掉")

    print()
    if missing or stale or extra:
        print(f"  ❌ 用户级副本与权威源**不一致**："
              f"{len(missing)} 缺失 · {len(stale)} 陈旧 · {len(extra)} 多余"
              f"（一致 {len(ok)}）")
        print("     修复：python .codebuddy/agents/_install_user.py")
        return 1
    print(f"  ✅ 全部一致 —— {len(ok)} 个用户级 agent 都等于「按本目录重算」的结果")
    return 0


def uninstall(files: list[Path], dest_dir: Path) -> int:
    removed = []
    for p in files:
        t = dest_dir / p.name
        if t.is_file():
            t.unlink()
            removed.append(p.name)
    print(f"  ✅ 已删除 {len(removed)} 个：{'、'.join(removed) if removed else '（无）'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="安装 agent-voide 子智能体到 CodeBuddy 用户级")
    ap.add_argument("--预览", dest="preview", action="store_true", help="只打印清单，不写文件")
    ap.add_argument("--校验", dest="verify", action="store_true",
                    help="重算并与磁盘比对（缺失/陈旧/多余），不写盘；不一致时退出码 1")
    ap.add_argument("--卸载", dest="uninstall", action="store_true", help="删除已安装的本批文件")
    ap.add_argument("--目标", dest="dest", default=str(DEFAULT_DEST), help="目标目录")
    ap.add_argument("--仅移植型", dest="only_port", action="store_true",
                    help="只处理移植型（参考 md 那 6 个自包含 agent）；默认整批 13 个。"
                         "装 / 校验 / 卸载要带同一口径")
    a = ap.parse_args()

    dest_dir = Path(a.dest).expanduser()
    abs_root = ROOT.as_posix()
    files = sources()
    if a.only_port:
        files = [p for p in files if kind(p) == "移植"]

    if a.verify:
        return verify(files, dest_dir, abs_root)
    if a.uninstall:
        return uninstall(files, dest_dir)

    print(f"  源目录：{HERE}")
    print(f"  数据根：{abs_root}")
    print(f"  目标  ：{dest_dir}")
    print(f"  待处理 {len(files)} 个 agent")
    print()
    rc = install(files, dest_dir, abs_root, a.preview)
    if not a.preview:
        print(f"  ⚠️ 用户级 agent 对本机**所有项目**生效；换项目后其路径基准仍是 {abs_root}")
        print("  校验（源侧）：python AI漫剧智能体工作流/07-智能体运行时/tests/test_agents.py")
        print("  校验（用户级）：python .codebuddy/agents/_install_user.py --校验")
    return rc


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
