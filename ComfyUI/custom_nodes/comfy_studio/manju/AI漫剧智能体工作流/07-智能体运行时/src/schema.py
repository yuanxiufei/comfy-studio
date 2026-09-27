# -*- coding: utf-8 -*-
"""数据模型 —— 资产卡 / 固定特征 / 状态变量 / 视觉 DNA。

═══════════════════════════════════════════════════════════════════
⚠️ ID 规范裁决（**必读**）
═══════════════════════════════════════════════════════════════════
用户提供的「AI漫剧资产库Agent」蓝图用 CHAR-001 / PROP-001 / COSTUME-001 / SCENE-001，
而本套工作流的**权威 ID 规范**（`00-总控路由.md` §四）是
    CHR_ / CST_ / PRP_ / ENV_ / EXP_ / POS_ / SHT_ / VID_ / AUD_
且 `02-服化道/01-资产库出图引擎.md` §〇.3 明文规定「**不得自造前缀**」。

故本项目**以工作流规范为准**（架构对齐：与 ID-REGISTRY 冲突时以项目既有规范为准），
但保留两套字面映射，由 `config.json` 的 `id_style` 切换，互不影响语义。

字段名严格对齐 `02-服化道/模板/ASSET_CARD.yaml`（权威），未自造字段。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any

# ─────────────────────────────────────────────────────────────
# 1. ID 规范（两套字面，同一语义）
# ─────────────────────────────────────────────────────────────

ID_STYLES: dict[str, dict[str, str]] = {
    "project": {          # 工作流权威规范（默认）
        "character": "CHR_{n:03d}",
        "costume": "CST_{n:03d}",
        "prop": "PRP_{n:03d}",
        "environment": "ENV_{n:03d}",
        "expression": "EXP_{owner}_{name}",
        "pose": "POS_{n:03d}_{name}",
    },
    "blueprint": {        # 用户蓝图的字面风格（可选）
        "character": "CHAR-{n:03d}",
        "costume": "COSTUME-{n:03d}",
        "prop": "PROP-{n:03d}",
        "environment": "SCENE-{n:03d}",
        "expression": "EXP-{owner}-{name}",
        "pose": "POSE-{n:03d}-{name}",
    },
}

ASSET_TYPE_CN = {"character": "角色", "costume": "服装", "prop": "道具",
                 "environment": "场景", "expression": "表情", "pose": "动作"}

ID_STATUS = ("RESERVED", "DRAFT", "LOCKED", "DEPRECATED")

# 项目规范 → 蓝图风格 的字面映射（供外部系统互通）
ID_CROSSWALK = {
    "CHR_": "CHAR-", "CST_": "COSTUME-", "PRP_": "PROP-", "ENV_": "SCENE-",
}


def make_id(asset_type: str, n: int, style: str = "project",
            owner: str = "", name: str = "") -> str:
    """按模板生成 ID。

    ⚠️ 表情/动作的模板含 `{owner}` / `{name}` —— 为空时会生成 `POS_001_` / `EXP__`
    这种**带悬空分隔符**的 ID（实测踩到）。故格式化后做一次清理：
      ① 折叠连续分隔符（`EXP__` → `EXP_`）
      ② 去掉尾部分隔符（`POS_001_` → `POS_001`）
    """
    tbl = ID_STYLES.get(style) or ID_STYLES["project"]
    tpl = tbl.get(asset_type)
    if tpl is None:
        raise ValueError(f"未知资产类型：{asset_type}（可选 {list(tbl)}）")
    out = tpl.format(n=n, owner=(owner or "").replace("_", ""), name=name or "")
    out = re.sub(r"([_\-])\1+", r"\1", out)          # 折叠连续分隔符
    return re.sub(r"[_\-]+$", "", out)               # 去尾部分隔符


_PATTERNS = [
    (r"^CHR_(\d{1,3})", "character"), (r"^CST_(\d{1,3})", "costume"),
    (r"^PRP_(\d{1,3})", "prop"), (r"^ENV_(\d{1,3})", "environment"),
    (r"^CHAR-(\d{1,3})", "character"), (r"^COSTUME-(\d{1,3})", "costume"),
    (r"^PROP-(\d{1,3})", "prop"), (r"^SCENE-(\d{1,3})", "environment"),
]


def parse_id(asset_id: str) -> tuple[str, int] | None:
    import re
    s = (asset_id or "").strip()
    for pat, t in _PATTERNS:
        m = re.match(pat, s)
        if m:
            return t, int(m.group(1))
    return None


# ─────────────────────────────────────────────────────────────
# 2. 资产卡（字段对齐 ASSET_CARD.yaml）
# ─────────────────────────────────────────────────────────────

@dataclass
class FixedFeatures:
    """终身固定核心识别特征库 —— **100% 不可改动**。

    是所有状态派生（_State_A/B/C）的唯一铁则。
    修改本区块 ≡ 重新设计角色，必须递增主版本号并通知全项目。
    """

    core_bone_structure: str = ""
    facial_contour: str = ""
    iris_color: str = ""
    permanent_marks: list[str] = field(default_factory=list)
    signature_micro_expressions: list[str] = field(default_factory=list)
    # 项目补充（规格未覆盖，对接 05-音乐音频）
    voice_base_timbre: str = ""
    voice_speed: str = ""
    voice_verbal_tics: list[str] = field(default_factory=list)
    body_fixed_habit_moves: list[str] = field(default_factory=list)

    # ── 英文伴生字段 ──
    # 为什么成对：英文 prompt 里夹中文会被多数图像模型忽略。
    # 中文留给人读（中文提示词 / 资产卡），英文进 prompt_en。
    core_bone_structure_en: str = ""
    facial_contour_en: str = ""
    permanent_marks_en: list[str] = field(default_factory=list)
    signature_micro_expressions_en: list[str] = field(default_factory=list)
    body_fixed_habit_moves_en: list[str] = field(default_factory=list)


@dataclass
class StageVariables:
    """剧情适配变量项 —— 各状态卡之间**可以不同**。"""

    skin_state: str = ""
    aging_marks: str = ""
    hair_color_change: str = ""
    facial_hair: str = ""
    injury_marks: str = ""
    body_shape: str = ""
    physique_vibe: str = ""
    hairstyle_change: str = ""
    makeup: str = ""
    full_outfit: str = ""
    core_accessories: str = ""

    # 英文伴生字段（见 FixedFeatures 说明）
    skin_state_en: str = ""
    physique_vibe_en: str = ""
    hairstyle_change_en: str = ""
    injury_marks_en: str = ""
    full_outfit_en: str = ""
    core_accessories_en: str = ""


@dataclass
class VisualDNA:
    """视觉 DNA —— fixed_features + stage_variables 的展开明细。

    与本卡 fixed_features 冲突时，**以 fixed_features 为准**。
    """

    face_shape: str = ""
    jaw: str = ""
    cheekbone: str = ""
    brow_ridge: str = ""
    eye_shape: str = ""
    eye_color: str = ""
    nose_bridge: str = ""
    lips: str = ""
    hair_color: str = ""
    hair_length: str = ""
    hair_volume: str = ""
    hair_style: str = ""
    hair_parting: str = ""
    bangs: str = ""
    height: str = ""
    shoulder_width: str = ""
    body_type: str = ""
    silhouette: str = ""
    primary_color: str = ""
    material: str = ""
    layers: str = ""
    signature_accessory: str = ""
    signature_points: list[str] = field(default_factory=list)
    # 道具 / 场景
    structure: str = ""
    craft: str = ""
    surface_texture: str = ""
    wear: str = ""
    scale_reference: str = ""

    # ── 英文伴生字段（进 prompt_en；中文留给人读）──
    face_shape_en: str = ""
    jaw_en: str = ""
    brow_ridge_en: str = ""
    nose_bridge_en: str = ""
    lips_en: str = ""
    eye_shape_en: str = ""
    eye_color_en: str = ""
    hair_length_en: str = ""
    hair_volume_en: str = ""
    hair_color_en: str = ""
    hair_parting_en: str = ""
    bangs_en: str = ""
    hair_style_en: str = ""
    height_en: str = ""
    body_type_en: str = ""
    shoulder_width_en: str = ""
    primary_color_en: str = ""
    material_en: str = ""
    surface_texture_en: str = ""
    silhouette_en: str = ""
    layers_en: str = ""
    signature_accessory_en: str = ""
    signature_points_en: list[str] = field(default_factory=list)
    palette4_en: list[str] = field(default_factory=list)
    structure_en: str = ""
    craft_en: str = ""
    wear_en: str = ""
    scale_reference_en: str = ""


@dataclass
class SceneDNA:
    """场景 DNA —— 字段按工作流 `02-服化道/引擎/TURNAROUND-STANDARD.md` **§四 场景标准（§09）**
    的「必须生成要素」11 项 + §37 输出协议的 Environment Lock / Lighting Lock 对齐。

    ⚠️ **场景与前三类的核心区别：环境不使用纯白背景**（§四 开头明文）。
    故 `layout_scene` 与角色/道具的三视图版式完全不同。
    """

    # ── 必须生成要素（§四·4.1 逐项）──
    building: str = ""            # 建筑类型
    spatial_scale: str = ""       # 空间尺度
    materials: str = ""           # 材料
    light_source: str = ""        # 光线方向与性质（Lighting Lock 核心）
    atmosphere: str = ""          # 氛围
    era: str = ""                 # 时代
    circulation: str = ""         # 人物动线
    foreground: str = ""          # 前景
    midground: str = ""           # 中景
    background: str = ""          # 后景

    # ── §四·4.2 一致性要求：与 Character+Costume+Props 对齐 ──
    props_in_scene: str = ""      # 陈设道具（对应 PROP INDEX）
    scale_vs_character: str = ""  # 空间尺度 vs 角色身高比例

    # ── §四·4.3 多角度：锁定 vs 允许变化 ──
    locked_elements: list[str] = field(default_factory=list)   # 建筑/门窗/家具/地面/光源/主空间关系
    variable_elements: list[str] = field(default_factory=list)  # 天气/时间/人物/灯光状态/道具摆放
    # 英文伴生（进 English prompt；缺了它这两行会在英文里留一串中文）
    locked_elements_en: list[str] = field(default_factory=list)
    variable_elements_en: list[str] = field(default_factory=list)

    # ── 样式 ──
    architectural_style: str = ""  # 建筑风格（快速公式第 2 段）
    time_of_day: str = ""
    weather: str = ""
    primary_color: str = ""

    # ── 英文伴生字段（进 English Environment Prompt）──
    name_en: str = ""             # 场景的英文名（`SCENE: …` 段用）
    building_en: str = ""
    spatial_scale_en: str = ""
    materials_en: str = ""
    light_source_en: str = ""
    atmosphere_en: str = ""
    era_en: str = ""
    circulation_en: str = ""
    foreground_en: str = ""
    midground_en: str = ""
    background_en: str = ""
    props_in_scene_en: str = ""
    architectural_style_en: str = ""
    time_of_day_en: str = ""
    weather_en: str = ""
    primary_color_en: str = ""


@dataclass
class SheetDNA:
    """表情集 / 动作集 DNA —— 字段按 `02-服化道/引擎/EXPRESSION-POSE-LIBRARY.md`。

    表情与动作**必须挂在角色上**（ID 规范：`EXP_<角色>_<表情名>` / `POS_<3位>_<动作名>`），
    故用 `owner` 记录所属角色，并把「铁律」要求的**一致性锚点**显式保存。
    """

    owner: str = ""                       # 所属角色 ID（如 CHR_001）
    sheet_kind: str = ""                  # expression | pose
    items: list[str] = field(default_factory=list)        # 中文名（如「微笑」）
    items_en: list[str] = field(default_factory=list)      # 英文描述词（库中原词）
    layout: str = ""                      # 网格布局（§1.3：4→2×2 · 16→4×4 · 25→5×5）
    is_baseline: bool = False             # 是否基线（表情 16 式必建）

    # ── 铁律（§10）：这些**绝不允许变**，必须写进 Consistency Constraints ──
    consistency_anchors: list[str] = field(default_factory=list)
    # ── 允许变的（只改这些）──
    mutable_parts: list[str] = field(default_factory=list)
    mutable_parts_en: list[str] = field(default_factory=list)   # 其英文（进 EN prompt）

    # ── 动作专用（§11）──
    clothing_state: str = ""              # 服装状态必须与剧情阶段一致（CST_00X_状态）
    prop_ids: list[str] = field(default_factory=list)   # 道具必须引用 PROP ID
    physics_checks: list[str] = field(default_factory=list)  # 人体结构/重心/力学/身份/服装限制/道具使用
    physics_checks_en: list[str] = field(default_factory=list)  # 其英文（进 EN prompt）


@dataclass
class AssetCard:
    id: str = ""
    type: str = ""
    name: str = ""
    version: str = "v1"
    source: str = ""
    reference: list[str] = field(default_factory=list)

    id_status: str = "DRAFT"
    id_registered: bool = True

    age: int | None = None
    gender: str = ""
    occupation: str = ""
    role: str = ""
    world: str = ""
    camp: str = ""

    fixed_features: FixedFeatures = field(default_factory=FixedFeatures)
    stage_variables: StageVariables = field(default_factory=StageVariables)
    visual_dna: VisualDNA = field(default_factory=VisualDNA)
    scene_dna: SceneDNA = field(default_factory=SceneDNA)
    sheet_dna: SheetDNA = field(default_factory=SheetDNA)

    # 版式变体：`standard`（默认）| `panorama360`（§4.6 场景空间基准方案）
    # 全景不是"另一种画风"，而是**空间基准底板** —— 先出它定布局，再出常规图。
    layout_variant: str = "standard"

    locked: list[str] = field(default_factory=list)
    editable: list[str] = field(default_factory=list)

    parent_asset: str = ""
    related_assets: list[str] = field(default_factory=list)

    prompt_cn: str = ""
    prompt_en: str = ""
    negative_prompt: str = ""

    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    # ── 序列化 ──
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AssetCard":
        d = dict(d or {})
        ff = d.pop("fixed_features", {}) or {}
        sv = d.pop("stage_variables", {}) or {}
        vd = d.pop("visual_dna", {}) or {}
        sd = d.pop("scene_dna", {}) or {}
        sh = d.pop("sheet_dna", {}) or {}
        known = set(cls.__dataclass_fields__)
        card = cls(**{k: v for k, v in d.items() if k in known})
        card.fixed_features = FixedFeatures(
            **{k: v for k, v in ff.items() if k in FixedFeatures.__dataclass_fields__})
        card.stage_variables = StageVariables(
            **{k: v for k, v in sv.items() if k in StageVariables.__dataclass_fields__})
        card.visual_dna = VisualDNA(
            **{k: v for k, v in vd.items() if k in VisualDNA.__dataclass_fields__})
        card.scene_dna = SceneDNA(
            **{k: v for k, v in sd.items() if k in SceneDNA.__dataclass_fields__})
        card.sheet_dna = SheetDNA(
            **{k: v for k, v in sh.items() if k in SheetDNA.__dataclass_fields__})
        return card

    # ── 一致性指纹 ──
    def fingerprint(self) -> str:
        """固定特征指纹 —— 同 parent 的派生卡指纹**必须一致**。

        只取终身固定的部分（fixed_features + 面部 DNA + 标志性识别点），
        故意**不含** stage_variables —— 那本就是允许变化的。
        """
        vd = self.visual_dna
        core = {
            "fixed_features": asdict(self.fixed_features),
            "face": {k: getattr(vd, k) for k in
                     ("face_shape", "jaw", "cheekbone", "brow_ridge",
                      "eye_shape", "eye_color", "nose_bridge", "lips")},
            # 英文伴生字段也纳入：**prompt 用的是英文**，英文变了图片就会变，
            # 所以「固定特征」必须连英文一起锁（只锁中文会漏掉实际生效的那一半）。
            "face_en": {k: getattr(vd, k) for k in
                        ("face_shape_en", "jaw_en", "brow_ridge_en",
                         "eye_shape_en", "eye_color_en", "nose_bridge_en", "lips_en")},
            "signature_points": sorted(vd.signature_points or []),
            "signature_points_en": sorted(vd.signature_points_en or []),
        }
        blob = json.dumps(core, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class GenerationResult:
    asset_id: str
    version: str
    provider: str
    model: str
    image_paths: list[str] = field(default_factory=list)
    prompt_path: str = ""
    metadata_path: str = ""
    width: int = 0
    height: int = 0
    ok: bool = True
    error: str = ""
    duration_ms: int = 0
