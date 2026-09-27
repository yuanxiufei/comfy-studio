# -*- coding: utf-8 -*-
r"""**项目级子智能体**测试（`.codebuddy/agents/manju-*.md`）。

═══════════════════════════════════════════════════════════════════
为什么 07 的测试要管仓库根的 agent 配置
═══════════════════════════════════════════════════════════════════
那 7 个 `.codebuddy/agents/manju-*.md` 是**本仓库的交付物** ——
它们告诉 CodeBuddy「AI漫剧工作流的 7 个流程 agent 怎么用这个仓库」。
它们和 07 的关系是：**规则只读工作流、确定性步骤调 07 的代码**。
所以校验它们"引用的路径与命令是否真实"是 07 的职责边界内的事。

═══════════════════════════════════════════════════════════════════
三类问题（都是"看起来对但实际错"）
═══════════════════════════════════════════════════════════════════
① **frontmatter 能否被 YAML 解析** —— 描述里的冒号/引号最容易破坏它，
   而且是**静默**的（agent 加载失败或字段被截断，你不会立刻知道）。
② **必填字段齐不齐** —— 官方：`agentic` 模式 `name` 与 `description` 必填。
③ ⭐ **引用的路径是否指向唯一一份** —— 工作流里 `00-主控智能体.md` 有 **5 份**
   （01/02/04/05/06 各一份）。只写文件名会让 agent **读错模块的文档**，
   而那看起来"完全正常"。

⚠️ 检查器也要**被检查**：本文件第一版把 Windows 的 `\` 当成 `/` 做后缀匹配，
于是把 18 条**真实存在**的路径全判成"找不到" —— 差点让我去改对的代码。
（同日在 `tests/test_dict.py` 也踩过"断言自己写错"。）

⚠️ **用户级**（`~/.codebuddy/agents/`，由 `.codebuddy/agents/_install_user.py` 装）
是**机器相关**的，不能当测试前提 —— 故本文件只测那个安装器的**纯函数**
（路径绝对化必须单遍且幂等、注记必须声明路径基准），
若本机确实装过，再顺带核对那份副本是否等于"按本目录重算"的结果。

运行：`python tests/test_agents.py`
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parent                       # 07-智能体运行时
WF = RUN.parent                         # AI漫剧智能体工作流
ROOT = WF.parent                        # 漫剧数据根（`manju/`）—— 非仓库根，见下


def _find_agents_dir(start: Path) -> Path:
    """向上找项目级子智能体目录。

    ⚠️ **搬迁后不能再拼 `ROOT / ".codebuddy"`**：项目级 agent 现在住 **workspace 根**
    （CodeBuddy 只认那里，数据根下没有 `.codebuddy/`），而 workspace 根在数据根的**上方**
    四级 —— 所以只能往上探测。探测不到时回退到旧拼法，让下游的「目录存在」断言报出
    真实路径，而不是在这里抛异常。
    """
    for d in (start, *start.parents):
        cand = d / ".codebuddy" / "agents"
        if cand.is_dir():
            return cand
    return start / ".codebuddy" / "agents"


AG = _find_agents_dir(WF)

sys.path.insert(0, str(RUN))

try:
    import yaml
    HAVE_YAML = True
except Exception:                                          # noqa: BLE001
    HAVE_YAML = False

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'OK  ' if ok else '❌  '} {label}"
          + (f"   ← {detail}" if detail and not ok else ""))


def main() -> int:
    print(f"  agent 目录：{AG}")
    if not AG.is_dir():
        check("项目级子智能体目录存在", False, str(AG))
        return 1
    files = sorted(p for p in AG.glob("*.md") if not p.name.startswith("_"))
    # ⭐ **两种形态，两套判据** —— 混用会得出错误结论：
    #   · **联动型**（`manju-0N-*`）：规则**只给路径**，确定性步骤调 07 的代码 →
    #     必须写"不改工作流权威文档"，且引用路径要**唯一**、命令要**存在**。
    #   · **移植型**（其余，来自 `智能体搭建参考md/`）：规则**全文内联**、**不依赖**本仓库 →
    #     必须能**追溯源规格**；不能拿本仓库的路径规则去要求它。
    linked = [p for p in files if re.match(r"^manju-0\d-", p.name)]
    ported = [p for p in files if p not in linked]
    modules: dict[str, list[tuple[str, str]]] = {}      # 模块号 → [(agent 文件, agentMode)]

    # ⭐ 载入生成器，用于**重算**移植型内容（见下"逐字一致"断言）
    import importlib.util
    _spec = importlib.util.spec_from_file_location("_manju_build", AG / "_build.py")
    BUILD = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(BUILD)
    by_name = {it["name"]: it for it in BUILD.SOURCES}
    check(f"联动型子智能体 {len(linked)} 个（期望 7：00–06）", len(linked) == 7, str(len(linked)))
    check(f"移植型子智能体 {len(ported)} 个（期望 6：参考 md 逐字移植）",
          len(ported) == 6, str(len(ported)))
    # ⭐ 无孤儿：每个 .md 要么是联动型，要么在生成器的 SOURCES 里（否则"无源可再生成"）
    orphans = [p.name for p in files
               if p not in linked and p.stem not in by_name]
    check("无孤儿生成物（每个移植型都能追溯到 SOURCES）", not orphans, str(orphans))

    # 工作流全部 .md（判"歧义"用）
    # ⚠️ 统一转 `/` —— Windows 上 `Path` 给 `\`，直接拿 `/` 匹配会**全部落空**
    all_md = [str(p.relative_to(ROOT)).replace("\\", "/") for p in WF.rglob("*.md")]

    help_txt = subprocess.run(
        [sys.executable, "main.py", "-h"], cwd=RUN, capture_output=True,
        text=True, encoding="utf-8", errors="replace").stdout
    m = re.search(r"\{([a-z0-9,\-]+)\}", help_txt)
    cmds = set(m.group(1).split(",")) if m else set()
    check(f"读到 07 的子命令清单（{len(cmds)} 个）", len(cmds) > 10, str(cmds))

    for p in files:
        kind = "联动" if p in linked else "移植"
        print()
        print(f"── {p.name}（{kind}型）──")
        t = p.read_text(encoding="utf-8")
        mt = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", t, re.S)
        if not mt:
            check("有 frontmatter 块", False, p.name)
            continue
        fm_txt, body = mt.group(1), mt.group(2)

        if HAVE_YAML:
            try:
                fm = yaml.safe_load(fm_txt) or {}
            except Exception as e:                          # noqa: BLE001
                check("frontmatter 可被 YAML 解析", False, f"{type(e).__name__}: {e}")
                continue
            if not isinstance(fm, dict):
                check("frontmatter 可被 YAML 解析", False, type(fm).__name__)
                continue
        else:
            fm = dict(l.split(":", 1) for l in fm_txt.splitlines()
                      if ":" in l and not l.startswith(" "))  # 退化的兜底解析

        check("有 name", bool(fm.get("name")), str(fm.get("name")))
        check("有 description（agentic 必填）", bool(fm.get("description")))
        d = str(fm.get("description", ""))
        check("description 写了**触发条件**（'当…时使用'）",
              "当" in d and "使用" in d, d[:60])
        check("有 tools 白名单（官方建议：只给所需）", bool(fm.get("tools")))
        check("agentMode ∈ agentic/manual",
              fm.get("agentMode") in ("agentic", "manual"), str(fm.get("agentMode")))
        check("name == 文件名", fm.get("name") == p.stem,
              f"{fm.get('name')} vs {p.stem}")

        if kind == "联动":
            # ⭐ 第一纪律必须写进 System Prompt
            check("写明「不改工作流权威文档」", "不改工作流权威文档" in body)
            check("写明「规则只读工作流、不复制」",
                  "只读工作流" in body or "绝不复制" in body)

            # ⭐ 路径：完整路径要存在；简写路径必须**唯一**
            for ref in sorted(set(re.findall(r"`([0-9A-Za-z\u4e00-\u9fff_\-/]+\.md)`", body))):
                if ref.startswith("AI漫剧智能体工作流/"):
                    check(f"路径存在: {ref}", (ROOT / ref).is_file())
                    continue
                hits = [q for q in all_md if q.endswith("/" + ref) or q == ref]
                if len(hits) == 1:
                    check(f"简写路径唯一: {ref}", True)
                elif len(hits) > 1:
                    check(f"⚠️ 简写路径**歧义**: {ref}", False,
                          f"命中 {len(hits)} 份（agent 会读错模块）")
                else:
                    check(f"路径存在: {ref}", False, "工作流里找不到")

            # ⭐ 命令必须真实存在（写了不存在的命令 = 误导 agent）
            for c in sorted(set(re.findall(r"main\.py\s+([a-z0-9\-]+)", body))):
                check(f"命令存在: main.py {c}", c in cmds)
            # 收集「模块 → agent」（联动型从**文件名**取模块号）
            m_link = re.match(r"^manju-(\d\d)-", p.name)
            if m_link:
                modules.setdefault(m_link.group(1), []).append(
                    (p.name, fm.get("agentMode", "")))
        else:
            # ⭐ 移植型：必须能**追溯到源规格**（否则"改了源文件却没重生成"无从发现）
            m_src = re.search(r"生成自 `智能体搭建参考md/([^`]+)`", body)
            check("正文写明出处（生成自 …）", bool(m_src))
            if m_src:
                sp = ROOT / "智能体搭建参考md" / m_src.group(1)
                check(f"源规格存在，可追溯: {m_src.group(1)[:28]}", sp.is_file(), str(sp))
                check("源规格非空", sp.is_file() and sp.stat().st_size > 2000)
            # ⚠️ 不要断言「含『用途/适用』」—— 实测：6 份规格里只有部分有那个元信息块，
            #    把它当通用条件是**假断言**（会让一份好文件被判失败）。
            check("正文有标题（规格原文被完整搬运）",
                  any(l.startswith("# ") for l in body.splitlines()))
            check(f"正文规模合理（> 5000 字符，实测 {len(body)}）", len(body) > 5000)

            # ⭐⭐ 生成物必须与「按源规格**重算**的结果」逐字一致。
            #   抓两类**都不会报错**的静默问题：
            #     ① 改了源规格却忘了重跑 `_build.py` → 部署的 agent 是旧规则；
            #     ② 有人手改了生成物 → 下次生成会被覆盖，改动**静默丢失**。
            it = by_name.get(p.stem)
            if it:
                try:
                    want, _, _ = BUILD.render(it)
                except FileNotFoundError as e:
                    # 源规格被改名/移走 → 给**干净**的失败信息，而不是崩栈
                    check("生成物 == 按源规格重算（逐字）", False,
                          f"源规格读不到：{e} → 源文件改名后需同步 `_build.py` 的 SOURCES")
                else:
                    check("生成物 == 按源规格重算（逐字）",
                          t.replace("\r\n", "\n") == want,
                          "不一致 → 跑 `python .codebuddy/agents/_build.py` 重新生成")
            check("正文未夹入本仓库专属路径（移植型应自包含）",
                  "AI漫剧智能体工作流" not in body)

            # 收集「模块 → agent」（移植型从正文的 `服务模块 **NN**` 取 —— 机器可读）
            m_port = re.search(r"服务模块 \*\*(\d\d)\*\*", body)
            check("正文声明了**服务模块**（机器可读，供下面那条不变量用）",
                  bool(m_port), str(m_port))
            if m_port:
                modules.setdefault(m_port.group(1), []).append(
                    (p.name, fm.get("agentMode", "")))

    # ══════════════════════════════════════════════════════════════════
    # 随包预置快照（宿主侧 `Comfy-Desktop/lib/comfy_studio/agent/presets/`）
    # ══════════════════════════════════════════════════════════════════
    # 就是上面那 6 份源规格，**在两处各存一份**：此处是**权威源**，宿主侧那份是**随包快照**。
    # 查证过的依据（不是"顺手多存一份"）：
    #   · 宿主包必须**自带正文** —— 它由桌面壳按 `-m comfy_studio` 启动、cwd 是壳自带的 lib
    #     （`Comfy-Desktop/src/main/lib/comfyStudioHost.ts` 的 `getBundledLibDir`），ComfyUI 装
    #     在哪由用户的 `--comfyui-dir` 决定；让宿主去猜引擎树的落点，等于把"随包"变成"看运气"。
    #   · 而引擎侧正文里的 `智能体搭建参考md/…` 引用（`src/flow_prompts.py` 的提示词、07 的
    #     README）以**本数据根**为基准，搬进宿主包就指错了地方。
    # 两份都留 → 唯一能挡住"改了源规格、面板下拉里还是旧人设"的就是下面这条逐字对拍。
    # ⚠️ 不做"目录在才查"式的静默跳过：本文件本来就只在本仓库里跑得通（`AG` 不存在时上面
    #    直接判失败），少查一次等于白留 —— 那正是"换台机器就永远不跑"的老毛病。
    # ⚠️ 宿主侧**不能**放对应的对拍：那个包要能跟着桌面壳单独分发，在那里往上找仓库根、
    #    找不到就跳过，就是同一个毛病换了个地方。
    PRESETS = AG.parent.parent / "Comfy-Desktop" / "lib" / "comfy_studio" / "agent" / "presets"
    print()
    print("── ⭐ 随包预置快照 == 源规格（面板下拉读的就是那份）──")
    check("宿主侧随包预置目录存在", PRESETS.is_dir(), str(PRESETS))
    if PRESETS.is_dir():
        want_src = {it["src"] for it in BUILD.SOURCES}          # 生成器认的那 6 份
        got_src = {p.name for p in PRESETS.glob("*.md")} - {"README.md"}
        check(f"预置的规格清单与生成器的源规格一致（{len(want_src)} 份）",
              got_src == want_src,
              f"仅出现在一侧：{sorted(got_src ^ want_src)}"
              " → 增删/改名要同时改 _build.py 的 SOURCES 与 catalog.py 的 PRESET_AGENTS")
        stale = []
        for name in sorted(want_src & got_src):
            same = (ROOT / "智能体搭建参考md" / name).read_bytes() == (PRESETS / name).read_bytes()
            check(f"逐字一致: {name}", same)
            if not same:
                stale.append(name)
        if stale:
            print("     ⚠️ 修法：python .codebuddy/agents/_build.py")
            print("        —— 生成移植型 agent 的同时会把源规格**按字节**同步到宿主侧；")
            print(f"        权威源是引擎侧那份，别反向抄 {PRESETS}。")
        # ⭐ 上面比的是"两份文件"；这里再钉一次**生成脚本自己认的落点** —— 脚本里的路径
        #    写错时，`--预览` 会把 6 份全报成"待同步"（真同步下去会覆盖成源内容，不报错），
        #    而它平时跑起来只说"已同步"，看不出认错了地方。
        synced, _same = BUILD.sync_presets(preview=True)        # 只算不写
        check("生成脚本认的宿主预置落点就是这里（无待同步项）",
              not synced, f"脚本认为待同步 {synced} → 落点 {BUILD.PRESETS}")
        check("生成脚本能读出宿主清单登记的 6 份（与源规格同名）",
              BUILD.preset_filenames() == want_src,
              f"清单里是 {sorted(BUILD.preset_filenames())}")

    # ⭐⭐ 核心不变量：**自动入口必须是"名册里登记的那几个"**
    #
    #   风险（实测）：主 Agent 按 `description` 挑；若同一职责有两个 agentic agent，
    #   **同一句话会走两条路、产出不一致** —— 不报错、不复现，是最难查的一类问题。
    #
    #   ⚠️ 但不能简单断言"每模块恰好一个" —— 实测：模块 05 的两份规格**职责本就互斥**
    #      （`manju-suno-lyric-master` 管**写歌**；`manju-audio-tuning-master` 管
    #      **声线 / 环境声 / Foley / 调音**），两个自动入口是**合理**的。
    #      把"恰好一个"当铁律会**逼着把互斥的职责合并或砍掉**（我第一版就这么写了，
    #      当场被这条规则自己抓出来）。
    #
    #   故改为**名册**：新增/移动自动入口必须**改这张表**（即人工确认过职责不重叠）。
    #   这不是"第二权威"—— 它正是**测试的预期**；现实偏离就红。
    EXPECTED_AUTO = {
        "00": {"manju-00-orchestrator.md"},
        "01": {"manju-script-creator.md"},                       # 与工作流零重叠且厚得多
        "02": {"manju-02-asset.md"},                             # 规格与工作流文档 100% 同一份
                                                                 # → 移植型冗余；且代码强制一致性
        "03": {"manju-storyboard-director.md"},
        "04": {"manju-04-video.md"},                             # 无规格，只有联动型
        "05": {"manju-suno-lyric-master.md",                     # 写歌
               "manju-audio-tuning-master.md"},                  # 声线/环境声/Foley/调音（与写歌互斥）
        "06": {"manju-06-compliance.md"},                        # 无规格，只有联动型
    }
    print()
    print("── ⭐ 自动入口必须是名册里登记的那几个 ──")
    check(f"覆盖模块 00–06（实测 {sorted(modules)}）",
          sorted(modules) == [f"0{i}" for i in range(7)], str(sorted(modules)))
    for mod in sorted(modules):
        actual = {n for n, m in modules[mod] if m == "agentic"}
        want = EXPECTED_AUTO.get(mod, set())
        extra, missing = actual - want, want - actual
        check(f"模块 {mod}：自动入口 = 名册（{len(want)} 个）", not extra and not missing,
              f"多出 {sorted(extra)}；缺失 {sorted(missing)}")
    # 名册里不得出现不存在的文件（防"名册过时"变成静默放行）
    all_names = {p.name for p in files}
    ghost = {n for s in EXPECTED_AUTO.values() for n in s} - all_names
    check("名册里的 agent 都真实存在", not ghost, str(sorted(ghost)))

    print()
    print("  模块 ｜ 自动可调用（名册）                ｜ 手动（不参与自动）")
    print("  ─────┼──────────────────────────────────────┼──────────────────────")
    for mod in sorted(modules):
        a = sorted(n for n, m in modules[mod] if m == "agentic")
        h = sorted(n for n, m in modules[mod] if m != "agentic")
        print(f"   {mod}  ｜ {'、'.join(x.replace('manju-', '') for x in a) or '（⚠️ 无）':36s} ｜ "
              f"{'、'.join(x.replace('manju-', '') for x in h) or '—'}")

    # ══════════════════════════════════════════════════════════════════
    # 用户级安装器（`.codebuddy/agents/_install_user.py`）
    # ══════════════════════════════════════════════════════════════════
    # ⚠️ 用户级副本落在 `~/.codebuddy/agents/` —— **机器相关**，故先测**纯函数**，
    #    不把"这台机器装没装"当成前提（否则换台机器就假失败）。
    #    要测的恰好是最容易静默错的那点：**分遍替换会让路径里再套一条路径**
    #    （`…/AI漫剧智能体工作流/D:/…/AI漫剧智能体工作流/07-智能体运行时`），
    #    它不报错、还挺像路径 —— 故这里逐条钉住。
    print()
    print("── 用户级安装器：路径绝对化自检 ──")
    _s2 = importlib.util.spec_from_file_location("_manju_install", AG / "_install_user.py")
    INST = importlib.util.module_from_spec(_s2)
    _s2.loader.exec_module(INST)
    R = ROOT.as_posix()

    # ① 裸写法（模块 02 正文里就是 `07-智能体运行时/assets/`）必须被绝对化
    t1 = INST.convert("`07-智能体运行时/assets/`", R)[0]
    check("裸写法 `07-智能体运行时/…` 被绝对化",
          t1 == f"`{R}/AI漫剧智能体工作流/07-智能体运行时/assets/`", t1[:90])
    # ② 长写法**只套一次**前缀（分遍替换会套两次）
    t2 = INST.convert("AI漫剧智能体工作流/07-智能体运行时", R)[0]
    check("长写法不重复套前缀（必须单遍替换）",
          t2 == f"{R}/AI漫剧智能体工作流/07-智能体运行时", t2[:130])
    # ③ **幂等**：对已绝对化的文本再跑一次结果不变（重复安装不会叠加）
    check("绝对化**幂等**（重复安装不叠加前缀）", INST.convert(t2, R)[0] == t2)
    # ④ 中文**紧邻**也要替换（左边界故意只列 ASCII，不交给 Unicode `\w`）
    check("中文紧邻的裸写法也替换（边界只列 ASCII）",
          INST.convert("见07-智能体运行时/README.md", R)[0] ==
          f"见{R}/AI漫剧智能体工作流/07-智能体运行时/README.md")
    # ⑤ 注记必须**声明路径基准** —— 用户级在别的项目里跑，相对写法只能靠它消歧
    nt = INST.note("x", R)
    check("注记声明路径基准（仓库根 + 工作流根）", R in nt and "路径基准" in nt)
    check("注记写明「目录不存在就向用户索要」（禁止猜路径）", "索要" in nt)

    # ⑥ 本机**确实装过**用户级副本时，它必须等于「按本目录重算」的结果 ——
    #    抓 ①改了源没重装 ②有人手改了那份副本（下次安装会**静默覆盖**它）。
    dest = Path.home() / ".codebuddy" / "agents"
    if dest.is_dir() and (dest / files[0].name).is_file():
        stale = [p.name for p in files
                 if (dest / p.name).is_file()
                 and (dest / p.name).read_text(encoding="utf-8").replace("\r\n", "\n")
                 != INST.render(p, R)[0]]
        gone = [p.name for p in files if not (dest / p.name).is_file()]
        check(f"用户级副本 {len(files) - len(stale) - len(gone)}/{len(files)} 个与源一致",
              not stale and not gone,
              f"陈旧 {stale}；缺失 {gone} → 跑 `python .codebuddy/agents/_install_user.py`")
    else:
        print(f"  ··   用户级副本：{dest} 下未安装 → 跳过（装了才会核对）")

    print()
    print("=" * 66)
    if FAIL:
        print(f"❌ 失败 {len(FAIL)} 项 / 共 {len(PASS) + len(FAIL)} 项：")
        for f in FAIL:
            print("   ·", f)
        return 1
    print(f"✅ 全部通过 —— {len(PASS)} 项")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
