# -*- coding: utf-8 -*-
"""`00-总控路由.md` §六「全局一致性守护」里那句**漂移检测**的实现。

═══════════════════════════════════════════════════════════════════
为什么要有这个文件
═══════════════════════════════════════════════════════════════════
§六 原文（**这是机制，不是规则**）：

> **漂移检测**：每当有模块交付，检查其引用的 ID 是否都在 ID 总表中、
> 风格锚点是否与风格锚点表一致、是否自造了未登记 ID。

在此之前，这句话只是被 `module_loader.guardians()` **原样粘进 System Prompt**
—— 也就是"让模型自己记得"。但"ID 在不在总表里"是**纯确定性的**，
用代码做**必然比让模型记得更可靠**，而且**错了会当场说**。

于是本文件把它变成代码：交付物 → 抓出所有 ID → 对照 ID 总表 → 报四类问题。

═══════════════════════════════════════════════════════════════════
⚠️ 一处必须诚实的地方：**不是所有前缀本项目都能判定**
═══════════════════════════════════════════════════════════════════
`SHT_` / `VID_` / `AUD_` 归 01/03/04 模块管，本项目**没有它们的总表**。
若把它们也当"未登记 ID"报出来，就会天天误报 —— 检查器一旦有噪声就没人看
（本项目已踩过：文件统计把运行态算进去 → "跑一次失败一次"）。

故明确分两档：
    · **本模块管**（CHR/CST/PRP/ENV/EXP/POS）→ 可判定，未登记即报
    · **外来前缀**（SHT/VID/AUD）        → **不判定**，只列出并说明归谁管
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# ID 语法（权威：`00-总控路由.md` §四）
# ─────────────────────────────────────────────────────────────

# 前缀 → 资产类型
PREFIX_TYPE: dict[str, str] = {
    "CHR_": "character", "CST_": "costume", "PRP_": "prop",
    "ENV_": "environment", "EXP_": "expression", "POS_": "pose",
    "SHT_": "storyboard", "VID_": "video", "AUD_": "audio",
}

# 蓝图字面（`config.json` 的 `id_style=blueprint`；同一语义，跨系统互通）
ALIAS_TYPE: dict[str, str] = {
    "CHAR-": "character", "COSTUME-": "costume",
    "PROP-": "prop", "SCENE-": "environment",
}

# 本项目**有总表、可判定**的类型
OWNED = {"character", "costume", "prop", "environment", "expression", "pose"}
# 归其他模块管、本项目**无总表、不判定**的类型（0X → 模块号）
FOREIGN_OWNER = {"storyboard": "03-分镜导演", "video": "04-视频生成",
                 "audio": "05-音乐音频"}

# 抓 ID 形式 token —— ⚠️ **必须按前缀分结构写，不能用一个通用字符类**。
# 第一版写成 `(?:CHR|…|AUD)_[A-Za-z0-9_\-]*[A-Za-z0-9\u4e00-\u9fa5]`，
# 于是 `EXP_CHR001_愤怒` 只匹配到 `EXP_CHR001_愤`（中段类不认中文，尾类只吃 1 字）
# —— 漏掉最后一个汉字，并连带把它的未登记判定也判错。
#
# 另：中文名后缀**天然有歧义**（`POS_001_跪姿已产出` 无分隔符时会多吃字）。
# 故把中文名**限定在 1–6 字**，并在此声明：中文后缀的 ID 请用空格/标点分隔。
# 前缀分结构后，ASCII 的（CHR/CST/PRP/ENV/SHT/VID/AUD）不受影响，边界严格。
_CN_NAME = r"[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9]{0,5}"
SCAN_RE = re.compile(
    r"EXP_[A-Za-z0-9]+_" + _CN_NAME + r"|"                    # 表情：EXP_CHR001_愤怒
    r"POS_\d{1,3}(?:_" + _CN_NAME + r")?|"                     # 动作：POS_001_跪姿
    r"(?:CHR|CST|PRP|ENV)_\d{1,3}(?:_[A-Za-z][A-Za-z0-9_]*)?|"  # 主资产 + ASCII 派生后缀
    r"VID_SHT_S\d{2,3}_\d{3}|"                                # 镜头视频
    r"SHT_S\d{2,3}_\d{3}|"                                    # 分镜
    r"AUD_[A-Z]+_\d{1,3}|"                                     # 音频
    r"(?:CHAR|COSTUME|PROP|SCENE)-\d{1,3}")                    # 蓝图字面

# 「主 ID + 派生后缀」的分界：前 3 位给前缀，之后是派生
#   CHR_001_State_B → base CHR_001   ｜  POS_001_跪姿 → base POS_001
#   ENV_001_PanoramaBase → base ENV_001
#   EXP_CHR001_愤怒 → **整体**（它本身就是一个独立资产）
_BASE_RE = re.compile(r"^(CHR|CST|PRP|ENV|POS)_(\d{3})(?:_|$)")


def type_of(token: str) -> str:
    """token 属于哪类资产（认不出返回空串）。"""
    for pre, t in PREFIX_TYPE.items():
        if token.startswith(pre):
            return t
    for pre, t in ALIAS_TYPE.items():
        if token.upper().startswith(pre):
            return t
    return ""


def base_of(token: str) -> str:
    """取**主 ID**：派生变体归到它的主 ID（`ENV_001_S01` → `ENV_001`）。

    表情（`EXP_CHR001_愤怒`）与分镜/视频/音频**不做归并** —— 它们各自是独立条目。
    """
    m = _BASE_RE.match(token)
    return f"{m.group(1)}_{m.group(2)}" if m else token


def extract(text: str) -> list[str]:
    """抓出文本里所有 ID token（去重保序）。"""
    out: list[str] = []
    for m in SCAN_RE.finditer(text or ""):
        t = m.group(0).rstrip("_-.")
        if t and t not in out:
            out.append(t)
    return out


# ─────────────────────────────────────────────────────────────
# 报告
# ─────────────────────────────────────────────────────────────

@dataclass
class DriftReport:
    """漂移检测结果。四类问题 + 两张"不判定/未接入"的诚实说明。"""

    scope: str = ""
    known: int = 0                      # 总表条目数
    refs: list[str] = field(default_factory=list)          # 抓到的引用
    unregistered: list[str] = field(default_factory=list)  # ❗未登记（自造/笔误）
    malformed: list[tuple[str, str]] = field(default_factory=list)   # 格式非法
    type_conflict: list[str] = field(default_factory=list)           # 一号两类型
    registry_gap: list[str] = field(default_factory=list)  # ⚠️两张单子不一致
    bad_locks: list[str] = field(default_factory=list)     # ❗不是 §一 的 LOCK_*
    orphans: list[str] = field(default_factory=list)       # ℹ️登记了但无人引用
    style_mismatch: list[tuple[str, str]] = field(default_factory=list)  # ⚠️字面风格
    foreign: list[tuple[str, str]] = field(default_factory=list)     # 外来前缀
    anchor: "AnchorReport | None" = None                   # §六 风格锚点一致性
    unchecked: list[str] = field(default_factory=list)     # 本命令未核验的项

    @property
    def ok(self) -> bool:
        return not (self.unregistered or self.malformed or self.type_conflict
                    or self.bad_locks
                    or (self.anchor is not None and not self.anchor.ok))

    def render(self) -> str:
        L: list[str] = []
        L.append(f"  范围：{self.scope}")
        L.append(f"  ID 总表：{self.known} 条 ｜ 本次抓到的引用：{len(self.refs)} 个")
        L.append("")
        if self.unregistered:
            L.append(f"  ❌ **未登记 ID（自造 / 笔误 / 引用不存在的资产）："
                     f"{len(self.unregistered)} 个**")
            for t in self.unregistered[:20]:
                L.append(f"      {t}")
            L.append("      依据：§六「是否自造了未登记 ID」—— 必须先登记再引用")
        if self.malformed:
            L.append(f"  ❌ **ID 格式不合规范：{len(self.malformed)} 个**")
            for t, why in self.malformed[:20]:
                L.append(f"      {t}  ← {why}")
        if self.type_conflict:
            L.append(f"  ❌ **一号两类型：{len(self.type_conflict)} 个**")
            for t in self.type_conflict:
                L.append(f"      {t}")
        if self.bad_locks:
            L.append(f"  ❌ **不是 §一 锁定清单里的项：{len(self.bad_locks)} 个**")
            for t in self.bad_locks[:10]:
                L.append(f"      {t}")
            L.append("      依据：§六「当前所有 `LOCK_*`」+ `LOCK-SYSTEM.md` §一"
                     "（本项目 6 个 agent 曾硬编码 `CUT`/`STRUCTURE`/「建筑」等"
                     "**不是锁定项**的名字当锁定项）")
        if self.registry_gap:
            L.append(f"  ⚠️ 两张单子不一致：{len(self.registry_gap)} 处")
            for t in self.registry_gap[:10]:
                L.append(f"      {t}")
        if self.style_mismatch:
            L.append(f"  ⚠️ 字面风格与工作流规范不同（**不算错**）："
                     f"{len(self.style_mismatch)} 个")
            for t, why in self.style_mismatch[:5]:
                L.append(f"      {t}  ← {why}")
        if self.foreign:
            L.append(f"  ● 外来前缀（**本项目无总表，不判定**）：")
            seen: dict[str, int] = {}
            for t, owner in self.foreign:
                seen[owner] = seen.get(owner, 0) + 1
            for owner, n in seen.items():
                L.append(f"      {n} 处 → 归 `{owner}` 管；要校它得去那个模块")
        if self.orphans:
            L.append(f"  ℹ️ 库里登记但**未见任何交付物引用**：{len(self.orphans)} 个")
            L.append(f"      {'、'.join(self.orphans[:12])}"
                     + ("…" if len(self.orphans) > 12 else ""))
        if self.anchor is not None:
            L.append("")
            L.append("  ── §六 风格锚点一致性（防全片画风漂移）──")
            L.append(self.anchor.render())
        if not (self.unregistered or self.malformed or self.type_conflict
                or self.registry_gap or self.foreign or self.orphans):
            L.append("")
            L.append("  ✅ 未发现 ID 漂移（引用的 ID 都在总表里，格式合规）")
        if self.unchecked:
            L.append("")
            L.append("  ⚠️ **本命令未核验的项**（不要以为 drift 通过 = 一切都对）：")
            for u in self.unchecked:
                L.append(f"      · {u}")
        return "\n".join(L)


# ─────────────────────────────────────────────────────────────
# 检测
# ─────────────────────────────────────────────────────────────

# 格式检查：前缀后**必须**是 3 位（§四 `CHR_<3位>`）
_BAD_DIGITS = [(re.compile(rf"^{p}(\d+)(?:_|$)"), p) for p in
               ("CHR_", "CST_", "PRP_", "ENV_", "POS_")]


def _check_format(token: str) -> str:
    """返回**格式问题**描述；合规返回空串。

    只判「位数不符 §四」这类硬错误。**蓝图字面不在此判** —— 它是同一语义的
    另一套字面（`id_style=blueprint` 时完全合法），见 `_style_mismatch()`。
    """
    for pat, pre in _BAD_DIGITS:
        m = pat.match(token)
        if m and len(m.group(1)) != 3:
            return f"§四 要求 `{pre}<3位>`（如 {pre}001），此处是 {len(m.group(1))} 位"
    return ""


def _style_mismatch(token: str) -> str:
    """蓝图字面 vs 工作流字面 —— ⚠️ **警告，不是错误**。

    本项目同时支持两套字面（`config.json` 的 `id_style`），语义相同。
    把蓝图字面判成 ❌ 会在 `id_style=blueprint` 的项目里**天天误报** ——
    而检查器一旦有噪声就没人看了（本项目已踩过同类：文件统计把运行态算进去）。
    """
    for alias in ALIAS_TYPE:
        if token.upper().startswith(alias):
            return (f"这是蓝图风格字面（`{alias}`）；工作流 §四 规范是下划线形式。"
                    f"若 `config.json` 的 `id_style=blueprint` 则属正常")
    return ""


# §六 的「**锁定清单**」判据（`LOCK-SYSTEM.md` §一 的 13 项）
LOCK_RE = re.compile(r"\bLOCK_[A-Z][A-Z_]*")


def check_locks(text: str, valid: set[str]) -> list[str]:
    """交付物里出现的 `LOCK_*` 是否都在 §一 的清单里。

    ⚠️ 这一条能抓到一类**真实发生过的错**：本项目 6 个 agent 曾各自硬编码
    `["CUT","LAYER_ORDER"]` / `["STRUCTURE"]` / `["建筑","门窗"]` 当锁定项 ——
    它们**都不是 §一 的 `LOCK_*`**。若当时有这个检查，会当场报出来。
    """
    if not valid:
        return []
    out: list[str] = []
    for m in LOCK_RE.finditer(text or ""):
        t = m.group(0)
        if t not in valid and t not in out:
            out.append(t)
    return out


def check_text(text: str, known: set[str], scope: str = "（文本）",
               valid_locks: set[str] | None = None) -> DriftReport:
    """检查**一段文本**里引用的 ID 是否都在总表中。

    :param known: ID 总表（主 ID 集合；只需含主 ID，派生后缀自动放行）
    :param valid_locks: §一 的 `LOCK_*` 清单（给了才做锁定项合法性检查）
    """
    rep = DriftReport(scope=scope, known=len(known))
    if valid_locks:
        rep.bad_locks = check_locks(text, valid_locks)
    for t in extract(text):
        rep.refs.append(t)
        kind = type_of(t)
        if not kind:
            continue
        if kind in FOREIGN_OWNER:
            rep.foreign.append((t, FOREIGN_OWNER[kind]))
            continue
        why = _check_format(t)
        if why:
            rep.malformed.append((t, why))
            continue
        # 蓝图字面：只提醒风格，不阻断（见 `_style_mismatch`）
        style = _style_mismatch(t)
        if style:
            rep.style_mismatch.append((t, style))
        # 全程命中 → 通过（派生后缀归主 ID）
        if t in known or base_of(t) in known:
            continue
        rep.unregistered.append(t)
    return rep


def load_registry(root: Path) -> tuple[set[str], list[str]]:
    """读 ID 总表，返回 `(主 ID 集合, 两张单子不一致的说明)`。

    总表 = `config/id_registry.json` 的 `issued` **并上** `assets/*/*` 实际目录。
    两者不一致本身就是漂移（登记了但没卡 / 有卡但没登记）。
    """
    root = Path(root)
    reg_path = root / "config" / "id_registry.json"
    issued: dict[str, dict] = {}
    if reg_path.exists():
        try:
            issued = json.loads(reg_path.read_text(encoding="utf-8")) \
                .get("issued", {}) or {}
        except Exception as e:                                       # noqa: BLE001
            return set(), [f"`{reg_path.name}` 解析失败：{e}"]

    on_disk: set[str] = set()
    for sub in ("characters", "costumes", "props", "scenes", "expressions", "poses"):
        d = root / "assets" / sub
        if d.is_dir():
            on_disk |= {p.name for p in d.iterdir() if p.is_dir()}

    gap: list[str] = []
    for aid in sorted(set(issued) - on_disk):
        gap.append(f"{aid}：已登记但 `assets/` 下**没有卡片**（登记了却没做？被删了？）")
    for aid in sorted(on_disk - set(issued)):
        gap.append(f"{aid}：`assets/` 下有卡片但**未登记**（绕过了 ID 分配？）")
    return set(issued) | on_disk, gap


# 资产类型 → 磁盘目录（`assets/` 下）
TYPE_DIRS: dict[str, str] = {
    "characters": "character", "costumes": "costume", "props": "prop",
    "scenes": "environment", "expressions": "expression", "poses": "pose",
}


def check_conflicts(root: Path) -> list[str]:
    """一号两类型：同一 ID 归属了两种类型。

    ⚠️ **第一版实现是错的，而且错得没有价值**：它遍历 `issued`（`{id: {type}}`）
    去找"同一 ID 两种类型" —— 但那是 **dict**，**一个 key 不可能有两种值**，
    所以它**逻辑上永远返回空**。这是本项目反复强调的那类东西：
    **一个不可能报错的检查器等于没有**（写成函数、看着像检查，从不产出任何结果）。

    正确判据只能来自"两处独立事实的对照"：
      ① 同一 ID 出现在**多个类型目录**（`assets/characters/CHR_001` 与
         `assets/scenes/CHR_001` 同时存在）
      ② **总表登记的类型** 与 **卡片里写的类型** 不一致
    """
    root = Path(root)
    out: list[str] = []

    # ① 磁盘上同名 ID 落在多个类型目录
    seen: dict[str, set[str]] = {}
    for sub, t in TYPE_DIRS.items():
        d = root / "assets" / sub
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.is_dir():
                seen.setdefault(p.name, set()).add(t)
    for aid, types in sorted(seen.items()):
        if len(types) > 1:
            out.append(f"{aid}：同时存在于 "
                       f"{' 与 '.join(sorted(types))} 两种类型目录（号位被两类共用）")

    # ② 总表登记类型 ≠ 卡片实际类型
    reg_path = root / "config" / "id_registry.json"
    if reg_path.exists():
        try:
            issued = json.loads(reg_path.read_text(encoding="utf-8")) \
                .get("issued", {}) or {}
        except Exception:                                            # noqa: BLE001
            issued = {}
        inv = {v: k for k, v in TYPE_DIRS.items()}
        for aid, info in issued.items():
            want = (info or {}).get("type", "")
            sub = inv.get(want)
            if not sub:
                continue
            card = root / "assets" / sub / aid / "latest.json"
            if not card.exists():
                continue
            try:
                got = json.loads(card.read_text(encoding="utf-8")).get("type", "")
            except Exception:                                        # noqa: BLE001
                continue
            if got and got != want:
                out.append(f"{aid}：总表登记为 {want}，卡片实际是 {got}")
    return out


def anchor_items(root: Path) -> list[tuple[str, str]]:
    """收集所有带风格锚点的交付物：资产卡（源头）+ `output/` 下的提示词包。"""
    root = Path(root)
    out: list[tuple[str, str]] = []
    ad = root / "assets"
    for sub in sorted(ad.iterdir()) if ad.is_dir() else []:
        if not sub.is_dir():
            continue
        for card in sorted(sub.glob("*/latest.json")):
            try:
                out.append((f"assets/{sub.name}/{card.parent.name}/latest.json",
                            card.read_text(encoding="utf-8")))
            except Exception:                                        # noqa: BLE001
                continue
    od = root / "output"
    for f in sorted(od.rglob("*")) if od.is_dir() else []:
        if f.is_file() and f.suffix in (".md", ".json", ".txt"):
            try:
                out.append((str(f.relative_to(root)),
                            f.read_text(encoding="utf-8", errors="replace")))
            except Exception:                                        # noqa: BLE001
                continue
    return out


def scan_output(root: Path, known: set[str],
                authoritative: dict[str, str] | None = None,
                valid_locks: set[str] | None = None) -> DriftReport:
    """扫全部交付物（`output/` 下的提示词包 / 索引表 / 元数据）做漂移检测。

    :param authoritative: 权威风格锚点（来自工作流规则）。给了才做锚点一致性核验。
    """
    root = Path(root)
    rep = DriftReport(scope="全库交付物（output/ 下的提示词 / 索引表 / 元数据）",
                      known=len(known))
    if authoritative:
        rep.anchor = check_anchors(anchor_items(root), authoritative)
    referenced: set[str] = set()
    files = sorted((root / "output").rglob("*")) if (root / "output").is_dir() else []
    seen_tokens: list[str] = []
    for f in files:
        if not f.is_file():
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except Exception:                                            # noqa: BLE001
            continue
        span = check_text(txt, known, scope=str(f.relative_to(root)),
                          valid_locks=valid_locks)
        for t in span.refs:
            if t not in seen_tokens:
                seen_tokens.append(t)
        for t in span.refs:
            referenced.add(base_of(t))
        rep.unregistered += span.unregistered
        rep.malformed += span.malformed
        rep.foreign += span.foreign
        rep.bad_locks += span.bad_locks
    # 去重保序
    rep.unregistered = list(dict.fromkeys(rep.unregistered))
    rep.bad_locks = list(dict.fromkeys(rep.bad_locks))
    rep.refs = seen_tokens
    # 库里登记但无人引用
    rep.orphans = sorted(known - referenced)
    return rep


# ─────────────────────────────────────────────────────────────
# §六 的另一项：**风格锚点一致性**（防全片画风漂移）
# ─────────────────────────────────────────────────────────────
#
# §六 原文要求比对「风格锚点表」，并把它列为防画风漂移的手段。
# 而那张表的模板被指到 `TURNAROUND-STANDARD.md` §七 —— **指错了**（§七 是光影设计）。
# 风格锚点的**权威定义**其实在 `02-服化道/模板/VISUAL_BIBLE.md` §4.8
# （「风格 DNA / 风格锚点」+「**全片所有 prompt 末尾强制追加，一字不改**」）。
#
# ⭐ 更关键的是：本项目**每条提示词里都真的带着这段锚点**，且它来自权威规则。
# 于是"锚点有没有漂移"是**可确定性判定的** —— 不需要先有那张表：
#   ① 每个交付物里的锚点，应与**权威规则里的锚点逐字相同**
#   ② 各交付物之间也应逐字相同
# 这就是 §六 想防的东西（"防全片画风漂移"），而且能在**交付当场**报出来。

# 锚点两段（由 `prompt_engine._tail_block()` 写入，值来自工作流 §六）
#
# ⚠️ 取值的**终止符必须同时包含「真换行」与「转义换行 `\n`」** ——
# 实测踩到：资产卡是 JSON，里面的换行是**两个字符** `\` + `n`，
# 于是 `[^\n]+` 不认它、一路吞到整行末尾，抓到的值与权威值**肉眼看着一样**
# 却判定不等（8 处全误报）。凡"在 JSON 里用正则取一行"都要防这个。
#   ⚠️ 终止符要**三样都认**：真换行 `\n` · 转义换行 `\`+`n` · **引号**（JSON 串的结束引号）。
#      实测第二次踩到：JSON 里 `"prompt_en": "…quality.",` 的那个 `"` 是**字符串结束引号**
#      （不是 `\"`），只认 `\"` 就会把它和逗号一起吃进来。
_ANCHOR_STOP = r"(?:\\n|\n|\"|$)"
ANCHOR_PATTERNS: dict[str, str] = {
    "cinematic_quality": r"CINEMATIC QUALITY[^\n:]*:\s*(.+?)" + _ANCHOR_STOP,
    "quality_targets": r"Quality targets:\s*(.+?)" + _ANCHOR_STOP,
}
ANCHOR_LABEL = {"cinematic_quality": "光影/电影感锚点",
                "quality_targets": "画质参数锚点"}


def extract_anchor(text: str) -> dict[str, str]:
    """从一段提示词里抽出**风格锚点**（两段）。抽不到返回空 dict。"""
    out: dict[str, str] = {}
    for k, pat in ANCHOR_PATTERNS.items():
        m = re.search(pat, text or "")
        if m:
            # 去掉 markdown 反引号/句末句点等包裹，便于逐字比对
            out[k] = m.group(1).strip().strip("`").rstrip(".").strip()
    return out


@dataclass
class AnchorReport:
    """风格锚点一致性（§六「防全片画风漂移」）。"""

    authoritative: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)             # 交付物没带锚点
    deviated: list[tuple[str, str, str, str]] = field(default_factory=list)
    #  ↑ (来源, 锚点名, 实际值, 权威值)
    inconsistent: list[tuple[str, str]] = field(default_factory=list)
    #  ↑ 各交付物之间不一致 (锚点名, 说明)
    checked: int = 0

    @property
    def ok(self) -> bool:
        return not (self.deviated or self.inconsistent)

    def render(self) -> str:
        L: list[str] = []
        L.append(f"  风格锚点：已核验 {self.checked} 个交付物")
        for k, v in self.authoritative.items():
            L.append(f"      权威 {ANCHOR_LABEL.get(k, k)}：{v[:96]}")
        if self.deviated:
            L.append(f"  ❌ **风格锚点与权威规则不一致（画风漂移）："
                     f"{len(self.deviated)} 处**")
            for src, k, got, want in self.deviated[:8]:
                L.append(f"      {src} · {ANCHOR_LABEL.get(k, k)}")
                L.append(f"          实际：{got[:90]}")
                L.append(f"          权威：{want[:90]}")
            L.append("      依据：§六「防全片画风漂移」+ `VISUAL_BIBLE.md` §4.8"
                     "「全片所有 prompt 末尾强制追加，**一字不改**」")
        if self.inconsistent:
            L.append(f"  ❌ **交付物之间锚点互相不一致：{len(self.inconsistent)} 处**")
            for k, why in self.inconsistent[:6]:
                L.append(f"      {ANCHOR_LABEL.get(k, k)}：{why}")
        if self.missing:
            L.append(f"  ⚠️ 未带风格锚点的交付物：{len(self.missing)} 个")
            for m in self.missing[:8]:
                L.append(f"      {m}")
        if self.checked and not (self.deviated or self.inconsistent or self.missing):
            L.append("  ✅ 全部交付物的风格锚点与权威规则**逐字一致**（无画风漂移）")
        elif not self.checked:
            L.append("  · 尚无带锚点的交付物可核验")
        return "\n".join(L)


def check_anchors(items: list[tuple[str, str]],
                  authoritative: dict[str, str],
                  ) -> AnchorReport:
    """核验风格锚点一致性。

    :param items: `[(来源名, 文本), …]`
    :param authoritative: 权威锚点（来自工作流规则，见 `rule_source`）
    """
    rep = AnchorReport(authoritative=dict(authoritative))
    per_key: dict[str, dict[str, list[str]]] = {}
    for src, txt in items:
        a = extract_anchor(txt)
        if not a:
            rep.missing.append(src)
            continue
        rep.checked += 1
        for k, got in a.items():
            want = (authoritative or {}).get(k, "")
            if want and got != want:
                rep.deviated.append((src, k, got, want))
            per_key.setdefault(k, {}).setdefault(got, []).append(src)
    # 各交付物之间
    for k, mp in per_key.items():
        if len(mp) > 1:
            vals = sorted(mp, key=lambda v: -len(mp[v]))
            rep.inconsistent.append(
                (k, f"出现 {len(mp)} 种写法；多数写法用在 {len(mp[vals[0]])} 个交付物，"
                    f"另有 {len(mp[vals[1]])} 个不同"))
    return rep


# ─────────────────────────────────────────────────────────────
# 仍需诚实交代的项（不能假装比对过）
# ─────────────────────────────────────────────────────────────

UNCHECKED_NOTES = [
    "**ID 的语义正确性**：本命令只验「ID 在不在总表、格式对不对」，"
    "**不验**「这个 ID 用在这里对不对」（如某镜头是否真该出现该角色）—— 那需要读剧本语义。",
    "**风格锚点的「风格本身对不对」**：只验**有没有漂移**（各交付物与权威规则是否逐字一致），"
    "不验艺术判断（如 LUT 选得合不合适）—— 那要人看。",
    "**交接清单里的 `风格锚点：` 字段**（各模块主控要求的那一栏）：那是**人手写的自由文本**"
    "（工作流示例里出现过「与 02 一致，未改动」「见上，全片固定」「无」等同义不同字的写法），"
    "**无法确定性比对** → 不判定。可机验的是**机器生成的锚点段**"
    "（提示词 / 资产卡 / 元数据里的 `CINEMATIC QUALITY` 与 `Quality targets`），本命令已覆盖。",
    "**风格锚点表的位置**（已于 2026-09-24 订正）：原 §六 把它指到 "
    "`TURNAROUND-STANDARD.md` **§七**，而 §七 是「光影设计的三个来源与分工」"
    "—— 实为**差一节**：画质参数与电影感具体化就在该文件 **§六**。"
    "现权威来源写作「`02-服化道/模板/VISUAL_BIBLE.md` §4.8（画风/LUT）+ "
    "`TURNAROUND-STANDARD.md` §六（画质参数）」。"
    "本节**不依赖那张表**，而是直接拿权威规则里的锚点比对（见 `check_anchors`）。",
]
