# -*- coding: utf-8 -*-
"""Prop Agent —— 道具资产（蓝图 §四）。

道具**必须独立生成**（`TURNAROUND-STANDARD.md` §三：道具必须独立生成）。
必填字段 19 项来自工作流 §3.1，本项目在生成后由 `consistency.check_required` 校验覆盖率。
"""

from __future__ import annotations

from .nl_parser import short_name
from .schema import AssetCard, VisualDNA

# 道具品类 → 结构 / 材质 / 工艺 / 表面 / 磨损 预设（**中英双语**）
# 英文进 prompt_en，中文进 prompt_cn —— 英文 prompt 里夹中文会被多数图像模型忽略。
PROP_PRESETS: dict[str, dict] = {
    "枪": {"structure": "机匣 + 枪管 + 弹匣 + 瞄具 + 握把，折叠式枪托",
           "structure_en": "receiver, barrel, magazine, optic sight, grip, folding stock",
           "material": "钛合金", "craft": "CNC 铣削 + 阳极氧化",
           "material_en": "titanium alloy", "craft_en": "CNC milled, anodised",
           "surface": "哑光黑阳极氧化面，导轨为磨砂钢",
           "surface_en": "matte black anodised finish, brushed-steel rails",
           "wear": "枪口与抛壳窗有磨损露铜，握把缠带起毛",
           "wear_en": "muzzle and ejection port worn through to brass, frayed grip wrap",
           "scale": "全长 92cm，与成人前臂约等长",
           "scale_en": "92cm overall length, roughly a forearm"},
    "刀": {"structure": "单刃刀身 + 护手 + 缠绕刀柄 + 尾帽",
           "structure_en": "single-edged blade, guard, wrapped handle, pommel cap",
           "material": "磨砂钢", "craft": "锻造 + 手工开刃",
           "material_en": "brushed steel", "craft_en": "forged, hand-sharpened",
           "surface": "刀身有锻造流水纹，护手为做旧黄铜",
           "surface_en": "forge-flow pattern on the blade, aged brass guard",
           "wear": "刃口有细密崩口，刀柄缠带被汗渍浸深",
           "wear_en": "fine nicks along the edge, sweat-darkened handle wrap",
           "scale": "全长 42cm", "scale_en": "42cm overall length"},
    "剑": {"structure": "双刃剑身 + 十字护手 + 剑柄 + 配重球",
           "structure_en": "double-edged blade, crossguard, hilt, pommel",
           "material": "磨砂钢", "craft": "折叠锻打 + 研磨",
           "material_en": "brushed steel", "craft_en": "folded forged, polished",
           "surface": "剑身抛光，护手有浮雕纹样",
           "surface_en": "polished blade, relief-patterned crossguard",
           "wear": "护手边缘磕碰缺损，剑柄皮革包覆磨损",
           "wear_en": "chipped crossguard edges, worn leather grip wrap",
           "scale": "全长 105cm", "scale_en": "105cm overall length"},
    "装置": {"structure": "外壳 + 核心模块 + 接口阵列 + 散热栅 + 状态指示灯",
             "structure_en": "housing, core module, port array, heat vents, status lamp",
             "material": "铝合金", "craft": "冲压 + 精密装配",
             "material_en": "aluminium alloy", "craft_en": "stamped, precision assembled",
             "surface": "磨砂铝面 + 局部亚克力透光窗",
             "surface_en": "brushed aluminium with an acrylic light window",
             "wear": "边角掉漆，指示灯罩有划痕",
             "wear_en": "chipped paint on corners, scratched lamp cover",
             "scale": "24cm × 16cm × 8cm，可单手持握",
             "scale_en": "24 x 16 x 8 cm, one-handed"},
    "药": {"structure": "瓶体 + 密封盖 + 标签区 + 内胆",
           "structure_en": "bottle body, sealed cap, label panel, inner vial",
           "material": "玻璃", "craft": "吹制 + 金属封口",
           "material_en": "glass", "craft_en": "blown, metal-sealed",
           "surface": "琥珀色透光瓶体，金属盖为磨砂钢",
           "surface_en": "amber translucent glass, brushed-steel cap",
           "wear": "标签边缘卷曲，瓶身有轻微磕痕",
           "wear_en": "curling label edges, light scuffs on the body",
           "scale": "高 12cm，容量 30ml", "scale_en": "12cm tall, 30ml capacity"},
}
DEFAULT_PROP = {
    "structure": "主体 + 功能部件 + 连接件 + 表面细节",
    "structure_en": "main body, functional parts, connectors, surface details",
    "material": "铝合金", "craft": "精密加工 + 表面处理",
    "material_en": "aluminium alloy", "craft_en": "precision machined, surface treated",
    "surface": "哑光主体配金属点缀",
    "surface_en": "matte body with metal accents",
    "wear": "均匀轻微使用痕迹",
    "wear_en": "even, light wear",
    "scale": "单手可持，与人体比例约为前臂长",
    "scale_en": "one-handed; roughly a forearm in length",
}


