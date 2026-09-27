# -*- coding: utf-8 -*-
"""规则来源层 —— **从工作流加载权威规则，本项目不复制一份**。

═══════════════════════════════════════════════════════════════════
为什么必须有这一层
═══════════════════════════════════════════════════════════════════
本项目是 `AI漫剧智能体工作流` 的**代码实现**，不是它的替代品。
工作流里已有权威规则，本项目**只读取、不复制、不改写** —— 否则必然发散，
正是工作流自身质量守则 §2「单一权威来源」与 §五·4「改权威层必须同步实体层」要防的事。

加载的权威文件
──────────────
  02-服化道/引擎/NEGATIVE-PROMPT-LIBRARY.md   → 负面词（通用 / 三视图 / 按模块 / 修复映射表）
  02-服化道/引擎/TURNAROUND-STANDARD.md       → 三视图硬标准 · 版式英文段 · 文字屏蔽 · 质量参数
  02-服化道/模板/ASSET_CARD.yaml              → 资产卡字段与 id_status 枚举（schema.py 已对齐）
  00-总控路由.md                              → ID 规范（CHR_/CST_/PRP_/ENV_…）

两种运行模式
────────────
  **live（默认）**：每次运行从工作流目录**实时读取** —— 工作流一改，Agent 立刻跟上。
  **snapshot**    ：`export` 把规则快照到 `vendor/` 并记录来源 hash，
                    供**单独迁移**（不含工作流目录）时使用；
                    快照与原文不一致时会提示「降级运行」并给出 diff 摘要。

> ⚠️ 本模块**只读**工作流文件。任何写工作流的动作都不在这里发生。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .overrides import Overrides

# ─────────────────────────────────────────────────────────────
# 权威文件清单（相对于工作流根）
# ─────────────────────────────────────────────────────────────

RULE_FILES = {
    "negative": "02-服化道/引擎/NEGATIVE-PROMPT-LIBRARY.md",
    "turnaround": "02-服化道/引擎/TURNAROUND-STANDARD.md",
    "asset_card": "02-服化道/模板/ASSET_CARD.yaml",
    "router": "00-总控路由.md",
    # ⚠️ 在 `模板/` 下，不在 `引擎/` 下（实测按常识猜路径踩到过）
    "index_templates": "02-服化道/模板/INDEX-TEMPLATES.md",
    # 锁定系统与修改引擎（自述「这是连续生产的核心机制」）
    "lock": "02-服化道/引擎/LOCK-SYSTEM.md",
}


# ─────────────────────────────────────────────────────────────
# Markdown 解析小工具
# ─────────────────────────────────────────────────────────────

_HEADING = re.compile(r"^(#{1,6})\s*(.+?)\s*$")
_FENCE = re.compile(r"^\s*```")


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _heading_level(line: str) -> int:
    """返回标题级别（# 的个数）；不是标题返回 0。"""
    m = _HEADING.match(line)
    return len(m.group(1)) if m else 0


def _find_heading(text: str, keyword: str, *, level: int | None = None,
                  start: int = 0) -> int:
    """返回**含该关键词**的标题行号；找不到返回 -1。

    :param level: 只匹配该级别的标题（None = 不限）
    :param start: 从第几行开始找
    """
    ls = _lines(text)
    for i in range(max(0, start), len(ls)):
        m = _HEADING.match(ls[i])
        if m and keyword in m.group(2):
            if level is None or len(m.group(1)) == level:
                return i
    return -1


def _find_line(text: str, keyword: str, *, start: int = 0) -> int:
    """找**任意一行**含该关键词（标题或粗体行都认）。

    工作流里有「**电影感必须具体化（§49），不得只写 `cinematic, masterpiece`：**」
    这类**粗体行作为小标题**的写法 —— 只按 `#` 标题找会漏，进而取错代码块。
    """
    ls = _lines(text)
    for i in range(max(0, start), len(ls)):
        if keyword in ls[i]:
            return i
    return -1


def _code_block_after(text: str, start: int) -> list[str]:
    """取 start 行之后的**第一个** ``` 块的内容行。"""
    ls = _lines(text)
    i = start + 1
    while i < len(ls) and not _FENCE.match(ls[i]):
        i += 1
    if i >= len(ls):
        return []
    i += 1
    out = []
    while i < len(ls) and not _FENCE.match(ls[i]):
        out.append(ls[i].strip())
        i += 1
    return out


