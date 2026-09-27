# -*- coding: utf-8 -*-
"""`02-服化道/引擎/LOCK-SYSTEM.md` 的**锁定系统与修改引擎**。

═══════════════════════════════════════════════════════════════════
为什么要有这个文件
═══════════════════════════════════════════════════════════════════
该文档开头自述：「**这是连续生产的核心机制。**」
其 §三「修改执行四步」标着 **（强制）**：

    STEP 1  解析指令 → 生成 LOCK / MODIFY 映射
    STEP 2  **冲突检测** → 若修改项与 locked_assets 冲突，
            列出「将发生变化的锁定项」并提示用户
    STEP 3  受控生成 → 锁定项写入 prompt 的 Consistency Constraints
    STEP 4  **记录变更** → 追加 CHANGELOG（changed / unchanged / reason），
            必要时递增版本

而本轮之前，本项目**一条都没实现**：`LOCK-SYSTEM.md` 只被列为"素材"，
`AssetCard.locked` / `.editable` 字段**定义了但无人写入**。
于是「改到了锁定项」不会有任何提示 —— 而 §二 那张表的存在意义正是
「用户说『只换发型』→ 其余全部 LOCK」，**不提示就等于没锁**。

═══════════════════════════════════════════════════════════════════
纪律：锁定项清单从工作流解析，不在代码里硬编码
═══════════════════════════════════════════════════════════════════
13 个 `LOCK_*`（§一）与 §二 的「用户说 → LOCK/MODIFY」映射表，
全部用 `rule_source` **运行时读取**。工作流改了这里自动跟上。

⚠️ 代码里唯一的"表"是 `FIELD_TO_LOCK` —— 那是**翻译**（把本项目的
`change_fields`（如 `hair_color`）译成工作流的锁定项名（`HAIR`）），
不是规则。且有 `validate_field_map()` 自检：**译出的名字必须都在 §一 清单里**，
否则报错 —— 防止工作流改了锁定项名而代码悄悄失联。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# 翻译表（**不是规则**）：本项目 change_fields → 工作流 §一 的锁定项名
# ─────────────────────────────────────────────────────────────
FIELD_TO_LOCK: dict[str, str] = {
    # 发型发色 → LOCK_HAIR
    "hair": "HAIR", "hair_style": "HAIR", "hair_color": "HAIR",
    "hair_length": "HAIR", "bangs": "HAIR",
    # 脸型五官 → LOCK_FACE
    "eye_color": "FACE", "eye_shape": "FACE", "face_shape": "FACE",
    "jaw": "FACE", "nose_bridge": "FACE", "lips": "FACE",
    "cybernetic_eye": "FACE",
    # 体型比例 → LOCK_BODY
    "body": "BODY", "body_type": "BODY", "height": "BODY",
    "shoulder_width": "BODY", "cybernetic_arm": "BODY", "cybernetic_leg": "BODY",
    # 服装 / 色彩 / 道具 / 环境 / 光影 / 镜头 / 表情 / 动作
    "clothing": "COSTUME", "costume": "COSTUME", "material": "COSTUME",
    "color": "COLOR", "primary_color": "COLOR",
    "prop": "PROP", "equipment": "PROP", "signature_accessory": "PROP",
    "environment": "ENVIRONMENT", "scene": "ENVIRONMENT",
    "lighting": "LIGHTING",
    "camera": "CAMERA",
    "expression": "EXPRESSION",
    "pose": "POSE",
    # 身份 / 世界观
    "age": "CHARACTER", "gender": "CHARACTER", "occupation": "CHARACTER",
    "world": "WORLD",
}
# ⭐ §四·补 A「终身固定核心识别特征库（**100% 不可改动**）」→ 本项目字段
#    原文 5 项：核心骨相 · 五官轮廓 · **瞳色** · 标志性永久识别点 · 终身不变的微表情习惯
#    并明文：「**修改本组 = 重新设计角色**，必须递增主版本号并通知全项目」。
#
# ⚠️ 这是**翻译**（工作流用中文描述特征，本项目用字段名），不是规则；
#    `validate_lifelong_map()` 会自检译出的 LOCK 名都在 §一 清单里。
LIFELONG_FIELDS: dict[str, list[str]] = {
    "核心骨相": ["face_shape", "jaw", "brow_ridge"],
    "五官轮廓": ["nose_bridge", "lips", "eye_shape"],
    "瞳色": ["eye_color"],
    "标志性永久识别点": ["permanent_marks", "signature_points"],
    "终身不变的微表情习惯": [],          # 本项目的字段里没有对应项（诚实留空）
}
# 这些字段所属的锁定项（用于默认锁定集）
#
# ⚠️ 「核心骨相」→ **`FACE`**（不是 `BODY`）：原文注解是「头颅与**面部骨架**结构」，
#    而 §四·补 B 里「**身形变化** / 体态气质」明确属于**可变项** ——
#    若把骨相译成 `BODY`，就会与 §四·补 B 直接冲突（同一样东西既终身固定又可变）。
_LIFELONG_LOCK_OF = {"核心骨相": "FACE", "五官轮廓": "FACE", "瞳色": "FACE",
                     "标志性永久识别点": "CHARACTER", "终身不变的微表情习惯": "EXPRESSION"}

# §四·补 B「剧情适配变量项（**各状态卡之间可不同**）」→ 锁定项（**翻译**）
VARIABLE_LOCKS: dict[str, list[str]] = {
    "外貌变化": ["HAIR"],              # 发色变化 / 胡须毛发变化
    "体态变化": ["BODY"],              # 身形变化 / 体态气质（≠ §四·补 A 的核心骨相）
    "发型妆容": ["HAIR"],              # 发型 / 妆容
    "服装配饰": ["COSTUME", "PROP"],   # 全套穿搭 / 核心配饰
}


def lifelong_conflicts(change_fields: list[str]) -> list[str]:
    """改到 §四·补 A 的**终身固定**项 → 返回冲突说明（空 = 没碰到）。"""
    out: list[str] = []
    for item, fields in LIFELONG_FIELDS.items():
        hit = [f for f in fields if f in change_fields]
        if hit:
            out.append(
                f"**{item}**（本次将改动：{'、'.join(hit)}）—— "
                f"`LOCK-SYSTEM.md` §四·补 A 列为「**100% 不可改动**」；"
                f"原文：「修改本组 = **重新设计角色**，必须递增主版本号并通知全项目」。"
                f"若只是当前状态（造型/服装/表情）变化，请改 `stage_variables` 而非这些字段")
    return out


# §四·补 A / B 是**角色**的规则；其余三类资产没有对应的权威清单
CHARACTER_LIKE = ("character", "expression", "pose")


def default_locks(rules, asset_type: str = "character") -> list[str]:
    """新建资产时的默认锁定集 —— 取 §四·补 A 终身固定项对应的 `LOCK_*`（仅角色类）。

    ⚠️ **此前 6 个 agent 各写一套，且每套都错**（实测逐条查过）：

    | 位置 | 原写法 | 错在哪 |
    |---|---|---|
    | `character_agent` | `["FACE","HAIR","BODY"]` | **正是** `ASSET_CARD.yaml` 第 104 行**注释里的举例**；HAIR 不在 §四·补 A（头发可改），却漏了真正不可改的**瞳色** |
    | `costume_agent` | `["CUT","LAYER_ORDER"]` | `CUT`/`LAYER_ORDER` **不是 §一 的 `LOCK_*` 名** |
    | `prop_agent` | `["STRUCTURE"]` | `STRUCTURE` 不在 §一 |
    | `scene_agent` | `["建筑","门窗",…]` | 那是 §32 的**中文空间要素**，被错当成锁定项 |
    | `expression_agent` / `pose_agent` | `locked=MUTABLE_PARTS` | **语义反转** —— 注释写着「只有这几项**允许**改」，却写进了 `locked`；且 `locked == editable` |

    → 现统一为：**只从 §四·补 A 推导**；角色以外的类型**返回空**（不臆造 ——
      §四·补 A/B 明写是角色的规则，硬套到道具上就是编）。
    """
    if asset_type and asset_type not in CHARACTER_LIKE:
        return []
    out: list[str] = []
    names = SHORT_NAMES(rules)
    for item in LIFELONG_FIELDS:
        n = _LIFELONG_LOCK_OF.get(item, "")
        if n and n in names and f"LOCK_{n}" not in out:
            out.append(f"LOCK_{n}")
    return out


def default_editable(rules, asset_type: str = "character") -> list[str]:
    """新建资产时的默认**可变**集 —— 取 §四·补 B「各状态卡之间可不同」的项（仅角色类）。

    与 `default_locks()` 互补：`locked` = 终身固定（§四·补 A），
    `editable` = 剧情适配变量（§四·补 B）。两者**不应有交集**（有交集说明翻译错了）
    —— 这一点由测试钉住。
    """
    if asset_type and asset_type not in CHARACTER_LIKE:
        return []
    out: list[str] = []
    names = SHORT_NAMES(rules)
    for locks in VARIABLE_LOCKS.values():
        for n in locks:
            if n in names and f"LOCK_{n}" not in out:
                out.append(f"LOCK_{n}")
    return out


def validate_lifelong_map(rules) -> list[str]:
    """自检：§四·补 A 译出的 LOCK 名必须在 §一 清单里（防工作流改名后失联）。"""
    names = SHORT_NAMES(rules)
    return [f"§四·补 A 的「{item}」译出 `LOCK_{n}`，但它不在 §一 锁定清单里"
            for item, n in _LIFELONG_LOCK_OF.items() if n and n not in names]


# 识别点属"身份"层（§四·补 A 终身固定核心识别特征）
FIELD_TO_LOCK["signature_points"] = "CHARACTER"


# ─────────────────────────────────────────────────────────────
# 报告
# ─────────────────────────────────────────────────────────────

@dataclass
class LockReport:
    """§三 STEP 2「冲突检测」的结果。"""

    directive: dict[str, str] = field(default_factory=dict)   # LOCK_* → LOCK/MODIFY
    changed: list[str] = field(default_factory=list)          # 本次变更项（短名）
    unchanged: list[str] = field(default_factory=list)        # 本次保持项（短名）
    conflicts: list[str] = field(default_factory=list)        # ⚠️ 将发生变化的锁定项
    unknown_fields: list[str] = field(default_factory=list)   # 译不出的 change_fields
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def render(self) -> str:
        L: list[str] = []
        if self.directive:
            L.append("  指令解析（§三 STEP 1）：" + " ｜ ".join(
                f"{k}={'LOCK' if v.upper() == 'LOCK' else 'MODIFY'}"
                for k, v in sorted(self.directive.items())))
        if self.changed:
            L.append(f"  changed  ：{', '.join(self.changed)}")
        if self.unchanged:
            L.append(f"  unchanged：{', '.join(self.unchanged)}")
        if self.conflicts:
            L.append(f"  ❌ **将发生变化的锁定项：{len(self.conflicts)} 个**"
                     f"（§三 STEP 2 要求列出来并提示用户）")
            for c in self.conflicts:
                L.append(f"      {c}")
        if self.unknown_fields:
            L.append(f"  ⚠️ 译不出锁定项名的字段：{', '.join(self.unknown_fields)}"
                     f"（`src/lock.py` 的 FIELD_TO_LOCK 需补）")
        for n in self.notes:
            L.append(f"  ℹ️ {n}")
        return "\n".join(L)


# ─────────────────────────────────────────────────────────────
# 解析工作流
# ─────────────────────────────────────────────────────────────

def lock_names(rules) -> list[str]:
    """§一「可锁定资产清单」的 13 个 `LOCK_*`（从工作流解析）。"""
    return list(getattr(rules, "lock_names", []) or [])


def validate_field_map(rules) -> list[str]:
    """自检：`FIELD_TO_LOCK` 译出的名字必须都在 §一 清单里。

    ⚠️ 这是防"代码与工作流失联"的钩子 —— 若工作流把 `LOCK_COLOR` 改名为别的，
    这里会立刻报出来，而不是等到"检索不到锁定项"时才发现。
    """
    full = set(lock_names(rules))
    if not full:
        return ["⚠️ 未能从 `LOCK-SYSTEM.md` §一 解析出任何 `LOCK_*` —— 锁定机制失效"]
    # ⚠️ 必须**补回 `LOCK_` 前缀**再比 —— `FIELD_TO_LOCK` 存的是短名（`BODY`），
    #    而 §一 清单是全名（`LOCK_BODY`）。第一版直接拿短名比全名，
    #    于是**每一项都误报**（13 项全红）—— 典型"判据两边不同源"。
    short = {short_name(x) for x in full}
    bad = sorted({v for v in FIELD_TO_LOCK.values() if v not in short})
    return [f"`FIELD_TO_LOCK` 译出 `{b}`（= `LOCK_{b}`），但它不在工作流 §一 的锁定清单里"
            f"（清单：{', '.join(sorted(short))}）" for b in bad]


def short_name(lock: str) -> str:
    """`LOCK_HAIR` → `HAIR`（CHANGELOG 模板用的是短名）。"""
    return lock[5:] if lock.startswith("LOCK_") else lock


def parse_directive(text: str, rules) -> dict[str, str]:
    """§三 STEP 1：把用户话解析成 `LOCK_* → LOCK/MODIFY` 映射。

    依据 §二「自然语言 → 锁定映射表」：命中某行的「用户说」即采用该行的解释。
    例：「人物不变，只换衣服」→ `{CHARACTER: LOCK, FACE: LOCK, HAIR: LOCK,
    BODY: LOCK, COSTUME: MODIFY}`。
    """
    out: dict[str, str] = {}
    for row in getattr(rules, "nl_lock_map", []) or []:
        phrase, expr = row[0], row[1]
        # ⚠️ §二 的表里，某些「用户说」带括号注解（如「全部保持不变（§43）」）——
        #    不去掉括号就永远匹配不上用户的实际说法（实测踩到）。
        phrase = re.sub(r"[（(].*?[)）]", "", phrase or "").strip()
        if not phrase or phrase not in text:
            continue
        for part in expr.split(","):
            part = part.strip()
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip().upper()
            if not k or v not in ("LOCK", "MODIFY"):
                continue
            # `CHARACTER DNA` 这类带空格的写法 → 取首词
            k = k.split()[0].strip()
            if k == "ALL":
                # `ALL=LOCK` → 展开为全部 13 项
                for n in lock_names(rules):
                    out.setdefault(short_name(n), "LOCK")
            elif k:
                out[k] = v
        # ── 第二种表达形式：`WORLD/CHARACTER/FACE/... 全 LOCK`（无 `=`）──
        #    实测 §二 的「全部保持不变（§43）」是这种写法；只认 `K=V` 会漏掉它。
        if "=" not in expr and "全 LOCK" in expr:
            head = expr.split("全 LOCK", 1)[0]
            for tok in re.split(r"[/、,，\s]+", head):
                tok = tok.strip()
                if tok in SHORT_NAMES(rules):
                    out[tok] = "LOCK"
    return out


def SHORT_NAMES(rules) -> set[str]:
    """§一 清单的**短名**集合（`LOCK_HAIR` → `HAIR`）。"""
    return {short_name(n) for n in lock_names(rules)}


# ── §二 里**不是 LOCK 映射**的那几行：指令语义（§44–§49 与 §33 回滚）──
#    ⚠️ 它们也是 §二 的正式内容，不能当"解析失败"丢掉 —— 而是**另一类机制**。
#    `rollback` 三项正是本模块 CHANGELOG 的用武之地（§33「恢复」命令）。
COMMAND_KINDS: dict[str, str] = {
    "重新生成": "resample",      # §44：保持资产身份不变，只重新采样画面（不递增版本）
    "换风格": "restyle",         # §45：DNA 全 LOCK，STYLE=MODIFY
    "做成漫画": "restyle", "做成动漫": "restyle",
    "写实": "restyle",           # §48：保持原始 Character DNA
    "高级感": "restyle", "电影感": "restyle",
    "恢复上一版": "rollback_prev",
    "恢复原版": "rollback_first",
    "取消这次修改": "rollback_cancel",
}


def command_kind(text: str) -> str:
    """识别 §二 里的**指令语义**（非 LOCK 映射那几行）。找不到返回空串。"""
    for phrase, kind in COMMAND_KINDS.items():
        if phrase in text:
            return kind
    return ""


def locks_from_fields(change_fields: list[str], rules) -> tuple[list[str], list[str]]:
    """把本项目的 `change_fields` 译成锁定项短名 → `(changed, 译不出的原始字段)`。

    `changed` 按工作流 §一 清单的**顺序**排列（稳定输出，便于人读与 diff）。
    """
    order = [short_name(n) for n in lock_names(rules)]
    got: list[str] = []
    unknown: list[str] = []
    for f in change_fields:
        name = FIELD_TO_LOCK.get(f)
        if name is None:
            unknown.append(f)
        elif name not in got:
            got.append(name)
    got.sort(key=lambda n: order.index(n) if n in order else 999)
    return got, unknown


def detect_conflicts(card, change_fields: list[str], rules,
                     directive: dict[str, str] | None = None) -> LockReport:
    """§三 STEP 2「冲突检测」：**修改项与 locked_assets 冲突时列出来**。

    冲突的判据（两条独立事实的对照）：
      · 卡片上被标为 `LOCK_*` 的项（`card.locked`），
      · 与本次实际要改的项（由 `change_fields` 译出），
      · **取交集** —— 即"改到了锁定项"。
    但若用户在**同一句里明确要求改它**（§二 映射成 `X=MODIFY`），
    那是**有意为之**，不算冲突，只记一条说明。
    """
    rep = LockReport()
    directive = directive or {}
    rep.directive = dict(directive)
    changed, unknown = locks_from_fields(change_fields, rules)
    rep.changed, rep.unknown_fields = changed, unknown

    order = [short_name(n) for n in lock_names(rules)]
    rep.unchanged = [n for n in order if n not in changed]

    # ── 冲突来源 ①：§四·补 A 的**终身固定**项被改动 ──
    #    ⚠️ 这是**最该报**的一类：原文说「修改 = 重新设计角色」。
    #    但它**与 §二 的锁定无关** —— §二 的 `X=LOCK` 是"本次别动"，
    #    §四·补 A 是"永远别动"。两者必须分开报（混在一起会让人以为是同一种约束）。
    real_fields = [f for f in change_fields if f in FIELD_TO_LOCK]
    rep.conflicts.extend(lifelong_conflicts(real_fields))

    # ── 冲突来源 ②：卡片上被标为 `LOCK_*`，而本次要改它 ──
    #    ⚠️ 语义必须是「**用户明确声明过要锁**」，**不能**是"上次没改到的项"。
    #    第一版把 `unchanged`（= 全部减 changed）也当锁定写进卡片，于是
    #    「把她的衣服换成红色」这类**用户明确要求的**改动会被判成"锁定项冲突"
    #    —— 纯误报。故 `locked` 只由 `directive`（§二的 `X=LOCK`）写入。
    locked_on_card = {short_name(x) if x.startswith("LOCK_") else x
                      for x in (getattr(card, "locked", None) or [])}
    for name in changed:
        if name not in locked_on_card:
            continue
        if directive.get(name, "").upper() == "MODIFY":
            rep.notes.append(
                f"`{name}` 在卡片上是锁定项，但本条指令**明确要求改它**"
                f"（§二 映射为 `{name}=MODIFY`）→ 不算冲突；"
                f"修改后应解除该项锁定")
        else:
            rep.notes.append(
                f"`{name}` —— 卡片上有 `LOCK_{name}`（来自此前某条「全 LOCK」指令），"
                f"本次变更会改动它。若确实要改，请明说「只改 {name}」")
    # §二 未命中时**明说** —— 否则用户会以为那张表被用上了
    # （实测：「把她的头发换成银白色」不在 §二 的 17 行固定话术里）
    if not directive:
        rep.notes.append(
            "指令未命中 `LOCK-SYSTEM.md` §二 的映射表（那 17 行是固定话术，"
            "如「只换发型」「人物不变，只换衣服」）→ 本次**按 change_fields 直接推导** "
            "changed/unchanged，不做 §二 级的 `ALL=LOCK` 展开")
    return rep


# ─────────────────────────────────────────────────────────────
# §三 STEP 4：变更记录（CHANGELOG）
# ─────────────────────────────────────────────────────────────

CHANGELOG_REL = "output/CHANGELOG.yaml"


def _esc(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def append_entry(root: Path | str, *, asset: str, version: str,
                 changed: list[str], unchanged: list[str], reason: str) -> Path:
    """追加一条变更记录（§三 STEP 4「记录变更」，模板字段严格对齐）。

    ⚠️ 落成 **YAML 文本**（不是".yaml 后缀的 JSON"）—— 因为该文件的权威模板是
    `02-服化道/模板/CHANGELOG.yaml`，要能被人工直接读、也是「恢复上一版」的依据。
    只写不读的"记录"等于没有记录，故本模块同时提供 `read_entries()`。

    ⚠️ `changed` / `unchanged` **必须完整、不得省略**（模板 §项目管理 明文）。
    故这里不接受空 `unchanged` 以外的省略 —— 空列表也要显式写出。
    """
    root = Path(root)
    p = root / CHANGELOG_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if not p.exists():
        lines += ["# CHANGELOG — 版本控制与修改记录（由 07-智能体运行时 追加）",
                  "# 字段与 `02-服化道/模板/CHANGELOG.yaml` 严格对齐",
                  "#   changed / unchanged 必须完整，不得省略",
                  "", "CHANGELOG:", ""]
    lines += [f"  - version: {_esc(version)}",
              f"    asset: {_esc(asset)}",
              f"    changed: [{', '.join(_esc(x) for x in changed)}]",
              f"    unchanged: [{', '.join(_esc(x) for x in unchanged)}]",
              f"    reason: {_esc(reason)}", ""]
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return p


def read_entries(root: Path | str) -> list[dict]:
    """读回全部变更记录（供「恢复上一版」与 `drift` 校验）。

    ⚠️ 只用标准库解析这**一种**固定格式（每条 5 个键、缩进固定），
    不引入 YAML 依赖 —— 项目承诺"装完 Python 就能跑"。
    若格式被人改乱，返回已解析的部分并保留原文行号供排查（不静默丢弃）。
    """
    p = Path(root) / CHANGELOG_REL
    if not p.exists():
        return []
    out: list[dict] = []
    cur: dict | None = None
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s.startswith("- version:"):
            cur = {"version": _unq(s.split(":", 1)[1])}
            out.append(cur)
            continue
        if cur is None or ":" not in s or s.startswith("#"):
            continue
        k, v = s.split(":", 1)
        k, v = k.strip(), v.strip()
        if k in ("asset", "reason"):
            cur[k] = _unq(v)
        elif k in ("changed", "unchanged"):
            body = v.strip().strip("[]")
            cur[k] = [_unq(x.strip()) for x in body.split(",") if x.strip()]
    return out


def _unq(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    return s
