# -*- coding: utf-8 -*-
r"""把本目录（`.codebuddy/agents/`）的子智能体**安装到 CodeBuddy 用户级**。

═══════════════════════════════════════════════════════════════════════
为什么需要「安装」而不是「复制」
═══════════════════════════════════════════════════════════════════════
本目录的 agent 是**项目级**的：只在 comfy-studio 这个 workspace 里生效。
用户级（`~/.codebuddy/agents/`）的 agent 会**在本机所有项目里生效** —— 那时 cwd 是
别人的项目，所以安装要保证两件事：

  ① **标注派生关系**：写明权威源与重装命令，防止有人直接改用户级那份
     （改了会在下次安装时**静默丢失**）；
  ② **声明自包含**：这 7 个 agent 的正文把规则**全文内联**，不引用本仓库任何路径 ——
     正因如此，安装**不需要**做任何路径绝对化：`render` 只加一段注记，一个字都不改正文。

⚠️ 从前这里有一套「路径绝对化」（相对写法 → 机器绝对路径 + `cd /d` 改写），服务的对象是
那批**联动型** agent（`manju-0N-*`：只给规则路径、真干活靠本仓库 `07-智能体运行时/` 的代码）。
它们随引擎侧 `AI漫剧智能体工作流/` 一并删除后，用户级只剩自包含的这 7 个，
那套机制**再无对象** —— 留着反而危险（它会把正文里偶然出现的路径串改写成机器路径）。
故已整体移除，只留下一条**反向守卫**：正文里出现本仓库路径就报错（见 :data:`REPO_PATH`）。

⚠️ **源仍在本目录**（单一权威来源）。用户级那份是**派生物**，不要手改。
⚠️ 本文件与 `_build.py` 不共享渲染逻辑：`_build.py` 管「规格 → agent」，本文件管
   「agent → 用户级副本」。两条链都不改正文，各算各的不会漂。

═══════════════════════════════════════════════════════════════════════
用法
═══════════════════════════════════════════════════════════════════════
    python .codebuddy/agents/_install_user.py             # 安装（覆盖同名）
    python .codebuddy/agents/_install_user.py --校验       # 只比对不写盘（非 0 = 不一致）
    python .codebuddy/agents/_install_user.py --预览       # 只看清单，不写
    python .codebuddy/agents/_install_user.py --卸载       # 删除已装的本批文件
    python .codebuddy/agents/_install_user.py --目标 <目录>  # 换目标（默认 ~/.codebuddy/agents）

⚠️ 仓库自带的校验只覆盖**项目级**：
    cd ComfyUI/custom_nodes && python -m unittest comfy_studio.tests.test_agent_presets -t .
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

DEFAULT_DEST = Path.home() / ".codebuddy" / "agents"

#: 本批 agent：`_build.py` 生成的这一批（也是 `--校验` 认领"属于本批"的文件用的）。
OWNED_GLOB = "studio-*.md"

#: 正文里**不许出现**的写法 —— 指向本仓库的落点。命中即说明这份 agent 不再是自包含的：
#: 它在别人的项目里会指着不存在的文件干活，而且**不报错**（这正是最坏的一种失败）。
#: ⚠️ 只查**源正文**、不查注记：注记里必须写权威源的绝对路径（那是它的用处）。
REPO_PATH = re.compile(
    r"ComfyUI/|Comfy-Desktop/|\.codebuddy/|AI漫剧智能体工作流|智能体搭建参考md"
)


def note(name: str) -> str:
    """安装副本的注记：派生关系 + 权威源 + 重装命令 + 自包含声明。"""
    src_dir = f"{REPO_ROOT.as_posix()}/.codebuddy/agents"
    return (
        "> ⚠️ 本文件是**用户级安装副本**（`~/.codebuddy/agents/`，对本机**所有项目**生效）。\n"
        f"> 权威源：`{src_dir}/{name}.md` —— **不要直接改这里**；\n"
        f"> 改源后重装：`python \"{src_dir}/_install_user.py\"`"
        "（`--校验` 只比对、不写盘）。\n"
        ">\n"
        "> 📦 这份人设**自包含**：规则全文内联在正文里，**不引用本仓库的任何路径** ——\n"
        "> 所以在别的项目里照样干活。若你（或某次改动）让它开始引用某个仓库路径，\n"
        "> 那说明它不该被装到用户级，去源目录把它改回自包含。\n"
    )


def render(src: Path) -> tuple[str, int]:
    """纯函数：按声明**算出**用户级该有的完整内容 → `(内容, 正文字符数)`。

    ⭐ 安装与 `--校验` **共用这一份** —— 否则"校验用的算法"与"安装用的算法"
    会各自漂移，校验就成了摆设。

    ⚠️ **不改正文**：只把注记插在 frontmatter 之后。自包含是这 7 份的既有性质，
    这里只负责**核对**它（见 :data:`REPO_PATH`），不负责"改造成自包含"。
    """
    text = src.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip() + "\n"

    m = re.match(r"\A---\r?\n.*?\r?\n---\r?\n", text, re.S)
    if not m:
        raise ValueError(f"{src.name}：没有 frontmatter（用户级 agent 必须有）")

    body = text[m.end():]
    # ⚠️ 「自包含」说的是**规格正文**（那份要能整份带走）；而 `_build.py` 注入的出处注记
    #    以 `> 生成自 ` 开头，它里面**必须**写仓库落点（那是它的用处）—— 核对前先剥掉，
    #    否则每个文件都会被自己那行出处判红。
    # ⚠️ frontmatter 与注记之间隔着一个**空行**，所以 `body` 的第一个字符是 `\n`：
    #    核对前必须先 `lstrip("\n")`，否则 `startswith("> 生成自 ")` 恒为假、注记剥不掉，
    #    7 个文件会被各自那行出处**全部**判红（2026-09-28 实测：报的首个是
    #    `studio-asset-library.md` 位置 8，恰好是注记里那个 `Comfy-Desktop/`）。
    spec = body.lstrip("\n")
    if spec.startswith("> 生成自 "):
        cut = spec.find("\n\n")
        spec = spec[cut + 2:] if cut != -1 else spec
    bad = REPO_PATH.search(spec)
    if bad:
        raise AssertionError(
            f"{src.name}：正文里有本仓库路径 {bad.group(0)!r}（位置 {bad.start()}）——"
            " 这份 agent 不再是**自包含**的，装到用户级会在别人的项目里"
            "指着不存在的文件干活。修法：把它改回自包含（规则全文内联），"
            "或者别把它装到用户级。")
    return text[: m.end()] + "\n" + note(src.stem) + "\n" + body, len(body)


def expected(src: Path) -> str:
    """只要内容（校验用）。"""
    return render(src)[0]


def sources() -> list[Path]:
    return sorted(HERE.glob(OWNED_GLOB))


def first_diff(want: str, got: str) -> str:
    """给"陈旧/手改"一条**可定位**的线索，而不是只说"不一致"。"""
    w, g = want.split("\n"), got.split("\n")
    for i, (a, b) in enumerate(zip(w, g), 1):
        if a != b:
            return f"首处不同在第 {i} 行：期望 {a[:56]!r} / 实得 {b[:56]!r}"
    return f"行数不同（期望 {len(w)}，实得 {len(g)}）"


def install(files: list[Path], dest_dir: Path, preview: bool) -> int:
    total = 0
    for p in files:
        out, body_chars = render(p)
        if not preview:
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / p.name).write_text(out, encoding="utf-8", newline="\n")
        total += len(out)
        flag = "（预览）" if preview else ""
        print(f"  ✅ {p.name:36s} 正文 {body_chars:6d} 字符 ｜ 整份 {len(out):6d} 字符 {flag}")
    print()
    print(f"  合计 {total} 字符（≈ {total / 1024:.0f} KB）")
    return 0


def verify(files: list[Path], dest_dir: Path) -> int:
    ok: list[str] = []
    missing: list[str] = []
    stale: list[tuple[str, str]] = []          # (文件名, 首处不同)
    for p in files:
        d = dest_dir / p.name
        if not d.is_file():
            missing.append(p.name)
            continue
        want = expected(p)
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
        print(f"  OK   {n:36s} 与源一致")
    for n in missing:
        print(f"  ❌   {n:36s} 未安装 —— 跑 `_install_user.py` 装它")
    for n, why in stale:
        print(f"  ❌   {n:36s} 与源不一致（源改了没重装 / 有人手改了副本）→ {why}")
    for n in extra:
        print(f"  ⚠️   {n:36s} 目标目录里有、源里没有 → 源改名/删除后留下的陈旧副本，建议删掉")

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
    ap = argparse.ArgumentParser(
        description="把本目录的 studio-* 子智能体安装到 CodeBuddy 用户级")
    ap.add_argument("--预览", dest="preview", action="store_true", help="只打印清单，不写文件")
    ap.add_argument("--校验", dest="verify", action="store_true",
                    help="重算并与磁盘比对（缺失/陈旧/多余），不写盘；不一致时退出码 1")
    ap.add_argument("--卸载", dest="uninstall", action="store_true", help="删除已安装的本批文件")
    ap.add_argument("--目标", dest="dest", default=str(DEFAULT_DEST), help="目标目录")
    a = ap.parse_args()

    dest_dir = Path(a.dest).expanduser()
    files = sources()
    if not files:
        print(f"  ❌ {HERE} 里没有 {OWNED_GLOB}"
              " —— 先跑 `python .codebuddy/agents/_build.py` 生成它们")
        return 1

    if a.verify:
        return verify(files, dest_dir)
    if a.uninstall:
        return uninstall(files, dest_dir)

    print(f"  源目录：{HERE}")
    print(f"  目标  ：{dest_dir}")
    print(f"  待处理 {len(files)} 个 agent")
    print()
    rc = install(files, dest_dir, a.preview)
    if not a.preview:
        print("  ⚠️ 用户级 agent 对本机**所有项目**生效；这 7 份自包含，换项目不用改一个字")
        print("  校验（项目级）：cd ComfyUI/custom_nodes && python -m unittest "
              "comfy_studio.tests.test_agent_presets -t .")
        print("  校验（用户级）：python .codebuddy/agents/_install_user.py --校验")
    return rc


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