def _split_terms(block_lines: list[str]) -> list[str]:
    """把 code block 拆成词表。

    分隔符含 `·` —— 工作流的字段清单用「时代 · 身份 · 阶层 · …」这种中点分隔，
    漏掉它会整行当成一个词（实测：服装 25 字段只解析出 5 项）。
    """
    joined = " ".join(block_lines)
    raw = re.split(r"[,，、·\n]+", joined)
    out, seen = [], set()
    for t in raw:
        t = t.strip().strip("。.;；")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def _table_after(text: str, start: int) -> list[dict[str, str]]:
    """取 start 行之后的第一个 Markdown 表格（表头 + 行）。"""
    ls = _lines(text)
    i = start + 1
    while i < len(ls) and not ls[i].strip().startswith("|"):
        i += 1
    if i >= len(ls):
        return []
    header = [c.strip().strip("*`") for c in ls[i].strip().strip("|").split("|")]
    i += 1
    if i < len(ls) and re.match(r"^\|[\s:|-]+\|?\s*$", ls[i]):
        i += 1
    rows = []
    while i < len(ls) and ls[i].strip().startswith("|"):
        cells = [c.strip().strip("*`") for c in ls[i].strip().strip("|").split("|")]
        if len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
        i += 1
    return rows


# ─────────────────────────────────────────────────────────────
# 主类
# ─────────────────────────────────────────────────────────────

@dataclass
class DriftReport:
    ok: bool = True
    missing: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    detail: str = ""


