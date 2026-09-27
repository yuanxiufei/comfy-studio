# -*- coding: utf-8 -*-
"""本机专属覆盖层 —— `prompts/overrides/`。

═══════════════════════════════════════════════════════════════════
它解决什么问题
═══════════════════════════════════════════════════════════════════
本项目的第一条纪律是「**规则只读工作流，不复制**」（工作流质量守则 §2 单一权威来源）。
但现实里总有**本机专属**的需求：

  · 某个客户要求的额外禁止项
  · 特定模型的参数偏好
  · 临时试验的版式变体

这些**不该写进工作流**（会污染权威层），也不该去改代码（下次更新就丢）。
`overrides/` 就是那个出口：**在不碰工作流、不碰代码的前提下增补规则**。

═══════════════════════════════════════════════════════════════════
文件名约定
═══════════════════════════════════════════════════════════════════
    `prompts/overrides/<scope>.<target>.md`

    scope （作用范围）
        `all`            → 全部资产
        `character` / `costume` / `prop` / `environment` / `expression` / `pose`

    target（作用点与语义）
        `negative`  → **追加**负面词（该 scope）
        `extra`     → **追加**一段正向提示词（该 scope）
        `layout`    → **替换**版式段（该 scope）—— 唯一有替换语义的

例：
    `all.negative.md`          给所有资产再加几条负面词（如某平台特有伪影）
    `character.extra.md`       只给角色补一段（如客户指定的站姿说明）
    `environment.layout.md`    换掉场景的版式段（如改用等距柱状投影）

═══════════════════════════════════════════════════════════════════
两条设计原则（都是"静默坑"的预防）
═══════════════════════════════════════════════════════════════════
① **未识别的文件名必须报警，不能静默忽略。**
   用户写 `character.neg.md`（`neg` 不是合法 target），若静默忽略，他会以为
   「规则加了但没生效、agent 坏了」—— 比报错难查得多。

② **除了 `layout`，一律只有"追加"语义。**
   追加是安全的（最坏是多几条约束）；替换会**悄悄抹掉工作流的权威规则**。
   故替换只保留 `layout` 一个位置，且会在 `rules` / `doctor` 里高亮。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# 合法 scope / target
SCOPES = ("all", "character", "costume", "prop", "environment",
          "expression", "pose")
TARGETS = ("negative", "extra", "layout")

# 单文件体积上限（防止误把整份文档塞进来 —— 覆盖层应当"短而具体"）
MAX_KB = 8


@dataclass
class Override:
    """一个已加载的覆盖项。"""

    path: Path
    scope: str
    target: str
    text: str
    replaces: bool = False          # True = 替换语义（仅 layout）

    @property
    def rel(self) -> str:
        return self.path.name

    def __str__(self) -> str:
        kind = "替换" if self.replaces else "追加"
        return f"{self.rel}（{self.scope} · {kind} {self.target}）"


@dataclass
class Overrides:
    """`prompts/overrides/` 的加载器。

    :param root: 项目根（`07-智能体运行时/`）。目录不存在时一切为空、不报错。
    """

    root: Path | str
    items: list[Override] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)     # 文件名不合约定
    problems: list[str] = field(default_factory=list)    # 内容问题（过大等）

    # 缓存：`(scope, target)` → 合并后的文本
    _merged: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.dir = self.root / "prompts" / "overrides"
        self._scan()

    # ── 扫描 ──
    def _scan(self) -> None:
        if not self.dir.is_dir():
            return
        for p in sorted(self.dir.glob("*.md")):
            if p.name.startswith((".", "_")) or p.name.lower() == "readme.md":
                continue    # `.gitkeep` / `README.md` / `_开头的示例` 不算覆盖
            parts = p.stem.split(".")
            if len(parts) != 2:
                self.unknown.append(p.name)
                continue
            scope, target = parts[0].strip(), parts[1].strip()
            if scope not in SCOPES or target not in TARGETS:
                self.unknown.append(p.name)
                continue
            try:
                text = p.read_text(encoding="utf-8").strip()
            except Exception as e:                                   # noqa: BLE001
                self.problems.append(f"{p.name}：读取失败（{e}）")
                continue
            kb = len(text.encode("utf-8")) / 1024
            if kb > MAX_KB:
                self.problems.append(
                    f"{p.name}：{kb:.1f} KB 超过 {MAX_KB} KB 上限 —— "
                    f"覆盖层应当**短而具体**；若是一整套规则，请改工作流（权威层）")
                continue
            if not text:
                self.problems.append(f"{p.name}：内容为空")
                continue
            # ⚠️ `extra` / `layout` 的内容会进**英文** prompt：中文在那儿会被多数
            #    图像模型直接忽略（约束静默失效，比报错更难发现）。
            #    只提醒、不拦截 —— 也可能是有意为之（如给中文平台的版本）。
            if target in ("extra", "layout"):
                cn = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
                if cn:
                    self.problems.append(
                        f"{p.name}：内容含 {len(cn)} 个中文字符（{''.join(cn[:10])}…）—— "
                        f"该文件进**英文** prompt，中文多半会被图像模型忽略")
            self.items.append(Override(path=p, scope=scope, target=target,
                                       text=text, replaces=(target == "layout")))

    # ── 查询 ──
    def _text(self, scope: str, target: str) -> str:
        key = (scope, target)
        if key not in self._merged:
            hits = [o for o in self.items
                    if o.target == target and o.scope in (scope, "all")]
            # `exact scope` 的文件排在 `all` 之后，便于人读时能看出各自来源
            hits.sort(key=lambda o: (o.scope == "all", o.rel))
            self._merged[key] = "\n\n".join(
                f"<!-- override: {o.rel} -->\n{o.text}" for o in hits)
        return self._merged[key]

    def negative_extra(self, asset_type: str) -> list[str]:
        """该资产类型要**追加**的负面词（逗号/换行分隔，已去重保序）。"""
        raw = self._text(asset_type, "negative")
        out: list[str] = []
        for term in re.split(r"[,\n]", raw):
            t = re.sub(r"<!--.*?-->", "", term).strip()
            if t and t not in out:
                out.append(t)
        return out

    def prompt_extra(self, asset_type: str) -> str:
        """该资产类型要**追加**的正向段（去掉来源注释行）。"""
        raw = self._text(asset_type, "extra")
        return re.sub(r"<!--.*?-->\s*", "", raw).strip()

    def layout(self, asset_type: str) -> str:
        """该资产类型的**替换**版式段；无则空串。"""
        raw = self._text(asset_type, "layout")
        return re.sub(r"<!--.*?-->\s*", "", raw).strip()

    # ── 报告 ──
    def active(self) -> list[Override]:
        """实际生效的覆盖项（供 `rules` / `doctor` 展示）。"""
        return list(self.items)

    def is_empty(self) -> bool:
        return not self.items

    def report(self) -> str:
        """人读报告。**必须展示** —— 静默生效的覆盖会让"prompt 为什么变了"无从查起。"""
        if self.is_empty() and not self.unknown and not self.problems:
            return ("  （无覆盖项）\n"
                    "  约定：`prompts/overrides/<scope>.<target>.md`，"
                    "scope = all|character|costume|prop|environment|expression|pose，"
                    "target = negative（追加）|extra（追加）|layout（替换）")
        lines: list[str] = []
        if self.items:
            lines.append(f"  生效 {len(self.items)} 项：")
            for o in self.items:
                head = o.text.splitlines()[0][:58] if o.text else ""
                mark = "⚠️ 替换" if o.replaces else "＋ 追加"
                lines.append(f"    {mark} {o.rel:<28s} [{o.scope}] {head}")
        if self.unknown:
            lines.append(f"  ❌ 文件名不符合约定（**未生效**，共 {len(self.unknown)} 个）：")
            for n in self.unknown:
                lines.append(f"      {n}")
            lines.append("      约定：`<scope>.<target>.md` —— "
                         f"scope ∈ {', '.join(SCOPES)}；target ∈ {', '.join(TARGETS)}")
        if self.problems:
            lines.append("  ⚠️ 内容问题：")
            for p in self.problems:
                lines.append(f"      {p}")
        return "\n".join(lines)