def _set_if_empty(dc, fld: str, val) -> bool:
    cur = getattr(dc, fld, None)
    if cur in ("", None, [], ()):
        setattr(dc, fld, val)
        return True
    return False


def _pick_preset(text: str, name: str) -> dict:
    blob = f"{text} {name}"
    for k, v in PROP_PRESETS.items():
        if k in blob:
            return v
    return DEFAULT_PROP


_KEY2FLD = {"structure": "structure", "material": "material", "craft": "craft",
            "surface": "surface_texture", "wear": "wear",
            "scale": "scale_reference", "primary_color": "primary_color"}


def _write(vd, src: dict, keys) -> None:
    """把 `src` 的值写入 vd（**只填空白**，故调用顺序即优先级）。"""
    for k in keys:
        fld = _KEY2FLD.get(k, k)
        _set_if_empty(vd, fld, src.get(k, "") or "")
        en = src.get(k + "_en", "")
        if en:
            setattr(vd, fld + "_en", getattr(vd, fld + "_en", "") or en)


def complete(card: AssetCard, parsed, rules, llm=None) -> tuple[AssetCard, list[str]]:
    notes: list[str] = []
    vd: VisualDNA = card.visual_dna

    # ⭐ ① **先把用户原话写进去**（顺序即优先级）——
    #    ⚠️ 此前只用 `parsed.raw` 查预设，从不使用用户给的器物词：
    #    「携带**密码本**」会被补成预设里的「铝合金 + 精密加工」（实测踩到）。
    #    通用补全层按**语法**抽（「携带/手握/提着 + X」），**不依赖题材词表**。
    from . import generic
    from .nl_parser import COLORS, MATERIALS
    hit, fb, gnotes = generic.prop_from_text(parsed.raw, MATERIALS, COLORS)
    _write(vd, hit, ("structure", "material", "primary_color"))

    # ⭐ ② 再跑题材预设（只补仍空白的）—— **但只在真的命中了品类预设时**。
    #    ⚠️ 未命中会返回 `DEFAULT_PROP`（铝合金 / 精密加工），那是"看起来具体、
    #    其实与题材无关"的值 —— 会让「密码本」配上「铝合金」（实测踩到）。
    preset = _pick_preset(parsed.raw, card.name)
    if preset is DEFAULT_PROP:
        notes.append("ℹ️ **未命中道具品类预设** → 本次依「**你的原话 + 与题材无关的"
                     "通用骨架**」补全，不套用某一品类的默认值。想更具体可在描述里"
                     "多给几个词（如「携带黄铜怀表，表面有磨损」）")
    else:
        # 中文进 prompt_cn，英文进 prompt_en（字段成对写入）
        for fld, key in (("structure", "structure"),
                         ("material", "material"), ("craft", "craft"),
                         ("surface_texture", "surface"),
                         ("wear", "wear"), ("scale_reference", "scale")):
            _set_if_empty(vd, fld, preset[key])
            en = preset.get(key + "_en", "")
            if en:
                setattr(vd, fld + "_en", getattr(vd, fld + "_en", "") or en)
    notes.append(f"道具结构：{vd.structure[:40]}…")
    notes.append(f"材质/工艺：{vd.material} · {vd.craft}")
    notes.append(f"尺度参照：{vd.scale_reference}")

    # 用户明确给的材质优先
    if parsed.material_hints:
        vd.material = "、".join(parsed.material_hints)
        notes.append(f"⚠️ 采用用户指定材质：{vd.material}")

    # ⭐ ③ 最后写**兜底值**（只填真空白）并如实标注
    _write(vd, fb, ("structure", "material", "craft", "surface", "wear", "scale",
                    "primary_color"))
    notes.extend(gnotes)
    if hit:
        notes.insert(0, "✅ 已按**你的原话**填道具：" + "、".join(
            f"{k}={v}" for k, v in hit.items() if not k.endswith("_en") and v))
    _set_if_empty(vd, "primary_color", "哑光黑 + 磨砂钢原色")
    # ⚠️ 必须显式给英文 —— 靠 `tr()` 逐词替换会产出 `哑光black + brushed steel原色`
    #    这种**中英混排**（实测踩到）。
    _set_if_empty(vd, "primary_color_en", "matte black and brushed-steel natural tone")
    _set_if_empty(vd, "signature_points",
                  [x for x in [vd.structure.split("+")[0].strip() if vd.structure else "",
                               vd.surface_texture.split("，")[0]] if x])

    # ⚠️ 原写法 `["STRUCTURE"]` / `["COLOR","WEAR"]` **不是 §一 的 `LOCK_*` 名**。
    #    现由 `agent._create` 统一按权威设置；道具类无 §四·补 A/B 对应清单 → 不臆造。

    notes.append(f"道具必填字段：{len(rules.prop_fields)} 项（由一致性检查校验覆盖率）")
    return card, notes


def build_card(parsed, asset_id: str, now: str) -> AssetCard:
    return AssetCard(
        id=asset_id, type="prop",
        name=parsed.name or short_name(parsed.raw) or "prop",
        source=parsed.raw, created_at=now, updated_at=now,
        world=parsed.world, occupation=parsed.occupation,
    )
