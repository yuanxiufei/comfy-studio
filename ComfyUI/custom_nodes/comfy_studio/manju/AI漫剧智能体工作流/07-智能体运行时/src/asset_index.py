"""项目资产索引 → ID 的翻译层。

S4 分镜的门禁要求「每镜标了景别/机位/时长/**对应 ENV/CST/PRP**」，
而剧本里写的是**中文名**（`【场景1：市医院 · 产房外走廊／深夜 23:58】`、`萧易：…`），
所以必须有个地方把名字翻成 `ENV_001` / `CHR_002`。规矩三条：

  1. **只认项目里已登记的 ID**（`03_台账/ID注册表` + `02_资产索引/四张索引`），
     查不到就留空并由调用方计数 —— 号位永不复用，机器不许自造 ID。
  2. 匹配是**归一化后比对**（去空白、统一全角、`·` 忽略），再加上"最长包含"兜底
     （剧本写 `产房外走廊`、表里写 `市医院 · 产房外走廊`，得能对上）。
  3. 索引表是**人写的 Markdown**，列序不保证 —— 所以按**表头列名**取值
     （`名称` / `场景名` / `归属` / `首次出场`），不按列号猜。

`three_fields()` 读 `04_交付与出图/` 里那张「世界观三字段」表 ——
`生产流程规范（S0-S7）.md` §2.6 规定提示词里没有【所属色线】【时代/地域】【材质档】
就是不合格、不许出图，这里把它变成可机器核对的清单。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

__all__ = ["INDEX_REL", "REGISTRY_REL", "DELIVERY_REL", "Registry", "check_three_fields",
           "episode_targets", "load_project_registry", "norm", "parse_md_tables",
           "three_fields"]

REGISTRY_REL = os.path.join("00_PROJECT", "03_台账", "ID注册表（ID-REGISTRY）.md")
INDEX_REL = os.path.join("00_PROJECT", "02_资产索引")
DELIVERY_REL = os.path.join("00_PROJECT", "04_交付与出图")

ID_RE = re.compile(r"([A-Z]{3})_(\d{3,})")
_TABLE = {"·": "", "‧": "", "．": "", "。": "", "／": "/", "＋": "+", "，": ",",
          "（": "(", "）": ")", "「": "", "」": "", "：": ":", "“": "", "”": "",
          " ": "", "\u3000": "", "\t": ""}


def norm(s: str) -> str:
    """归一化：去空白/分隔符、统一全角小写 —— **只用于比对**，不改原值。"""
    return (s or "").translate(str.maketrans(_TABLE)).strip().lower()


def _undress(s: str) -> str:
    """去掉 markdown 装饰（`**粗体**`、`` `代码` ``），留干净的单元格文本。"""
    return re.sub(r"\*\*|__|`", "", str(s or "")).strip()


def parse_md_tables(text: str):
    """抽出 Markdown 表格：逐个 yield `(最近的小标题, 表头, 数据行)`。

    只认"以 `|` 开头"的行，所以正文里的竖线不会再被误当成表格。
    """
    heading, header, rows = "", None, []
    for raw in (text or "").splitlines():
        ln = raw.strip()
        if ln.startswith("#"):
            if header and rows:
                yield heading, header, rows
            heading, header, rows = ln.lstrip("# ").strip(), None, []
            continue
        if not ln.startswith("|"):
            continue
        cells = [_undress(c) for c in ln.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
            continue                                   # |---|---| 分隔行
        if header is None:
            header = cells
            continue
        rows.append(cells)
    if header and rows:
        yield heading, header, rows


@dataclass
class Registry:
    """项目里所有已登记 ID 的合并视图（一个 ID 一行，后读的索引只补缺字段）。"""
    rows: dict = field(default_factory=dict)      # ID → {列名: 值}
    origin: dict = field(default_factory=dict)    # ID → 来源文件
    aliases: dict = field(default_factory=dict)   # norm(名/别名) → ID
    props: dict = field(default_factory=dict)     # norm(道具名) → PRP_ID
    sources: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    # ── 基本信息 ──
    def name_of(self, aid: str) -> str:
        return self.rows.get(aid, {}).get("名称", "")

    def by_prefix(self, prefix: str) -> dict:
        p = prefix if prefix.endswith("_") else prefix + "_"
        return {k: v for k, v in self.rows.items() if k.startswith(p)}

    def detail(self, aid: str) -> dict:
        return self.rows.get(aid, {})

    def note(self) -> str:
        return (f"已登记 {len(self.rows)} 个 ID（CHR {len(self.by_prefix('CHR'))} · "
                f"CST {len(self.by_prefix('CST'))} · PRP {len(self.by_prefix('PRP'))} · "
                f"ENV {len(self.by_prefix('ENV'))}）"
                + (f"；⚠️ 有 {len(self.errors)} 处读取问题" if self.errors else ""))

    # ── 名字 → ID ──
    def _longest(self, key: str, prefix: str) -> str:
        """最长包含兜底：`产房外走廊` ↔ `市医院 · 产房外走廊`。"""
        best, blen = "", 0
        for k, v in self.aliases.items():
            if not v.startswith(prefix + "_") or len(k) < 3:
                continue
            if (k in key or key in k) and len(k) > blen:
                best, blen = v, len(k)
        return best

    def env_for(self, place: str) -> str:
        key = norm(place)
        if not key:
            return ""
        hit = self.aliases.get(key) or ""
        if hit.startswith("ENV_"):
            return hit
        return self._longest(key, "ENV")

    def char_for(self, name: str) -> str:
        key = norm(name)
        if not key:
            return ""
        hit = self.aliases.get(key) or ""
        if hit.startswith("CHR_"):
            return hit
        return self._longest(key.split("(")[0], "CHR")

    def known_names(self, text: str) -> list:
        """文本里**逐字出现**的已登记角色名（用于给动作镜挂人物）。"""
        t = norm(text)
        out = []
        for k, v in self.aliases.items():
            if v.startswith("CHR_") and len(k) >= 2 and k in t:
                nm = self.name_of(v)
                if nm and nm not in out:
                    out.append(nm)
        return out

    def costumes_of(self, chr_id: str, scene_no: int | None = None) -> list:
        """某角色的服装。给了 `scene_no` 就按「首次出场」列的 `S0X` 过筛 ——
        不过筛的话会把整部剧的服装都挂到每一镜上（`CST_001` 是 S01、
        `CST_002` 是 S03，混在一起分镜表就没法用了）。"""
        out = []
        want = norm(chr_id)
        for cid, row in sorted(self.by_prefix("CST").items()):
            m = ID_RE.search(row.get("归属", "") or "")
            if not m or norm(m.group(0)) != want:
                continue
            ref = row.get("首次出场", "")
            if scene_no is not None and not re.search(rf"S0*{int(scene_no)}(?![0-9])", ref):
                continue
            out.append(cid)
        return out

    def props_in(self, text: str) -> list:
        t = norm(text)
        return [pid for k, pid in sorted(self.props.items()) if len(k) >= 2 and k in t]


# ── 读盘 ──

def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _md_files(d: str) -> list:
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, fn) for fn in sorted(os.listdir(d)) if fn.lower().endswith(".md")]


def _env_aliases(name: str) -> list:
    """场景名可能带分隔符或并列（`市医院 · 产房外走廊`、`小学门口 + 教室门口`），
    拆开也各注册一份 —— 这样剧本里只写其中一段时对得上
    （实测 EP02 写 `小学教室门口`，注册表写 `小学门口 + 教室门口`，
    拆开后靠"最长包含"能落到 ENV_006）。"""
    out = [name]
    for part in re.split(r"[·‧+/／]", name):
        p = part.strip()
        if len(p) >= 3:
            out.append(p)
    return out


def load_project_registry(project_dir: str) -> Registry:
    """读 `ID注册表` + `02_资产索引/*.md`，合成"一个 ID 一行"的视图。

    合并规则：**先读到的列值为准**（注册表排在索引前面），
    所以注册表定"这个 ID 叫什么"，索引补"它长什么样"（场景锁定项等）。
    """
    reg = Registry()
    regs = os.path.join(project_dir, REGISTRY_REL)
    files = ([regs] if os.path.isfile(regs) else []) + _md_files(os.path.join(project_dir, INDEX_REL))
    if not files:
        reg.errors.append(f"既没有 {REGISTRY_REL} 也没有 {os.path.join(INDEX_REL, '*.md')} —— 资产 ID 无从回填")
        return reg

    for path in files:
        fn = os.path.basename(path)
        try:
            text = _read(path)
        except OSError as e:                                        # noqa: PERF203
            reg.errors.append(f"{fn}: {e}")
            continue
        reg.sources.append(fn)
        for _heading, header, rows in parse_md_tables(text):
            i_id = next((i for i, h in enumerate(header) if norm(h) in ("id", "编号")), None)
            if i_id is None:
                continue
            i_nm = next((i for i, h in enumerate(header) if "名" in h), None)
            for r in rows:
                m = ID_RE.search(r[i_id] if i_id < len(r) else "")
                if not m:
                    continue
                aid = m.group(0)
                cur = reg.rows.setdefault(aid, {})
                reg.origin.setdefault(aid, fn)
                for i, h in enumerate(header):
                    if h and i < len(r) and r[i]:
                        cur.setdefault(h, r[i])
                if i_nm is not None and i_nm < len(r) and r[i_nm]:
                    cur.setdefault("名称", r[i_nm])          # 统一成"名称"，下游不用管列名叫啥
                name = cur.get("名称") or ""
                if not name:
                    continue
                for alias in (_env_aliases(name) if aid.startswith("ENV_") else [name]):
                    reg.aliases.setdefault(norm(alias), aid)
                head = re.split(r"[（(]", name)[0].strip()        # `老人（九幻真人）` 也可用 `老人` 指
                if head and head != name:
                    reg.aliases.setdefault(norm(head), aid)
                if aid.startswith("PRP_"):
                    reg.props.setdefault(norm(name), aid)
    return reg


def three_fields(project_dir: str) -> dict:
    """读「世界观三字段」表 → `{ID: {"色线": …, "时代地域": …, "材质档": …}}`。"""
    out = {}
    for path in _md_files(os.path.join(project_dir, DELIVERY_REL)):
        for _heading, header, rows in parse_md_tables(_read(path)):
            if not any("色线" in h for h in header):
                continue
            cols = {
                "色线": next((i for i, h in enumerate(header) if "色线" in h), None),
                "时代地域": next((i for i, h in enumerate(header)
                                  if "时代" in h or "地域" in h), None),
                "材质档": next((i for i, h in enumerate(header) if "材质" in h), None),
            }
            i_key = next((i for i, h in enumerate(header) if "资产" in h), 0)
            for r in rows:
                m = ID_RE.search(r[i_key] if i_key < len(r) else "")
                if not m:
                    continue
                out.setdefault(m.group(0), {
                    k: (r[i] if i is not None and i < len(r) else "") for k, i in cols.items()})
    return out


def check_three_fields(project_dir: str, ids) -> tuple:
    """三字段体检 → `(齐了的, {ID: [缺的列]})`。§2.6：缺字段**不许出图**。"""
    table = three_fields(project_dir)
    ok, bad = [], {}
    for aid in ids:
        row = table.get(aid)
        if not row:
            bad[aid] = ["整行都没登记"]
            continue
        miss = [k for k, v in row.items() if str(v).strip() in ("", "—", "-", "/")]
        (bad.setdefault(aid, miss) if miss else ok.append(aid))
    return ok, bad


_EP_RE = re.compile(r"EP\s*0*(\d+)", re.I)
_SEC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*s\b|(\d+(?:\.\d+)?)\s*秒")


def episode_targets(project_dir: str) -> dict:
    """从项目自己的表里读**每集目标时长** → `{"EP01": 105.0, …}`。

    出处：`05_流程/每集物料单（EP01-EP05）.md` §一 与
    `01_剧本/00_总纲/分集大纲与三表.md` §一都有张"集 / 时长"表
    （105s/95s/110s/110s/110s）。**不写死默认值** —— 目标时长是项目的决定，
    不是运行时的常数。

    ⚠️ `01_剧本/`（v1 老位置）与 `01_剧本/00_总纲/`（v2）**两份都扫**：
    `_md_files` 只看一层，不递归，漏了哪一边就是"大纲里明明写了 105s，
    却按默认值出片"—— 静默的。多列一个目录比多猜一个默认值便宜。
    """
    out: dict = {}
    dirs = [os.path.join(project_dir, "00_PROJECT", "05_流程"),
            os.path.join(project_dir, "00_PROJECT", "01_剧本", "00_总纲"),
            os.path.join(project_dir, "00_PROJECT", "01_剧本")]
    for d in dirs:
        for path in _md_files(d):
            for _h, header, rows in parse_md_tables(_read(path)):
                i_ep = next((i for i, h in enumerate(header) if "集" in h), None)
                i_sec = next((i for i, h in enumerate(header) if "时长" in h), None)
                if i_ep is None or i_sec is None:
                    continue
                for r in rows:
                    if i_ep >= len(r) or i_sec >= len(r):
                        continue
                    me, ms = _EP_RE.search(r[i_ep]), _SEC_RE.search(r[i_sec])
                    if not (me and ms):
                        continue
                    val = float(ms.group(1) or ms.group(2))
                    if val > 0:
                        out.setdefault(f"EP{int(me.group(1)):02d}", val)
    return out
