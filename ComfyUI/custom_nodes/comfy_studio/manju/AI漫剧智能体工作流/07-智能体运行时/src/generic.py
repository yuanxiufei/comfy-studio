# -*- coding: utf-8 -*-
"""通用补全层 —— **任何一部小说都适用**，不依赖"我预先想到的题材"。

═══════════════════════════════════════════════════════════════════
它解决什么问题（实测量化过）
═══════════════════════════════════════════════════════════════════
此前各模块靠**固定题材表**补全：角色 11 题材 · 服装**只 4 类** ·
道具**只 5 类** · 批量 5 个世界观池。实测 5 种输入的命中情况：

| 输入 | world | 服装预设 | 道具预设 | 场景预设 |
|---|---|---|---|---|
| 废土女佣兵 | `wasteland` ✅ | — | — | — |
| **民国谍战女特工（旗袍/密码本）** | **空** ❌ | **无** | **无** | **无** |
| 仙侠剑修（青衫/飞剑） | `ancient` | **无** | 剑 ✅ | **无** |
| 都市言情总裁（西装/腕表） | `modern` | **无** | **无** | **赛博都市街道** ❌ 配错 |
| 现代刑侦（夹克/配枪） | `modern` | **无** | 枪 ✅ | **无** |

→ **5 种里的服装预设全部没命中**，于是「穿**旗袍**的女特工」被补成
「**棉**质三层功能服装、**深灰黑**」—— 把用户给的事实换成了预设里的**假具体值**。

根因有两条：
  ① **丢了用户原话**：`costume`/`prop`/`scene` 三个模块只用 `parsed.raw` 去**查预设**，
     **从不使用** `parsed.clothing_hints` / `equipment_hints`；
  ② **预设被当成唯一来源**：没命中就给「棉 / 深灰黑 / 铝合金 / 精密加工」这类
     **看起来具体、其实与题材无关**的值。

═══════════════════════════════════════════════════════════════════
本模块的原则
═══════════════════════════════════════════════════════════════════
**① 用户原话 > 预设值。**
   "这一部小说的事实" 优先于 "我预先想到的题材"。

**② 抽取按「语法」而不是「词表」。**
   ⚠️ 这是它能"任何小说都行"的关键：加词表是打地鼠（今天加"旗袍"，明天遇到"襦裙"
   又不行）。改用**结构信号** —— 「穿/着/戴 + X」「携带/握着 + X」「在 + 场所」，
   于是**不需要认识那个词**也能把它抽出来。

**③ 抽不到就**如实标注**，不假装具体。**
   兜底值仍然给（prompt 需要可用的值），但会在返回的 `notes` 里**逐项说明**哪些是兜底，
   让人知道该去补哪里 —— 而不是让人以为"棉"是从描述里识别出来的。

**④ 预设仍是加速器。** 命中题材预设时照旧用它（更具体），本模块只补**没命中**的部分。
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────
# ① 语法抽取：动词后的名词短语（**不依赖任何题材词表**）
# ─────────────────────────────────────────────────────────────

# 服装/配饰类动词（**长的在前**，先匹配「身穿」再匹配「穿」）
# ⚠️ **不要放单字「着」** —— 实测踩到：它会让「戴着**腕表**」「提着**提灯**」
#    「背着**步枪**」全被算成"服装形制"（「着」在中文里太常见）。
CLOTHING_VERBS = ("穿着", "身穿", "身着", "披着", "套着", "裹着",
                  "穿", "披", "裹", "身着")
ACCESSORY_VERBS = ("戴着", "佩戴", "配着", "别着", "头戴", "戴")
ITEM_VERBS = ("携带", "拿着", "握着", "手持", "拎着", "背着", "抱着", "提着",
              "别着", "配着", "带着", "手拿", "背", "提", "拿", "握", "持", "配", "佩")
PLACE_PREPS = ("在", "位于", "身处", "来到", "走进", "站在")

# 名词短语的**终止符**（这些字之后不再属于该短语）
# ⚠️ **不含中文数字** —— 实测踩到：含「九」会让「头戴**九翟冠**」在首字就被截空，
#    于是"配饰"整项丢失。宁可能多吃一个字，也不要丢词。
_STOP = "的了着地得是，。；、,.;!！？?和与或及以及之其把被"


def noun_after(text: str, verbs: tuple[str, ...], *,
               maxlen: int = 14) -> list[str]:
    """把 `text` 里「动词 + 名词短语」的**短语**抽出来。

    例：`"穿旗袍的女特工"` → `["旗袍"]`；`"携带密码本"` → `["密码本"]`。

    ⚠️ 走的是**结构**而不是词表 —— 见模块 docstring 原则②。
    """
    out: list[str] = []
    for v in verbs:
        start = 0
        while True:
            i = text.find(v, start)
            if i < 0:
                break
            start = i + len(v)
            frag = text[start:start + maxlen]
            # 截到第一个终止符
            cut = len(frag)
            for j, ch in enumerate(frag):
                if ch in _STOP:
                    cut = j
                    break
            w = frag[:cut].strip()
            # 太短（1 字）多半是虚词/量词，丢弃
            if len(w) >= 2 and w not in out:
                out.append(w)
    return out


# ⚠️ 场所后缀 = **字**表（不是词表）—— 汉字里"以某字结尾就表示场所"的字是**有限且
#    与题材无关**的，故它不会像名词表那样随题材失效。这是本项目"通用性"的支点之一。
#
# 提出到模块级（2026-09-24）：`nl_parser._detect_asset_type` 也要用它做**类型兜底**
# （「民国上海洋行的大厅」→ 场景）。若两处各存一份，判据必然分叉 —— 那正是
# 本项目反复强调的「同一知识两处维护」。
PLACE_SUFFIX = (
    "室厅站街城宫殿院馆楼桥港厂所场店校宅府谷洞山林舱岛屿湾庄塔台"
    # ⚠️ 2026-09-24 补：此前只有上列，于是「**洋行**」「当铺」「客栈」
    #    这类**没有上述后缀**的场所全抽不到（而它们在民国/古代题材很常见）。
    "铺栈驿寨堡寺庙观阁苑园斋堂房舫舟船关仓行道心门口井")


def prep_place(text: str, *, maxlen: int = 14) -> list[str]:
    """抽「在 / 位于 / 身处 + 场所」里的场所短语。

    ⚠️ 「在」太常用（"在 2026 年"），故要求其后短语**以场所字结尾**
    （见 `PLACE_SUFFIX`）—— 没有后缀的场合宁可**不抽**，也不给出错的场所词。
    """
    SUFFIX = PLACE_SUFFIX
    out: list[str] = []
    for v in PLACE_PREPS:
        start = 0
        while True:
            i = text.find(v, start)
            if i < 0:
                break
            start = i + len(v)
            frag = text[start:start + maxlen]
            cut = len(frag)
            for j, ch in enumerate(frag):
                if ch in _STOP:
                    cut = j
                    break
            # 去掉尾部的方位词（「霓虹街道**上**」→「霓虹街道」）
            w = frag[:cut].strip().rstrip("上里中内外的")
            if len(w) < 2:
                continue
            # ① 自带场所后缀 → 认
            # ② **结构信号**：「<X>的<含场所后缀的词>」时，X 也是场所
            #    （「上海**洋行**的**大厅**」→ 洋行 ✓；「**进行**改革」的「改革」无后缀 → 不认）
            tail = frag[cut:cut + 8]
            # ⚠️ 判据是「**以场所字结尾**」而不是「含场所字」——
            #    实测：含判据会把「在**进行**改革」抽成场所（因为「行」在表里）。
            #    以结尾判：洋行 ✓ / 客栈 ✓ / 街道 ✓ / 进行改革 ✗（结尾是「革」）。
            if w[-1] in SUFFIX:
                if w not in out:
                    out.append(w)
            elif tail.startswith("的") and any(ch in tail for ch in SUFFIX):
                if w not in out:
                    out.append(w)
    return out


# ─────────────────────────────────────────────────────────────
# ② 与题材无关的结构骨架（**不是**"棉/深灰黑"那种假具体值）
# ─────────────────────────────────────────────────────────────
#
# ⚠️ 骨架描述的是**这类资产在结构上必须回答什么**（服装：廓形/层次/材质/配件/磨损；
#    道具：结构/材质/工艺/表面/磨损），这些**与题材无关** —— 这正是工作流
#    §2.1（服装 25 字段）/ §3.1（道具 19 字段）的定义方式。
#
# 兜底值刻意写成"可用的中性描述"而不是某个具体题材的实物，
# 并由 `notes` 标明它是**兜底**（原则③）。

GENERIC_CLOTHING = {
    "silhouette": "依身份与场合决定的廓形（描述未指明形制）",
    "silhouette_en": "a silhouette determined by status and occasion (form not specified)",
    "layers": "内层 + 外层（层次随形制而定）",
    "layers_en": "base layer + outer layer (stratification depends on the garment form)",
    "material": "依场合选择的面料（描述未指明材质）",
    "material_en": "a fabric chosen for the occasion (material not specified)",
    "primary": "依身份决定的配色（描述未指明颜色）",
    "primary_en": "a palette determined by status (colour not specified)",
    "accessory": "一件与身份匹配的标志性配件",
    "accessory_en": "one signature accessory matching the station",
    "wear": "均匀轻微使用痕迹",
    "wear_en": "even, light wear",
}

GENERIC_PROP = {
    "structure": "主体 + 功能部件 + 连接件 + 表面细节",
    "structure_en": "main body, functional parts, connectors, surface details",
    "material": "依用途选择的材料（描述未指明材质）",
    "material_en": "a material chosen for the purpose (material not specified)",
    "craft": "成型 + 表面处理",
    "craft_en": "formed, then surface-treated",
    "surface": "表面处理与可见做工",
    "surface_en": "surface treatment and visible workmanship",
    "wear": "与使用年限相符的磨损",
    "wear_en": "wear consistent with years of use",
    "scale": "单手可持，与人体比例约为前臂长",
    "scale_en": "one-handed; roughly a forearm in length",
}

GENERIC_SCENE = {
    "building": "由原文场所词界定的空间（描述未给出建筑细节）",
    "building_en": "a space defined by the place word in the input",
    "spatial_scale": "常规室内/室外尺度",
    "spatial_scale_en": "ordinary interior or exterior scale",
    "materials": "依时代与用途推断的材料",
    "materials_en": "materials inferred from period and use",
    "light_source": "主光 + 副光，方向明确",
    "light_source_en": "a clear key light plus fill, with a definite direction",
    "atmosphere": "叙事所需的情绪基调",
    "atmosphere_en": "the emotional register the scene requires",
    "era": "",                    # 由 `era_from_text()` 填；填不出留空
    "circulation": "围绕主要家具/构筑物的日常动线",
    "circulation_en": "daily circulation around the main furniture or structures",
    "foreground": "近景层次元素", "foreground_en": "foreground layer elements",
    "midground": "中景主体", "midground_en": "midground subject",
    "background": "远景背景", "background_en": "background layer",
    "style": "依时代与阶级决定的风格（描述未指明流派）",
    "style_en": "a style determined by period and class (not specified)",
}

# 时代词（**通用性较高**：多数小说会点明时代，且这些词不绑定题材）
ERA_WORDS = [("民国", "the Republican era (early 20th c. China)"),
             ("清末", "late Qing dynasty"), ("清朝", "Qing dynasty"),
             ("明代", "Ming dynasty"), ("明朝", "Ming dynasty"),
             ("宋代", "Song dynasty"), ("唐朝", "Tang dynasty"),
             ("古代", "pre-modern"), ("上古", "ancient times"),
             ("未来", "the future"), ("近未来", "the near future"),
             ("当代", "contemporary"), ("现代", "modern day"),
             ("末法", "a declining age"), ("末日", "post-apocalypse")]


def era_from_text(text: str) -> tuple[str, str]:
    """从原文抽时代（**中英成对**）。抽不到返回 `("", "")`。"""
    for cn, en in ERA_WORDS:
        if cn in text:
            return cn, en
    return "", ""


# ─────────────────────────────────────────────────────────────
# ③ 组装：从原文抽到的「事实」 + 兜底（并标明哪些是兜底）
# ─────────────────────────────────────────────────────────────

def _first(lst: list[str], default: str = "") -> str:
    return lst[0] if lst else default


_HAS_CJK = re.compile(r"[\u4e00-\u9fa5]")


def tr_safe(cn: str, generic_en: str) -> tuple[str, bool]:
    """词表词 → 英文；**`tr()` 兜底若原样返回中文，则改用通用英文**。

    ⚠️ `tr()` 只认识词表里的词 —— 词表外的词它会**原样返回中文**。
    实测：`MATERIALS` 扩容前「丝」不在表里，`material_en = tr('丝') = '丝'`
    → 英文 prompt 又夹了中文（第 7 次同款的变体）。故所有"经 tr 进英文"的值都过这道闸。
    """
    from .prompt_engine import tr
    t = tr(cn or "")
    if not t or _HAS_CJK.search(t):
        return generic_en, bool(cn)
    return t, False


def safe_en(cn: str, generic_en: str) -> tuple[str, bool]:
    """把抽取到的**中文词**安全地放进**英文**字段。

    ⚠️ **本项目第 7 次同款问题，且这次是本模块自己引入的**：
    第一版把抽到的词直接拼进英文，产出了
        `STRUCTURE: body and functional parts of **密码本**`
        `LAYOUT: ... the architecture of **废弃医院** (per the input)`
    —— 英文 prompt 里夹中文会被多数图像模型忽略（约束静默失效）。

    :return: `(英文短语, 是否需要补英文)`
             含中文时**不拼进英文**，改用与题材无关的英文表述，并标记需要补英文
             （配了 LLM 时由精修步骤翻译；也可在资产卡/本机覆盖层里手工补）。
    """
    if not cn:
        return generic_en, False
    if _HAS_CJK.search(cn):
        return generic_en, True
    return cn, False


def _en_of(words: list[str], generic_en: str) -> tuple[str, bool]:
    """取第一个**可安全进英文**的词；全含中文则回退通用英文并标记。"""
    for w in words:
        if not _HAS_CJK.search(w):
            return w, False
    return generic_en, bool(words)



def clothing_from_text(text: str, material_vocab: list[str],
                       color_vocab: list[str]) -> tuple[dict, dict, list[str]]:
    """服装：**用户原话优先**，抽不到的字段用兜底并记入 notes。

    :return: `(从原文抽到的, 兜底值, 兜底说明)`

    ⚠️ **必须分成两个字典**（踩过）：第一版把"抽到的"和"兜底值"混在一起返回，
    但兜底值**总是非空**，于是调用方先写它 → **预设永远被覆盖**（连"战术/甲胄"
    这种命中预设的也拿不到）。分开后调用顺序才能是：
        ① 先写「抽到的」（用户原话赢）
        ② 再跑题材预设（补仍空白的）
        ③ 最后写「兜底值」（只填真空白，并如实标注）
    """
    garments = noun_after(text, CLOTHING_VERBS)
    accs = noun_after(text, ACCESSORY_VERBS)
    mats = [m for m in material_vocab if m in text]
    cols = [c for c in color_vocab if c in text]
    hit: dict[str, str] = {}
    fb: dict[str, str] = {}
    notes: list[str] = []
    need_en: list[str] = []

    if garments:
        hit["silhouette"] = "、".join(garments)
        en, need = _en_of(garments, "the specified garment")
        hit["silhouette_en"] = en
        if need:
            need_en.append(f"服装形制（{'、'.join(garments)}）")
    else:
        fb["silhouette"] = GENERIC_CLOTHING["silhouette"]
        fb["silhouette_en"] = GENERIC_CLOTHING["silhouette_en"]
        notes.append("服装形制（廓形/层次）：描述里没有可识别的服装词，已用通用骨架 —— "
                     "想更准请写「穿<具体衣物>」，如「穿旗袍」")
    if mats:
        hit["material"] = mats[0]
        # ⚠️ 材质/颜色来自本项目词表 → 可翻译；但 `tr()` 对**表外词会原样返回中文**，
        #    故必须过 `tr_safe()` 这道闸（实测：曾因「丝」不在表里而把中文送进英文）
        hit["material_en"], miss = tr_safe(mats[0], "the specified material")
        if miss:
            need_en.append(f"材质（{mats[0]}）")
    else:
        fb["material"] = GENERIC_CLOTHING["material"]
        fb["material_en"] = GENERIC_CLOTHING["material_en"]
        notes.append("服装材质：描述里没有材质词，已用中性描述（未假装具体材质）")
    if cols:
        hit["primary"] = "、".join(cols)
        ens = [tr_safe(c, "")[0] for c in cols]
        if all(ens):
            hit["primary_en"] = " and ".join(ens)
        else:
            need_en.append(f"颜色（{'、'.join(cols)}）")
    else:
        fb["primary"] = GENERIC_CLOTHING["primary"]
        fb["primary_en"] = GENERIC_CLOTHING["primary_en"]
        notes.append("服装配色：描述里没有颜色词，已用中性描述")
    if accs:
        hit["accessory"] = "、".join(accs)
        en, need = _en_of(accs, "the specified accessory")
        hit["accessory_en"] = en
        if need:
            need_en.append(f"配饰（{'、'.join(accs)}）")
    else:
        fb["accessory"] = GENERIC_CLOTHING["accessory"]
        fb["accessory_en"] = GENERIC_CLOTHING["accessory_en"]
    fb["wear"] = GENERIC_CLOTHING["wear"]
    fb["wear_en"] = GENERIC_CLOTHING["wear_en"]
    if need_en:
        notes.append("⚠️ 以下词是**中文**，英文 prompt 里已改用通用英文表述（避免夹中文）："
                     + "、".join(need_en) + " —— 配了 LLM 时会自动译；"
                     "也可在资产卡或 `prompts/overrides/` 里补英文")
    return hit, fb, notes


def prop_from_text(text: str, material_vocab: list[str],
                   color_vocab: list[str]) -> tuple[dict, dict, list[str]]:
    """道具：**用户原话优先**（携带/手握 的那个东西 就是道具名与结构起点）。

    :return: `(从原文抽到的, 兜底值, 兜底说明)` —— 见 `clothing_from_text` 的说明。
    """
    items = noun_after(text, ITEM_VERBS)
    mats = [m for m in material_vocab if m in text]
    cols = [c for c in color_vocab if c in text]
    hit: dict[str, str] = {}
    fb: dict[str, str] = {}
    notes: list[str] = []
    need_en: list[str] = []

    if items:
        hit["name"] = items[0]
        hit["structure"] = f"{items[0]}的本体与功能部件"
        # ⚠️ **不要把中文器物词拼进英文** —— 英文 prompt 里夹中文会被模型忽略
        en, need = safe_en(items[0], "the specified item")
        hit["structure_en"] = f"body and functional parts of {en}"
        if need:
            need_en.append(f"器物名（{items[0]}）")
    else:
        fb["structure"] = GENERIC_PROP["structure"]
        fb["structure_en"] = GENERIC_PROP["structure_en"]
        notes.append("道具结构：描述里没有可识别的器物词，已用通用骨架 —— "
                     "想更准请写「携带<具体物件>」，如「携带密码本」")
    if mats:
        hit["material"] = mats[0]
        hit["material_en"], miss = tr_safe(mats[0], "the specified material")
        if miss:
            need_en.append(f"材质（{mats[0]}）")
    else:
        fb["material"] = GENERIC_PROP["material"]
        fb["material_en"] = GENERIC_PROP["material_en"]
        notes.append("道具材质：描述里没有材质词，已用中性描述")
    if cols:
        hit["primary_color"] = "、".join(cols)
        ens = [tr_safe(c, "")[0] for c in cols]
        if all(ens):
            hit["primary_color_en"] = " and ".join(ens)
        else:
            need_en.append(f"颜色（{'、'.join(cols)}）")
    fb.update({k: v for k, v in GENERIC_PROP.items()
               if k not in ("material", "material_en", "structure",
                            "structure_en")})
    if need_en:
        notes.append("⚠️ 以下词是**中文**，英文 prompt 里已改用通用英文表述（避免夹中文）："
                     + "、".join(need_en) + " —— 配了 LLM 时会自动译")
    return hit, fb, notes


def scene_from_text(text: str) -> tuple[dict, dict, list[str]]:
    """场景：**用户原话的场所词**作为空间名与建筑描述起点。

    :return: `(从原文抽到的, 兜底值, 兜底说明)` —— 见 `clothing_from_text` 的说明。
    """
    places = prep_place(text)
    era_cn, era_en = era_from_text(text)
    hit: dict[str, str] = {}
    fb: dict[str, str] = dict(GENERIC_SCENE)
    notes: list[str] = []
    need_en: list[str] = []

    if places:
        hit["name"] = places[0]
        # ⚠️ 场所词多半是中文，**不要拼进英文**（英文 prompt 里夹中文会被忽略）
        en, need = safe_en(places[0], "the specified location")
        hit["building"] = f"{places[0]}的建筑构成（依原文场所词）"
        hit["building_en"] = f"the architecture of {en} (per the input)"
        fb.pop("building", None)
        fb.pop("building_en", None)
        if need:
            need_en.append(f"场所名（{places[0]}）")
    else:
        notes.append("场景空间：描述里没有可识别的场所词（要求含「室/厅/街/城/宫」"
                     "等场所后缀），已用通用骨架 —— 想更准请写「在<具体场所>」")
    if era_cn:
        # 时代词的英文来自 `ERA_WORDS` 的**成对表**（不是拼中文）✓
        hit["era"], hit["era_en"] = era_cn, era_en
        fb.pop("era", None)
    else:
        notes.append("场景时代：描述里没有时代词（如「民国」「未来」），era 留空")
    if need_en:
        notes.append("⚠️ 以下词是**中文**，英文 prompt 里已改用通用英文表述（避免夹中文）："
                     + "、".join(need_en) + " —— 配了 LLM 时会自动译")
    return hit, fb, notes