class RuleSource:
    """权威规则的**只读**访问器。

    :param workflow_root: `AI漫剧智能体工作流/` 的路径。
                          为 None 时自动从本项目位置往上找。
    :param vendor_dir:    快照目录（live 读取失败时回退到这里）。
    """

    def __init__(self, workflow_root: str | os.PathLike | None = None,
                 vendor_dir: str | os.PathLike | None = None):
        self.vendor_dir = Path(vendor_dir) if vendor_dir else \
            Path(__file__).resolve().parent.parent / "vendor"
        self.workflow_root = Path(workflow_root) if workflow_root else self._autodetect()
        self._cache: dict[str, object] = {}
        self.mode = "live" if self.workflow_root and self.workflow_root.is_dir() else "snapshot"
        # ⭐ 本机覆盖层（`prompts/overrides/`）挂在这里 —— 于是**所有**读取规则的地方
        #    都不必改签名就自动生效（见 `overrides.py` 的两条设计原则）。
        self.overrides = Overrides(self._project_root())
        if self.mode == "snapshot":
            self._load_snapshot()

    @staticmethod
    def _project_root() -> Path:
        """本项目根（`07-智能体运行时/`）= `src/` 的上一级。"""
        return Path(__file__).resolve().parent.parent

    # ── 定位工作流根 ──
    def _autodetect(self) -> Path | None:
        """本项目位于 `AI漫剧智能体工作流/07-资产库Agent/`，故工作流根 = 上上级。"""
        here = Path(__file__).resolve()
        for p in [here.parent.parent.parent, *here.parents]:
            if (p / "02-服化道" / "引擎" / "NEGATIVE-PROMPT-LIBRARY.md").exists():
                return p
        env = os.getenv("WORKFLOW_ROOT")
        if env and Path(env).is_dir():
            return Path(env)
        return None

    # ── 读取 ──
    def raw(self, key: str) -> str:
        """读某个权威文件的原文。缺失时回退快照，再缺失则抛错。"""
        rel = RULE_FILES[key]
        if self.mode == "live":
            p = self.workflow_root / rel
            if p.exists():
                return p.read_text(encoding="utf-8")
        snap = self.vendor_dir / "rules" / Path(rel).name
        if snap.exists():
            return snap.read_text(encoding="utf-8")
        raise FileNotFoundError(
            f"权威规则缺失：{rel}\n"
            f"  · 工作流目录：{self.workflow_root or '（未找到）'}\n"
            f"  · 快照目录：{self.vendor_dir}\n"
            f"  解决：把本项目与其所在的工作流目录一起复制；"
            f"或先在有工作流的机器上执行 `python main.py export` 生成快照。")

    # ── 负面词库 ──
    @property
    def negative_common(self) -> list[str]:
        if "neg_common" not in self._cache:
            t = self.raw("negative")
            i = _find_heading(t, "通用负面提示词")
            self._cache["neg_common"] = _split_terms(_code_block_after(t, i))
        return self._cache["neg_common"]  # type: ignore[return-value]

    @property
    def negative_three_view(self) -> list[str]:
        if "neg_3v" not in self._cache:
            t = self.raw("negative")
            i = _find_heading(t, "三视图专用")
            self._cache["neg_3v"] = _split_terms(_code_block_after(t, i))
        return self._cache["neg_3v"]  # type: ignore[return-value]

    @property
    def negative_by_module(self) -> dict[str, list[str]]:
        """按模块追加的负面词 —— key 为中文模块名（角色/服装/道具/表情/动作/场景）。

        源文件里每个模块块有**中英两行**，这里只取英文行（生图用）。
        """
        if "neg_mod" in self._cache:
            return self._cache["neg_mod"]  # type: ignore[return-value]
        t = self.raw("negative")
        ls = _lines(t)
        start = _find_heading(t, "按模块追加")
        if start < 0:
            self._cache["neg_mod"] = {}
            return {}
        base = _heading_level(ls[start])
        out: dict[str, list[str]] = {}
        i = start + 1
        while i < len(ls):
            lv = _heading_level(ls[i])
            if lv and lv <= base:              # 回到同级或更高级标题 → 本节结束
                break
            if lv == base + 1:                 # 仅取直接子标题（角色/服装/道具/…）
                name = re.sub(r"（.*?）", "", _HEADING.match(ls[i]).group(2)).strip()
                block = _code_block_after(t, i)
                # 该块含中英两行 → 取英文行（ASCII 占比高且更长的那行）
                best = ""
                for b in block:
                    asc = sum(1 for c in b if ord(c) < 128)
                    if len(b) > 0 and asc > len(b) * 0.6 and len(b) > len(best):
                        best = b
                terms = [x.strip() for x in best.split(",") if x.strip()] \
                    or _split_terms(block)
                if terms:
                    out[name] = terms
            i += 1
        self._cache["neg_mod"] = out
        return out

    @property
    def failure_repair_map(self) -> dict[str, dict[str, str]]:
        """ERROR RECOVERY 修复映射表：FAILURE-00X → {现象, 处理, 追加负面词}。"""
        if "fail_map" in self._cache:
            return self._cache["fail_map"]  # type: ignore[return-value]
        t = self.raw("negative")
        i = _find_heading(t, "ERROR RECOVERY")
        rows = _table_after(t, i)
        out = {}
        for r in rows:
            key = r.get("编号", "").strip()
            if key:
                out[key] = {"现象": r.get("失败现象", ""),
                            "处理": r.get("处理方案", ""),
                            "追加": r.get("追加负面词", "")}
        self._cache["fail_map"] = out
        return out

    def negative_for(self, asset_type: str, failures: list[str] | None = None,
                     *, three_view: bool = True) -> str:
        """按「通用 + 模块 + （三视图）+ 修复追加」四层叠加，依负面词库 §五·1「默认全量追加」。

        注：§五·2 规定 fail 后**只增不换** —— 故 failures 是**追加**而非替换。
        """
        MODCN = {"character": "角色", "costume": "服装", "prop": "道具",
                 "expression": "表情", "pose": "动作", "environment": "场景"}
        terms = list(self.negative_common)
        if three_view and asset_type in ("character", "prop", "costume"):
            terms += self.negative_three_view
        terms += self.negative_by_module.get(MODCN.get(asset_type, ""), [])
        for fid in (failures or []):
            extra = self.failure_repair_map.get(fid, {}).get("追加", "")
            if extra:
                terms += [x.strip() for x in extra.split(",") if x.strip()]
        return ", ".join(dict.fromkeys(terms))

    # ── 三视图标准 ──
    @property
    def turnaround_standard(self) -> dict[str, str]:
        """§1.1 默认硬标准表（画幅/背景/布局/灯光/…）。"""
        if "ta_std" not in self._cache:
            t = self.raw("turnaround")
            i = _find_heading(t, "默认硬标准")
            self._cache["ta_std"] = {r.get("项", ""): r.get("标准", "")
                                     for r in _table_after(t, i)}
        return self._cache["ta_std"]  # type: ignore[return-value]

    def _en_segment(self, key: str, cache_key: str, heading: str) -> str:
        if cache_key not in self._cache:
            t = self.raw("turnaround")
            i = _find_heading(t, heading)
            self._cache[cache_key] = " ".join(_code_block_after(t, i)).replace("\n", " ")
        return self._cache[cache_key]  # type: ignore[return-value]

    @property
    def turnaround_en_segment(self) -> str:
        """§1.3 可拼接英文标准段（三视图）。"""
        return self._en_segment("turnaround", "ta_en", "可拼接英文标准段")

    @property
    def costume_en_segment(self) -> str:
        """§2.3 服装**可拼接英文标准段**。

        ⚠️ 修（2026-09-24）：原用标题「服装标准（§07）」定位 → `_code_block_after`
        取到该标题下的**第一个**代码块，那是 **§2.1 必填描述字段（25 项）**，
        于是 `LAYOUT:` 段里被塞进一串**中文字段名**（英文 prompt 里夹中文）。
        现改用**精确小节标题** `2.3 可拼接英文标准段`。
        """
        return self._en_segment("turnaround", "cst_en", "2.3 可拼接英文标准段")

    @property
    def prop_en_segment(self) -> str:
        """§3.3 道具**可拼接英文标准段**（同 `costume_en_segment` 的修正理由）。"""
        return self._en_segment("turnaround", "prp_en", "3.3 可拼接英文标准段")

    @property
    def scene_en_segment(self) -> str:
        """§四·4.4 场景可拼接英文标准段（§09）。

        ⚠️ 场景的英文段**与前三条结构不同** —— 它是 `Cinematic environment, [...]`
        开头的电影环境描述，且**不含 pure white background**（§四 明文：
        「环境不使用纯白背景」）。故场景的 `_tail_block` 也必须换掉背景段。

        ⚠️ 必须用**精确小节号**定位：若只写「场景标准（§09）」，`_code_block_after`
        会取到该标题下的**第一个**代码块（那是「必须生成要素」的元素清单，不是英文段）。
        """
        return self._en_segment("turnaround", "env_en", "4.4 可拼接英文标准段")

    @property
    def scene_negative(self) -> list[str]:
        """§四·4.5 场景负面词（中英双写，只取英文行）。

        注：`negative_by_module` 也会带一组场景词（来自负面词库 §三）；
        这里额外取 §四·4.5 —— 两者是**不同章节**的独立声明，都应叠加。
        """
        if "neg_scene" in self._cache:
            return self._cache["neg_scene"]  # type: ignore[return-value]
        t = self.raw("turnaround")
        i = _find_heading(t, "场景负面词")
        terms: list[str] = []
        for b in _code_block_after(t, i):
            for part in b.split(","):
                s = part.strip()
                # 只取英文行（含中文的行整体跳过）
                if s and not re.search(r"[\u4e00-\u9fa5]", s) and s not in terms:
                    terms.append(s)
        self._cache["neg_scene"] = terms
        return terms  # type: ignore[return-value]

    # ── 场景 360° 全景基准（§4.6）──
    @property
    def panorama(self) -> dict:
        """§四·4.6 场景空间基准方案：360° 全景。

        工作流原话：「**全景定基准 → 六角度出分镜可用图**」——
        先出一张 360° 全景确定**空间的完整布局**，避免"只顾一面墙"导致后续多角度空间矛盾。

        ⚠️ 解析按**标签定位**（「中文正向模板」/「英文正向模板」/「反向提示词」），
        不要按"第 N 个代码块"——该节里还夹着用途引用、参数表、技术要点，
        按序号取会在原文微调后**静默取错**（同 §2.3/§3.3 的教训）。
        """
        if "pano" in self._cache:
            return self._cache["pano"]  # type: ignore[return-value]
        t = self.raw("turnaround")
        i = _find_heading(t, "360° 全景")
        seg = "\n".join(_lines(t)[i:]) if i >= 0 else t

        def _norm(s: str) -> str:
            """折叠**重复逗号**并压空白。

            ⚠️ 原文的模板是**多行**的，且行尾/行首各自带逗号：
                    8K超高清,
                    高动态范围HDR,
                逐行 strip 后再用 ", " 拼接 → 变成 `8K超高清,, 高动态范围HDR`（实测踩到）。
            """
            s = re.sub(r"\s*,(\s*,)+", ", ", s)
            s = re.sub(r"\s+", " ", s)
            return s.strip(" ,")

        def block_after(label: str) -> str:
            """按**标签**取其后第一个代码块（不按序号 —— 见 docstring 的说明）。"""
            ls = _lines(seg)
            for k, l in enumerate(ls):
                if label in l:
                    out: list[str] = []
                    for j in range(k + 1, len(ls)):
                        if ls[j].lstrip().startswith("```"):
                            if out:
                                break
                            continue
                        if out or ls[j].strip():
                            out.append(ls[j].strip())
                    return _norm(" ".join(x for x in out if x))
            return ""

        params: dict[str, str] = {}
        if i >= 0:
            # 去掉 markdown 反引号（表里形如 `` `5824×2880`（2:1） ``）——
            # 留着会显示成「分辨率=5824×2880`（2:1）」
            params = {r.get("项", ""): (r.get("值", "") or "").replace("`", "")
                      for r in _table_after(t, i)}

        self._cache["pano"] = {
            "cn": block_after("中文正向模板"),
            "en": block_after("英文正向模板"),
            "negative": block_after("反向提示词"),
            "params": {k: v for k, v in params.items() if k},
            "usage": [l.strip("- ").strip() for l in _lines(seg)
                      if l.strip().startswith(("1.", "2.", "3."))],
        }
        return self._cache["pano"]  # type: ignore[return-value]

    # ── 场景六角度（`模板/INDEX-TEMPLATES.md` §4.1）──
    @property
    def scene_angles(self) -> dict:
        """§4.1 场景资产库索引表 —— **场景多角度生成的必需机制**。

        原文警告（**必须记住**）：
            「⚠️ 这是场景多角度生成的必需机制。**不建此表 → 各角度独立从文字生成
              → 空间必然漂移。**」

        生成铁则（原文 4 条，逐字保留）：
            1. **必须先出 S01**（纯文字 prompt），保存其 URL 为 `<场景名>_S01_url`
            2. **S02–S06 全部以 S01 为 reference_image**，追加 `same scene as reference`
            3. 每张只写该视角**实际可见**的物品，不可见的不写
            4. 材质词/颜色词从场景圣经**复制，不替换同义词**
        """
        if "s_ang" in self._cache:
            return self._cache["s_ang"]  # type: ignore[return-value]
        t = self.raw("index_templates")
        i = _find_heading(t, "场景资产库索引表")
        rows = _table_after(t, i) if i >= 0 else []
        angles = [{"no": r.get("编号", ""), "shot": r.get("景别", ""),
                   "cam": r.get("摄像机方位→朝向", ""),
                   "cover": r.get("空间覆盖/动作区域", "")}
                  for r in rows if r.get("编号")]
        if not angles:            # 表头写法变化时的兜底（避免静默空表）
            angles = [{"no": f"S{n:02d}", "shot": "", "cam": "", "cover": ""}
                      for n in range(1, 7)]

        # 生成铁则（编号列表）
        rules: list[str] = []
        ls = _lines(t)
        for k in range(max(0, i), min(len(ls), i + 40)):
            m = re.match(r"^\s*([1-9])[.、]\s*(.+)$", ls[k])
            if m and ("S01" in m.group(2) or "reference" in m.group(2)
                      or "可见" in m.group(2) or "复制" in m.group(2)):
                rules.append(m.group(2).strip())

        # 分镜选图规则（第二张表）
        picks: list[dict] = []
        j = None
        for k in range(max(0, i), min(len(ls), i + 40)):
            if "分镜选图规则" in ls[k]:
                j = k
                break
        if j is not None:
            picks = [{"shot": r.get("分镜景别", ""), "first": r.get("优先", ""),
                      "alt": r.get("备选", "")}
                     for r in _table_after(t, j) if r.get("分镜景别")]

        self._cache["s_ang"] = {"angles": angles, "rules": rules, "picks": picks}
        return self._cache["s_ang"]  # type: ignore[return-value]

    # ── 文字屏蔽（RULE-005）──
    @property
    def text_block_positive(self) -> str:
        if "tb_pos" not in self._cache:
            t = self.raw("turnaround")
            i = _find_heading(t, "文字屏蔽的强制写法")
            block = _code_block_after(t, i)
            pos = ""
            for b in block:
                if b.startswith("正向追加"):
                    pos = b.split("：", 1)[-1].strip()
            self._cache["tb_pos"] = pos or "NO TEXT, no annotations, no labels, no words"
        return self._cache["tb_pos"]  # type: ignore[return-value]

    @property
    def text_block_negative(self) -> str:
        """含**权重 1.8** 的反向词 —— §1.6 强调「缺了它模型仍会生成标注文字」。"""
        if "tb_neg" not in self._cache:
            t = self.raw("turnaround")
            i = _find_heading(t, "文字屏蔽的强制写法")
            block = _code_block_after(t, i)
            neg = ""
            for b in block:
                if b.startswith("反向追加"):
                    neg = b.split("：", 1)[-1].strip()
            # 若反向追加跨多行，拼上后续行
            if neg and not neg.rstrip().endswith(")"):
                try:
                    k = block.index([x for x in block if x.startswith("反向追加")][0])
                    neg = " ".join(block[k:]).split("：", 1)[-1].strip()
                except Exception:
                    pass
            self._cache["tb_neg"] = neg or (
                "(text, font, letters, words, annotations, labels, descriptions, "
                "dimensions, handwriting, chart, arrows, indicators, view labels, "
                "any text:1.8), signature, watermark, username, logo, speech bubble")
        return self._cache["tb_neg"]  # type: ignore[return-value]

    # ── 质量参数 ──
    @property
    def quality_params(self) -> list[str]:
        if "quality" not in self._cache:
            t = self.raw("turnaround")
            i = _find_heading(t, "质量参数默认值")
            self._cache["quality"] = _code_block_after(t, i)
        return self._cache["quality"]  # type: ignore[return-value]

    @property
    def cinematic_concrete(self) -> str:
        """§49「电影感必须具体化」—— 不得只写 `cinematic, masterpiece`。

        ⚠️ 该小标题在权威文档里是**粗体行**（不是 `#` 标题），故用 `_find_line`。
        否则会取到文件里的第一个代码块（实测：错取 §1.2 的中文标准，污染英文 prompt）。
        """
        if "cine" not in self._cache:
            t = self.raw("turnaround")
            i = _find_line(t, "电影感必须具体化")
            self._cache["cine"] = " ".join(_code_block_after(t, i))
        return self._cache["cine"]  # type: ignore[return-value]

    # 工作流 §六 的 4 项中文质量参数 → 英文（prompt 用；保证英文 prompt 里不夹中文）
    QUALITY_EN = {
        "写实 / 拟真人优先": "photorealistic / lifelike priority",
        "超高细节": "ultra-high detail",
        "8K 级视觉细节": "8K-level visual detail",
        "电影级灯光质量": "cinematic lighting quality",
    }

    @property
    def quality_params_en(self) -> str:
        return "; ".join(self.QUALITY_EN.get(q, q) for q in self.quality_params)

    # ── 必填字段清单（供补全时自检完整性）──
    def _fields_under(self, section_kw: str) -> list[str]:
        """取某标准节下的「必填描述字段」清单（§2.1 服装 25 项 / §3.1 道具 19 项）。"""
        t = self.raw("turnaround")
        sec = _find_heading(t, section_kw)
        if sec < 0:
            return []
        # 从该节往后找第一个「必填描述字段」子标题（限制在本节范围内）
        nxt = _find_heading(t, "、", level=2, start=sec + 1)  # 下一个二级标题
        scope_end = nxt if nxt > sec else len(_lines(t))
        h = _find_heading(t, "必填描述字段", start=sec + 1)
        if h < 0 or h > scope_end:
            return []
        return _split_terms(_code_block_after(t, h))

    @property
    def costume_fields(self) -> list[str]:
        if "cst_f" not in self._cache:
            self._cache["cst_f"] = self._fields_under("服装标准")
        return self._cache["cst_f"]  # type: ignore[return-value]

    @property
    def prop_fields(self) -> list[str]:
        if "prp_f" not in self._cache:
            self._cache["prp_f"] = self._fields_under("道具标准")
        return self._cache["prp_f"]  # type: ignore[return-value]

    # ── ID 规范（从 00-总控路由.md 读）──
    @property
    def id_prefixes(self) -> dict[str, str]:
        """从路由文档的 ID 表里读出「类型 → 前缀」，避免代码里硬编码。"""
        if "id_pfx" in self._cache:
            return self._cache["id_pfx"]  # type: ignore[return-value]
        out: dict[str, str] = {}
        try:
            t = self.raw("router")
            i = _find_heading(t, "ID")
            for r in _table_after(t, i):
                name, pfx = r.get("类型", "").strip(), r.get("前缀", "").strip()
                # ⚠️ `_table_after` 已把单元格的反引号剥掉，故这里按裸值匹配；
                #    同时兼容未剥的情况（两种写法都认）。
                m = re.match(r"`?([A-Z]+_)`?", pfx)
                if name and m:
                    out[name] = m.group(1)
        except Exception:
            pass
        self._cache["id_pfx"] = out
        return out

    # ── 快照与漂移 ──
    def source_hashes(self) -> dict[str, str]:
        """各权威文件的内容 hash（用于漂移检测）。"""
        out = {}
        for key, rel in RULE_FILES.items():
            try:
                out[rel] = hashlib.sha256(self.raw(key).encode("utf-8")).hexdigest()[:16]
            except FileNotFoundError:
                out[rel] = ""
        return out

    def export(self) -> dict:
        """把权威规则**快照**到 vendor/，供不含工作流目录的机器使用。"""
        rules_dir = self.vendor_dir / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        for key, rel in RULE_FILES.items():
            try:
                (rules_dir / Path(rel).name).write_text(self.raw(key), encoding="utf-8")
            except FileNotFoundError:
                continue
        meta = {"workflow_root": str(self.workflow_root or ""),
                "hashes": self.source_hashes()}
        (self.vendor_dir / "snapshot.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def _load_snapshot(self) -> None:
        self._snap_meta = {}
        p = self.vendor_dir / "snapshot.json"
        if p.exists():
            try:
                self._snap_meta = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                self._snap_meta = {}

    def verify_snapshot(self) -> DriftReport:
        """对比快照与当前工作流：是否漂移。"""
        rep = DriftReport()
        meta_p = self.vendor_dir / "snapshot.json"
        if not meta_p.exists():
            rep.ok = False
            rep.detail = "尚无快照（执行 `python main.py export` 生成）"
            return rep
        old = json.loads(meta_p.read_text(encoding="utf-8")).get("hashes", {})
        if self.mode != "live":
            rep.detail = "当前为快照模式（无工作流目录），无法比对"
            return rep
        now = self.source_hashes()
        for rel, h in now.items():
            if not h:
                rep.missing.append(rel)
            elif old.get(rel) and old[rel] != h:
                rep.changed.append(rel)
        rep.ok = not (rep.missing or rep.changed)
        rep.detail = ("一致" if rep.ok else
                      f"漂移：缺失 {len(rep.missing)} · 变更 {len(rep.changed)}")
        return rep

    # ── 锁定系统（`LOCK-SYSTEM.md`；见 `src/lock.py`）──
    @property
    def lock_names(self) -> list[str]:
        """§一「可锁定资产清单」的 13 个 `LOCK_*`。

        代码块形态为「`LOCK_XXX` + 空白 + 中文说明」→ 取每行首个 token。
        """
        if "locks" not in self._cache:
            t = self.raw("lock")
            i = _find_heading(t, "可锁定资产清单")
            out: list[str] = []
            for b in _code_block_after(t, i):
                tok = b.strip().split()[0] if b.strip() else ""
                if tok.startswith("LOCK_") and tok not in out:
                    out.append(tok)
            self._cache["locks"] = out
        return self._cache["locks"]  # type: ignore[return-value]

    @property
    def nl_lock_map(self) -> list[tuple[str, str]]:
        """§二「自然语言 → 锁定映射表」→ `[(用户说, 解释), …]`（16 行）。

        ⚠️ 这张表是**锁定的实际含义**：用户说「只换发型」→ 其余全部 LOCK。
        不解析它，锁定系统就只是一串没人用的常量（本项目此前正是如此）。
        """
        if "nl_lock" not in self._cache:
            t = self.raw("lock")
            i = _find_heading(t, "自然语言 → 锁定映射表")
            out: list[tuple[str, str]] = []
            for r in _table_after(t, i):
                # 表头形如「用户说 / 自动解释」；取前两列，不写死表头字面
                vals = list(r.values())
                if len(vals) >= 2 and vals[0] and vals[1]:
                    out.append((vals[0], vals[1]))
            self._cache["nl_lock"] = out
        return self._cache["nl_lock"]  # type: ignore[return-value]

    # ── 概览 ──
    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "workflow_root": str(self.workflow_root or "（未找到）"),
            "vendor_dir": str(self.vendor_dir),
            "negative_common": len(self.negative_common),
            "negative_three_view": len(self.negative_three_view),
            "negative_modules": list(self.negative_by_module),
            "failure_rules": list(self.failure_repair_map),
            "quality_params": self.quality_params,
            "costume_fields": len(self.costume_fields),
            "prop_fields": len(self.prop_fields),
            "id_prefixes": self.id_prefixes,
        }
