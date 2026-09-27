# -*- coding: utf-8 -*-
"""Asset Manager —— 资产库的落盘与版本管理（蓝图 §十 / §十一 / §十二 / §十三）。

═══════════════════════════════════════════════════════════════════
目录约定（对齐蓝图）
═══════════════════════════════════════════════════════════════════
    assets/characters/CHR_001/        card.json  v001.json  latest.json
    output/images/CHR_001/            v001.png   latest.png
    output/prompts/CHR_001/           v001.md    latest.md
    output/metadata/CHR_001.json      创建/修改时间 · prompt · negative · 模型 · 分辨率 …

版本铁则（蓝图 §十）：**修改不覆盖原资产**
    「给她增加机械右腿」→ 生成 CHR_001 v002，v001 保留。

ID 分配（蓝图 §八）：从注册表取号，**只增不复用**（对齐 ASSET_CARD 的
DEPRECATED「号位永久保留不复用」）。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .schema import AssetCard, GenerationResult, make_id, parse_id

TYPE_DIR = {"character": "characters", "costume": "costumes",
            "prop": "props", "environment": "scenes",
            "expression": "expressions", "pose": "poses"}


def normalize_version(v: str) -> str:
    """版本号统一为**三位**：`v1` / `1` / `v001` → `v001`。

    ⚠️ 必须**在版本号被用到之前**调用（不只是 `save()` 里）。实测踩到：
    `_maybe_generate()` 跑在 `save()` **之前**，于是出图存档成了
    `output/images/CHR_001/**v1**.png`，而资产卡是 `v**001**.json`
    —— 同一份资产两种编号，`--reference` 想指向旧图时会指空。
    """
    raw = v if str(v).startswith("v") else f"v{v}"
    num = raw[1:]
    return f"v{int(num):03d}" if num.isdigit() else raw


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AssetManager:
    """资产库的唯一读写入口。"""

    def __init__(self, root: str | os.PathLike, id_style: str = "project"):
        self.root = Path(root)
        self.id_style = id_style
        self.assets_dir = self.root / "assets"
        self.output_dir = self.root / "output"
        self.config_dir = self.root / "config"
        for p in (self.assets_dir, self.output_dir / "images",
                  self.output_dir / "prompts", self.output_dir / "metadata",
                  self.output_dir / "previews", self.config_dir):
            p.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.config_dir / "id_registry.json"
        self.registry = self._load_registry()

    # ── ID 注册表 ──

    def _load_registry(self) -> dict:
        if self.registry_path.exists():
            try:
                return json.loads(self.registry_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"id_style": self.id_style, "next": {}, "issued": {}}

    def _save_registry(self) -> None:
        self.registry_path.write_text(
            json.dumps(self.registry, ensure_ascii=False, indent=2), encoding="utf-8")

    def peek_next_id(self, asset_type: str) -> str:
        """看下一个可用号（不占用）。"""
        n = int(self.registry.get("next", {}).get(asset_type, 1))
        return make_id(asset_type, n, self.id_style)

    def allocate_id(self, asset_type: str, note: str = "",
                    owner: str = "", name: str = "") -> str:
        """分配并**占用**一个 ID。号位只增不复用。

        `owner` / `name` 供 `EXP_<角色>_<表情名>` / `POS_<3位>_<动作名>` 两类模板用
        （见 `schema.make_id`）。
        """
        nxt = self.registry.setdefault("next", {})
        n = int(nxt.get(asset_type, 1))
        aid = make_id(asset_type, n, self.id_style, owner=owner, name=name)
        nxt[asset_type] = n + 1
        self.registry.setdefault("issued", {})[aid] = {
            "type": asset_type, "n": n, "note": note, "at": now_str()}
        self._save_registry()
        return aid

    def resolve_id(self, token: str, asset_type: str = "") -> str:
        """把用户口头的指代解析成真实 ID：「上一个 / 她 / 它」→ 最近的**同类**资产。

        ⚠️ **类型限定是刚需，不是优化**。原实现对所有指代（含空串）一律返回
        「最近创建的资产」，于是库里同时有角色和场景时，
        「把**她**的头发换成银白色」会改到**场景**上（实测踩到：改出了 ENV_001 v002）。

        :param asset_type: 期望的资产类型（`character` / `costume` / …）；
                           留空则不限类型（保持旧的"最近创建"语义）。
                           人物代词「她 / 他」在未给类型时按 `character` 处理 ——
                           因为指代一个人时，"某个场景"不是合理候选。
        """
        t = (token or "").strip()
        if parse_id(t):
            return t
        issued = self.registry.get("issued", {})
        if not issued:
            return t
        if t in ("previous", "上一", "上一个", "她", "他", "它", ""):
            want = asset_type or ("character" if t in ("她", "他") else "")
            ids = [k for k, v in issued.items()
                   if not want or (v or {}).get("type") == want]
            return ids[-1] if ids else list(issued)[-1]
        return t

    # ── 路径 ──

    def card_dir(self, asset_id: str) -> Path:
        """资产卡所在目录。

        ⚠️ **不能只靠 `parse_id()` 推类型** —— 实测：它对两种 ID 模板
          · `EXP_<角色ID>_<表情名>`（如 `EXP_CHR001_基线16式`）
          · `POS_<3位>_<动作名>`（如 `POS_001_基础18动作`）
        **返回 `None`**，于是这里回退成 `character` → 表情集/动作集卡被写进
        `assets/characters/`，而 `assets/expressions/`、`assets/poses/`
        **永远是空的**（`TYPE_DIR` 里那两项形同虚设）。
        后果：按类型找资产的人（`list` / 人工翻目录 / 下游模块）找不到表情集。

        注册表里**每个已分配的 ID 都记了 `type`**，那才是准确来源；
        `parse_id()` 只作为注册表缺失时的兜底。
        """
        issued = self.registry.get("issued", {}) or {}
        rec = issued.get(asset_id)
        if isinstance(rec, dict) and rec.get("type"):
            t = rec["type"]
        else:
            t = (parse_id(asset_id) or ("character", 0))[0]
        return self.assets_dir / TYPE_DIR.get(t, "characters") / asset_id

    def card_path(self, asset_id: str, version: str = "latest") -> Path:
        return self.card_dir(asset_id) / f"{version}.json"

    # ── 读写 ──

    def save(self, card: AssetCard) -> Path:
        """保存资产卡到 `vNNN.json` 并更新 `latest.json`。

        ⚠️ 版本号**统一为三位**（`v1` → `v001`）——否则同一目录里两种编号并存，
        排序与 glob 都会错乱。见 `normalize_version()`。
        """
        card.updated_at = now_str()
        d = self.card_dir(card.id)
        d.mkdir(parents=True, exist_ok=True)
        ver = normalize_version(card.version)
        card.version = ver
        blob = json.dumps(card.to_dict(), ensure_ascii=False, indent=2)
        (d / f"{ver}.json").write_text(blob, encoding="utf-8")
        (d / "latest.json").write_text(blob, encoding="utf-8")
        self.registry.setdefault("issued", {}).setdefault(card.id, {
            "type": card.type, "at": card.created_at or now_str()})
        self._save_registry()
        return d / f"{ver}.json"

    def load(self, asset_id: str, version: str = "latest") -> AssetCard | None:
        p = self.card_path(asset_id, version)
        if not p.exists():
            return None
        return AssetCard.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def next_version(self, asset_id: str) -> str:
        d = self.card_dir(asset_id)
        n = 1
        if d.exists():
            vs = [int(f.stem[1:]) for f in d.glob("v*.json")
                  if f.stem[1:].isdigit()]
            n = (max(vs) + 1) if vs else 1
        return f"v{n:03d}"

    def history(self, asset_id: str) -> list[str]:
        d = self.card_dir(asset_id)
        if not d.exists():
            return []
        return sorted(f.stem for f in d.glob("v*.json"))

    def list_assets(self, asset_type: str = "", world: str = "",
                    keyword: str = "") -> list[AssetCard]:
        """资产库查询（蓝图 §十七）。"""
        out: list[AssetCard] = []
        dirs = [self.assets_dir / TYPE_DIR[asset_type]] if asset_type else \
            [self.assets_dir / v for v in TYPE_DIR.values()]
        for base in dirs:
            if not base.exists():
                continue
            for sub in sorted(base.iterdir()):
                if not sub.is_dir():
                    continue
                c = self.load(sub.name)
                if not c:
                    continue
                if world and world not in (c.world or ""):
                    continue
                if keyword:
                    blob = json.dumps(c.to_dict(), ensure_ascii=False)
                    if keyword not in blob:
                        continue
                out.append(c)
        return out

    # ── 产出物落盘（蓝图 §十一 / §十二 / §十三）──

    def write_prompt(self, card: AssetCard, extra: str = "") -> Path:
        d = self.output_dir / "prompts" / card.id
        d.mkdir(parents=True, exist_ok=True)
        md = (f"# {card.id} {card.name} · {card.version}\n\n"
              f"> 生成时间：{now_str()}｜类型：{card.type}｜世界观：{card.world}\n\n"
              f"## English Prompt (MASTER)\n\n```text\n{card.prompt_en}\n```\n\n"
              f"## 中文提示词\n\n```text\n{card.prompt_cn}\n```\n\n"
              f"## Negative Prompt\n\n```text\n{card.negative_prompt}\n```\n")
        if extra:
            md += f"\n## 附加说明\n\n{extra}\n"
        (d / f"{card.version}.md").write_text(md, encoding="utf-8")
        (d / "latest.md").write_text(md, encoding="utf-8")
        return d / f"{card.version}.md"

    def write_metadata(self, card: AssetCard, result: GenerationResult) -> Path:
        p = self.output_dir / "metadata" / f"{card.id}.json"
        prev = {}
        if p.exists():
            try:
                prev = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                prev = {}
        hist = prev.get("history", [])
        hist.append({
            "version": card.version, "at": now_str(), "provider": result.provider,
            "model": result.model, "width": result.width, "height": result.height,
            "images": [os.path.basename(x) for x in result.image_paths],
            "duration_ms": result.duration_ms, "ok": result.ok,
            "input": card.source, "fingerprint": card.fingerprint(),
        })
        meta = {
            "id": card.id, "name": card.name, "type": card.type,
            "world": card.world, "id_status": card.id_status,
            "created_at": card.created_at, "updated_at": card.updated_at,
            "latest_version": card.version,
            "fingerprint": card.fingerprint(),
            "prompt_en": card.prompt_en, "prompt_cn": card.prompt_cn,
            "negative_prompt": card.negative_prompt,
            "provider": result.provider, "model": result.model,
            "resolution": f"{result.width}x{result.height}",
            "history": hist,
        }
        p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def place_images(self, card: AssetCard, image_paths: list[str]) -> list[str]:
        """把生成图移入 `output/images/<ID>/vNNN.png` 并更新 `latest.png`。

        ⚠️ **同路径时必须跳过拷贝**：`_maybe_generate()` 传给出图 Provider 的
        `out_path` 与这里的 `dst` 是**同一个路径**（都是
        `output/images/<ID>/<版本>.png`），而 `shutil.copyfile(src, dst)` 在
        src == dst 时抛 `SameFileError`。

        实测后果很隐蔽：图**已经写出来了**，异常却被 `_maybe_generate` 吞成
        `ok=False` → `images` 为空 → 「产出图像」整段不打印 → 看起来像"没出图"。
        （这个 bug 一直存在，直到新加的「出图失败要报错」机制把它照出来。）
        """
        d = self.output_dir / "images" / card.id
        d.mkdir(parents=True, exist_ok=True)
        final = []
        for i, src in enumerate(image_paths):
            suffix = "" if len(image_paths) == 1 else f"_{i + 1}"
            dst = d / f"{card.version}{suffix}.png"
            if os.path.abspath(str(src)) != os.path.abspath(str(dst)):
                shutil.copyfile(src, dst)
            final.append(str(dst))
        if final:
            shutil.copyfile(final[0], d / "latest.png")
        return final

    def export(self, out_zip: str, asset_ids: list[str] | None = None) -> str:
        """导出 ZIP（蓝图 §十九：ZIP 用于跨电脑迁移）。"""
        import zipfile
        ids = asset_ids or [c.id for c in self.list_assets()]
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for aid in ids:
                for base in (self.card_dir(aid), self.output_dir / "images" / aid,
                             self.output_dir / "prompts" / aid):
                    if base.exists():
                        for f in base.rglob("*"):
                            if f.is_file():
                                z.write(f, f.relative_to(self.root))
                mp = self.output_dir / "metadata" / f"{aid}.json"
                if mp.exists():
                    z.write(mp, mp.relative_to(self.root))
        return out_zip

    def diff_versions(self, asset_id: str, v1: str, v2: str) -> list[str]:
        """对比两个版本，列出**哪些字段变了**（供改一处时核对）。"""
        a, b = self.load(asset_id, v1), self.load(asset_id, v2)
        if not a or not b:
            return [f"版本不存在：{asset_id} {v1} 或 {v2}"]
        da, db = a.to_dict(), b.to_dict()
        out = []
        for k in sorted(set(da) | set(db)):
            if k in ("created_at", "updated_at"):
                continue
            if da.get(k) != db.get(k):
                if isinstance(da.get(k), dict):
                    for kk in sorted(set(da[k]) | set(db.get(k) or {})):
                        if da[k].get(kk) != (db.get(k) or {}).get(kk):
                            out.append(f"{k}.{kk}: {da[k].get(kk)!r} → "
                                       f"{(db.get(k) or {}).get(kk)!r}")
                else:
                    out.append(f"{k}: {da.get(k)!r} → {db.get(k)!r}")
        return out
